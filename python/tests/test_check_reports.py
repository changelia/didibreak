"""check prints the text report on stdout, or only the JSON report (task 18)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from fixture_repos import build_fixture_repository, fixture_names
from test_check_end_to_end import cases_file

from didibreak import __version__, cli, llm
from didibreak.cli import main
from didibreak.config import Config

SCHEMA = Path(__file__).resolve().parents[2] / "spec" / "report.schema.json"
needs_schema = pytest.mark.skipif(
    not SCHEMA.is_file(), reason="needs the full repository checkout"
)


def validate(report: Any) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)


@needs_schema
@pytest.mark.parametrize("case", fixture_names())
def test_json_stdout_is_one_valid_report(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    main(["check", "--cases-file", str(path), "--format", "json"])

    out = capsys.readouterr().out
    report = json.loads(out)
    validate(report)
    assert report["tool"] == {"name": "didibreak", "version": __version__}
    found = {(f["function"], tuple(f["args"])) for f in report["findings"]}
    documented = {
        (f["function"], tuple(f["args"])) for f in fixture.expected["findings"]
    }
    assert found == documented
    assert report["usage"]["calls"] == 0


def test_text_report_goes_to_stdout_with_the_header_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    main(["check", "--cases-file", str(path)])

    captured = capsys.readouterr()
    assert captured.out.startswith(f"didibreak {__version__} · working tree vs HEAD (")
    assert "UNCLEAR      app/utils/phone.py::normalize_phone" in captured.out
    assert "LLM:" not in captured.out  # --cases-file runs send no requests
    assert captured.err == ""


@needs_schema
def test_nothing_to_check_still_prints_a_json_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    fixture.repository.commit("commit the change")
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--format", "json"]) == 0

    report = json.loads(capsys.readouterr().out)
    validate(report)
    assert report["summary"]["functions_checked"] == 0
    assert report["findings"] == []


def test_estimate_goes_to_stderr_in_json_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    monkeypatch.chdir(fixture.repository.path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = ["'995 555 12 34 56'"]

    def handler(request: httpx.Request) -> httpx.Response:
        case = {"args": args, "kwargs": [], "rationale": "r"}
        body = {
            "choices": [
                {
                    "message": {"content": json.dumps({"cases": [case]})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 500, "completion_tokens": 100},
        }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)

    main(["check", "--format", "json"])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["usage"]["calls"] == 1
    assert report["usage"]["input_tokens"] == 500
    assert "Estimated: up to" in captured.err
    assert "sk-fake" not in captured.out + captured.err
