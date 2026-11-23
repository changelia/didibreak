"""Child process of the execution harness: run cases against one function.

didibreak.harness starts this file as a script with the user's interpreter.
It uses only the standard library and the runtime I/O guard next to it
(_io_guard.py, loaded by its path), because that interpreter may not have
didibreak installed.

Results cross the process boundary as JSON, never pickle. Return values are
normalized here (Detailed Design section 4) because the objects themselves
cannot leave the process.

A coroutine function (``async def`` in both versions, request key
``is_async``) is called like any other function, and the coroutine it
returns is run with ``asyncio.run``: a new event loop per case, under the
same timeout.

For an instance method (request key ``is_method``, task 30) each case
first builds the instance from its constructor arguments, under the guard
and the timeout, then calls the method on it. The outcome also records the
instance's state after the call: its ``__dict__`` and slots, each value
normalized like a return value. A constructor that raises gives an outcome
marked ``construction_failed``; one that works is recorded under
``construction`` (the instance's repr and state right after it was built).
For ``Class.__init__`` itself that construction is the outcome (task 38).
"""

import ast
import enum
import hashlib
import importlib
import importlib.util
import json
import os
import random
import signal
import sys
from collections.abc import Callable
from typing import Any, TextIO

REPR_LIMIT = 2000
MESSAGE_LIMIT = 500
# Larger values are compared by type only instead of growing the results file
# or recursing without end (cycles).
_MAX_NODES = 10_000
_MAX_DEPTH = 100
# Decimal conversion of larger ints raises ValueError (int max_str_digits).
_MAX_INT_BITS = 13_000
# A longer str or bytes value is not stored: its length and SHA-256 digest
# stand for it, so two such values are still compared exactly. The parent
# needed about 5 bytes of memory per returned character (pre-launch review,
# finding 13: 232 MB for one 40 MB string).
MAX_TEXT_LENGTH = 100_000
# All stored str and bytes of one value together; a value with more text is
# compared by type only, like one with too many elements.
_MAX_TOTAL_TEXT = 1_000_000
# After an async case times out, asyncio.run cancels the coroutine and waits
# for it to finish. A coroutine that ignores the cancellation would wait
# forever, so the alarm fires once more after this many seconds.
ASYNC_CLEANUP_SECONDS = 1.0


class CaseTimeout(BaseException):
    """Raised by the alarm handler when a case runs longer than its timeout.

    A BaseException so that ``except Exception`` in user code does not catch it.
    """


class _Unrepresentable(Exception):
    pass


class _Budget:
    def __init__(self) -> None:
        self.nodes_left = _MAX_NODES
        self.text_left = _MAX_TOTAL_TEXT

    def take(self, depth: int) -> None:
        self.nodes_left -= 1
        if self.nodes_left < 0 or depth > _MAX_DEPTH:
            raise _Unrepresentable

    def take_text(self, length: int) -> None:
        self.text_left -= length
        if self.text_left < 0:
            raise _Unrepresentable


# Builtin types compared by value. A subclass (namedtuple, OrderedDict,
# defaultdict, IntEnum, StrEnum, ...) is normalized through its builtin base;
# the base's own methods are used so that overrides cannot change the result.
# bool comes before int because bool is a subclass of int.
_SCALAR_BASES: tuple[type, ...] = (bool, int, float, str, bytes)
_CONTAINER_BASES: tuple[type, ...] = (list, tuple, set, frozenset, dict)


def _base_type(value: object) -> type | None:
    for base in (*_SCALAR_BASES, *_CONTAINER_BASES):
        if isinstance(value, base):
            return base
    return None


def _text(kind: str, length: int, budget: _Budget, value: Any) -> dict[str, Any]:
    """A str or bytes node: the content, or length and digest when too long."""
    if length > MAX_TEXT_LENGTH:
        # The base type's own data, so that overrides cannot change it.
        data = value if kind == "bytes" else str.encode(value, "utf-8", "surrogatepass")
        digest = hashlib.sha256(data).hexdigest()
        return {"type": kind, "length": length, "digest": digest}
    budget.take_text(length)
    content = bytes.hex(value) if kind == "bytes" else str.__str__(value)
    return {"type": kind, "value": content}


