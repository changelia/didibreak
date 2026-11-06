"""didibreak check with LLM-generated cases from a fake provider, on every fixture."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fixture_repos import build_fixture_repository, fixture_names

from didibreak import cli, llm
from didibreak.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main
from didibreak.config import Config

MALICIOUS = "__import__('os').system('echo pwned')"


def documented_cases(expected: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_function: dict[str, list[dict[str, Any]]] = {}
    for group in ("findings", "same_behavior", "flaky_functions"):
        for item in expected[group]:
            pairs = [{"name": k, "value": v} for k, v in item["kwargs"].items()]
            case = {"args": item["args"], "kwargs": pairs, "rationale": "fixture"}
            by_function.setdefault(item["function"], []).append(case)
    return by_function


def install_fake_llm(
    monkeypatch: pytest.MonkeyPatch, replies: dict[str, list[dict[str, Any]]]
) -> list[str]:
    """OpenAI-style fake: returns the documented cases for the function asked about."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        function = prompt.split("Function: ", 1)[1].split("\n", 1)[0]
        asked.append(function)
        cases = replies.get(function, [])
        body = {
            "model": "fake-luna",
            "choices": [
                {
                    "message": {"content": json.dumps({"cases": cases})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 120,
                "completion_tokens_details": {"reasoning_tokens": 80},
            },
        }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return asked


@pytest.mark.parametrize("case", fixture_names())
def test_llm_cases_reproduce_the_documented_findings(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    replies = documented_cases(fixture.expected)
    asked = install_fake_llm(monkeypatch, replies)
    monkeypatch.chdir(fixture.repository.path)

    code = main(["check"])

    expected_functions = [f["function"] for f in fixture.expected["changed_functions"]]
    assert asked == expected_functions  # one request per testable function
    assert code == (EXIT_FINDINGS if fixture.expected["findings"] else EXIT_OK)
    err = capsys.readouterr().err
    for finding in fixture.expected["findings"]:
        assert f"{finding['function']}({', '.join(finding['args'])})" in err
    if asked:
        assert f"LLM: {len(asked)} calls" in err
        assert f"{120 * len(asked)} output tokens ({80 * len(asked)} reasoning)" in err


def test_malicious_cases_are_dropped_counted_and_never_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    replies = documented_cases(fixture.expected)
    function = "app/utils/phone.py::normalize_phone"
    replies[function].append({"args": [MALICIOUS], "kwargs": [], "rationale": "x"})
    install_fake_llm(monkeypatch, replies)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check"]) == EXIT_FINDINGS
    err = capsys.readouterr().err
    assert "1 invalid cases dropped" in err
    assert "pwned" not in err
    assert "3 cases" in err  # only the documented cases ran


def test_other_rejected_request_skips_the_function_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository("float_precision", tmp_path / "repo")
    replies = documented_cases(fixture.expected)
    bad = httpx.Response(400, json={"error": {"message": "context too long"}})

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        if "::mean\n" in prompt:
            return bad
        cases = replies["app/stats.py::price_with_tax"]
        content = json.dumps({"cases": cases})
        body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check"]) == EXIT_FINDINGS  # price_with_tax still ran
    err = capsys.readouterr().err
    assert (
        "app/stats.py::mean (llm request rejected: HTTP 400: context too long)" in err
    )
    assert "app/stats.py::price_with_tax(10.05)" in err


def test_rejected_key_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    rejected = httpx.Response(401, json={"error": {"message": "Incorrect API key"}})

    def create(config: Config, environment: Mapping[str, str]) -> object:
        transport = httpx.MockTransport(lambda request: rejected)
        return llm.create_client(config, environment, transport)

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-rejected")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "rejected the API key" in err
    assert "sk-fake-rejected" not in err
