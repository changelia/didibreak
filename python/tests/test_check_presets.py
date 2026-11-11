"""check with the provider presets openrouter, ollama and lmstudio (task 34)."""

import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from fixture_repos import FixtureRepository, build_fixture_repository

from didibreak import cli, llm
from didibreak.cli import EXIT_ERROR, EXIT_FINDINGS, main
from didibreak.config import Config


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FixtureRepository:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    monkeypatch.chdir(fixture.repository.path)
    for variable in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    return fixture


@pytest.fixture
def requests(
    monkeypatch: pytest.MonkeyPatch, repo: FixtureRepository
) -> list[httpx.Request]:
    """A fake OpenAI-compatible service; returns the requests it received."""
    received: list[httpx.Request] = []
    items = repo.expected["findings"] + repo.expected["same_behavior"]
    cases = [{"args": i["args"], "kwargs": [], "rationale": "r"} for i in items]

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        body = {
            "choices": [
                {
                    "message": {"content": json.dumps({"cases": cases})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 600},
        }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    return received


def write_config(repo: FixtureRepository, text: str) -> None:
    (repo.repository.path / "pyproject.toml").write_text(
        f"[tool.didibreak]\n{text}", encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("provider", "url"),
    [
        ("ollama", "http://localhost:11434/v1/chat/completions"),
        ("lmstudio", "http://localhost:1234/v1/chat/completions"),
    ],
)
def test_local_preset_needs_only_a_model_and_costs_nothing(
    requests: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    provider: str,
    url: str,
) -> None:
    assert main(["check", "--provider", provider, "--model", "llama3.2"]) == (
        EXIT_FINDINGS
    )

    assert str(requests[0].url) == url
    assert "authorization" not in requests[0].headers
    assert ", cost $0 (local)" in capsys.readouterr().out


def test_openrouter_preset_sends_its_key_and_warns_without_a_price(
    requests: list[httpx.Request],
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    write_config(repo, 'provider = "openrouter"\nmodel = "openai/gpt-6-sol"\n')

    assert main(["check"]) == EXIT_FINDINGS

    assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer sk-or-fake"
    out, err = capsys.readouterr()
    assert "max_cost is not enforced" in err
    assert "sk-or-fake" not in out + err


def test_cli_provider_overrides_the_pyproject_preset(
    requests: list[httpx.Request], repo: FixtureRepository
) -> None:
    write_config(repo, 'provider = "openrouter"\nmodel = "llama3.2"\n')

    assert main(["check", "--provider", "ollama"]) == EXIT_FINDINGS

    assert requests[0].url.host == "localhost"


def test_cli_preset_discards_the_pyproject_url_and_key(
    requests: list[httpx.Request],
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Task 34 review, decision 5: --provider ollama must not send the
    # request, or the OpenRouter key, to the OpenRouter URL from pyproject.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    write_config(
        repo,
        'model = "llama3.2"\n'
        'base_url = "https://openrouter.ai/api/v1"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n',
    )

    assert main(["check", "--provider", "ollama"]) == EXIT_FINDINGS

    assert str(requests[0].url) == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in requests[0].headers


def test_cli_base_url_still_overrides_a_cli_preset(
    requests: list[httpx.Request], repo: FixtureRepository
) -> None:
    write_config(repo, 'model = "llama3.2"\n')
    argv = ["check", "--provider", "lmstudio", "--base-url", "http://127.0.0.1:8080/v1"]

    assert main(argv) == EXIT_FINDINGS

    assert str(requests[0].url) == "http://127.0.0.1:8080/v1/chat/completions"


def test_pyproject_base_url_overrides_a_pyproject_preset(
    requests: list[httpx.Request], repo: FixtureRepository
) -> None:
    write_config(
        repo,
        'provider = "lmstudio"\nmodel = "llama3.2"\n'
        'base_url = "http://127.0.0.1:8080/v1"\n',
    )

    assert main(["check"]) == EXIT_FINDINGS

    assert str(requests[0].url) == "http://127.0.0.1:8080/v1/chat/completions"


def test_preset_without_a_model_exits_2_before_any_request(
    requests: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--provider", "ollama"]) == EXIT_ERROR

    assert requests == []
    assert "the ollama preset has no default model" in capsys.readouterr().err
