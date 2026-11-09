"""Whether a case's inputs contradict the function's type annotations (task 21a).

Pure functions over source text. Only simple annotations are understood:
builtin types, ``None``, ``Optional``/``Union``/``X | Y``, and ``list``,
``dict``, ``tuple``, ``set``, ``frozenset`` (or their ``typing`` aliases) of
these. Anything else (``Any``, ``Iterable``, ``Literal``, user classes,
aliases) is unknown and never contradicts. Numbers follow PEP 484: an
``int`` is acceptable as a ``float`` and both as a ``complex``; a ``bool``
is an ``int``.
"""

import ast
from collections.abc import Mapping, Sequence

from didibreak.functions import ChangedFunction
from didibreak.harness import Case

_BUILTIN_TYPES: Mapping[str, tuple[type, ...]] = {
    "int": (int,),
    "float": (float, int),
    "complex": (complex, float, int),
    "str": (str,),
    "bytes": (bytes,),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
    "tuple": (tuple,),
    "set": (set,),
    "frozenset": (frozenset,),
}
_TYPING_CONTAINERS = {
    "List": "list",
    "Dict": "dict",
    "Tuple": "tuple",
    "Set": "set",
    "FrozenSet": "frozenset",
}
_ANYTHING = ("object", "Any")


def _name(node: ast.expr) -> str | None:
    """``int`` for ``int``; ``List`` for ``typing.List`` or ``t.List``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _union_members(node: ast.expr) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [node.left, node.right]
    if not isinstance(node, ast.Subscript):
        return None
    name = _name(node.value)
    if name == "Optional":
        return [node.slice, ast.Constant(None)]
    if name == "Union":
        members = node.slice
        return list(members.elts) if isinstance(members, ast.Tuple) else [members]
    return None


def value_matches(value: object, annotation: ast.expr) -> bool | None:
    """Whether a literal value fits an annotation.

    Args:
        value: A value produced by ``ast.literal_eval``.
        annotation: The annotation's AST.

    Returns:
        True or False for simple annotations; None when the annotation is not
        understood (never a contradiction).
    """
    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return value is None
        if isinstance(annotation.value, str):  # a quoted annotation
            try:
                parsed = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
            return value_matches(value, parsed)
        return None
    members = _union_members(annotation)
    if members is not None:
        results = [value_matches(value, member) for member in members]
        if any(result is True for result in results):
            return True
        return None if None in results else False
    if isinstance(annotation, ast.Subscript):
        return _container_matches(value, annotation)
    name = _name(annotation)
    if name in _ANYTHING:
        return True
    if name == "None":
        return value is None
    container = _TYPING_CONTAINERS.get(name or "", name or "")
    if container in _BUILTIN_TYPES:
        return isinstance(value, _BUILTIN_TYPES[container])
    return None


def _all_match(values: Sequence[object], annotation: ast.expr) -> bool | None:
    results = [value_matches(item, annotation) for item in values]
    if False in results:
        return False
    return None if None in results else True


def _container_matches(value: object, annotation: ast.Subscript) -> bool | None:
    name = _name(annotation.value)
    container = _TYPING_CONTAINERS.get(name or "", name or "")
    if container not in ("list", "set", "frozenset", "dict", "tuple"):
        return None
    if not isinstance(value, _BUILTIN_TYPES[container]):
        return False
    parameters = annotation.slice
    items = list(parameters.elts) if isinstance(parameters, ast.Tuple) else [parameters]
    if container == "dict":
        if len(items) != 2 or not isinstance(value, dict):
            return None
        keys = _all_match(list(value), items[0])
        values = _all_match(list(value.values()), items[1])
        if False in (keys, values):
            return False
        return None if None in (keys, values) else True
    assert isinstance(value, list | set | frozenset | tuple)
    elements = list(value)
    if container != "tuple":
        return _all_match(elements, items[0]) if len(items) == 1 else None
    if len(items) == 2 and isinstance(items[1], ast.Constant) and items[1].value is ...:
        return _all_match(elements, items[0])
    if len(items) != len(elements):
        return False
    results = [
        value_matches(item, kind) for item, kind in zip(elements, items, strict=True)
    ]
    if False in results:
        return False
    return None if None in results else True


def _definition(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return node
    return None


def contradicts_annotations(
    source: str,
    args: Sequence[object],
    kwargs: Mapping[str, object],
    *,
    skip_first: bool = False,
) -> bool:
    """Whether the inputs contradict one of the function's simple annotations.

    Arguments that cannot be bound to a parameter (too many, unknown names)
    are not judged here: calling the function shows that.

    Args:
        source: Dedented source of the function (decorators allowed).
        args: Positional argument values.
        kwargs: Keyword argument values.
        skip_first: True for class methods, whose ``cls`` is bound already.

    Returns:
        True only when an argument definitely does not fit its annotation.
    """
    definition = _definition(source)
    if definition is None:
        return False
    parameters = definition.args
    positional = [*parameters.posonlyargs, *parameters.args][int(skip_first) :]
    pairs: list[tuple[object, ast.expr | None]] = []
    for index, value in enumerate(args):
        if index < len(positional):
            pairs.append((value, positional[index].annotation))
        elif parameters.vararg is not None:
            pairs.append((value, parameters.vararg.annotation))
    # Positional-only parameters cannot be passed by name.
    by_name = {
        parameter.arg: parameter
        for parameter in [*parameters.args, *parameters.kwonlyargs]
        if parameter in positional or parameter in parameters.kwonlyargs
    }
    for name, value in kwargs.items():
        if name in by_name:
            pairs.append((value, by_name[name].annotation))
        elif parameters.kwarg is not None:
            pairs.append((value, parameters.kwarg.annotation))
    return any(
        annotation is not None and value_matches(value, annotation) is False
        for value, annotation in pairs
    )


def case_contradicts(function: ChangedFunction, case: Case) -> bool:
    """Whether a case's inputs fall outside the function's annotated contract.

    A changed function's case counts only if it contradicts the annotations
    of both versions: an input the base version accepted is still a real
    input when the new version narrows the annotation.

    Args:
        function: The changed or new function, with its sources.
        case: The inputs, as literal source text.

    Returns:
        True when the finding for this case should be dropped.
    """
    args = [ast.literal_eval(text) for text in case.args]
    kwargs = {name: ast.literal_eval(text) for name, text in case.kwargs.items()}
    skip_first = function.function_type == "classmethod"
    sources = [function.new_source]
    if function.old_source is not None:
        sources.append(function.old_source)
    return all(
        contradicts_annotations(source, args, kwargs, skip_first=skip_first)
        for source in sources
    )
