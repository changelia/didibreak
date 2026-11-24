"""Deterministic boundary inputs for simply annotated parameters (task 31).

Pure functions over source text. For each parameter whose annotation is
simple (``int``, ``float``, ``str``, ``bool``, ``None``, ``Optional`` /
``Union`` / ``X | Y`` of these, ``list[X]`` and ``dict[K, V]`` of these),
a typical value and a few boundary values are built in code: ``0``, ``-1``
and a large ``int``; ``''``, ``' '`` and a non-ASCII ``str``; ``None`` for
``Optional``; empty containers. Each boundary case changes one parameter
from the typical call, round-robin over the parameters, up to a limit.

Boundary cases cost no tokens. They apply to functions and to the
arguments of methods; a method's instance is built from the constructor
arguments of the first LLM case, and constructors get none. A function
with a required parameter that is not annotated, or not simply annotated,
gets none: there is no call to start from.
"""

import ast
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from didibreak.arguments import case_problem, normalized_case
from didibreak.cases import is_constructor, is_method
from didibreak.compare import finding_id
from didibreak.functions import ChangedFunction
from didibreak.harness import Case

DEFAULT_BOUNDARY_CASES = 6
RATIONALE = "boundary value for "

# (typical value, boundary values) as Python literals, per simple type.
_SCALARS: dict[str, tuple[object, tuple[object, ...]]] = {
    "int": (1, (0, -1, 2**31)),
    "float": (1.5, (0.0, -1.0, 1e16)),
    "str": ("abc", ("", " ", "naïve café ☃")),
    "bool": (True, (False,)),
}
_TYPING_CONTAINERS = {"List": "list", "Dict": "dict"}


@dataclass(frozen=True)
class Values:
    """A parameter's typical value and its boundary values.

    Attributes:
        typical: A value the function most likely accepts.
        boundaries: Edge values to try one at a time.
    """

    typical: object
    boundaries: tuple[object, ...]


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _union_members(node: ast.expr) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*(_union_members(node.left) or [node.left]), node.right]
    if not isinstance(node, ast.Subscript):
        return None
    name = _name(node.value)
    if name == "Optional":
        return [node.slice, ast.Constant(None)]
    if name == "Union":
        members = node.slice
        return list(members.elts) if isinstance(members, ast.Tuple) else [members]
    return None


def annotation_values(annotation: ast.expr | None) -> Values | None:
    """Typical and boundary values for a simple annotation.

    Args:
        annotation: The parameter's annotation, or None.

    Returns:
        The values, or None when the annotation is missing or not simple.
    """
    if annotation is None:
        return None
    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return Values(None, ())
        if isinstance(annotation.value, str):  # a quoted annotation
            try:
                parsed = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
            return annotation_values(parsed)
        return None
    members = _union_members(annotation)
    if members is not None:
        return _union_values(members)
    if isinstance(annotation, ast.Subscript):
        return _container_values(annotation)
    name = _name(annotation)
    if name == "None":
        return Values(None, ())
    if name in _SCALARS:
        typical, boundaries = _SCALARS[name]
        return Values(typical, boundaries)
    if _TYPING_CONTAINERS.get(name or "", name) in ("list", "dict"):
        empty: object = [] if _TYPING_CONTAINERS.get(name or "", name) == "list" else {}
        return Values(empty, ())
    return None


def _union_values(members: Sequence[ast.expr]) -> Values | None:
    values = [annotation_values(member) for member in members]
    if any(value is None for value in values):
        return None
    known = [value for value in values if value is not None]
    present = [value for value in known if value.typical is not None]
    if not present:
        return Values(None, ())
    boundaries: list[object] = []
    if len(present) < len(known):
        boundaries.append(None)
    for index, value in enumerate(present):
        if index:
            boundaries.append(value.typical)
        boundaries.extend(value.boundaries)
    return Values(present[0].typical, tuple(_distinct(boundaries)))


def _container_values(annotation: ast.Subscript) -> Values | None:
    name = _name(annotation.value)
    container = _TYPING_CONTAINERS.get(name or "", name)
    parameters = annotation.slice
    items = list(parameters.elts) if isinstance(parameters, ast.Tuple) else [parameters]
    if container == "list" and len(items) == 1:
        element = annotation_values(items[0])
        return None if element is None else Values([element.typical], ([],))
    if container == "dict" and len(items) == 2:
        key, value = annotation_values(items[0]), annotation_values(items[1])
        if key is None or value is None:
            return None
        try:
            typical = {key.typical: value.typical}
        except TypeError:  # an unhashable key type
            return None
        return Values(typical, ({},))
    return None


def _distinct(values: Sequence[object]) -> list[object]:
    kept: list[object] = []
    for value in values:
        if not any(type(value) is type(seen) and value == seen for seen in kept):
            kept.append(value)
    return kept


