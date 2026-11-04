"""Comparison rules: which cases show a behavior difference (Spec, Comparison rules).

Pure functions over the outcomes recorded by the harness. The old version is
the reference: a case is a finding when the current version behaves
differently. Intent never hides a finding; it only labels it later.
"""

import ast
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from didibreak._harness_child import normalize
from didibreak.harness import Case

# Floats are equal when math.isclose(before, after, rel_tol, abs_tol) holds,
# at any depth inside lists, tuples, sets and dicts (Spec). NaN equals NaN.
FLOAT_RELATIVE_TOLERANCE = 1e-9
FLOAT_ABSOLUTE_TOLERANCE = 1e-12
# Hex characters of SHA-256 kept as the finding id (Q14).
FINDING_ID_LENGTH = 12


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
