"""Harness plus comparison rules on every fixture case reproduce expected.json."""

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from fixture_repos import FIXTURES_DIR, fixture_names, load_expected

from didibreak.compare import NEW_FUNCTION_LABEL, Comparison, compare_cases
from didibreak.functions import module_name
from didibreak.harness import Case, HarnessSettings, Outcome, Target, run_cases

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)


def copy_tree(name: str, version: str, destination: Path) -> Path:
    tree = destination / version
    shutil.copytree(
        FIXTURES_DIR / name / version,
        tree,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return tree


def run_version(tree: Path, function: str, cases: list[Case]) -> list[Outcome]:
    path, qualname = function.split("::")
    target = Target(tree, tree, module_name(path), qualname)
    result = run_cases(target, cases, SETTINGS)
    assert result.skip_reason is None
    return list(result.outcomes)


def compare_fixture(
    name: str, tmp_path: Path
) -> dict[str, tuple[list[Case], Comparison]]:
    expected = load_expected(name)
    before_tree = copy_tree(name, "before", tmp_path)
    after_tree = copy_tree(name, "after", tmp_path)
    groups = ("findings", "same_behavior", "flaky_functions")
    cases: dict[str, list[Case]] = {}
    for entry in (entry for group in groups for entry in expected[group]):
        case = Case(tuple(entry["args"]), entry["kwargs"])
        cases.setdefault(entry["function"], []).append(case)
    new = {
        item["function"]
        for item in expected["changed_functions"]
        if item["kind"] == "new"
    }
    results = {}
    for function, function_cases in cases.items():
        before = (
            None
            if function in new
            else run_version(before_tree, function, function_cases)
        )
        after = run_version(after_tree, function, function_cases)
        results[function] = (
            function_cases,
            compare_cases(function, function_cases, before, after),
        )
    return results


def shape(outcome: Outcome | None) -> dict[str, str] | None:
    if outcome is None:
        return None
    return {"kind": outcome.kind, "type_name": outcome.type_name, "repr": outcome.repr}


@pytest.mark.parametrize("name", fixture_names())
def test_fixture_findings_match_expected_json(name: str, tmp_path: Path) -> None:
    expected = load_expected(name)

    results = compare_fixture(name, tmp_path)

    found: list[dict[str, Any]] = [
        {
            "function": finding.function,
            "args": list(finding.case.args),
            "kwargs": dict(finding.case.kwargs),
            "before": shape(finding.before),
            "after": shape(finding.after),
        }
        for _, comparison in results.values()
        for finding in comparison.findings
    ]
    wanted = [
        {key: entry[key] for key in ("function", "args", "kwargs", "before", "after")}
        for entry in expected["findings"]
    ]
    assert found == wanted


@pytest.mark.parametrize("name", fixture_names())
def test_fixture_flaky_cases_are_dropped(name: str, tmp_path: Path) -> None:
    expected = load_expected(name)

    results = compare_fixture(name, tmp_path)

    dropped = sum(comparison.flaky_dropped for _, comparison in results.values())
    assert dropped == len(expected["flaky_functions"])


def test_new_function_findings_carry_the_new_function_label(tmp_path: Path) -> None:
    results = compare_fixture("new_function", tmp_path)

    labels = {
        finding.label
        for _, comparison in results.values()
        for finding in comparison.findings
    }
    assert labels == {NEW_FUNCTION_LABEL}
