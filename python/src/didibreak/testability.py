"""Testability rules: which changed functions cannot be tested safely, and why.

Pure functions over a module's source. The categories come from task 07:
generators (async generators too) and obvious I/O; async functions are run
since task 29, and instance methods since task 30, except properties,
dunder methods and methods of classes that do I/O while they are built.
These rules are the static safety boundary: a function that matches is
never executed.
Names are resolved through the module's imports and aliases, so
``from subprocess import run`` and ``import shutil as sh`` are recognized.
"""

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

# Everything treated as obvious I/O, in one place (documented in limitations.md).
# A heuristic over names in the source, not a sandbox: I/O hidden in another
# module, or reached through getattr or eval, is not seen (docs/safety.md).
OBVIOUS_IO = {
    # Calls to these fully qualified names; `*` is a glob (fnmatch) wildcard.
    "calls": (
        "open",
        "io.open",
        # Running commands and processes.
        "os.system",
        "os.popen",
        "os.exec*",
        "os.spawn*",
        "os.posix_spawn*",
        "os.fork*",
        "os.kill*",
        "asyncio.create_subprocess_*",
        # Network from coroutines.
        "asyncio.open_connection",
        "asyncio.open_unix_connection",
        "asyncio.start_server",
        "asyncio.start_unix_server",
        # Changing files and folders.
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.removedirs",
        "os.rename",
        "os.renames",
        "os.replace",
        "os.mkdir",
        "os.makedirs",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "os.symlink",
        "os.link",
        "shutil.rmtree",
        "shutil.move",
        "shutil.copy*",
        "shutil.chown",
        "shutil.make_archive",
        "shutil.unpack_archive",
        # Network and databases.
        "urllib.request.*",
        "sqlite3.connect",
        "sqlalchemy.create_engine",
    ),
    # Any use or import of these modules, or of a submodule of them
    # (``http.client`` matches ``http.client.HTTPSConnection``, not
    # ``http.HTTPStatus``).
    "modules": (
        "subprocess",
        "pty",
        "socket",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "websockets",
        "http.client",
        "smtplib",
        "ftplib",
        "imaplib",
        "poplib",
        "paramiko",
        "psycopg",
        "psycopg2",
        "pymysql",
        "MySQLdb",
        "mysql.connector",
        "pymongo",
        "redis",
        "boto3",
        # Async drivers and clients.
        "asyncpg",
        "aiomysql",
        "aiosqlite",
        "aiofiles",
        "motor",
        "aioboto3",
        "aiobotocore",
    ),
    # pathlib.Path methods, matched by method name on any object because the
    # type of a variable is not known from the source. ``replace`` is left
    # out: it would match every ``str.replace``.
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
        "rename",
        "chmod",
        "symlink_to",
        "hardlink_to",
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

ASYNC_GENERATOR_REASON = "async generator"
INSTANCE_METHOD_REASON = "instance method"
PROPERTY_REASON = "property"
DUNDER_REASON = "dunder method"
# Methods that run while an instance is built: I/O in them skips every
# method of the class (task 30).
CONSTRUCTION_METHODS = ("__new__", "__init__", "__post_init__")
# Decorators that make a method a property; ``x.setter`` and the like too.
PROPERTY_DECORATORS = ("property", "cached_property", "functools.cached_property")
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
        class_nodes: The module-level class definitions by name (task 30).
    """

    aliases: Mapping[str, str]
    functions: Mapping[str, _FunctionNode]
    classes: frozenset[str] = frozenset()
    class_nodes: Mapping[str, ast.ClassDef] = field(default_factory=dict)


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
    class_nodes: dict[str, ast.ClassDef] = {}
    for node in tree.body:
        if isinstance(node, _FunctionNode):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            class_nodes[node.name] = node
            for member in node.body:
                if isinstance(member, _FunctionNode):
                    functions[f"{node.name}.{member.name}"] = member
    return ModuleContext(
        aliases=_import_aliases(tree.body),
        functions=functions,
        classes=frozenset(class_nodes),
        class_nodes=class_nodes,
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


def _io_module(name: str) -> str | None:
    """The OBVIOUS_IO module that a dotted name belongs to, if any."""
    for module in OBVIOUS_IO["modules"]:
        if name == module or name.startswith(f"{module}."):
            return module
    return None


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
    if _io_module(canonical):
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


def _imports_io_module(imported: str, node: ast.Import | ast.ImportFrom) -> bool:
    # ``from http import client`` imports http.client; ``import http`` alone
    # is not I/O until a client submodule is used (seen by the other checks).
    if _io_module(imported):
        return True
    if isinstance(node, ast.ImportFrom):
        return any(_io_module(f"{imported}.{alias.name}") for alias in node.names)
    return False


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
                if imported and _imports_io_module(imported, node):
                    return f"import {imported}"
    for node in nodes:
        if isinstance(node, ast.Call) and (found := _io_in_call(node, aliases)):
            return found
    for node in nodes:
        if isinstance(node, ast.Name | ast.Attribute):
            name = _dotted_name(node)
            canonical = None if name is None else _canonical(name, aliases)
            if canonical is not None and _io_module(canonical):
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
    """Return why a function cannot be tested, or None if it can.

    The first matching rule wins: for an instance method, property,
    dunder method and I/O while the class is built; then for every
    function, generator (``async generator`` for one defined with ``async
    def``) and I/O. Other async functions are tested: the harness awaits
    them (task 29), and instance methods are called on an instance built
    from literal constructor arguments (task 30).

    Args:
        context: The module version the function belongs to.
        qualname: ``name`` or ``Class.name``.
        function_type: ``function``, ``staticmethod``, ``classmethod`` or ``method``.
        is_async: True for ``async def``.

    Returns:
        A short user-readable reason, or None.
    """
    function = context.functions.get(qualname)
    if function is None:
        return None
    if function_type == "method":
        reason = _method_reason(context, qualname, function)
        if reason is not None:
            return reason
    if is_generator(function):
        return ASYNC_GENERATOR_REASON if is_async else GENERATOR_REASON
    found = find_io_through_calls(qualname, context)
    if found is not None:
        return f"{IO_REASON_PREFIX}{found}"
    # TODO(task 30): removed once the pipeline builds instances.
    return INSTANCE_METHOD_REASON if function_type == "method" else None


def _is_property(function: _FunctionNode) -> bool:
    for decorator in function.decorator_list:
        name = _dotted_name(decorator)
        if name in PROPERTY_DECORATORS:
            return True
        if name is not None and name.rpartition(".")[2] in (
            "setter",
            "getter",
            "deleter",
        ):
            return True
    return False


def class_io(class_name: str, context: ModuleContext) -> str | None:
    """Obvious I/O that runs while an instance of a class is built.

    Looks at ``__new__``, ``__init__`` and ``__post_init__`` (and the
    same-module functions they call) and at the class body outside its
    methods, such as a class attribute set from a call.

    Args:
        class_name: A module-level class.
        context: Its module.

    Returns:
        ``name (in Class.__init__)`` or ``name (in the class body)``, or None.
    """
    for method in CONSTRUCTION_METHODS:
        qualname = f"{class_name}.{method}"
        if qualname in context.functions:
            found = find_io_through_calls(qualname, context)
            if found is not None:
                return f"{found} (in {qualname})"
    node = context.class_nodes.get(class_name)
    if node is None:
        return None
    for statement in node.body:
        if isinstance(statement, _FunctionNode | ast.ClassDef):
            continue
        for call in ast.walk(statement):
            if isinstance(call, ast.Call) and (
                found := _io_in_call(call, context.aliases)
            ):
                return f"{found} (in the class body)"
    return None


def _method_reason(
    context: ModuleContext, qualname: str, function: _FunctionNode
) -> str | None:
    name = qualname.rpartition(".")[2]
    if name.startswith("__") and name.endswith("__"):
        return DUNDER_REASON
    if _is_property(function):
        return PROPERTY_REASON
    found = class_io(qualname.partition(".")[0], context)
    return None if found is None else f"{IO_REASON_PREFIX}{found}"
