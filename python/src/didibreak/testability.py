"""Testability rules: which changed functions v0.1 cannot test safely, and why.

Pure functions over a module's source. The categories come from task 07:
async functions, instance methods, generators and obvious I/O. These rules
are the v0.1 safety boundary: a function that matches is never executed.
Names are resolved through the module's imports and aliases, so
``from subprocess import run`` and ``import shutil as sh`` are recognized.
"""

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase

# Everything treated as obvious I/O, in one place (documented in limitations.md).
OBVIOUS_IO = {
    # Calls to these fully qualified names; `*` is a glob (fnmatch) wildcard.
    "calls": (
        "open",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "shutil.rmtree",
        "shutil.move",
        "shutil.copy*",
        "urllib.request.*",
        "sqlite3.connect",
    ),
    # Any use of these modules.
    "modules": ("subprocess", "requests", "httpx", "socket"),
    # pathlib.Path methods, matched by method name on any object because the
    # type of a variable is not known from the source.
    "path_methods": (
        "open",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "unlink",
        "rmdir",
        "mkdir",
        "touch",
    ),
    # Database sessions: a call `<receiver>.<method>(...)` such as session.commit().
    "database_receivers": ("session", "db", "cursor", "conn", "connection"),
    "database_methods": (
        "add",
        "commit",
        "delete",
        "execute",
        "executemany",
        "flush",
        "merge",
        "query",
        "refresh",
        "rollback",
        "scalars",
    ),
}

ASYNC_REASON = "async function"
INSTANCE_METHOD_REASON = "instance method"
GENERATOR_REASON = "generator"
IO_REASON_PREFIX = "obvious I/O: "

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class ModuleContext:
    """What the testability rules need to know about one module version.

    Attributes:
        aliases: Local name to fully qualified name, from module-level imports
            (``run`` -> ``subprocess.run``, ``sh`` -> ``shutil``).
        functions: Module-level functions and methods of module-level classes
            by qualified name (``name`` or ``Class.name``).
        classes: Names of module-level classes.
    """

    aliases: Mapping[str, str]
    functions: Mapping[str, _FunctionNode]
    classes: frozenset[str] = frozenset()


