"""Every fixture case is well-formed, builds a repository and tells the truth.

The documented outcomes in expected.json are checked by running the fixture
functions (our own test data) directly, so later milestones can rely on them.
"""

import ast
import asyncio
import inspect
import math
from pathlib import Path
from typing import Any

import pytest
from fixture_repos import (
    FIXTURE_KEYS,
    build_fixture_repository,
    fixture_names,
    fixture_timeout,
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
    instance = None
    if "init_args" in item:  # an instance method (task 30)
        owner = load_version(case, version, file)
        for part in qualname.split(".")[:-1]:
            owner = getattr(owner, part)
        init_args = [ast.literal_eval(text) for text in item["init_args"]]
        init_kwargs = {k: ast.literal_eval(v) for k, v in item["init_kwargs"].items()}
        if qualname.endswith(".__init__"):  # the construction is the outcome
            module = file.removesuffix(".py").replace("/", ".")
            return _construct(owner, module, init_args, init_kwargs)
        instance = owner(*init_args, **init_kwargs)
        target = getattr(instance, qualname.rsplit(".", 1)[-1])
    try:
        value = target(*args, **kwargs)
        if inspect.iscoroutine(value):
            timeout = fixture_timeout(case)
            value = asyncio.run(asyncio.wait_for(value, timeout))
    except TimeoutError:
        return {
            "kind": "timeout",
            "type_name": "",
            "repr": f"<timed out after {timeout:g} s>",
        }
    except Exception as error:
        kind, result = "exception", error
    else:
        kind, result = "return", value
    result_type = type(result)
    outcome = {
        "kind": kind,
        "type_name": f"{result_type.__module__}.{result_type.__qualname__}",
        "repr": repr(result),
    }
    if instance is not None:
        outcome["state"] = _state(instance)
    return outcome


def _state(instance: object) -> str:
    # The harness's state text: the attributes sorted by name.
    attributes = sorted(vars(instance).items())
    return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in attributes) + "}"


def _construct(
    owner: Any, module: str, args: list[Any], kwargs: dict[str, Any]
) -> dict[str, str]:
    """Build the instance, as the harness checks a constructor (task 38).

    ``module`` is the class's module as the harness imports it; the fixture
    versions are loaded under other names.
    """
    try:
        instance = owner(*args, **kwargs)
    except Exception as error:
        kind = type(error)
        return {
            "kind": "exception",
            "type_name": f"{kind.__module__}.{kind.__qualname__}",
            "repr": repr(error),
        }
    return {
        "kind": "return",
        "type_name": f"{module}.{owner.__qualname__}",
        "repr": repr(instance),
        "state": _state(instance),
    }


def _same(
    before: dict[str, str], after: dict[str, str], constructor: bool = False
) -> bool:
    if before["kind"] == "timeout" or after["kind"] == "timeout":
        return before == after
    if before.get("state") != after.get("state"):
        return False
    if before["kind"] != after["kind"] or before["type_name"] != after["type_name"]:
        return False
    if before["kind"] == "exception" or ("state" in before and constructor):
        # Same exception type = same behavior (Spec comparison rules); an
        # instance is compared by its type and state only.
        return True
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
        "async_regression",
        "async_intended_change",
        "async_timeout",
        "async_exception",
        "method_regression",
        "method_state_regression",
        "dataclass_method",
        "constructor_change",
        "method_blocked",
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
        constructor = item["function"].endswith(".__init__")
        assert _same(
            _call(case, "before", item), _call(case, "after", item), constructor
        )


@pytest.mark.parametrize("case", CASES)
def test_documented_flaky_functions_change_between_runs(case: str) -> None:
    for item in load_expected(case)["flaky_functions"]:
        results = {_call(case, "after", item)["repr"] for _ in range(5)}
        assert len(results) > 1
