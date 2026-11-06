"""Analysis pipeline: run the cases of each changed function on both versions.

Wires the base worktree, a temporary copy of the working tree, the harness
and the comparison rules together for ``didibreak check``. Cases come from
the hidden developer option ``--cases-file`` until LLM case generation
exists (task 14).
"""

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from didibreak.cases import (
    CASES_SCHEMA,
    CASES_SCHEMA_NAME,
    PromptTemplate,
    accept_cases,
    build_messages,
)
from didibreak.compare import Comparison, Finding, compare_cases
from didibreak.config import ConfigError, find_pyproject
from didibreak.functions import ChangedFunction, import_root, module_name
from didibreak.gitdiff import base_worktree, working_tree_copy
from didibreak.harness import Case, HarnessSettings, Target, run_cases
from didibreak.llm.common import (
    LLMClient,
    LLMInvalidResponseError,
    LLMUnavailableError,
    TokenUsage,
)

NO_CASES_REASON = "no cases"
# Skip reasons for case generation (Detailed Design section 10).
INVALID_RESPONSE_REASON = "invalid llm response"
UNAVAILABLE_REASON = "llm unavailable"
NO_VALID_CASES_REASON = "no valid cases"
# Until intent labelling exists (task 17), the relation of a finding to the
# intent cannot be decided: "unclear" (Detailed Design section 5.3).
UNLABELLED = "unclear"


def _case(item: object, number: int) -> tuple[str, Case]:
    where = f"case {number}"
    if not isinstance(item, dict):
        raise ValueError(f"{where}: expected an object")
    function = item.get("function")
    if not isinstance(function, str) or "::" not in function:
        raise ValueError(f'{where}: "function" must be "path/to/file.py::name"')
    args = item.get("args", [])
    kwargs = item.get("kwargs", {})
    rationale = item.get("rationale", "")
    if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        raise ValueError(f'{where}: "args" must be a list of strings')
    if not (
        isinstance(kwargs, dict) and all(isinstance(v, str) for v in kwargs.values())
    ):
        raise ValueError(f'{where}: "kwargs" must map names to strings')
    if not isinstance(rationale, str):
        raise ValueError(f'{where}: "rationale" must be a string')
    for text in (*args, *kwargs.values()):
        try:
            ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            raise ValueError(f"{where}: not a Python literal: {text!r}") from None
    return function, Case(tuple(args), dict(kwargs), rationale)


def load_cases_file(path: Path) -> Mapping[str, tuple[Case, ...]]:
    """Read cases from a JSON file (hidden developer option ``--cases-file``).

    The format is the case-generation schema (Detailed Design section 5.1)
    with a ``function`` key per case::

        {"cases": [{"function": "app/phone.py::normalize_phone",
                    "args": ["'995 555 12 34 56'"], "kwargs": {},
                    "rationale": "country code without plus"}]}

    Args:
        path: The JSON file.

    Returns:
        Cases by report name, in file order.

    Raises:
        ConfigError: If the file cannot be read or is not valid; the message
            names the file and the case.
    """
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"cases file {path}: cannot read it: {error}") from None
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ConfigError(f'cases file {path}: expected {{"cases": [...]}}')
    cases: dict[str, list[Case]] = {}
    for number, item in enumerate(data["cases"], start=1):
        try:
            function, case = _case(item, number)
        except ValueError as error:
            raise ConfigError(f"cases file {path}: {error}") from None
        cases.setdefault(function, []).append(case)
    return {function: tuple(items) for function, items in cases.items()}


@dataclass(frozen=True)
class Analysis:
    """Result of running and comparing all changed functions.

    Attributes:
        findings: Behavior differences, by function then case order.
        checked: Functions whose cases ran on both versions.
        skipped: Functions that could not be run, with ``skip_reason`` set.
        cases_run: Cases run for the checked functions.
        flaky_dropped: Cases dropped as flaky.
        timeouts_dropped: Cases dropped because both versions timed out.
    """

    findings: tuple[Finding, ...]
    checked: tuple[ChangedFunction, ...]
    skipped: tuple[ChangedFunction, ...]
    cases_run: int
    flaky_dropped: int
    timeouts_dropped: int


def tree_import_root(tree: Path, path: str) -> str:
    """Import root of a file inside one tree (Detailed Design section 3).

    Args:
        tree: Root of the tree (repository, worktree or copy).
        path: Tree-relative POSIX path of the file.

    Returns:
        Tree-relative import root; ``""`` is the tree itself.
    """
    pyproject = find_pyproject((tree / path).parent, stop=tree)
    project = None if pyproject is None else pyproject.parent.relative_to(tree)
    folder = None if project is None else project.as_posix()
    return import_root(path, "" if folder == "." else folder)


def _target(tree: Path, path: str, qualname: str) -> Target:
    root = tree_import_root(tree, path)
    return Target(tree, tree / root, module_name(path, root), qualname)