def _scalar(base: type, value: Any, budget: _Budget) -> dict[str, Any]:
    if base is bool:
        return {"type": "bool", "value": bool(value)}
    if base is int:
        number = int.__index__(value)
        if number.bit_length() > _MAX_INT_BITS:
            raise _Unrepresentable
        return {"type": "int", "value": number}
    if base is float:
        # repr round-trips exactly and also covers nan and inf.
        return {"type": "float", "value": float.__repr__(value)}
    if base is str:
        return _text("str", str.__len__(value), budget, value)
    return _text("bytes", bytes.__len__(value), budget, value)


def _container(
    base: type[Any], value: Any, budget: _Budget, depth: int
) -> dict[str, Any]:
    if base is dict:
        pairs = sorted(dict.items(value), key=lambda pair: repr(pair[0]))
        entries = [
            [_normalize(key, budget, depth + 1), _normalize(item, budget, depth + 1)]
            for key, item in pairs
        ]
        return {"type": "dict", "items": entries}
    elements = list(base.__iter__(value))
    if base is set or base is frozenset:
        elements.sort(key=repr)
    items = [_normalize(item, budget, depth + 1) for item in elements]
    return {"type": base.__name__, "items": items}


def _normalize(value: object, budget: _Budget, depth: int) -> dict[str, Any]:
    budget.take(depth)
    if value is None:
        return {"type": "none"}
    base = _base_type(value)
    if base is None:
        if isinstance(value, enum.Enum):
            # Members of enums without a builtin base (IntEnum and StrEnum
            # have one): the class and the member name identify the value.
            return {"type": "enum", "class": type_name(value), "name": value.name}
        raise _Unrepresentable
    if base in _CONTAINER_BASES:
        node = _container(base, value, budget, depth)
    else:
        node = _scalar(base, value, budget)
    if type(value) is not base:
        # The real class stays part of the value: Point(1, 2) and (1, 2)
        # are not the same result.
        node["class"] = type_name(value)
    return node


def normalize(value: object) -> dict[str, Any] | None:
    """Return a tagged JSON structure for a value, or None if not representable.

    Args:
        value: A return value of the function under test.

    Returns:
        ``{"type": ..., "value": ...}`` for scalars (bytes as hex, floats as
        their repr; a str or bytes longer than MAX_TEXT_LENGTH as
        ``{"type": ..., "length": ..., "digest": ...}``),
        ``{"type": ..., "items": [...]}`` for containers (sets sorted by
        repr, dicts as key-value pairs sorted by the key's repr), or None
        for anything else, including very large or deeply nested values
        and values whose dict keys or set elements raise in ``__repr__``
        (sorting calls it). Subclasses of these types are normalized through
        their builtin base and carry their qualified type name under
        ``"class"``. Other enum members become ``{"type": "enum", "class":
        ..., "name": ...}``.
    """
    try:
        return _normalize(value, _Budget(), depth=0)
    except (_Unrepresentable, RecursionError):
        return None
    except Exception:
        # User __repr__ code raised (audit 35a, finding 5); CaseTimeout is a
        # BaseException and still ends the case.
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


# True while an async case runs: the alarm then also limits the cleanup.
_running_async = [False]


def _on_alarm(signal_number: int, frame: object) -> None:
    if _running_async[0]:
        signal.setitimer(signal.ITIMER_REAL, ASYNC_CLEANUP_SECONDS)
    raise CaseTimeout


def _await(value: object) -> object:
    """Run a returned coroutine to its end in a new event loop."""
    # Imported here, under the guard, so that runs of sync functions do not
    # pay for it; importing reads files and changes none.
    import asyncio
    import inspect

    if not inspect.iscoroutine(value):
        return value  # a decorator made the function return something else
    _running_async[0] = True
    try:
        return asyncio.run(value)
    finally:
        _running_async[0] = False


