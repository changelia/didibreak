"""check: cost estimate, confirmation, cost limit and case cache (fake provider)."""

import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fixture_repos import FixtureRepository, build_fixture_repository

from didibreak import cli, llm
from didibreak.cache import GITIGNORE_TEXT
from didibreak.cli import EXIT_FINDINGS, EXIT_OK, main
from didibreak.config import Config

FUNCTION = "app/utils/phone.py::normalize_phone"


class FakeStdin(io.StringIO):
    """A terminal-like stdin with a prepared answer."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FixtureRepository:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    monkeypatch.chdir(fixture.repository.path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return fixture


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch, repo: FixtureRepository) -> list[str]:
    """Install a fake provider that answers with the documented cases."""
    order: list[str] = []
    items = repo.expected["findings"] + repo.expected["same_behavior"]
    cases = [{"args": i["args"], "kwargs": [], "rationale": "r"} for i in items]

    def handler(request: httpx.Request) -> httpx.Response:
        order.append("request")
        body = {
            "model": "gpt-6-luna",
            "choices": [
                {
                    "message": {"content": json.dumps({"cases": cases})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 600,
                "completion_tokens_details": {"reasoning_tokens": 400},
            },
        }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    real_print_estimate = cli._print_estimate

    def recording_print_estimate(*args: Any) -> None:
        order.append("estimate")
        real_print_estimate(*args)

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setattr(cli, "_print_estimate", recording_print_estimate)
    return order


def test_estimate_is_printed_before_any_request(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check"]) == EXIT_FINDINGS

    assert events == ["estimate", "request"]
    err = "".join(capsys.readouterr())
    assert (
        "Estimated: up to 2 LLM calls (1 + up to 1 refinement) with gpt-6-luna" in err
    )
    assert "(limit $0.50)" in err


def test_actual_tokens_and_cost_are_reported(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check"])

    expected = (1000 * 0.10 + 600 * 0.50) / 1_000_000
    err = "".join(capsys.readouterr())
    assert (
        "LLM: 1 call · 1000 input tokens · 600 output tokens (400 reasoning) · "
        f"cost ${expected:.4f}"
    ) in err


@pytest.mark.parametrize("answer", ["n\n", "no\n", ""])
def test_declining_the_estimate_sends_nothing(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    monkeypatch.setattr("sys.stdin", FakeStdin(answer))

    assert main(["check"]) == EXIT_OK

    assert events == ["estimate"]
    err = "".join(capsys.readouterr())
    assert "Continue? [Y/n]" in err
    assert "Cancelled: no LLM request was sent." in err


@pytest.mark.parametrize("answer", ["\n", "y\n", "YES\n"])
def test_accepting_the_estimate_continues(
    events: list[str], monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    monkeypatch.setattr("sys.stdin", FakeStdin(answer))

    assert main(["check"]) == EXIT_FINDINGS
    assert events == ["estimate", "request"]


@pytest.mark.parametrize("flags", [["--yes"], ["--format", "json"]])
def test_yes_and_json_mode_do_not_ask(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
) -> None:
    monkeypatch.setattr("sys.stdin", FakeStdin("n\n"))

    main(["check", *flags])

    assert events == ["estimate", "request"]
    assert "Continue?" not in "".join(capsys.readouterr())


def test_second_run_uses_the_cache_without_any_request(
    events: list[str],
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["check"]) == EXIT_FINDINGS
    first = "".join(capsys.readouterr())
    events.clear()

    def no_network(config: Config, environment: Mapping[str, str]) -> object:
        raise AssertionError("a cache hit must not create a client")

    monkeypatch.setattr(cli, "create_client", no_network)

    assert main(["check"]) == EXIT_FINDINGS
    second = "".join(capsys.readouterr())
    assert "request" not in events  # the estimate may still list a refinement
    assert "LLM: 0 calls" in second
    assert "Estimated: up to 1 LLM call (0 + up to 1 refinement)" in second
    assert f"{FUNCTION}('995 555 12 34 56')" in first
    assert f"{FUNCTION}('995 555 12 34 56')" in second
    output = repo.repository.path / ".didibreak"
    assert (output / ".gitignore").read_text() == GITIGNORE_TEXT
    assert len(list((output / "cache" / "cases").glob("*.json"))) == 1
    assert repo.repository.git("status", "--porcelain", "--", ".didibreak") == ""


def test_no_cache_asks_the_llm_again(events: list[str]) -> None:
    main(["check"])
    events.clear()

    main(["check", "--no-cache"])

    assert events == ["estimate", "request"]


def test_cost_limit_skips_cleanly_and_reports_it(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--max-cost", "0.000001"]) == EXIT_OK

    assert events == ["estimate"]  # the request would exceed the limit
    err = "".join(capsys.readouterr())
    assert "(limit $0.000001)" in err
    assert "The estimate is above max_cost" in err
    assert f"skipped: {FUNCTION} (cost limit)" in err


def test_token_limit_skips_cleanly_and_reports_it(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--max-tokens", "100"]) == EXIT_OK

    assert events == ["estimate"]  # the request would exceed the limit
    err = "".join(capsys.readouterr())
    assert "The estimate is above max_tokens (100)" in err
    assert f"skipped: {FUNCTION} (token limit)" in err


def test_token_limit_from_pyproject_applies_and_the_flag_overrides_it(
    events: list[str], repo: FixtureRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo.repository.path / "pyproject.toml").write_text(
        "[tool.didibreak]\nmax_tokens = 100\n", encoding="utf-8"
    )
    assert main(["check", "--no-cache"]) == EXIT_OK
    assert f"skipped: {FUNCTION} (token limit)" in "".join(capsys.readouterr())

    assert main(["check", "--no-cache", "--max-tokens", "1000000"]) == EXIT_FINDINGS
    assert events == ["estimate", "estimate", "request"]


def test_unpriced_remote_model_runs_with_a_warning_and_unknown_cost(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--model", "my-private-model"]) == EXIT_FINDINGS

    assert events == ["estimate", "request"]
    out, err = capsys.readouterr()
    assert ", cost unknown (limit 200,000 tokens)" in out
    assert "no price is known for model 'my-private-model'" in err
    assert "max_cost is not enforced; max_tokens (200,000) still applies" in err
    assert (
        '[tool.didibreak.prices] "my-private-model" = { input = ..., output = ... }'
        in err
    )
    assert "output tokens (400 reasoning) · cost unknown" in out


def test_unpriced_model_warns_even_in_quiet_mode(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", "--model", "my-private-model", "-q"])

    out, err = capsys.readouterr()
    assert "Estimated" not in out + err
    assert "max_cost is not enforced" in err


def test_unpriced_model_json_report_has_null_cost(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["check", "--model", "my-private-model", "--format", "json"])

    out, err = capsys.readouterr()
    report = json.loads(out)
    assert code == EXIT_FINDINGS
    assert report["usage"]["cost_usd"] is None
    assert report["usage"]["calls"] == 1  # a difference found: no refinement
    assert "max_cost is not enforced" in err


def test_unpriced_model_is_still_bounded_by_max_tokens(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["check", "--model", "my-private-model", "--max-tokens", "100"]

    assert main(argv) == EXIT_OK

    assert events == ["estimate"]
    assert f"skipped: {FUNCTION} (token limit)" in "".join(capsys.readouterr())


@pytest.mark.parametrize("host", ["localhost:11434", "127.0.0.1:1234"])
def test_local_endpoint_without_a_price_costs_nothing(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    host: str,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    argv = ["check", "--provider", "openai", "--base-url", f"http://{host}/v1"]
    (Path.cwd() / "pyproject.toml").write_text(
        '[tool.didibreak]\nmodel = "llama3.2"\napi_key_env = ""\n', encoding="utf-8"
    )

    assert main(argv) == EXIT_FINDINGS

    assert events == ["estimate", "request"]
    err = "".join(capsys.readouterr())
    assert "Estimated: up to 2 LLM calls (1 + up to 1 refinement) with llama3.2" in err
    assert ", cost $0 (local)" in err
    assert "output tokens (400 reasoning) · cost $0 (local)" in err


def test_unpriced_model_with_all_cases_cached_needs_no_price(
    events: list[str], monkeypatch: pytest.MonkeyPatch, repo: FixtureRepository
) -> None:
    (repo.repository.path / "pyproject.toml").write_text(
        '[tool.didibreak.prices]\n"my-private-model" = { input = 1.0, output = 2.0 }\n',
        encoding="utf-8",
    )
    argv = ["check", "--model", "my-private-model", "--refine-rounds", "0"]
    assert main(argv) == EXIT_FINDINGS
    (repo.repository.path / "pyproject.toml").unlink()
    events.clear()

    assert main(argv) == EXIT_FINDINGS
    assert events == []  # all cached, no refinement: no request, no price needed


def test_configured_price_gives_a_cost_for_an_unknown_model(
    events: list[str], repo: FixtureRepository, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo.repository.path / "pyproject.toml").write_text(
        '[tool.didibreak.prices]\n"my-private-model" = { input = 1.0, output = 2.0 }\n',
        encoding="utf-8",
    )

    main(["check", "--model", "my-private-model"])

    expected = (1000 * 1.0 + 600 * 2.0) / 1_000_000
    assert f"cost ${expected:.4f}" in "".join(capsys.readouterr())


def test_quiet_mode_prints_no_estimate(
    events: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", "-q"])

    assert events == ["request"]
    assert "Estimated" not in "".join(capsys.readouterr())