def _run(
    function: ChangedFunction,
    cases: Sequence[Case],
    trees: tuple[Path, Path],
    base_path: str,
    settings: HarnessSettings,
) -> Comparison | str:
    """Run one function on both versions; a str is the skip reason."""
    base_tree, current_tree = trees
    before = None
    if function.kind == "changed":
        base = run_cases(
            _target(base_tree, base_path, function.qualname), cases, settings
        )
        if base.skip_reason is not None:
            return f"{base.skip_reason} (base version)"
        before = base.outcomes
    current_target = _target(current_tree, function.file, function.qualname)
    current = run_cases(current_target, cases, settings)
    if current.skip_reason is not None:
        return current.skip_reason
    return compare_cases(
        function.report_name, cases, before, current.outcomes, function.raised_types
    )


def analyze(
    root: Path,
    base_sha: str,
    functions: Sequence[ChangedFunction],
    base_paths: Mapping[str, str],
    cases: Mapping[str, Sequence[Case]],
    settings: HarnessSettings,
    skip: Sequence[str] = (),
) -> Analysis:
    """Run every function's cases on the base and the current version.

    The base version runs from a temporary git worktree, the current version
    from a temporary copy of the working tree; the user's working tree is
    never executed or written. Both are removed afterwards.

    Args:
        root: Repository root.
        base_sha: Base commit.
        functions: Testable changed and new functions from detection.
        base_paths: Base path of each working-tree file, for renamed files.
        cases: Cases by report name.
        settings: Harness settings.
        skip: Repository-relative folders not copied (the output folder).

    Returns:
        Findings (unlabelled ones as ``unclear``) and counts.

    Raises:
        GitError: If the base worktree or the copy cannot be created.
        OSError: If a file cannot be copied.
    """
    if not functions:  # nothing to run: no worktree, no copy
        return Analysis((), (), (), 0, 0, 0)
    comparisons: list[Comparison] = []
    checked: list[ChangedFunction] = []
    skipped: list[ChangedFunction] = []
    with base_worktree(root, base_sha) as base, working_tree_copy(root, skip) as copy:
        for function in functions:
            function_cases = cases.get(function.report_name, ())
            if not function_cases:
                skipped.append(replace(function, skip_reason=NO_CASES_REASON))
                continue
            base_path = base_paths.get(function.file, function.file)
            result = _run(function, function_cases, (base, copy), base_path, settings)
            if isinstance(result, str):
                skipped.append(replace(function, skip_reason=result))
            else:
                checked.append(function)
                comparisons.append(result)
    return Analysis(
        findings=tuple(
            finding if finding.label else replace(finding, label=UNLABELLED)
            for comparison in comparisons
            for finding in comparison.findings
        ),
        checked=tuple(checked),
        skipped=tuple(skipped),
        cases_run=sum(comparison.cases_run for comparison in comparisons),
        flaky_dropped=sum(comparison.flaky_dropped for comparison in comparisons),
        timeouts_dropped=sum(c.timeouts_dropped for c in comparisons),
    )


@dataclass(frozen=True)
class Generation:
    """Cases the LLM proposed for the changed functions.

    Attributes:
        cases: Accepted cases by report name; functions without any are in
            ``skipped``.
        skipped: Functions without cases, with ``skip_reason`` set.
        invalid_cases_dropped: Cases rejected by cases.accept_cases.
        usage: Token usage of all calls, failed ones included.
    """

    cases: Mapping[str, tuple[Case, ...]]
    skipped: tuple[ChangedFunction, ...]
    invalid_cases_dropped: int
    usage: TokenUsage


def generate_cases(
    client: LLMClient,
    functions: Sequence[ChangedFunction],
    count: int,
    template: PromptTemplate,
) -> Generation:
    """Ask the LLM for cases for each function and keep the valid ones.

    Args:
        client: The configured LLM client.
        functions: Testable changed and new functions.
        count: Cases to request per function (``cases``).
        template: The case generation prompt template.

    Returns:
        Accepted cases, skipped functions and usage. An invalid reply (after
        the client's one retry) skips that function; an unavailable provider
        skips it and all remaining functions.

    Raises:
        LLMAuthError: The key was rejected.
        LLMModelError: The model was not found.
        LLMRequestError: The provider rejected the request.
    """
    cases: dict[str, tuple[Case, ...]] = {}
    skipped: list[ChangedFunction] = []
    invalid = 0
    usage = TokenUsage()
    for index, function in enumerate(functions):
        messages = build_messages(function, count, template)
        try:
            reply = client.complete_json(messages, CASES_SCHEMA, CASES_SCHEMA_NAME)
        except LLMInvalidResponseError as error:
            usage += error.usage
            skipped.append(replace(function, skip_reason=INVALID_RESPONSE_REASON))
            continue
        except LLMUnavailableError:
            skipped += [
                replace(rest, skip_reason=UNAVAILABLE_REASON)
                for rest in functions[index:]
            ]
            break
        usage += reply.usage
        batch = accept_cases(reply.data, count, function.report_name)
        invalid += batch.invalid
        if batch.cases:
            cases[function.report_name] = batch.cases
        else:
            skipped.append(replace(function, skip_reason=NO_VALID_CASES_REASON))
    return Generation(cases, tuple(skipped), invalid, usage)