def _import_aliases(statements: list[ast.stmt]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    pending = list(statements)
    while pending:
        node = pending.pop(0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif not isinstance(node, _FunctionNode | ast.ClassDef):
            # Imports inside module-level if/try blocks still bind module names.
            pending.extend(
                child
                for child in ast.iter_child_nodes(node)
                if isinstance(child, ast.stmt)
            )
    return aliases


def module_context(source: str) -> ModuleContext:
    """Collect imports, aliases and functions of a module.

    Args:
        source: Python source text of the whole module.

    Returns:
        The module context.

    Raises:
        SyntaxError: If the source does not parse.
    """
    tree = ast.parse(source)
    functions: dict[str, _FunctionNode] = {}
    classes: set[str] = set()
    for node in tree.body:
        if isinstance(node, _FunctionNode):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
            for member in node.body:
                if isinstance(member, _FunctionNode):
                    functions[f"{node.name}.{member.name}"] = member
    return ModuleContext(
        aliases=_import_aliases(tree.body),
        functions=functions,
        classes=frozenset(classes),
    )


def _dotted_name(node: ast.expr) -> str | None:
    """Return ``a.b.c`` for a Name/Attribute chain, otherwise None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _canonical(name: str, aliases: Mapping[str, str]) -> str:
    first, _, rest = name.partition(".")
    if first not in aliases:
        return name
    return f"{aliases[first]}.{rest}" if rest else aliases[first]


def _is_database_call(name: str) -> bool:
    parts = name.split(".")
    return (
        len(parts) >= 2
        and parts[-2] in OBVIOUS_IO["database_receivers"]
        and parts[-1] in OBVIOUS_IO["database_methods"]
    )


def _io_in_call(call: ast.Call, aliases: Mapping[str, str]) -> str | None:
    name = _dotted_name(call.func)
    if name is None:
        return _path_method_call(call, aliases)
    canonical = _canonical(name, aliases)
    if any(fnmatchcase(canonical, pattern) for pattern in OBVIOUS_IO["calls"]):
        return canonical
    if canonical.split(".")[0] in OBVIOUS_IO["modules"]:
        return canonical
    if _is_database_call(name):
        return name
    return _path_method_call(call, aliases)


def _path_method_call(call: ast.Call, aliases: Mapping[str, str]) -> str | None:
    if not (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in OBVIOUS_IO["path_methods"]
    ):
        return None
    receiver = _dotted_name(call.func.value)
    if receiver is None:  # e.g. Path("x").write_text(...)
        return f"pathlib.Path.{call.func.attr}"
    return f"{_canonical(receiver, aliases)}.{call.func.attr}"


def find_obvious_io(function: _FunctionNode, context: ModuleContext) -> str | None:
    """Return the first obvious I/O use in a function body, if any.

    Names are resolved through module-level imports and through imports
    inside the function. Helpers nested inside the function count.

    Args:
        function: The function's AST.
        context: The module the function belongs to.

    Returns:
        The fully qualified name (e.g. ``subprocess.run``), or None.
    """
    aliases = {**context.aliases, **_import_aliases(list(function.body))}
    nodes = list(ast.walk(function))
    for node in nodes:
        if isinstance(node, ast.Import | ast.ImportFrom):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [module] if module else [alias.name for alias in node.names]
            for imported in names:
                if imported and imported.split(".")[0] in OBVIOUS_IO["modules"]:
                    return f"import {imported}"
    for node in nodes:
        if isinstance(node, ast.Call) and (found := _io_in_call(node, aliases)):
            return found
    for node in nodes:
        if isinstance(node, ast.Name):
            canonical = _canonical(node.id, aliases)
            if canonical.split(".")[0] in OBVIOUS_IO["modules"]:
                return canonical
    return None


def _called_functions(
    function: _FunctionNode, qualname: str, context: ModuleContext
) -> list[str]:
    """Qualified names of same-module functions that ``function`` calls."""
    class_name = qualname.split(".")[0] if "." in qualname else None
    called: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if name is None:
            continue
        owner, _, attribute = name.rpartition(".")
        if owner in ("cls", "self") and class_name:
            name = f"{class_name}.{attribute}"
        if name in context.functions and name not in called:
            called.append(name)
    return called


def reachable_functions(qualname: str, context: ModuleContext) -> Iterator[str]:
    """Yield a function and the same-module functions it calls, transitively.

    Breadth first, so each function is reached by its shortest call path;
    every function is yielded once. Calls into other modules are not followed.

    Args:
        qualname: The function to start from; yielded first.
        context: Its module.

    Yields:
        Qualified names of reachable functions defined in the module.
    """
    visited = {qualname}
    queue = [qualname]
    while queue:
        current = queue.pop(0)
        yield current
        for callee in _called_functions(context.functions[current], current, context):
            if callee not in visited:
                visited.add(callee)
                queue.append(callee)


def find_io_through_calls(qualname: str, context: ModuleContext) -> str | None:
    """Find obvious I/O in a function or in same-module functions it calls.

    Args:
        qualname: The function to check.
        context: Its module.

    Returns:
        ``name`` for I/O in the function itself, ``name (via helper)`` for
        I/O reached through a call (the shortest path), or None.
    """
    for current in reachable_functions(qualname, context):
        found = find_obvious_io(context.functions[current], context)
        if found is not None:
            return found if current == qualname else f"{found} (via {current})"
    return None


def _exception_type_name(
    name: str, aliases: Mapping[str, str], context: ModuleContext, module: str
) -> str:
    # The qualified name the harness reports at runtime (type_name).
    canonical = _canonical(name, aliases)
    if canonical != name:  # imported, e.g. errors.Bad -> app.errors.Bad
        return canonical
    if name.split(".")[0] in context.classes:
        return f"{module}.{name}"
    return name if "." in name else f"builtins.{name}"


def explicitly_raised(
    qualname: str, context: ModuleContext, module: str
) -> frozenset[str]:
    """Exception types raised by a ``raise`` statement in a function's code.

    The function's own body, helpers nested in it, and same-module functions
    it calls (transitively, see reachable_functions) are searched. A bare
    ``raise`` and raising a variable are ignored.

    Args:
        qualname: The function.
        context: Its module.
        module: Dotted module name, for exception classes defined in it.

    Returns:
        Qualified type names as the harness reports them, e.g.
        ``builtins.ValueError`` or ``app.parsing.InvalidAge``.
    """
    raised: set[str] = set()
    for current in reachable_functions(qualname, context):
        function = context.functions[current]
        aliases = {**context.aliases, **_import_aliases(list(function.body))}
        for node in ast.walk(function):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            expression = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = _dotted_name(expression)
            if name is not None:
                raised.add(_exception_type_name(name, aliases, context, module))
    return frozenset(raised)


def is_generator(function: _FunctionNode) -> bool:
    """Tell whether ``yield`` appears in the function's own body.

    Yields inside nested functions, lambdas or classes belong to those scopes.

    Args:
        function: The function's AST.

    Returns:
        True for a generator function.
    """
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(node, _FunctionNode | ast.Lambda | ast.ClassDef):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False


def skip_reason(
    context: ModuleContext, qualname: str, function_type: str, is_async: bool
) -> str | None:
    """Return why v0.1 cannot test a function, or None if it can.

    The first matching rule wins: async, instance method, generator, I/O.

    Args:
        context: The module version the function belongs to.
        qualname: ``name`` or ``Class.name``.
        function_type: ``function``, ``staticmethod``, ``classmethod`` or ``method``.
        is_async: True for ``async def``.

    Returns:
        A short user-readable reason, or None.
    """
    if is_async:
        return ASYNC_REASON
    if function_type == "method":
        return INSTANCE_METHOD_REASON
    function = context.functions.get(qualname)
    if function is None:
        return None
    if is_generator(function):
        return GENERATOR_REASON
    found = find_io_through_calls(qualname, context)
    return None if found is None else f"{IO_REASON_PREFIX}{found}"
