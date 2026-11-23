"""Analysis pipeline: run the cases of each changed function on both versions.

Wires the base worktree, a temporary copy of the working tree, the harness
and the comparison rules together for ``didibreak check``, and generates
cases with the LLM under the run's budget (cost and token limits). Cases
can also come from the hidden developer option ``--cases-file``.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from didibreak.arguments import case_problem, normalized_case
from didibreak.cases import (
    CASES_SCHEMA,
    CASES_SCHEMA_NAME,
    MAX_PREVIOUS_CASES,
    CaseBatch,
    CaseRun,
    PromptTemplate,
    accept_cases,
    build_messages,
    build_refinement_messages,
    cases_schema,
    is_constructor,
    is_method,
)
from didibreak.compare import (
    Comparison,
    Finding,
    compare_cases,
    constructor_findings,
    finding_id,
)
from didibreak.config import ConfigError, find_pyproject
from didibreak.contracts import case_contradicts
from didibreak.functions import ChangedFunction, import_root, module_name
from didibreak.gitdiff import base_worktree, working_tree_copy
from didibreak.harness import (
    Case,
    HarnessSettings,
    Outcome,
    Target,
    check_import,
    run_cases,
)
from didibreak.llm.common import (
    CHARS_PER_TOKEN,
    MAX_OUTPUT_TOKENS,
    LLMClient,
    LLMInvalidResponseError,
    LLMReply,
    LLMRequestError,
    LLMUnavailableError,
    Message,
    TokenUsage,
)
from didibreak.llm.pricing import Price, cost_usd

NO_CASES_REASON = "no cases"
# Skip reasons for case generation (Detailed Design section 10).
INVALID_RESPONSE_REASON = "invalid llm response"
UNAVAILABLE_REASON = "llm unavailable"
NO_VALID_CASES_REASON = "no valid cases"
NO_NEW_CASES_REASON = "no new cases"  # refinement proposed only tried cases
REQUEST_REJECTED_PREFIX = "llm request rejected: "
# Label of a changed-function finding before intent labelling runs (and
# when it cannot run): its relation to the intent is not decided yet.
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
    problem = case_problem(args, kwargs)
    if problem is not None:
        raise ValueError(f"{where}: {problem}")
    case = Case(*normalized_case(args, kwargs), rationale)
    if "init_args" in item or "init_kwargs" in item:
        case = _with_constructor(case, item, where)
    return function, case


def _with_constructor(case: Case, item: dict[str, Any], where: str) -> Case:
    # A method case (task 30): the class is built with these arguments.
    init_args = item.get("init_args", [])
    init_kwargs = item.get("init_kwargs", {})
    if not (isinstance(init_args, list) and all(isinstance(a, str) for a in init_args)):
        raise ValueError(f'{where}: "init_args" must be a list of strings')
    if not (
        isinstance(init_kwargs, dict)
        and all(isinstance(v, str) for v in init_kwargs.values())
    ):
        raise ValueError(f'{where}: "init_kwargs" must map names to strings')
    problem = case_problem(init_args, init_kwargs)
    if problem is not None:
        raise ValueError(f"{where}: constructor argument: {problem}")
    positional, keywords = normalized_case(init_args, init_kwargs)
    return replace(case, init_args=positional, init_kwargs=keywords)


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
        type_mismatch_dropped: Findings dropped because their inputs
            contradict the function's type annotations (task 21a).
        construction_dropped: Method cases dropped because the instance
            could not be built in either version (task 30); a case built in
            one version only is a ``Class.__init__`` finding instead (task
            38).
        runs: Every case run, with both outcomes, by report name (input for
            the refinement round).
    """

    findings: tuple[Finding, ...]
    checked: tuple[ChangedFunction, ...]
    skipped: tuple[ChangedFunction, ...]
    cases_run: int
    flaky_dropped: int
    timeouts_dropped: int
    runs: Mapping[str, tuple[CaseRun, ...]] = field(default_factory=dict)
    type_mismatch_dropped: int = 0
    construction_dropped: int = 0


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


def _target(tree: Path, path: str, function: ChangedFunction) -> Target:
    root = tree_import_root(tree, path)
    module = module_name(path, root)
    return Target(
        tree,
        tree / root,
        module,
        function.qualname,
        function.awaited,
        is_method(function),
    )


