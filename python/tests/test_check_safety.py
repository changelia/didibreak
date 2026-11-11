"""check end to end: the safety cases of the 35a audit (no LLM, --cases-file)."""

import json
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.cli import EXIT_OK, main

NOTIFY = """import os


def notify(name):
    os.system("touch " + os.environ["MARK_DIR"] + "/ran_" + name)
    return {result}
"""


def changed_repository(repository: GitRepository, before: str, after: str) -> None:
    repository.write("app/run.py", before)
    repository.commit("base")
    repository.write("app/run.py", after)


def write_cases(repository: GitRepository, function: str, *args: str) -> str:
    cases = [{"function": function, "args": [arg], "kwargs": {}} for arg in args]
    path = repository.write("cases.json", json.dumps({"cases": cases}))
    return str(path)


def test_a_function_running_a_shell_command_is_skipped_not_run(
    git_repository: GitRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Audit 35a, finding 1: before 0.1.4 this ran os.system with the case input.
    marks = tmp_path / "marks"
    marks.mkdir()
    monkeypatch.setenv("MARK_DIR", str(marks))
    changed_repository(git_repository, NOTIFY.format(result=1), NOTIFY.format(result=2))
    cases = write_cases(git_repository, "app/run.py::notify", "'x'")
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_OK

    assert list(marks.iterdir()) == []
    assert "app/run.py::notify (obvious I/O: os.system)" in capsys.readouterr().out
