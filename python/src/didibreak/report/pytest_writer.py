"""Reproducing pytest files (Detailed Design section 8).

One file per function in ``<output_dir>/tests/``, one test per finding. Each
test calls the function with the finding's inputs and asserts what the base
version did, so it passes on the base and fails where the behavior changed.
Rendering is pure; write_tests() is the only part that touches files.
"""

import ast
import builtins
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from didibreak._harness_child import normalize
from didibreak.cache import ignore_output_dir
from didibreak.compare import Finding
from didibreak.functions import module_name
from didibreak.harness import PROCESS_EXITED_TYPE, Outcome
from didibreak.pipeline import tree_import_root

# Comparison rule for floats (Spec, "Comparison rules").
_APPROX = "rel=1e-9, abs=1e-12"
# Names the generated code uses itself; a function with one of these names is
# imported under an alias.
_RESERVED = frozenset({"pytest", "result", "info", "_type_name"})
_TYPE_NAME_HELPER = """

def _type_name(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"
"""


@dataclass(frozen=True)
class Subject:
    """Where the tests import a function from.

    Attributes:
        report_name: ``path::qualname``.
        module: Dotted module name relative to the import root.
        qualname: ``name`` or ``Class.name``.
        import_root: Absolute import root of the file in the working tree.
    """

    report_name: str
    module: str
    qualname: str
    import_root: Path


def no_test_reason(finding: Finding) -> str | None:
    """Why a finding gets no test, or None when it gets one."""
    if finding.label == "expected":
        # A test of the old behavior would fail on the intended change, and
        # an AI agent might revert the requested work to make it pass
        # (owner decision 2026-11-09).
        return "expected change"
    before = finding.before
    if before is None:
        return "new function: no base behavior to assert"
    if before.kind == "timeout":
        return "the base version timed out"
    if before.type_name == PROCESS_EXITED_TYPE:
        return "the base version ended the process"
    return None


def literal_value(outcome: Outcome) -> tuple[bool, object]:
    """The base value as a literal, when its ``repr`` round-trips exactly.

    The repr counts as a literal only if ``ast.literal_eval`` reads it back
    and the result normalizes to the recorded value (a truncated repr or a
    subclass with a builtin-looking repr does not).
    """
    if outcome.value is None:
        return False, None
    try:
        value = ast.literal_eval(outcome.repr)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None
    normalized = json.loads(json.dumps(normalize(value)))
    return normalized == outcome.value, value


def _uses_approx(value: object) -> bool:
    if isinstance(value, float):
        return True
    items: Sequence[object] = ()
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, dict):
        items = list(value.values())
    numbers = all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in items
    )
    return bool(items) and numbers and any(isinstance(i, float) for i in items)


def _builtin_exception(type_name: str) -> str | None:
    module, _, name = type_name.rpartition(".")
    candidate = getattr(builtins, name, None)
    is_exception = isinstance(candidate, type) and issubclass(candidate, BaseException)
    return name if module == "builtins" and is_exception else None


def _call(subject_name: str, finding: Finding, qualname: str) -> str:
    arguments = [*finding.case.args]
    arguments += [f"{key}={value}" for key, value in finding.case.kwargs.items()]
    method = qualname.partition(".")[2]
    target = f"{subject_name}.{method}" if method else subject_name
    return f"{target}({', '.join(arguments)})"


def _return_lines(call: str, finding: Finding) -> list[str]:
    before = finding.before
    assert before is not None
    is_literal, value = literal_value(before)
    lines = [f"    result = {call}"]
    if not is_literal:
        return [
            *lines,
            "    # Weak check: the base value is not a literal, so only its type",
            "    # is compared.",
            f"    assert _type_name(result) == {before.type_name!r}",
        ]
    if _uses_approx(value):
        return [*lines, f"    assert result == pytest.approx({before.repr}, {_APPROX})"]
    lines.append(f"    assert result == {before.repr}")
    after_literal, after_value = literal_value(finding.after)
    if finding.after.kind == "return" and after_literal and after_value == value:
        # 1, 1.0 and True compare equal; the change is in the types.
        lines.append(f"    assert repr(result) == {before.repr!r}")
    return lines


def _exception_lines(call: str, before: Outcome) -> list[str]:
    name = _builtin_exception(before.type_name)
    if name is not None:
        return [
            f"    with pytest.raises({name}) as info:",
            f"        {call}",
            f"    assert type(info.value) is {name}",
        ]
    return [
        "    with pytest.raises(BaseException) as info:",
        f"        {call}",
        f"    assert _type_name(info.value) == {before.type_name!r}",
    ]


def _comment_lines(finding: Finding) -> list[str]:
    lines = []
    if finding.case.rationale:
        lines.append(f"# Case: {' '.join(finding.case.rationale.split())}")
    label = f"# Label: {finding.label or 'unclear'}"
    if finding.reason:
        label += f" ({' '.join(finding.reason.split())})"
    lines.append(label)
    return lines


def render_test(finding: Finding, subject_name: str, qualname: str) -> str:
    """One test function for one finding that has a base outcome."""
    before = finding.before
    assert before is not None
    call = _call(subject_name, finding, qualname)
    test_name = f"test_{qualname.replace('.', '_')}_{finding.id}"
    body = (
        _exception_lines(call, before)
        if before.kind == "exception"
        else _return_lines(call, finding)
    )
    return "\n".join([*_comment_lines(finding), f"def {test_name}() -> None:", *body])