CONSTRUCTION_FAILED_PREFIX = "construction failed: "
CONSTRUCTOR_CHANGED_REASON = (
    "constructor changed: no constructor arguments work in both versions"
)


def _construction_reason(
    function: ChangedFunction,
    before: Sequence[Outcome] | None,
    after: Sequence[Outcome],
) -> str:
    """Why a method whose instance was never built in both versions is skipped."""
    in_base = [o for o in before or () if o.construction_failed]
    in_current = [o for o in after if o.construction_failed]
    changed = before is not None and function.constructor != function.base_constructor
    if changed and len(in_base) < len(after) and len(in_current) < len(after):
        # Some arguments built each version, but never the same ones.
        return CONSTRUCTOR_CHANGED_REASON
    failed = in_current or in_base
    name = failed[0].type_name.rpartition(".")[2]
    where = " (base version)" if not in_current else ""
    return f"{CONSTRUCTION_FAILED_PREFIX}{name}{where}"


def _built_cases(
    function: ChangedFunction,
    cases: Sequence[Case],
    before: Sequence[Outcome] | None,
    after: Sequence[Outcome],
) -> tuple[list[int], str | None]:
    """Indexes of method cases whose instance was built in every version.

    Returns:
        The kept indexes, and a skip reason when none is left.
    """
    kept = [
        index
        for index in range(len(cases))
        if not after[index].construction_failed
        and not (before is not None and before[index].construction_failed)
    ]
    if kept or not cases:
        return kept, None
    return kept, _construction_reason(function, before, after)


def _unique_cases(function: ChangedFunction, cases: Sequence[Case]) -> list[Case]:
    # Cases that differ only in their (ignored) call arguments run once.
    kept: dict[str, Case] = {}
    for case in cases:
        kept.setdefault(finding_id(function.report_name, case), case)
    return list(kept.values())


@dataclass(frozen=True)
class _FunctionRun:
    """One function run on both versions.

    Attributes:
        skip_reason: Why the function was not compared, or None.
        comparison: Its comparison when it was compared.
        runs: Every compared case with both outcomes.
        constructor_findings: For a method, cases whose instance was built
            in one version only (task 38); reported even when the method
            itself is skipped.
    """

    skip_reason: str | None
    comparison: Comparison | None = None
    runs: tuple[CaseRun, ...] = ()
    constructor_findings: tuple[Finding, ...] = ()


def _run(
    function: ChangedFunction,
    cases: Sequence[Case],
    trees: tuple[Path, Path],
    base_path: str,
    settings: HarnessSettings,
) -> _FunctionRun:
    """Run one function on both versions and compare the outcomes.

    For an instance method, a case whose instance could not be built in
    one version or both is not compared (task 30); one built in one
    version only is a constructor finding (task 38). When no case is left,
    the method is skipped with the reason.
    """
    base_tree, current_tree = trees
    if is_method(function):
        cases = [c if c.is_method_case else replace(c, init_args=()) for c in cases]
    if is_constructor(function):  # only the constructor arguments matter
        cases = _unique_cases(function, [replace(c, args=(), kwargs={}) for c in cases])
    before = None
    if function.kind == "changed":
        base = run_cases(_target(base_tree, base_path, function), cases, settings)
        if base.skip_reason is not None:
            return _FunctionRun(f"{base.skip_reason} (base version)")
        before = base.outcomes
    current_target = _target(current_tree, function.file, function)
    current = run_cases(current_target, cases, settings)
    if current.skip_reason is not None:
        return _FunctionRun(current.skip_reason)
    after = current.outcomes
    if not is_method(function) or is_constructor(function):
        # For __init__ a failed construction is the outcome to compare.
        return _compared(function, cases, before, after)
    constructors = (
        ()
        if before is None
        else constructor_findings(function.report_name, cases, before, after)
    )
    built, reason = _built_cases(function, cases, before, after)
    if reason is not None:
        return _FunctionRun(reason, constructor_findings=constructors)
    failed_in_both = sum(
        1
        for index in range(len(cases))
        if after[index].construction_failed
        and (before is None or before[index].construction_failed)
    )
    olds = None if before is None else tuple(before[index] for index in built)
    result = _compared(
        function,
        [cases[index] for index in built],
        olds,
        tuple(after[index] for index in built),
    )
    assert result.comparison is not None
    comparison = replace(result.comparison, construction_dropped=failed_in_both)
    return replace(result, comparison=comparison, constructor_findings=constructors)


