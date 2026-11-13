"""check when no changed function could be checked (audit 35a, finding 3).

Owner decision 2026-11-11 (task 35 review): exit 2 when selected functions
exist and none was checked because of an error; exit 0, with a clear text
line and ``functions_checked: 0`` in JSON, when every changed function is
skipped by design.
"""

import json
from collections.abc import Mapping

import httpx
import pytest
from conftest import GitRepository

from didibreak import cli
from didibreak.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main
from didibreak.config import Config
from didibreak.llm import client_settings
from didibreak.llm.openai_compat import OpenAICompatibleClient

NOTHING_CHECKED = "No function was checked: every changed function was skipped"


def change(repository: GitRepository, before: str, after: str) -> None:
    repository.write("app/m.py", before)
    repository.commit("base")
    repository.write("app/m.py", after)


def write_cases(repository: GitRepository, *functions: str) -> str:
    cases = [{"function": f"app/m.py::{name}", "args": ["1"]} for name in functions]
    return str(repository.write("cases.json", json.dumps({"cases": cases})))


@pytest.fixture
def unavailable_provider(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Every request gets HTTP 503; retries do not wait."""
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    def create(config: Config, environment: Mapping[str, str]) -> object:
        settings = client_settings(config, environment)
        transport = httpx.MockTransport(handler)
        return OpenAICompatibleClient(settings, transport, sleep=lambda _: None)

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return received


def test_unreachable_provider_exits_2_and_still_prints_the_report(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unavailable_provider: list[httpx.Request],
) -> None:
    # Audit 35a reproduction: this used to exit 0 with nothing checked.
    change(git_repository, "def f(x):\n    return 1\n", "def f(x):\n    return 2\n")
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--format", "json"]) == EXIT_ERROR

    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["summary"]["functions_checked"] == 0
    assert report["summary"]["skipped"] == [
        {"function": "app/m.py::f", "reason": "llm unavailable"}
    ]
    assert unavailable_provider  # requests were tried
    assert (
        "didibreak: error: no changed function could be checked: "
        "app/m.py::f (llm unavailable)"
    ) in err


def test_import_failure_of_every_selected_function_exits_2(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change(
        git_repository,
        "def f(x):\n    return 1\n",
        "raise RuntimeError('boom')\n\n\ndef f(x):\n    return 2\n",
    )
    cases = write_cases(git_repository, "f")
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_ERROR

    out, err = capsys.readouterr()
    assert NOTHING_CHECKED in out
    assert "app/m.py::f (import failed: RuntimeError" in err


def test_every_function_skipped_by_design_exits_0_and_says_so(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change(
        git_repository,
        "async def f(x):\n    return 1\n",
        "async def f(x):\n    return 2\n",
    )
    monkeypatch.chdir(git_repository.path)

    assert main(["check"]) == EXIT_OK
    out = capsys.readouterr().out
    assert NOTHING_CHECKED in out
    assert "skipped: app/m.py::f (async function)" in out

    assert main(["check", "--format", "json"]) == EXIT_OK
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary["functions_checked"] == 0
    assert summary["skipped"] == [
        {"function": "app/m.py::f", "reason": "async function"}
    ]


def test_functions_without_cases_are_not_an_error(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change(git_repository, "def f(x):\n    return 1\n", "def f(x):\n    return 2\n")
    cases = str(git_repository.write("cases.json", '{"cases": []}'))
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_OK

    assert "skipped: app/m.py::f (no cases)" in capsys.readouterr().out


def test_one_checked_function_keeps_the_normal_exit_code(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = "def f(x):\n    return 1\n\n\ndef g(x):\n    return 1\n"
    after = "def f(x):\n    return 2\n\n\ndef g(x):\n    return 2\n"
    change(git_repository, before, after)
    cases = write_cases(git_repository, "f")  # g gets no cases
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_FINDINGS

    assert "no changed function could be checked" not in capsys.readouterr().err


def test_nothing_to_check_at_all_exits_0(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_repository.write("app/m.py", "def f(x):\n    return 1\n")
    git_repository.commit("base")
    monkeypatch.chdir(git_repository.path)

    assert main(["check"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "Nothing to check" in out
    assert NOTHING_CHECKED not in out


HOSTILE = "bad \x1b[2J\x1b]0;pwned\x07 request"


def hostile_provider(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """Every request gets ``status`` with terminal escape codes in the message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": HOSTILE}})

    def create(config: Config, environment: Mapping[str, str]) -> object:
        settings = client_settings(config, environment)
        transport = httpx.MockTransport(handler)
        return OpenAICompatibleClient(settings, transport, sleep=lambda _: None)

    monkeypatch.setattr(cli, "create_client", create)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.mark.parametrize(
    ("status", "shown"),
    [
        (
            400,
            "(llm request rejected: HTTP 400: bad \\x1b[2J\\x1b]0;pwned\\x07 request)",
        ),
        (404, "(HTTP 404: bad \\x1b[2J\\x1b]0;pwned\\x07 request)"),
    ],
)
def test_provider_text_in_the_error_line_cannot_control_the_terminal(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    shown: str,
) -> None:
    # Pre-launch review, finding 11: the exit-2 line and the 404 message
    # printed the provider's escape codes as they were.
    change(git_repository, "def f(x):\n    return 1\n", "def f(x):\n    return 2\n")
    hostile_provider(monkeypatch, status)
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--format", "json"]) == EXIT_ERROR

    err = capsys.readouterr().err
    assert "\x1b" not in err and "\x07" not in err
    assert shown in err
    assert err.count("\n") == err.count("didibreak: ") + err.count("Estimated: ")
