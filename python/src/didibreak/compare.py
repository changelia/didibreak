"""Comparison rules: which cases show a behavior difference (Spec, Comparison rules).

Pure functions over the outcomes recorded by the harness. The old version is
the reference: a case is a finding when the current version behaves
differently. Intent never hides a finding; it only labels it later.
"""

import ast
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from didibreak._harness_child import normalize
from didibreak.harness import Case, Outcome

# Floats are equal when math.isclose(before, after, rel_tol, abs_tol) holds,
# at any depth inside lists, tuples, sets and dicts (Spec). NaN equals NaN.
FLOAT_RELATIVE_TOLERANCE = 1e-9
FLOAT_ABSOLUTE_TOLERANCE = 1e-12
# Hex characters of SHA-256 kept as the finding id (Q14).
FINDING_ID_LENGTH = 12
NEW_FUNCTION_LABEL = "new_function"
HIGH_CONFIDENCE = "high"
LOW_CONFIDENCE = "low"


@dataclass(frozen=True)
class Finding:
    """One case where the current version behaves differently.

    Attributes:
        id: Deterministic id from finding_id().
        function: Report name ``path/to/file.py::qualname``.
        case: The inputs.
        before: Base outcome; None for a new function.
        after: Current outcome.
        confidence: ``high`` when compared by value or by kind/exception
            type, ``low`` when return values were compared by type only.
        label: ``new_function`` for new functions; set later by intent
            labelling (``expected`` / ``unexpected`` / ``unclear``).
        reason: One-sentence reason from intent labelling.
        test_file: Reproducing test written for this finding.
    """

    id: str
    function: str
    case: Case
    before: Outcome | None
    after: Outcome
    confidence: str
    label: str | None = None
    reason: str | None = None
    test_file: str | None = None


@dataclass(frozen=True)
class Comparison:
    """Result of comparing all cases of one function.

    Attributes:
        findings: Cases that differ, in case order.
        cases_run: Cases compared, including dropped ones.
        flaky_dropped: Cases dropped because a version gave different
            outcomes in its two runs.
        timeouts_dropped: Cases dropped because both versions timed out.
    """

    findings: tuple[Finding, ...]
    cases_run: int
    flaky_dropped: int
    timeouts_dropped: int


def floats_close(before: float, after: float) -> bool:
    """Whether two floats are equal within the tolerances; NaN equals NaN."""
    if math.isnan(before) and math.isnan(after):
        return True
    return math.isclose(
        before,
        after,
        rel_tol=FLOAT_RELATIVE_TOLERANCE,
        abs_tol=FLOAT_ABSOLUTE_TOLERANCE,
    )


def _items_equal(before: Any, after: Any) -> bool:
    # Dict entries are [key, value] pairs; other items are single nodes.
    if isinstance(before, list) and isinstance(after, list):
        return len(before) == len(after) and all(
            values_equal(left, right) for left, right in zip(before, after, strict=True)
        )
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        return values_equal(before, after)
    return False


def values_equal(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """Compare two normalized values (Detailed Design section 4).

    Args:
        before: Normalized value from the base version.
        after: Normalized value from the current version.

    Returns:
        True when type tag, class and content match; floats are compared
        with floats_close(), containers element by element in order (sets
        and dict keys arrive sorted by repr).
    """
    if before["type"] != after["type"] or before.get("class") != after.get("class"):
        return False
    if before["type"] == "float":
        return floats_close(float(before["value"]), float(after["value"]))
    if "items" in before or "items" in after:
        left, right = before.get("items", []), after.get("items", [])
        return len(left) == len(right) and all(
            _items_equal(x, y) for x, y in zip(left, right, strict=True)
        )
    scalar_keys = ("value", "name")  # "name" identifies enum members
    return all(before.get(key) == after.get(key) for key in scalar_keys)


def _canonical_argument(text: str) -> object:
    # The value, not its spelling: "'a'" and '"a"' are the same argument.
    # normalize() sorts sets and dict keys by repr, so the result does not
    # depend on the hash seed.
    normalized = normalize(ast.literal_eval(text))
    return text if normalized is None else normalized


def finding_id(function: str, case: Case) -> str:
    """Deterministic id of a finding (Detailed Design section 6).

    Args:
        function: Report name ``path/to/file.py::qualname``; the path is
            repository-relative, so the id is the same on every machine.
        case: The case's literal arguments.

    Returns:
        The first FINDING_ID_LENGTH hex characters of the SHA-256 of the
        function name and the normalized arguments.

    Raises:
        ValueError: If an argument is not a Python literal.
    """
    payload = {
        "function": function,
        "args": [_canonical_argument(text) for text in case.args],
        "kwargs": {
            name: _canonical_argument(text) for name, text in case.kwargs.items()
        },
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINDING_ID_LENGTH]


def difference(before: Outcome, after: Outcome) -> str | None:
    """Apply the Spec comparison rules to two stable outcomes of one case.

    Args:
        before: Base outcome.
        after: Current outcome.

    Returns:
        None when the behavior is the same, otherwise the finding's
        confidence: ``low`` when return values could only be compared by
        type, ``high`` otherwise. Raise vs return, and a timeout on one side
        only, are differences. Exceptions of the same type are the same
        (messages ignored). Both sides timing out counts as the same here;
        compare_cases() drops such cases.
    """
    if before.kind != after.kind:
        return HIGH_CONFIDENCE
    if before.kind == "timeout":
        return None
    if before.kind == "exception":
        return None if before.type_name == after.type_name else HIGH_CONFIDENCE
    if before.value is not None and after.value is not None:
        return None if values_equal(before.value, after.value) else HIGH_CONFIDENCE
    # Unrepresentable values (Spec): compared by type only.
    return None if before.type_name == after.type_name else LOW_CONFIDENCE


def _new_function_findings(
    function: str, cases: Sequence[Case], after: Sequence[Outcome]
) -> Comparison:
    # No base version (Spec): only exceptions, and timeouts, are reported.
    findings: list[Finding] = []
    flaky = 0
    for case, outcome in zip(cases, after, strict=True):
        if not outcome.stable:
            flaky += 1
        elif outcome.kind != "return":
            findings.append(
                Finding(
                    id=finding_id(function, case),
                    function=function,
                    case=case,
                    before=None,
                    after=outcome,
                    confidence=HIGH_CONFIDENCE,
                    label=NEW_FUNCTION_LABEL,
                )
            )
    return Comparison(tuple(findings), len(cases), flaky, timeouts_dropped=0)


def compare_cases(
    function: str,
    cases: Sequence[Case],
    before: Sequence[Outcome] | None,
    after: Sequence[Outcome],
) -> Comparison:
    """Compare the outcomes of every case of one function.

    Args:
        function: Report name ``path/to/file.py::qualname``.
        cases: The cases, in the order they were run.
        before: Base outcomes in case order; None for a new function.
        after: Current outcomes in case order.

    Returns:
        Findings and counts. A case whose outcome is unstable in either
        version is dropped as flaky; a case that timed out in both versions
        is dropped as well.

    Raises:
        ValueError: If the sequences have different lengths.
    """
    if before is None:
        return _new_function_findings(function, cases, after)
    findings: list[Finding] = []
    flaky = timeouts = 0
    for case, old, new in zip(cases, before, after, strict=True):
        if not (old.stable and new.stable):
            flaky += 1
        elif old.kind == new.kind == "timeout":
            timeouts += 1
        elif (confidence := difference(old, new)) is not None:
            findings.append(
                Finding(
                    finding_id(function, case), function, case, old, new, confidence
                )
            )
    return Comparison(tuple(findings), len(cases), flaky, timeouts)