def _compared(
    function: ChangedFunction,
    cases: Sequence[Case],
    before: Sequence[Outcome] | None,
    after: Sequence[Outcome],
) -> _FunctionRun:
    comparison = compare_cases(
        function.report_name, cases, before, after, function.raised_types
    )
    # Inputs outside the annotated contract rarely matter (task 21: all 25
    # false alarms); their findings are dropped and counted.
    kept = tuple(
        f for f in comparison.findings if not case_contradicts(function, f.case)
    )
    comparison = replace(
        comparison,
        findings=kept,
        type_mismatch_dropped=len(comparison.findings) - len(kept),
    )
    olds = before if before is not None else (None,) * len(cases)
    runs = tuple(
        CaseRun(case, old, new)
        for case, old, new in zip(cases, olds, after, strict=True)
    )
    return _FunctionRun(None, comparison, runs)


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
    runs: dict[str, tuple[CaseRun, ...]] = {}
    constructors: dict[str, Finding] = {}  # by id: one per class and arguments
    with base_worktree(root, base_sha) as base, working_tree_copy(root, skip) as copy:
        for function in functions:
            function_cases = cases.get(function.report_name, ())
            if not function_cases:
                skipped.append(replace(function, skip_reason=NO_CASES_REASON))
                continue
            base_path = base_paths.get(function.file, function.file)
            result = _run(function, function_cases, (base, copy), base_path, settings)
            for finding in result.constructor_findings:
                constructors.setdefault(finding.id, finding)
            if result.comparison is None:
                skipped.append(replace(function, skip_reason=result.skip_reason))
            else:
                checked.append(function)
                comparisons.append(result.comparison)
                runs[function.report_name] = result.runs
    found = {f.id: f for comparison in comparisons for f in comparison.findings}
    # A checked __init__ finds the same constructor findings as its methods.
    found |= {key: f for key, f in constructors.items() if key not in found}
    return Analysis(
        findings=tuple(
            finding if finding.label else replace(finding, label=UNLABELLED)
            for finding in found.values()
        ),
        checked=tuple(checked),
        skipped=tuple(skipped),
        cases_run=sum(comparison.cases_run for comparison in comparisons),
        flaky_dropped=sum(comparison.flaky_dropped for comparison in comparisons),
        timeouts_dropped=sum(c.timeouts_dropped for c in comparisons),
        runs=runs,
        type_mismatch_dropped=sum(c.type_mismatch_dropped for c in comparisons),
        construction_dropped=sum(c.construction_dropped for c in comparisons),
    )


def _import_problem(
    function: ChangedFunction,
    trees: tuple[Path, Path],
    base_path: str,
    settings: HarnessSettings,
) -> str | None:
    base_tree, current_tree = trees
    if function.kind == "changed":
        target = _target(base_tree, base_path, function)
        reason = check_import(target, settings)
        if reason is not None:
            return f"{reason} (base version)"
    return check_import(_target(current_tree, function.file, function), settings)


def check_imports(
    root: Path,
    base_sha: str,
    functions: Sequence[ChangedFunction],
    base_paths: Mapping[str, str],
    settings: HarnessSettings,
    skip: Sequence[str] = (),
) -> tuple[tuple[ChangedFunction, ...], tuple[ChangedFunction, ...]]:
    """Import every function's module in both versions before any LLM request.

    Same trees and skip reasons as ``analyze``; nothing is called.

    Args:
        root: Repository root.
        base_sha: Base commit.
        functions: Testable changed and new functions.
        base_paths: Base path of each working-tree file, for renamed files.
        settings: Harness settings.
        skip: Repository-relative folders not copied (the output folder).

    Returns:
        The importable functions, and the others with ``skip_reason`` set.

    Raises:
        GitError: If the base worktree or the copy cannot be created.
        OSError: If a file cannot be copied.
    """
    if not functions:
        return (), ()
    importable: list[ChangedFunction] = []
    skipped: list[ChangedFunction] = []
    with base_worktree(root, base_sha) as base, working_tree_copy(root, skip) as copy:
        for function in functions:
            base_path = base_paths.get(function.file, function.file)
            reason = _import_problem(function, (base, copy), base_path, settings)
            if reason is None:
                importable.append(function)
            else:
                skipped.append(replace(function, skip_reason=reason))
    return tuple(importable), tuple(skipped)