def render_test_file(
    subject: Subject,
    findings: Sequence[Finding],
    version: str,
    base_sha: str,
) -> str:
    """The whole test file for one function's findings (with base outcomes)."""
    imported = subject.qualname.partition(".")[0]
    subject_name = f"subject_{imported}" if imported in _RESERVED else imported
    alias = f" as {subject_name}" if subject_name != imported else ""
    tests = [render_test(f, subject_name, subject.qualname) for f in findings]
    code = "\n\n\n".join(tests)
    header = [
        f"# Reproducing tests for {subject.report_name}.",
        f"# Generated by didibreak {version} from base commit",
        f"# {base_sha}.",
        "# Each test asserts what the base version did; a failing test shows a",
        "# behavior change. Safe to edit and move.",
        "",
    ]
    if "pytest." in code:
        header.append("import pytest")
        header.append("")
    header.append(f"from {subject.module} import {imported}{alias}")
    helper = _TYPE_NAME_HELPER if "_type_name(" in code else ""
    return "\n".join(header) + "\n" + helper + "\n\n" + code + "\n"


def file_names(subjects: Sequence[Subject]) -> dict[str, str]:
    """File name per report name: ``test_<qualname>.py``, made unique.

    Functions whose names collide (same qualname in different files) get a
    short hash of their report name.
    """
    plain = {s.report_name: f"test_{s.qualname.replace('.', '_')}" for s in subjects}
    counts: dict[str, int] = {}
    for name in plain.values():
        counts[name] = counts.get(name, 0) + 1
    names = {}
    for report_name, name in plain.items():
        if counts[name] > 1:
            digest = hashlib.sha256(report_name.encode()).hexdigest()[:6]
            name = f"{name}_{digest}"
        names[report_name] = f"{name}.py"
    return names


CONFTEST_TEXT = """# Generated by didibreak: lets plain pytest import the checked code,
# and sets TZ=UTC and seeds random as didibreak's harness does.
# PYTHONHASHSEED cannot be set from here. Import roots are relative to
# this folder.
import os
import random
import sys
import time
from pathlib import Path

import pytest

IMPORT_ROOTS = {roots!r}

os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):  # Unix only
    time.tzset()

for _root in IMPORT_ROOTS:
    _path = str((Path(__file__).resolve().parent / _root).resolve())
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(autouse=True)
def _didibreak_random_seed() -> None:
    random.seed(0)
"""


def conftest_roots(text: str) -> tuple[str, ...]:
    """Import roots listed in an existing generated conftest.py."""
    for line in text.splitlines():
        if line.startswith("IMPORT_ROOTS = "):
            try:
                roots = ast.literal_eval(line.removeprefix("IMPORT_ROOTS = "))
            except (ValueError, SyntaxError):
                return ()
            if isinstance(roots, tuple):
                return tuple(r for r in roots if isinstance(r, str))
    return ()


def render_conftest(roots: Sequence[str]) -> str:
    """The conftest.py for the tests folder, roots sorted and unique."""
    return CONFTEST_TEXT.format(roots=tuple(sorted(set(roots))))


@dataclass(frozen=True)
class WrittenTests:
    """Result of write_tests().

    Attributes:
        findings: All findings, ``test_file`` set where a test was written.
        files: Written test files, as shown in the report.
        not_written: ``(call, reason)`` for findings without a test.
    """

    findings: tuple[Finding, ...]
    files: tuple[str, ...]
    not_written: tuple[tuple[str, str], ...]


def _subject(root: Path, report_name: str) -> Subject:
    path, _, qualname = report_name.partition("::")
    import_root = tree_import_root(root, path)
    return Subject(
        report_name, module_name(path, import_root), qualname, root / import_root
    )


def _shown(path: Path, root: Path) -> str:
    return (path.relative_to(root) if path.is_relative_to(root) else path).as_posix()


def finding_call(finding: Finding) -> str:
    """``path::qualname(args)`` as the text report shows a finding."""
    arguments = [*finding.case.args]
    arguments += [f"{key}={value}" for key, value in finding.case.kwargs.items()]
    return f"{finding.function}({', '.join(arguments)})"


def write_tests(
    root: Path,
    output_dir: Path,
    findings: Sequence[Finding],
    version: str,
    base_sha: str,
) -> WrittenTests:
    """Write one test file per function with findings into output_dir/tests.

    Files of functions without findings in this run are left alone; the
    file of a function with findings is replaced.

    Raises:
        OSError: A file cannot be written.
    """
    by_function: dict[str, list[Finding]] = {}
    not_written = []
    for finding in findings:
        reason = no_test_reason(finding)
        if reason is None:
            by_function.setdefault(finding.function, []).append(finding)
        else:
            not_written.append((finding_call(finding), reason))
    if not by_function:
        return WrittenTests(tuple(findings), (), tuple(not_written))
    subjects = [_subject(root, name) for name in by_function]
    names = file_names(subjects)
    folder = output_dir / "tests"
    folder.mkdir(parents=True, exist_ok=True)
    ignore_output_dir(output_dir)
    written: dict[str, str] = {}
    for subject in subjects:
        path = folder / names[subject.report_name]
        text = render_test_file(
            subject, by_function[subject.report_name], version, base_sha
        )
        path.write_text(text, encoding="utf-8")
        written[subject.report_name] = _shown(path, root)
    conftest = folder / "conftest.py"
    old = conftest.read_text(encoding="utf-8") if conftest.exists() else ""
    roots = [os.path.relpath(s.import_root, folder) for s in subjects]
    conftest.write_text(render_conftest([*conftest_roots(old), *roots]), "utf-8")
    updated = tuple(
        replace(f, test_file=written.get(f.function))
        if no_test_reason(f) is None
        else f
        for f in findings
    )
    return WrittenTests(updated, tuple(written.values()), tuple(not_written))
