"""check with intent labelling from a fake provider that follows expected.json."""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fixture_repos import build_fixture_repository, fixture_names, load_expected

from didibreak import cli, llm
from didibreak.cli import CASES_FILE_REASON, EXIT_FINDINGS, EXIT_OK, main
from didibreak.config import Config
from didibreak.intent import NO_INTENT_REASON

LINE = re.compile(r"^- finding_id (\w+): \w+\((.*)\) in (\S+) -> ", re.MULTILINE)
WITH_INTENT = [name for name in fixture_names() if load_expected(name)["intent"]]


def documented_cases(expected: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_function: dict[str, list[dict[str, Any]]] = {}
    for group in ("findings", "same_behavior", "flaky_functions"):
        for item in expected[group]:
            pairs = [{"name": k, "value": v} for k, v in item["kwargs"].items()]
            case = {"args": item["args"], "kwargs": pairs, "rationale": "fixture"}
            by_function.setdefault(item["function"], []).append(case)
    return by_function


def completion(data: object) -> httpx.Response:
    body = {
        "choices": [
            {"message": {"content": json.dumps(data)}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 300, "completion_tokens": 150},
    }
    return httpx.Response(200, json=body)


def install(
    monkeypatch: pytest.MonkeyPatch,
    expected: dict[str, Any],
    labeller: Any = None,
) -> list[str]:
    """Fake provider for cases and labels; returns the labelling prompts."""
    cases = documented_cases(expected)
    labels = {
        (f["function"], ", ".join(f["args"])): f["label"] for f in expected["findings"]
    }
    label_prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        if body["response_format"]["json_schema"]["name"] == "didibreak_labels":
            label_prompts.append(prompt)
            if labeller is not None:
                return labeller(prompt)
            found = [
                {
                    "finding_id": identifier,
                    "label": labels[(function, args)],
                    "reason": "matches the fixture",
                }
                for identifier, args, function in LINE.findall(prompt)
            ]
            return completion({"labels": found})
        function = prompt.split("Function: ", 1)[1].split("\n", 1)[0]
        return completion({"cases": cases.get(function, [])})

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return label_prompts


@pytest.mark.parametrize("case", WITH_INTENT)
def test_labels_and_exit_codes_follow_the_documented_intent(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    label_prompts = install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    code = main(["check", "--intent", fixture.expected["intent"]])

    findings = fixture.expected["findings"]
    failing = {"unexpected", "unclear", "new_function"}
    assert code == (
        EXIT_FINDINGS if any(f["label"] in failing for f in findings) else EXIT_OK
    )
    err = "".join(capsys.readouterr())
    for finding in findings:
        heading = finding["label"].upper().replace("_", "-")
        assert (
            f"{heading:<13}{finding['function']}({', '.join(finding['args'])})" in err
        )
    to_label = [f for f in findings if f["label"] != "new_function"]
    assert len(label_prompts) == (1 if to_label else 0)
    if to_label:
        assert f"Stated by the user: {fixture.expected['intent']}" in label_prompts[0]


def test_intended_change_passes_once_labelled_expected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--intent", fixture.expected["intent"]]) == EXIT_OK
    assert "matches the fixture" in "".join(capsys.readouterr())


def test_without_intent_nothing_is_labelled_and_findings_are_unclear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    label_prompts = install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check"]) == EXIT_FINDINGS

    assert label_prompts == []
    err = "".join(capsys.readouterr())
    assert "UNCLEAR      app/greetings.py::greeting('Ada')" in err
    assert NO_INTENT_REASON in err


def test_malformed_labels_leave_findings_unclear_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")

    def broken(prompt: str) -> httpx.Response:
        return completion({"labels": "not a list"})

    label_prompts = install(monkeypatch, fixture.expected, broken)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--intent", fixture.expected["intent"]]) == EXIT_FINDINGS

    assert len(label_prompts) == 2  # one retry
    err = "".join(capsys.readouterr())
    assert "UNCLEAR" in err
    assert "intent labelling failed: invalid llm response" in err


def test_all_commit_messages_since_the_base_are_the_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    fixture.repository.commit("Add an exclamation mark to greetings")
    fixture.repository.write("README.md", "docs\n")
    fixture.repository.commit("Document greetings")
    label_prompts = install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--base", "HEAD~2"]) == EXIT_OK

    assert (
        "Commit messages since the base (newest first):\n- Document greetings\n\n"
        "- Add an exclamation mark to greetings" in label_prompts[0]
    )


def test_against_head_the_last_commit_message_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    label_prompts = install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    main(["check"])  # base HEAD: the uncommitted change has no message

    assert label_prompts == []


def test_cases_file_runs_are_not_labelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    cases = [{"function": "app/greetings.py::greeting", "args": ["'Ada'"]}]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    monkeypatch.chdir(fixture.repository.path)

    argv = ["check", "--cases-file", str(path), "--intent", "add an exclamation mark"]
    assert main(argv) == EXIT_FINDINGS
    assert CASES_FILE_REASON in "".join(capsys.readouterr())


def test_estimate_counts_the_labelling_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("intended_change", tmp_path / "repo")
    install(monkeypatch, fixture.expected)
    monkeypatch.chdir(fixture.repository.path)

    main(["check", "--intent", "x"])

    err = "".join(capsys.readouterr())
    assert "Estimated: up to 3 LLM calls (1 + up to 1 refinement + 1 labelling)" in err