# Cost estimate (task 15). Prompts are measured exactly, at CHARS_PER_TOKEN
# characters per token. Output starts from the task 12 live run (537
# completion tokens, 399 of them reasoning, for 3 cases) and then follows
# the completion tokens actually observed in this run.
OUTPUT_TOKENS_PER_CASE = 180
COST_LIMIT_REASON = "cost limit"
TOKEN_LIMIT_REASON = "token limit"
# A refinement prompt also lists the cases already tried: about this many
# characters per case (call plus both outcomes).
PREVIOUS_CHARS_PER_CASE = 160
# Reply cap of a case-generation request (task 38). In 150 evaluation runs
# a reply used at most about 4,100 output tokens for 12 cases (median
# 1,300); the replies that reached the old 16,000 cap were runaway output,
# and the retry of such a reply often ran away too. A smaller cap halves
# what one costs; a larger one would only make it dearer.
REPLY_TOKENS_PER_CASE = 700
MIN_REPLY_TOKENS = 4000


@dataclass(frozen=True)
class Generation:
    """Cases the LLM proposed for the changed functions.

    Attributes:
        cases: Accepted cases by report name; functions without any are in
            ``skipped``.
        skipped: Functions without cases, with ``skip_reason`` set.
        invalid_cases_dropped: Cases rejected by cases.accept_cases.
        usage: Token usage of all calls, failed ones included.
        cost_usd: Cost of those calls; None when the model has no price.
    """

    cases: Mapping[str, tuple[Case, ...]]
    skipped: tuple[ChangedFunction, ...]
    invalid_cases_dropped: int
    usage: TokenUsage
    cost_usd: float | None = None


@dataclass(frozen=True)
class Estimate:
    """Expected LLM use before any call is made."""

    calls: int
    usage: TokenUsage
    cost_usd: float | None


def estimate_call(
    messages: Sequence[Message], count: int, output_per_case: float
) -> TokenUsage:
    """Expected tokens of one case-generation request."""
    characters = sum(len(message.content) for message in messages)
    return TokenUsage(
        input_tokens=math.ceil(characters / CHARS_PER_TOKEN),
        output_tokens=math.ceil(output_per_case * count),
        calls=1,
    )


def estimate_generation(
    functions: Sequence[ChangedFunction],
    count: int,
    template: PromptTemplate,
    price: Price | None,
) -> Estimate:
    """Expected calls, tokens and cost of generating cases for ``functions``.

    Args:
        functions: Functions that will be sent to the LLM (cache misses).
        count: Cases requested per function.
        template: The case generation prompt template.
        price: The model's price, or None (tokens only).

    Returns:
        One call per function; a retry after an unusable reply is not
        included.
    """
    usage = TokenUsage()
    for function in functions:
        messages = build_messages(function, count, template)
        usage += estimate_call(messages, count, OUTPUT_TOKENS_PER_CASE)
    cost = None if price is None else cost_usd(usage, price)
    return Estimate(len(functions), usage, cost)


def estimate_refinement(
    rounds: Sequence[tuple[ChangedFunction, int]],
    count: int,
    template: PromptTemplate,
    price: Price | None,
) -> Estimate:
    """Upper bound for refinement requests, one per (function, round).

    Args:
        rounds: Functions with the refinement round each request would be.
        count: Cases requested per call.
        template: The refinement prompt template.
        price: The model's price, or None (tokens only).

    Returns:
        The estimate if every listed refinement is needed.
    """
    usage = TokenUsage()
    for function, round_number in rounds:
        messages = build_refinement_messages(function, count, template, ())
        listed = min(count * round_number, MAX_PREVIOUS_CASES)
        call = estimate_call(messages, count, OUTPUT_TOKENS_PER_CASE)
        extra = math.ceil(listed * PREVIOUS_CHARS_PER_CASE / CHARS_PER_TOKEN)
        usage += replace(call, input_tokens=call.input_tokens + extra)
    cost = None if price is None else cost_usd(usage, price)
    return Estimate(len(rounds), usage, cost)


