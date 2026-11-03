"""Changed-function detection: compare function definitions in two file versions.

Pure functions over file contents; reading files and git happen elsewhere.
Candidates are module-level functions and methods of module-level classes.
Two versions count as the same when their normalized AST is equal, so
formatting, comments and docstrings do not count as changes.
"""

import ast
import copy
import io
import textwrap
import tokenize
from dataclasses import dataclass
from pathlib import PurePosixPath

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class FunctionDefinition:
    """One function definition in one version of a file."""

    qualname: str
    function_type: str
    is_async: bool
    line: int
    source: str
    fingerprint: str


def module_name(path: str) -> str:
    """Return the importable module name for a repository-relative path.

    A file under ``src/`` is imported relative to ``src``; otherwise relative to
    the repository root. ``__init__.py`` maps to its package.

    Args:
        path: Repository-relative POSIX path of a ``.py`` file.

    Returns:
        Dotted module name, e.g. ``app.utils.phone``.
    """
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def decode_source(content: bytes) -> str:
    """Decode Python source bytes honoring a PEP 263 coding declaration.

    Args:
        content: Raw file content.

    Returns:
        The source text.

    Raises:
        SyntaxError: If the declared encoding is unknown.
        UnicodeDecodeError: If the content does not match the encoding.
    """
    encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
    return content.decode(encoding)


def _function_type(node: _FunctionNode) -> str:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id in (
            "staticmethod",
            "classmethod",
        ):
            return decorator.id
    return "method"


def _fingerprint(node: _FunctionNode) -> str:
    # Docstrings and formatting cannot change behavior; leave them out.
    normalized = copy.deepcopy(node)
    body = normalized.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        normalized.body = body[1:]
    return ast.dump(normalized, include_attributes=False)


def _definition(
    node: _FunctionNode, qualname: str, function_type: str, lines: list[str]
) -> FunctionDefinition:
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    end = node.end_lineno or node.lineno
    return FunctionDefinition(
        qualname=qualname,
        function_type=function_type,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        line=start,
        source=textwrap.dedent("".join(lines[start - 1 : end])),
        fingerprint=_fingerprint(node),
    )


def definitions(source: str) -> dict[str, FunctionDefinition]:
    """Collect module-level functions and methods of module-level classes.

    Nested functions and nested classes are not candidates. A name defined
    twice keeps the last definition, as Python does.

    Args:
        source: Python source text.

    Returns:
        Definitions by qualified name.

    Raises:
        SyntaxError: If the source does not parse.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    found: dict[str, FunctionDefinition] = {}
    for node in tree.body:
        if isinstance(node, _FunctionNode):
            found[node.name] = _definition(node, node.name, "function", lines)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, _FunctionNode):
                    qualname = f"{node.name}.{member.name}"
                    found[qualname] = _definition(
                        member, qualname, _function_type(member), lines
                    )
    return found
