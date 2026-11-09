"""check writes reproducing tests that pass on the base and fail now (task 19)."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fixture_repos import build_fixture_repository, fixture_names
from test_check_end_to_end import cases_file

from didibreak.cli import main

PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def run_pytest(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*PYTEST, ".didibreak/tests"],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("case", fixture_names())
def test_generated_tests_pass_on_the_base_and_fail_on_the_change(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository(case, tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    repository = fixture.repository.path
    monkeypatch.chdir(repository)

    main(["check", "--cases-file", str(path), "--format", "json"])

    report = json.loads(capsys.readouterr().out)
    with_base = [
        f
        for f in report["findings"]
        if f["before"] is not None and f["label"] != "expected"
    ]
    assert all(f["test_file"] for f in with_base)
    others = [f for f in report["findings"] if f not in with_base]
    assert all(f["test_file"] is None for f in others)
    if not with_base:
        assert not (repository / ".didibreak" / "tests").exists()
        return
    current = run_pytest(repository)
    assert current.returncode == 1, current.stdout
    failed = re.search(r"(\d+) failed", current.stdout)
    assert failed and int(failed.group(1)) == len(with_base), current.stdout
    base = tmp_path / "base"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(base), "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    shutil.copytree(repository / ".didibreak" / "tests", base / ".didibreak" / "tests")
    on_base = run_pytest(base)
    assert on_base.returncode == 0, on_base.stdout
    assert f"{len(with_base)} passed" in on_base.stdout


def test_text_report_names_the_test_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    main(["check", "--cases-file", str(path)])

    out = capsys.readouterr().out
    assert "Reproducing tests: .didibreak/tests/test_normalize_phone.py\n" in out
    generated = fixture.repository.path / ".didibreak" / "tests"
    assert sorted(p.name for p in generated.iterdir()) == [
        "conftest.py",
        "test_normalize_phone.py",
    ]


def test_generated_tests_are_not_checked_as_changed_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)
    main(["check", "--cases-file", str(path)])
    capsys.readouterr()

    main(["check", "--cases-file", str(path)])

    assert "1 changed function(s) to check" in capsys.readouterr().out


def test_unwritable_output_folder_only_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.chdir(fixture.repository.path)

    code = main(["check", "--cases-file", str(path), "--output-dir", str(blocker)])

    captured = capsys.readouterr()
    assert code == 1
    assert "warning: could not write the reproducing tests" in captured.err
    assert "Reproducing tests" not in captured.out