@dataclass
class Budget:
    """Usage and cost of a run so far, shared by all rounds.

    Attributes:
        price: The model's price; None means no cost and no limit.
        max_cost: Limit in US dollars; None for no limit.
        count: Cases requested per call, for the output estimate.
        max_tokens: Limit on input + output tokens of the run; None for no
            limit. Applies with or without a price (task 34).
        usage: Tokens of all calls so far.
        cost: US dollars of all calls so far.
    """

    price: Price | None
    max_cost: float | None
    count: int
    max_tokens: int | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: float = 0.0

    def add(self, usage: TokenUsage) -> None:
        """Record the usage of finished calls."""
        self.usage += usage
        if self.price is not None:
            self.cost += cost_usd(usage, self.price)

    def refusal(
        self, messages: Sequence[Message], spent: TokenUsage | None = None
    ) -> str | None:
        """Why one more request with these messages must not be sent, or None.

        The request's estimate plus the usage so far must fit under max_cost
        (only with a price) and under max_tokens (always).

        Args:
            messages: The request to send.
            spent: Usage of earlier requests of the same call that is not
                recorded yet (a retry or fallback inside the client).

        Returns:
            COST_LIMIT_REASON, TOKEN_LIMIT_REASON, or None when it fits.
        """
        used = self.usage + (spent or TokenUsage())
        observed = used.calls and used.output_tokens / (used.calls * self.count)
        estimate = estimate_call(
            messages, self.count, observed or OUTPUT_TOKENS_PER_CASE
        )
        if self._over_max_cost(estimate + (spent or TokenUsage())):
            return COST_LIMIT_REASON
        tokens = _total(used) + _total(estimate)
        if self.max_tokens is not None and tokens > self.max_tokens:
            return TOKEN_LIMIT_REASON
        return None

    def reply_cap(self, messages: Sequence[Message], ceiling: int | None = None) -> int:
        """The output cap of one request: its ceiling, within both limits.

        A reply cut off at the cap and its retry then cannot take the run
        past max_tokens or max_cost (task 38).

        Args:
            messages: The request to send.
            ceiling: Cap without limits; None means the case-generation cap
                for ``count`` cases (case_reply_tokens()).

        Returns:
            At least 1 token; refusal() decides whether to send at all.
        """
        cap = case_reply_tokens(self.count) if ceiling is None else ceiling
        prompt = estimate_call(messages, 0, 0)
        if self.max_tokens is not None:
            cap = min(cap, self.max_tokens - _total(self.usage) - prompt.input_tokens)
        if self.price is not None and self.max_cost is not None:
            left = self.max_cost - self.cost - cost_usd(prompt, self.price)
            million = replace(prompt, output_tokens=1_000_000)
            per_million = cost_usd(million, self.price) - cost_usd(prompt, self.price)
            if per_million > 0:
                cap = min(cap, int(left / per_million * 1_000_000))
        return max(cap, 1)

    def _over_max_cost(self, estimate: TokenUsage) -> bool:
        if self.price is None or self.max_cost is None:
            return False  # without a price the cost limit cannot be enforced
        return self.cost + cost_usd(estimate, self.price) > self.max_cost


def case_reply_tokens(count: int) -> int:
    """Output cap of a case-generation reply for ``count`` cases (task 38)."""
    return min(MAX_OUTPUT_TOKENS, max(MIN_REPLY_TOKENS, REPLY_TOKENS_PER_CASE * count))


def _total(usage: TokenUsage) -> int:
    return usage.input_tokens + usage.output_tokens


_UNAVAILABLE = object()


def _ask(
    client: LLMClient,
    messages: Sequence[Message],
    spending: Budget,
    schema: tuple[dict[str, Any], str] = (CASES_SCHEMA, CASES_SCHEMA_NAME),
) -> LLMReply | str | object:
    """The reply, a skip reason for this function, or _UNAVAILABLE."""

    def may_continue(spent: TokenUsage) -> bool:
        return spending.refusal(messages, spent) is None

    try:
        reply = client.complete_json(
            messages,
            schema[0],
            schema[1],
            may_continue,
            max_output_tokens=spending.reply_cap(messages),
        )
    except LLMInvalidResponseError as error:
        spending.add(error.usage)
        return INVALID_RESPONSE_REASON
    except LLMRequestError as error:
        # Owner decision 2026-11-06: only 401/403/404 stop the run.
        return REQUEST_REJECTED_PREFIX + error.provider_message
    except LLMUnavailableError:
        return _UNAVAILABLE
    spending.add(reply.usage)
    return reply


