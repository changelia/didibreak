"""Every fixture case is well-formed, builds a repository and tells the truth.

The documented outcomes in expected.json are checked by running the fixture
functions (our own test data) directly, so later milestones can rely on them.
"""

import ast
import math
from pathlib import Path
from typing import Any

import pytest
from fixture_repos import (
    FIXTURE_KEYS,
    build_fixture_repository,
    fixture_names,
    load_expected,
    load_version,
)

from didibreak.cli import load_source_files
from didibreak.functions import detect_changed_functions
from didibreak.gitdiff import changed_python_files, resolve_base

LABELS = {"expected", "unexpected", "unclear", "new_function"}
CASES = fixture_names()


def _call(case: str, version: str, item: dict[str, Any]) -> dict[str, str]:
    """Run one documented call and return its outcome like the JSON report."""
    file, _, qualname = item["function"].partition("::")
    target: Any = load_version(case, version, file)
    for part in qualname.split("."):
        target = getattr(target, part)
    args = [ast.literal_eval(text) for text in item["args"]]
    kwargs = {key: ast.literal_eval(text) for key, text in item["kwargs"].items()}
    try:
        value = target(*args, **kwargs)
    except Exception as error:
        kind, result = "exception", error
    else:
        kind, result = "return", value
    result_type = type(result)
    return {
        "kind": kind,
        "type_name": f"{result_type.__module__}.{result_type.__qualname__}",
        "repr": repr(result),
    }


def _same(before: dict[str, str], after: dict[str, str]) -> bool:
    if before["kind"] != after["kind"] or before["type_name"] != after["type_name"]:
        return False
    if before["kind"] == "exception":
        return True  # same exception type = same behavior (Spec comparison rules)
    if before["type_name"] == "builtins.float":
        return math.isclose(
            float(before["repr"]), float(after["repr"]), rel_tol=1e-9, abs_tol=1e-12
        )
    return before["repr"] == after["repr"]


def test_the_required_cases_exist() -> None:
    assert set(CASES) >= {
        "phone_regression",
        "intended_change",
        "formatting_only",
        "new_function",
        "float_precision",
        "nondeterministic",
        "exception_type",
    }


@pytest.mark.parametrize("case", CASES)
def test_expected_file_is_complete(case: str) -> None:
    expected = load_expected(case)

    assert set(expected) == set(FIXTURE_KEYS)
    for finding in expected["findings"]:
        assert finding["label"] in LABELS
        assert (finding["before"] is None) == (finding["label"] == "new_function")
        assert {"kind", "type_name", "repr"} <= set(finding["after"])


@pytest.mark.parametrize("case", CASES)
def test_repository_has_the_base_commit_and_the_changed_working_tree(
    case: str, tmp_path: Path
) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    root = fixture.repository.path

    assert fixture.repository.git("rev-list", "--count", "HEAD").strip() == "1"
    for item in fixture.expected["changed_functions"]:
        file = item["function"].partition("::")[0]
        after = Path(__file__).parent / "fixtures" / case / "after" / file
        assert (root / file).read_text() == after.read_text()


@pytest.mark.parametrize("case", CASES)
def test_detection_reports_the_expected_functions(case: str, tmp_path: Path) -> None:
    fixture = build_fixture_repository(case, tmp_path / case)
    root = fixture.repository.path
    base = resolve_base(root, "HEAD")

    sources = load_source_files(root, base, changed_python_files(root, base))
    detection = detect_changed_functions(sources, max_functions=50)

    assert [
        {"function": f.report_name, "kind": f.kind} for f in detection.functions
    ] == fixture.expected["changed_functions"]
    assert [
        {"function": f.report_name, "reason": f.skip_reason} for f in detection.skipped
    ] == fixture.expected["skipped_functions"]


@pytest.mark.parametrize("case", CASES)
def test_documented_findings_are_real_behavior_differences(case: str) -> None:
    for finding in load_expected(case)["findings"]:
        after = _call(case, "after", finding)
        assert after == finding["after"]
        if finding["before"] is not None:
            before = _call(case, "before", finding)
            assert before == finding["before"]
            assert not _same(before, after)


@pytest.mark.parametrize("case", CASES)
def test_documented_same_behavior_cases_do_not_differ(case: str) -> None:
    expected = load_expected(case)
    new = {f["function"] for f in expected["changed_functions"] if f["kind"] == "new"}
    for item in expected["same_behavior"]:
        if item["function"] in new:
            # No base version; test_compare_fixtures checks there is no finding.
            continue
        assert _same(_call(case, "before", item), _call(case, "after", item))


@pytest.mark.parametrize("case", CASES)
def test_documented_flaky_functions_change_between_runs(case: str) -> None:
    for item in load_expected(case)["flaky_functions"]:
        results = {_call(case, "after", item)["repr"] for _ in range(5)}
        assert len(results) > 1