class MethodTarget:
    """An instance method: the class it is defined on and its name."""

    def __init__(self, owner: type, name: str) -> None:
        self.owner = owner
        self.name = name


def _load_function(
    request: dict[str, Any],
) -> Callable[..., object] | MethodTarget | str:
    """Import the function from the tree, or return the reason it cannot be run."""
    sys.path.insert(0, request["import_root"])
    try:
        module = importlib.import_module(request["module"])
    except BaseException as error:  # import runs arbitrary top-level code
        return f"import failed: {type(error).__name__}"
    # Leakage guard (Detailed Design section 3): an installed copy of the
    # package, for example an editable install, must not be tested instead.
    tree = os.path.realpath(request["tree"])
    location = getattr(module, "__file__", None)
    if (
        location is None
        or os.path.commonpath([tree, os.path.realpath(location)]) != tree
    ):
        return "import resolved outside tree"
    target: object = module
    try:
        for part in request["qualname"].split("."):
            owner, target = target, getattr(target, part)
    except BaseException:  # a module __getattr__ may raise anything
        return "function not found after import"
    if not callable(target):
        return "function not found after import"
    if request.get("is_method"):
        if not isinstance(owner, type):
            return "function not found after import"
        return MethodTarget(owner, request["qualname"].rsplit(".", 1)[-1])
    return target


def _literals(
    case: dict[str, Any], prefix: str = ""
) -> tuple[list[Any], dict[str, Any]]:
    args = [ast.literal_eval(text) for text in case.get(f"{prefix}args", [])]
    kwargs = {
        name: ast.literal_eval(text)
        for name, text in case.get(f"{prefix}kwargs", {}).items()
    }
    return args, kwargs


def _call(
    function: Callable[..., object],
    args: list[Any],
    kwargs: dict[str, Any],
    is_async: bool,
) -> dict[str, Any]:
    try:
        value = function(*args, **kwargs)
        if is_async:
            value = _await(value)
    except CaseTimeout:
        raise
    except BaseException as error:  # SystemExit is an outcome too
        return exception_outcome(error)
    return return_outcome(value)


def _call_method(
    target: MethodTarget, case: dict[str, Any], is_async: bool
) -> dict[str, Any]:
    init_args, init_kwargs = _literals(case, "init_")
    try:
        instance = target.owner(*init_args, **init_kwargs)
    except CaseTimeout:
        raise
    except BaseException as error:
        return {**exception_outcome(error), "construction_failed": True}
    # What the constructor did, before the method changes the instance: a
    # constructor that fails in one version only is a finding (task 38).
    construction = {
        "kind": "return",
        "type_name": type_name(instance),
        "repr": _safe_text(repr, instance, REPR_LIMIT),
        **instance_state(instance),
    }
    if target.name == "__init__":  # the constructor itself is checked
        return {**construction, "construction": construction}
    args, kwargs = _literals(case)
    outcome = _call(getattr(instance, target.name), args, kwargs, is_async)
    return {**outcome, **instance_state(instance), "construction": construction}


def run_case(
    function: Callable[..., object] | MethodTarget,
    case: dict[str, Any],
    timeout: float,
    is_async: bool = False,
) -> dict[str, Any]:
    """Call the function with one case's arguments and record the outcome.

    With ``is_async`` the returned coroutine is run with ``asyncio.run``;
    its result or exception is the outcome. For a MethodTarget the instance
    is built first, inside the same timeout; see instance_state().
    """
    random.seed(0)  # the same random sequence for every case and run
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        if isinstance(function, MethodTarget):
            return _call_method(function, case, is_async)
        args, kwargs = _literals(case)
        return _call(function, args, kwargs, is_async)
    except CaseTimeout:
        return timeout_outcome(timeout)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _slot_values(instance: object) -> dict[str, object]:
    values: dict[str, object] = {}
    for owner in type(instance).__mro__:
        slots = owner.__dict__.get("__slots__", ())
        for name in (slots,) if isinstance(slots, str) else slots:
            if name in ("__dict__", "__weakref__"):
                continue
            stored = (
                f"_{owner.__name__.lstrip('_')}{name}"
                if name.startswith("__")
                else name
            )
            descriptor = owner.__dict__.get(stored)
            try:
                values[stored] = descriptor.__get__(instance, owner)  # type: ignore[union-attr]
            except AttributeError:  # an empty slot
                continue
    return values


