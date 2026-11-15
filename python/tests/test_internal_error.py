"""check: an unexpected exception is an internal error with exit code 2.

Pre-launch review, finding 9: such an exception left with a traceback and
exit code 1, which means "findings" to the agents that read it.
"""

import json

import pytest
from conftest import GitRepository

from didibreak import cli
from didibreak.cli import (
    EXIT_ERROR,
    EXIT_FINDINGS,
    ISSUES_URL,
    internal_error_message,
    main,
    without_secrets,
)

SECRET = "FAKE-db-secret-123"


@pytest.fixture
def cases(git_repository: GitRepository, monkeypatch: pytest.MonkeyPatch) -> str:
    """A repository with one changed function and a cases file for it."""
    git_repository.write("app/run.py", "def f(x):\n    return 1\n")
    git_repository.commit("base")
    git_repository.write("app/run.py", "def f(x):\n    return 2\n")
    case = {"function": "app/run.py::f", "args": ["1"], "kwargs": {}}
    path = git_repository.write("cases.json", json.dumps({"cases": [case]}))
    monkeypatch.chdir(git_repository.path)
    return str(path)


def broken(*arguments: object) -> None:
    raise RuntimeError(f"boom \x1b[2J with {SECRET}")


def test_an_unexpected_exception_exits_2_with_one_line(
    cases: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "analyze", broken)
    monkeypatch.setenv("DB_PASSWORD", SECRET)

    code = main(["check", "--cases-file", cases, "--format", "json"])

    out, err = capsys.readouterr()
    assert code == EXIT_ERROR
    assert out == ""
    assert err.count("\n") == 1
    assert err.startswith("didibreak: error: internal error (RuntimeError: boom ")
    assert "This is a bug in didibreak, not a finding in your code" in err
    assert ISSUES_URL in err
    assert "Traceback" not in err
    assert "\x1b" not in err and SECRET not in err
    assert "\\x1b[2J with [redacted]" in err


def test_verbose_adds_the_traceback_without_secrets(
    cases: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "analyze", broken)
    monkeypatch.setenv("DB_PASSWORD", SECRET)

    assert main(["check", "--cases-file", cases, "-v"]) == EXIT_ERROR

    err = capsys.readouterr().err
    assert "Traceback (most recent call last):" in err
    assert "in broken" in err
    assert "\x1b" not in err and SECRET not in err
    assert err.rstrip().splitlines()[-1].startswith("didibreak: error: internal error")


def test_an_exception_while_loading_the_configuration_is_internal_too(
    cases: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_config", broken)

    assert main(["check", "--cases-file", cases]) == EXIT_ERROR

    assert "internal error (RuntimeError" in capsys.readouterr().err


def test_without_the_fault_the_same_run_reports_its_finding(cases: str) -> None:
    assert main(["check", "--cases-file", cases]) == EXIT_FINDINGS


def test_only_credential_like_values_are_removed() -> None:
    environment = {"DB_PASSWORD": SECRET, "EDITOR": "vim-editor", "API_KEY": "short"}

    cleaned = without_secrets(f"{SECRET} vim-editor short", environment)

    assert cleaned == "[redacted] vim-editor short"


def test_a_long_exception_message_is_cut() -> None:
    message = internal_error_message(ValueError("x" * 5000), {})

    assert len(message) < 700
    assert message.startswith("internal error (ValueError: xxx")
