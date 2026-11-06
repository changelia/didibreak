"""didibreak check with --cases-file on every fixture repository (task 11)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fixture_repos import build_fixture_repository, fixture_names

from didibreak import cli, pipeline
from didibreak.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_INTERRUPTED, EXIT_OK, main
from didibreak.functions import detect_changed_functions
from didibreak.gitdiff import changed_python_files, resolve_base
from didibreak.harness import HarnessSettings, Outcome
from didibreak.pipeline import UNLABELLED, analyze, load_cases_file

CASES = fixture_names()


def cases_file(expected: dict[str, Any], destination: Path) -> Path:
    """All documented cases of a fixture, in the --cases-file format."""
    groups = ("findings", "same_behavior", "flaky_functions")
    cases = [
        {"function": item["function"], "args": item["args"], "kwargs": item["kwargs"]}
        for group in groups
        for item in expected[group]
    ]
    path = destination / "cases.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def shape(outcome: Outcome | None) -> dict[str, str] | None:
    if outcome is None:
        return None
    return {"kind": outcome.kind, "type_name": outcome.type_name, "repr": outcome.repr}


def expected_label(label: str) -> str:
    # Without intent labelling (task 17) every changed-function finding is unclear.
    return label if label == "new_function" else UNLABELLED


@pytest.mark.parametrize("case", CASES)
def test_findings_match_the_expected_file(case: str, tmp_path: Path) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    root = fixture.repository.path
    base = resolve_base(root, "HEAD")
    files = changed_python_files(root, base)
    detection = detect_changed_functions(cli.load_source_files(root, base, files), 10)
    cases = load_cases_file(cases_file(fixture.expected, tmp_path))
    settings = HarnessSettings(python=sys.executable, timeout=5.0)

    analysis = analyze(root, base, detection.functions, {}, cases, settings)

    assert [
        {
            "function": finding.function,
            "label": finding.label,
            "args": list(finding.case.args),
            "kwargs": dict(finding.case.kwargs),
            "before": shape(finding.before),
            "after": shape(finding.after),
        }
        for finding in analysis.findings
    ] == [
        {**finding, "label": expected_label(finding["label"])}
        for finding in fixture.expected["findings"]
    ]
    assert analysis.flaky_dropped == len(fixture.expected["flaky_functions"])


def exit_code_without_intent(expected: dict[str, Any]) -> int:
    # Under the default --fail-on unclear every finding fails the run: changed
    # functions are unclear without intent labelling, and new_function
    # findings fail too (owner decision 2026-11-06).
    return EXIT_FINDINGS if expected["findings"] else EXIT_OK


@pytest.mark.parametrize("case", CASES)
def test_check_exit_code_and_listing(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)
    status = fixture.repository.status()

    code = main(["check", "--cases-file", str(path)])

    assert code == exit_code_without_intent(fixture.expected)
    err = capsys.readouterr().err
    for finding in fixture.expected["findings"]:
        assert f"{finding['function']}({', '.join(finding['args'])})" in err
    assert fixture.repository.status() == status  # working tree untouched


def test_new_function_findings_fail_only_the_default_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_fixture_repository("new_function", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--cases-file", str(path)]) == EXIT_FINDINGS
    code = main(["check", "--cases-file", str(path), "--fail-on", "unexpected"])
    assert code == EXIT_OK


def test_fail_on_unexpected_ignores_unclear_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--cases-file", str(path)]) == EXIT_FINDINGS
    code = main(["check", "--cases-file", str(path), "--fail-on", "unexpected"])
    assert code == EXIT_OK


def test_listing_shows_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("exception_type", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    main(["check", "--cases-file", str(path)])

    err = capsys.readouterr().err
    assert "3 cases · 1 behavior changes · 0 flaky dropped" in err
    assert "UNCLEAR      app/parsing.py::parse_age('')" in err
    assert "before raises builtins.ValueError → after raises builtins.IndexError" in err


def test_invalid_cases_file_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    monkeypatch.chdir(fixture.repository.path)

    assert main(["check", "--cases-file", "missing.json"]) == EXIT_ERROR
    assert "cases file" in capsys.readouterr().err


def test_ctrl_c_exits_with_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)

    def interrupt(*arguments: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "analyze", interrupt)

    assert main(["check", "--cases-file", str(path)]) == EXIT_INTERRUPTED
    assert "interrupted" in capsys.readouterr().err


def test_ctrl_c_during_execution_removes_the_worktree_and_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    path = cases_file(fixture.expected, tmp_path)
    monkeypatch.chdir(fixture.repository.path)
    trees: list[Path] = []

    def interrupt(
        function: object, cases: object, both: tuple[Path, Path], *rest: object
    ) -> None:
        trees.extend(both)
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "_run", interrupt)

    assert main(["check", "--cases-file", str(path)]) == EXIT_INTERRUPTED
    assert len(trees) == 2  # the base worktree and the working-tree copy
    assert not any(tree.exists() for tree in trees)
    worktrees = fixture.repository.git("worktree", "list", "--porcelain")
    assert worktrees.count("worktree ") == 1  # only the user's own