def _ask_valid(
    client: LLMClient,
    messages: Sequence[Message],
    spending: Budget,
    function: ChangedFunction,
    count: int,
    stop: str | None,
) -> tuple[CaseBatch, int] | str | object | None:
    """Accepted cases and the number rejected, a skip reason, or _UNAVAILABLE.

    When no case of a reply is valid, the same request is sent once more
    if the limits allow it (task 38: 3 of 38 evaluation runs lost a
    function this way to model variance). None when ``stop`` is set.
    """
    if stop is not None:
        return None
    schema = cases_schema(function)
    batch, rejected = CaseBatch((), 0), 0
    for attempt in range(2):
        if attempt and spending.refusal(messages) is not None:
            break  # no room for the second request: no valid cases
        result = _ask(client, messages, spending, schema)
        if attempt and result is not _UNAVAILABLE and not isinstance(result, LLMReply):
            break  # the second reply is unusable: still no valid cases
        if not isinstance(result, LLMReply):
            return result
        batch = accept_cases(
            result.data, count, function.report_name, is_method(function)
        )
        rejected += batch.invalid
        if batch.cases:
            break
    return batch, rejected


def generate_cases(
    client: LLMClient,
    functions: Sequence[ChangedFunction],
    count: int,
    template: PromptTemplate,
    budget: Budget | None = None,
    previous: Mapping[str, Sequence[CaseRun]] | None = None,
) -> Generation:
    """Ask the LLM for cases for each function and keep the valid ones.

    Args:
        client: The configured LLM client.
        functions: Testable changed and new functions.
        count: Cases to request per function (``cases``).
        template: The case generation or, with ``previous``, the refinement
            prompt template.
        budget: Shared spending and limits of the run (all rounds); None
            means no price and no limits.
        previous: For a refinement round, the cases already run per report
            name; their results go into the prompt and repeated cases are
            dropped.

    Returns:
        Accepted cases, skipped functions, and the usage and cost of this
        round. A reply without any valid case is asked for once more when
        the limits allow it (task 38). An invalid reply (after the client's
        one retry) skips that function; an unavailable provider, the cost
        limit or the token limit skips it and all remaining functions; any
        other rejected request (HTTP 4xx except 401/403/404) skips that
        function.

    Raises:
        LLMAuthError: The key was rejected (HTTP 401/403).
        LLMModelError: The model was not found (HTTP 404).
    """
    spending = budget or Budget(None, None, count)
    usage_before, cost_before = spending.usage, spending.cost
    cases: dict[str, tuple[Case, ...]] = {}
    skipped: list[ChangedFunction] = []
    invalid = 0
    for index, function in enumerate(functions):
        tried = tuple((previous or {}).get(function.report_name, ()))
        if previous is None:
            messages = build_messages(function, count, template)
        else:
            messages = build_refinement_messages(function, count, template, tried)
        stop = spending.refusal(messages)
        result = _ask_valid(client, messages, spending, function, count, stop)
        if result is _UNAVAILABLE:
            stop = UNAVAILABLE_REASON
        if stop is not None:
            skipped += [replace(rest, skip_reason=stop) for rest in functions[index:]]
            break
        if not isinstance(result, tuple):  # a skip reason
            skipped.append(replace(function, skip_reason=str(result)))
            continue
        batch, rejected = result
        invalid += rejected
        new = _not_tried(function.report_name, batch.cases, tried)
        if new:
            cases[function.report_name] = new
        else:
            reason = NO_NEW_CASES_REASON if batch.cases else NO_VALID_CASES_REASON
            skipped.append(replace(function, skip_reason=reason))
    usage = _usage_since(spending.usage, usage_before)
    cost = None if spending.price is None else spending.cost - cost_before
    return Generation(cases, tuple(skipped), invalid, usage, cost)


def _not_tried(
    function: str, cases: tuple[Case, ...], tried: Sequence[CaseRun]
) -> tuple[Case, ...]:
    seen = {finding_id(function, run.case) for run in tried}
    return tuple(case for case in cases if finding_id(function, case) not in seen)


def _usage_since(total: TokenUsage, before: TokenUsage) -> TokenUsage:
    def difference(now: int | None, then: int | None) -> int | None:
        return None if now is None else now - (then or 0)

    return TokenUsage(
        input_tokens=total.input_tokens - before.input_tokens,
        output_tokens=total.output_tokens - before.output_tokens,
        reasoning_tokens=difference(total.reasoning_tokens, before.reasoning_tokens),
        cached_input_tokens=total.cached_input_tokens - before.cached_input_tokens,
        calls=total.calls - before.calls,
        estimated_calls=total.estimated_calls - before.estimated_calls,
    )