def _attributes(instance: object) -> dict[str, object]:
    """The instance's attributes, read without running its __getattr__."""
    values = _slot_values(instance)
    try:
        own = object.__getattribute__(instance, "__dict__")
    except AttributeError:
        return values
    if isinstance(own, dict):
        values.update(dict.items(own))
    return values


def instance_state(instance: object) -> dict[str, Any]:
    """The ``state`` and ``state_repr`` keys of a method case's outcome.

    ``state`` lists every attribute in ``__dict__`` and in ``__slots__``,
    sorted by name, as ``[name, node]`` pairs: the value normalized like a
    return value, or ``{"type": "opaque", "class": ...}`` when it cannot
    be, so that such an attribute is compared by its type only.
    """
    try:
        attributes = sorted(
            _attributes(instance).items(), key=lambda item: str(item[0])
        )
    except CaseTimeout:
        raise
    except BaseException:  # a broken __slots__ or __dict__ is no state
        return {"state": None, "state_repr": "<state not readable>"}
    items = []
    shown = []
    for name, value in attributes:
        node = normalize(value) or {"type": "opaque", "class": type_name(value)}
        items.append([{"type": "str", "value": str(name)}, node])
        shown.append(f"{str(name)!r}: {_safe_text(repr, value, REPR_LIMIT)}")
    text = "{" + ", ".join(shown) + "}"
    return {"state": {"type": "state", "items": items}, "state_repr": text[:REPR_LIMIT]}


def _write(results: TextIO, record: dict[str, Any]) -> None:
    # One complete line per record, flushed, so the parent keeps every
    # finished case even if the process is killed later.
    results.write(json.dumps(record) + "\n")
    results.flush()


def install_guard(scratch: str) -> Callable[[], str | None]:
    """Install the runtime I/O guard (_io_guard.py, next to this file).

    Loaded by its path: this script runs with ``-P``, so its folder is not
    on ``sys.path``, and didibreak may not be installed for this
    interpreter.

    Returns:
        A function that names the first blocked event, or returns None.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_io_guard.py")
    spec = importlib.util.spec_from_file_location("_didibreak_io_guard", path)
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    blocked: Callable[[], str | None] = guard.install(scratch)
    return blocked


def _blocked_record(blocked: Callable[[], str | None]) -> dict[str, Any] | None:
    event = blocked()
    return None if event is None else {"skip_reason": f"blocked: {event}"}


def main(arguments: list[str]) -> None:
    """Run the request file's cases and append records to the results file.

    The first record is ``{"ready": true}`` or ``{"skip_reason": ...}``; then
    one outcome per case, in order. A case that tries a blocked operation
    ends the run with a ``{"skip_reason": "blocked: <event>"}`` record.
    """
    request_path, results_path = arguments
    with open(request_path, encoding="utf-8") as file:
        request = json.load(file)
    with open(results_path, "w", encoding="utf-8") as results:
        # Before the import: a module's top-level code is guarded too.
        blocked = install_guard(request["scratch"])
        function = _load_function(request)
        stop = _blocked_record(blocked)
        if stop is not None or isinstance(function, str):
            _write(results, stop or {"skip_reason": function})
            return
        _write(results, {"ready": True})
        signal.signal(signal.SIGALRM, _on_alarm)
        for case in request["cases"]:
            try:
                outcome = run_case(
                    function, case, request["timeout"], request.get("is_async", False)
                )
            except CaseTimeout:  # the alarm fired while cancelling the timer
                outcome = timeout_outcome(request["timeout"])
            stop = _blocked_record(blocked)
            _write(results, stop or outcome)
            if stop is not None:
                return


if __name__ == "__main__":
    main(sys.argv[1:])
    # Do not wait for threads the user's code may have started.
    os._exit(0)
