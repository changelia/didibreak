"""Fixture repositories with seeded behavior changes, for tests of every stage.

Each folder in ``tests/fixtures/`` holds one case:

- ``before/`` — files committed as the base version (``HEAD``);
- ``after/`` — the working tree, left uncommitted;
- ``expected.json`` — what didibreak should report (see FIXTURE_KEYS).

``build_fixture_repository`` turns a case into a real git repository, so a
test can run ``didibreak check`` (default base ``HEAD``) inside it.
"""

import importlib.util
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from conftest import GitRepository

from didibreak.functions import ChangedFunction, SourceFile, detect_changed_functions
from didibreak.harness import Case, case_call

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
# Per-case timeout for tests that run the harness directly; a case can set
# its own in [tool.didibreak] of before/pyproject.toml (async_timeout does).
DEFAULT_TIMEOUT = 5.0

# Keys of expected.json and what they mean.
FIXTURE_KEYS = {
    "description": "What the change does and why the case exists.",
    "intent": "Intent text to pass with --intent; null for none.",
    "changed_functions": "Testable functions detection must report: function, kind.",
    "skipped_functions": "Functions detection must skip: function, reason.",
    "findings": "Behavior differences to report: function, label, args, kwargs, "
    "before, after (outcomes as in the JSON report; before is null for new "
    "functions). An instance method's entries also have init_args and "
    "init_kwargs, and its outcomes a state, as in the JSON report.",
    "same_behavior": "Cases that must not produce a finding: function, args, "
    "kwargs. For a changed function both versions behave the same; for a new "
    "function the case returns or raises an exception type the function raises "
    "explicitly.",
    "flaky_functions": "Functions whose result changes between runs: function, "
    "args, kwargs; such cases are dropped as flaky.",
}


@dataclass(frozen=True)
class FixtureRepository:
    """A fixture case materialized as a git repository."""

    name: str
    repository: GitRepository
    expected: dict[str, Any]


def fixture_names() -> list[str]:
    """Names of all fixture cases, sorted."""
    return sorted(
        path.name
        for path in FIXTURES_DIR.iterdir()
        if (path / "expected.json").is_file()
    )


def load_expected(name: str) -> dict[str, Any]:
    """Read a case's expected.json."""
    path = FIXTURES_DIR / name / "expected.json"
    expected: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return expected


def build_fixture_repository(name: str, destination: Path) -> FixtureRepository:
    """Create a git repository: ``before/`` committed, ``after/`` uncommitted.

    Files that exist only in ``before/`` are deleted from the working tree.

    Args:
        name: Fixture case name.
        destination: Folder for the new repository (must not exist yet).

    Returns:
        The repository and the case's expectations.
    """
    case = FIXTURES_DIR / name
    repository = GitRepository(destination)
    shutil.copytree(case / "before", destination, dirs_exist_ok=True)
    repository.commit(f"base version of fixture {name}")
    for path in (case / "before").rglob("*"):
        if path.is_file():
            (destination / path.relative_to(case / "before")).unlink()
    shutil.copytree(case / "after", destination, dirs_exist_ok=True)
    return FixtureRepository(name, repository, load_expected(name))


def fixture_timeout(name: str) -> float:
    """The case's ``timeout`` from before/pyproject.toml, or DEFAULT_TIMEOUT."""
    path = FIXTURES_DIR / name / "before" / "pyproject.toml"
    if not path.is_file():
        return DEFAULT_TIMEOUT
    settings = tomllib.loads(path.read_text(encoding="utf-8"))
    return float(settings.get("tool", {}).get("didibreak", {}).get("timeout"))


def detected(name: str, function: str) -> ChangedFunction | None:
    """The fixture function as detection reports it, or None."""
    file, _, qualname = function.partition("::")
    before = FIXTURES_DIR / name / "before" / file
    after = FIXTURES_DIR / name / "after" / file
    old = before.read_bytes() if before.is_file() else None
    detection = detect_changed_functions(
        [SourceFile(file, old, after.read_bytes())], max_functions=50
    )
    found = [f for f in detection.functions if f.qualname == qualname]
    return found[0] if found else None


def is_awaited(name: str, function: str) -> bool:
    """Whether detection marks a fixture function as awaited (task 29)."""
    found = detected(name, function)
    return found is not None and found.awaited


def is_method(name: str, function: str) -> bool:
    """Whether a fixture function is an instance method (task 30)."""
    found = detected(name, function)
    return found is not None and found.function_type == "method"


def entry_case(entry: dict[str, Any]) -> Case:
    """The Case of a documented entry, with constructor arguments if any."""
    case = Case(tuple(entry["args"]), entry["kwargs"])
    if "init_args" not in entry:
        return case
    return Case(
        case.args, case.kwargs, "", tuple(entry["init_args"]), entry["init_kwargs"]
    )


def load_version(name: str, version: str, file: str) -> ModuleType:
    """Import one file of a case's ``before`` or ``after`` tree by path.

    Only for fixture code, which is part of this test suite.

    Args:
        name: Fixture case name.
        version: ``before`` or ``after``.
        file: Repository-relative path of the module.

    Returns:
        The imported module.
    """
    path = FIXTURES_DIR / name / version / file
    module_name = (
        f"fixture_{name}_{version}_{file.replace('/', '_').removesuffix('.py')}"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def documented_call(entry: dict[str, Any]) -> str:
    """The call of a documented entry as the text report prints it."""
    return case_call(entry["function"], entry_case(entry))


def documented_cases(expected: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The documented cases of a fixture as a fake LLM reply, by function."""
    by_function: dict[str, list[dict[str, Any]]] = {}
    for group in ("findings", "same_behavior", "flaky_functions"):
        for item in expected[group]:
            pairs = [{"name": k, "value": v} for k, v in item["kwargs"].items()]
            case = {"args": item["args"], "kwargs": pairs, "rationale": "fixture"}
            if "init_args" in item:  # an instance method (task 30)
                case["init_args"] = item["init_args"]
                case["init_kwargs"] = [
                    {"name": k, "value": v} for k, v in item["init_kwargs"].items()
                ]
            by_function.setdefault(item["function"], []).append(case)
    return by_function
