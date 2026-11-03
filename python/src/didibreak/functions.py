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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class SourceFile:
    """Both versions of one changed file.

    Attributes:
        path: Repository-relative path in the working tree.
        old_source: Content at the base commit; None for a new file.
        new_source: Content in the working tree; None for a deleted file.
    """

    path: str
    old_source: bytes | None
    new_source: bytes | None


@dataclass(frozen=True)
class ChangedFunction:
    """A function whose behavior may differ between base and working tree.

    Attributes:
        file: Repository-relative path in the working tree.
        module: Importable module name (Detailed Design section 3).
        qualname: ``name`` or ``Class.name``.
        kind: ``changed`` (exists in both versions) or ``new``.
        function_type: ``function``, ``staticmethod``, ``classmethod`` or
            ``method`` (instance method).
        is_async: True for ``async def``.
        line: First line in the working tree, decorators included.
        old_source: Base source, dedented; None for new functions.
        new_source: Working-tree source, dedented.
        skip_reason: Why the function is not tested; set by later stages.
    """

    file: str
    module: str
    qualname: str
    kind: str
    function_type: str
    is_async: bool
    line: int
    old_source: str | None
    new_source: str
    skip_reason: str | None = None

    @property
    def report_name(self) -> str:
        """Name used in reports: ``path/to/file.py::Class.name``."""
        return f"{self.file}::{self.qualname}"


@dataclass(frozen=True)
class SkippedFile:
    """A changed file whose functions cannot be compared."""

    path: str
    reason: str


@dataclass(frozen=True)
class Detection:
    """Result of comparing all changed files.

    Attributes:
        functions: Changed and new functions to check, by file then line.
        limited: Functions cut by ``max_functions`` (skip reason ``limit``).
        removed: ``path::qualname`` of functions that no longer exist.
        skipped_files: Files that could not be parsed, with the reason.
    """

    functions: tuple[ChangedFunction, ...]
    limited: tuple[ChangedFunction, ...]
    removed: tuple[str, ...]
    skipped_files: tuple[SkippedFile, ...]


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


def _parse_version(
    content: bytes | None, version: str
) -> dict[str, FunctionDefinition] | str:
    """Return definitions, or a skip reason when the version cannot be parsed."""
    if content is None:
        return {}
    try:
        source = decode_source(content)
    except (SyntaxError, UnicodeDecodeError) as error:
        # detect_encoding reports undecodable bytes as SyntaxError.
        return f"cannot read the {version} version as Python source text: {error}"
    try:
        return definitions(source)
    except SyntaxError as error:
        where = f", line {error.lineno}" if error.lineno else ""
        return f"syntax error in the {version} version{where}: {error.msg}"
    except ValueError as error:  # e.g. null bytes on Python 3.11
        return f"cannot parse the {version} version: {error}"


def _compare_file(
    file: SourceFile,
) -> tuple[list[ChangedFunction], list[str]] | SkippedFile:
    old = _parse_version(file.old_source, "base")
    if isinstance(old, str):
        return SkippedFile(file.path, old)
    new = _parse_version(file.new_source, "current")
    if isinstance(new, str):
        return SkippedFile(file.path, new)
    module = module_name(file.path)
    changed: list[ChangedFunction] = []
    for qualname, current in new.items():
        previous = old.get(qualname)
        if previous is not None and previous.fingerprint == current.fingerprint:
            continue
        changed.append(
            ChangedFunction(
                file=file.path,
                module=module,
                qualname=qualname,
                kind="new" if previous is None else "changed",
                function_type=current.function_type,
                is_async=current.is_async,
                line=current.line,
                old_source=None if previous is None else previous.source,
                new_source=current.source,
            )
        )
    removed = [f"{file.path}::{name}" for name in old if name not in new]
    return changed, removed


def detect_changed_functions(
    files: Sequence[SourceFile], max_functions: int
) -> Detection:
    """Find changed and new functions in all changed files.

    Args:
        files: Both versions of every changed or deleted file.
        max_functions: How many functions to keep; the rest are ``limited``.

    Returns:
        The detection result, ordered by file path, then line.
    """
    found: list[ChangedFunction] = []
    removed: list[str] = []
    skipped: list[SkippedFile] = []
    for file in files:
        result = _compare_file(file)
        if isinstance(result, SkippedFile):
            skipped.append(result)
            continue
        found.extend(result[0])
        removed.extend(result[1])
    found.sort(key=lambda function: (function.file, function.line))
    return Detection(
        functions=tuple(found[:max_functions]),
        limited=tuple(
            replace(function, skip_reason="limit") for function in found[max_functions:]
        ),
        removed=tuple(sorted(removed)),
        skipped_files=tuple(sorted(skipped, key=lambda item: item.path)),
    )
