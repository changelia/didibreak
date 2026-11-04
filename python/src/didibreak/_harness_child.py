"""Child process of the execution harness: run cases against one function.

didibreak.harness starts this file as a script with the user's interpreter.
It uses only the standard library and nothing from didibreak, because that
interpreter may not have didibreak installed.

Results cross the process boundary as JSON, never pickle. Return values are
normalized here (Detailed Design section 4) because the objects themselves
cannot leave the process.
"""

from typing import Any

REPR_LIMIT = 2000
MESSAGE_LIMIT = 500
# Larger values are compared by type only instead of growing the results file
# or recursing without end (cycles).
_MAX_NODES = 10_000
_MAX_DEPTH = 100
# Decimal conversion of larger ints raises ValueError (int max_str_digits).
_MAX_INT_BITS = 13_000


class CaseTimeout(BaseException):
    """Raised by the alarm handler when a case runs longer than its timeout.

    A BaseException so that ``except Exception`` in user code does not catch it.
    """


class _Unrepresentable(Exception):
    pass


class _Budget:
    def __init__(self) -> None:
        self.nodes_left = _MAX_NODES

    def take(self, depth: int) -> None:
        self.nodes_left -= 1
        if self.nodes_left < 0 or depth > _MAX_DEPTH:
            raise _Unrepresentable


def _normalize(value: object, budget: _Budget, depth: int) -> dict[str, Any]:
    budget.take(depth)
    kind = type(value)  # exact types only: subclasses may change equality
    if value is None:
        return {"type": "none"}
    if kind is bool:
        return {"type": "bool", "value": value}
    if kind is int:
        assert isinstance(value, int)
        if value.bit_length() > _MAX_INT_BITS:
            raise _Unrepresentable
        return {"type": "int", "value": value}
    if kind is float:
        assert isinstance(value, float)
        # repr round-trips exactly and also covers nan and inf.
        return {"type": "float", "value": repr(value)}
    if kind is str:
        return {"type": "str", "value": value}
    if kind is bytes:
        assert isinstance(value, bytes)
        return {"type": "bytes", "value": value.hex()}
    if kind is list or kind is tuple:
        assert isinstance(value, list | tuple)
        items = [_normalize(item, budget, depth + 1) for item in value]
        return {"type": kind.__name__, "items": items}
    if kind is set or kind is frozenset:
        assert isinstance(value, set | frozenset)
        ordered = sorted(value, key=repr)
        items = [_normalize(item, budget, depth + 1) for item in ordered]
        return {"type": kind.__name__, "items": items}
    if kind is dict:
        assert isinstance(value, dict)
        pairs = sorted(value.items(), key=lambda pair: repr(pair[0]))
        entries = [
            [_normalize(key, budget, depth + 1), _normalize(item, budget, depth + 1)]
            for key, item in pairs
        ]
        return {"type": "dict", "items": entries}
    raise _Unrepresentable


def normalize(value: object) -> dict[str, Any] | None:
    """Return a tagged JSON structure for a value, or None if not representable.

    Args:
        value: A return value of the function under test.

    Returns:
        ``{"type": ..., "value": ...}`` for scalars (bytes as hex, floats as
        their repr), ``{"type": ..., "items": [...]}`` for containers (sets
        sorted by repr, dicts as key-value pairs sorted by the key's repr), or
        None for anything else, including very large or deeply nested values.
    """
    try:
        return _normalize(value, _Budget(), depth=0)
    except (_Unrepresentable, RecursionError):
        return None


def type_name(value: object) -> str:
    """Qualified type name of a value, e.g. ``builtins.str``."""
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def _safe_text(convert: Any, value: object, limit: int) -> str:
    try:
        text = str(convert(value))
    except CaseTimeout:
        raise
    except BaseException as error:  # user __repr__/__str__ may raise anything
        text = f"<{convert.__name__} failed: {type(error).__name__}>"
    return text[:limit]


def return_outcome(value: object) -> dict[str, Any]:
    """Outcome record for a returned value."""
    outcome: dict[str, Any] = {
        "kind": "return",
        "type_name": type_name(value),
        "repr": _safe_text(repr, value, REPR_LIMIT),
    }
    normalized = normalize(value)
    if normalized is not None:
        outcome["value"] = normalized
    return outcome


def exception_outcome(error: BaseException) -> dict[str, Any]:
    """Outcome record for a raised exception."""
    return {
        "kind": "exception",
        "type_name": type_name(error),
        "repr": _safe_text(repr, error, REPR_LIMIT),
        "message": _safe_text(str, error, MESSAGE_LIMIT),
    }


def timeout_outcome(timeout: float) -> dict[str, Any]:
    """Outcome record for a case that ran longer than the timeout."""
    return {
        "kind": "timeout",
        "type_name": "",
        "repr": f"<timed out after {timeout:g} s>",
    }