@dataclass(frozen=True)
class _Parameter:
    name: str
    values: Values
    positional: bool
    required: bool


def _definition(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return None
    node = tree.body[0] if tree.body else None
    return node if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) else None


def _parameters(source: str, skip_first: bool) -> list[_Parameter] | None:
    """The parameters that boundary cases can fill, in call order.

    Returns:
        None when a required parameter has no simple annotation (no call
        can be built). Optional parameters without a simple annotation and
        ``*args`` / ``**kwargs`` are left out.
    """
    definition = _definition(source)
    if definition is None:
        return None
    arguments = definition.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (
        len(positional) - len(arguments.defaults)
    )
    defaults += list(arguments.defaults)
    entries = [
        (argument, default is None, argument not in arguments.posonlyargs, True)
        for argument, default in zip(positional, defaults, strict=True)
    ][int(skip_first) :]
    entries += [
        (argument, default is None, True, False)
        for argument, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        )
    ]
    found: list[_Parameter] = []
    for argument, required, by_name, positional_kind in entries:
        values = annotation_values(argument.annotation)
        if values is None:
            if required:
                return None
            continue
        if not required and not by_name:
            continue  # an optional positional-only parameter: keep its default
        found.append(
            _Parameter(argument.arg, values, positional_kind and required, required)
        )
    return found


def _call(
    found: Sequence[_Parameter], changed: _Parameter | None, value: object
) -> tuple[tuple[str, ...], dict[str, str]]:
    args: list[str] = []
    kwargs: dict[str, str] = {}
    for parameter in found:
        if parameter is changed:
            text = repr(value)
        elif parameter.required:
            text = repr(parameter.values.typical)
        else:
            continue  # an optional parameter keeps its default
        if parameter.positional:
            args.append(text)
        else:
            kwargs[parameter.name] = text
    return tuple(args), kwargs


def _variants(found: Sequence[_Parameter]) -> list[tuple[_Parameter, object]]:
    """Round-robin: the first boundary of every parameter, then the second..."""
    longest = max((len(p.values.boundaries) for p in found), default=0)
    return [
        (parameter, parameter.values.boundaries[index])
        for index in range(longest)
        for parameter in found
        if index < len(parameter.values.boundaries)
    ]


def boundary_cases(
    function: ChangedFunction, llm_cases: Sequence[Case], limit: int
) -> tuple[Case, ...]:
    """Boundary cases for a function, at most ``limit``, none an LLM duplicate.

    Args:
        function: The changed or new function.
        llm_cases: Its LLM (or cached) cases; a method's instance is built
            from the constructor arguments of the first of them.
        limit: Most boundary cases to add; 0 turns them off.

    Returns:
        The extra cases, in normal form, with a rationale naming the
        parameter. Cases whose finding id equals an LLM case's are dropped.
    """
    if limit <= 0 or is_constructor(function):
        return ()
    init: tuple[tuple[str, ...] | None, dict[str, str]] = (None, {})
    if is_method(function):
        builder = next((c for c in llm_cases if c.is_method_case), None)
        if builder is None:
            return ()
        init = (builder.init_args, dict(builder.init_kwargs))
    skip_first = function.function_type in ("method", "classmethod")
    found = _parameters(function.new_source, skip_first)
    if not found:
        return ()
    seen = {finding_id(function.report_name, case) for case in llm_cases}
    cases: list[Case] = []
    for parameter, value in _variants(found):
        case = _case(*_call(found, parameter, value), init, parameter.name)
        if case is None:
            continue
        identifier = finding_id(function.report_name, case)
        if identifier not in seen:
            seen.add(identifier)
            cases.append(case)
        if len(cases) == limit:
            break
    return tuple(cases)


def _case(
    args: tuple[str, ...],
    kwargs: dict[str, str],
    init: tuple[tuple[str, ...] | None, dict[str, str]],
    name: str,
) -> Case | None:
    if case_problem(args, kwargs) is not None:
        return None
    args, kwargs = normalized_case(args, kwargs)
    case = Case(args, kwargs, f"{RATIONALE}{name}")
    if init[0] is None:
        return case
    return replace(case, init_args=init[0], init_kwargs=init[1])


def with_boundary_cases(
    functions: Sequence[ChangedFunction],
    cases: Mapping[str, Sequence[Case]],
    limit: int,
) -> dict[str, tuple[Case, ...]]:
    """Each function's LLM cases followed by its boundary cases.

    Args:
        functions: The functions of the run.
        cases: LLM (or cached) cases by report name; functions without
            any stay without (a method needs an LLM case to be built).
        limit: Most boundary cases per function.

    Returns:
        The cases by report name.
    """
    combined = {name: tuple(found) for name, found in cases.items()}
    for function in functions:
        found = combined.get(function.report_name)
        if found:
            extra = boundary_cases(function, found, limit)
            combined[function.report_name] = (*found, *extra)
    return combined
