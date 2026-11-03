"""Testability rules: which changed functions v0.1 cannot test safely, and why.

Pure functions over a function's source. The categories come from task 07:
async functions, instance methods, generators and obvious I/O. Each skip
reason is a short string shown to the user.
"""

import ast

# Everything treated as obvious I/O, in one place (documented in limitations.md).
OBVIOUS_IO = {
    # Calls to these names.
    "calls": ("open", "os.remove"),
    # Any use of these modules.
    "modules": ("subprocess", "requests", "httpx", "socket"),
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


def _io_in_call(call: ast.Call) -> str | None:
    name = _dotted_name(call.func)
    if name is None:
        return None
    if name in OBVIOUS_IO["calls"]:
        return name
    parts = name.split(".")
    is_database_call = (
        len(parts) >= 2
        and parts[-2] in OBVIOUS_IO["database_receivers"]
        and parts[-1] in OBVIOUS_IO["database_methods"]
    )
    return name if is_database_call else None


def find_obvious_io(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return the first obvious I/O use in a function body, if any.

    Nested functions count: I/O in a helper defined inside the function is
    still I/O of the function.

    Args:
        function: The function's AST.

    Returns:
        The name as written in the code (e.g. ``subprocess.run``), or None.
    """
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and (found := _io_in_call(node)):
            return found
        if isinstance(node, ast.Name) and node.id in OBVIOUS_IO["modules"]:
            return _module_use(function, node.id)
        if isinstance(node, ast.Import | ast.ImportFrom):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [module] if module else [alias.name for alias in node.names]
            for imported in names:
                if imported and imported.split(".")[0] in OBVIOUS_IO["modules"]:
                    return f"import {imported}"
    return None


def _module_use(function: ast.AST, module: str) -> str:
    # Prefer the full call name (subprocess.run) over the bare module name.
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name and name.split(".")[0] == module:
                return name
    return module


def is_generator(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
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
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef
        ):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False


def skip_reason(source: str, function_type: str, is_async: bool) -> str | None:
    """Return why v0.1 cannot test a function, or None if it can.

    The first matching rule wins: async, instance method, generator, I/O.

    Args:
        source: Dedented source of the function (current version).
        function_type: ``function``, ``staticmethod``, ``classmethod`` or ``method``.
        is_async: True for ``async def``.

    Returns:
        A short user-readable reason, or None.
    """
    if is_async:
        return ASYNC_REASON
    if function_type == "method":
        return INSTANCE_METHOD_REASON
    node = ast.parse(source).body[0]
    if not isinstance(node, ast.FunctionDef):
        return None
    if is_generator(node):
        return GENERATOR_REASON
    found = find_obvious_io(node)
    return None if found is None else f"{IO_REASON_PREFIX}{found}"
