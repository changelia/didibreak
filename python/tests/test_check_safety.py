"""check end to end: the safety cases of the 35a audit (no LLM, --cases-file)."""

import json
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.cli import EXIT_ERROR, EXIT_OK, main

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


def limited_repository(git_repository: GitRepository) -> str:
    changed_repository(
        git_repository, "def f(x):\n    return 1\n", "def f(x):\n    return 2\n"
    )
    return write_cases(git_repository, "app/run.py::f", "1")


@pytest.mark.parametrize("flags", [["--timeout", "nan"], ["--max-cost", "inf"]])
def test_non_finite_limit_flags_exit_2_before_any_work(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
) -> None:
    # Audit 35a, finding 2: --timeout nan hid a real change and exited 0.
    cases = limited_repository(git_repository)
    monkeypatch.chdir(git_repository.path)

    with pytest.raises(SystemExit) as exit_info:
        main(["check", "--cases-file", cases, *flags])

    assert exit_info.value.code == EXIT_ERROR
    assert "must be a finite number greater than 0" in capsys.readouterr().err
    assert not (git_repository.path / ".didibreak").exists()


@pytest.mark.parametrize("line", ["timeout = nan", "max_cost = inf"])
def test_non_finite_limits_in_pyproject_exit_2_before_any_work(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    line: str,
) -> None:
    cases = limited_repository(git_repository)
    git_repository.write("pyproject.toml", f"[tool.didibreak]\n{line}\n")
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_ERROR

    assert "must be a finite number greater than 0" in capsys.readouterr().err
    assert not (git_repository.path / ".didibreak").exists()
