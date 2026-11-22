"""check on async functions: awaited, compared and reproduced (task 29)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.cli import EXIT_FINDINGS, EXIT_OK, main
from didibreak.functions import SourceFile, detect_changed_functions


def change(repository: GitRepository, before: str, after: str) -> str:
    repository.write("app/m.py", before)
    repository.commit("base")
    repository.write("app/m.py", after)
    cases = [{"function": "app/m.py::f", "args": ["-250"]}]
    return str(repository.write("cases.json", json.dumps({"cases": cases})))


def report(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    data: dict[str, object] = json.loads(capsys.readouterr().out)
    return data


ASYNC_BEFORE = "async def f(cents):\n    return f'${cents / 100:.2f}'\n"
ASYNC_AFTER = "async def f(cents):\n    return f'${abs(cents) / 100:,.2f}'\n"


def test_a_changed_async_function_is_awaited_and_its_change_found(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = change(git_repository, ASYNC_BEFORE, ASYNC_AFTER)
    monkeypatch.chdir(git_repository.path)

    code = main(["check", "--cases-file", cases, "--format", "json"])

    data = report(capsys)
    assert code == EXIT_FINDINGS
    finding = data["findings"][0]  # type: ignore[index]
    assert finding["before"]["repr"] == "'$-2.50'"
    assert finding["after"]["repr"] == "'$2.50'"
    test_file = Path(finding["test_file"])
    assert "asyncio.run(f(-250))" in test_file.read_text()


def test_the_reproducing_test_fails_on_the_change_and_passes_on_the_base(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = change(git_repository, ASYNC_BEFORE, ASYNC_AFTER)
    monkeypatch.chdir(git_repository.path)
    main(["check", "--cases-file", cases])
    capsys.readouterr()
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    tests = git_repository.path / ".didibreak" / "tests"

    on_change = subprocess.run(command, cwd=tests, capture_output=True, check=False)
    git_repository.write("app/m.py", ASYNC_BEFORE)
    on_base = subprocess.run(command, cwd=tests, capture_output=True, check=False)

    assert on_change.returncode == 1
    assert on_base.returncode == 0


def test_a_switch_from_def_to_async_def_shows_the_coroutine(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Callers of f now get a coroutine: neither version is awaited.
    cases = change(
        git_repository,
        "def f(cents):\n    return cents\n",
        "async def f(cents):\n    return cents\n",
    )
    monkeypatch.chdir(git_repository.path)

    code = main(["check", "--cases-file", cases, "--format", "json"])

    finding = report(capsys)["findings"][0]  # type: ignore[index]
    assert code == EXIT_FINDINGS
    assert finding["before"]["type_name"] == "builtins.int"
    assert finding["after"]["type_name"] == "builtins.coroutine"


def test_an_async_generator_is_still_skipped(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = change(
        git_repository,
        "async def f(cents):\n    yield cents\n",
        "async def f(cents):\n    yield -cents\n",
    )
    monkeypatch.chdir(git_repository.path)

    code = main(["check", "--cases-file", cases, "--format", "json"])

    summary = report(capsys)["summary"]
    assert code == EXIT_OK
    assert summary["skipped"] == [  # type: ignore[index]
        {"function": "app/m.py::f", "reason": "async generator"}
    ]


@pytest.mark.parametrize(
    ("before", "after", "awaited"),
    [
        (b"async def f():\n    return 1\n", b"async def f():\n    return 2\n", True),
        (None, b"async def f():\n    return 2\n", True),
        (b"def f():\n    return 1\n", b"async def f():\n    return 1\n", False),
        (b"async def f():\n    return 1\n", b"def f():\n    return 1\n", False),
        (b"def f():\n    return 1\n", b"def f():\n    return 2\n", False),
    ],
)
def test_only_functions_async_in_every_version_are_awaited(
    before: bytes | None, after: bytes, awaited: bool
) -> None:
    detection = detect_changed_functions(
        [SourceFile("app/m.py", before, after)], max_functions=10
    )

    assert [f.awaited for f in detection.functions] == [awaited]
