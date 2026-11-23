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
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from didibreak._harness_child import normalize
from didibreak.arguments import format_call
from didibreak.cache import ignore_output_dir
from didibreak.compare import Finding, is_constructor_finding
from didibreak.functions import module_name
from didibreak.harness import PROCESS_EXITED_TYPE, Outcome, case_call
from didibreak.pipeline import tree_import_root

# Comparison rule for floats (Spec, "Comparison rules").
_APPROX = "rel=1e-9, abs=1e-12"
# Names the generated code uses itself; a function with one of these names is
# imported under an alias.
_RESERVED = frozenset(
    {"pytest", "asyncio", "result", "info", "instance", "_type_name", "_state"}
)
_TYPE_NAME_HELPER = """

def _type_name(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"
"""
# Reads an instance's attributes the way the harness compared them: slots
# (private ones by their mangled name) and __dict__ (task 30).
_STATE_HELPER = """

def _state(instance: object) -> dict[str, object]:
    values: dict[str, object] = {}
    for owner in type(instance).__mro__:
        slots = owner.__dict__.get("__slots__", ())
        for name in (slots,) if isinstance(slots, str) else slots:
            if name in ("__dict__", "__weakref__"):
                continue
            if name.startswith("__"):
                name = f"_{owner.__name__.lstrip('_')}{name}"
            try:
                values[name] = owner.__dict__[name].__get__(instance, owner)
            except AttributeError:
                continue
    values.update(getattr(instance, "__dict__", {}))
    return values
"""


@dataclass(frozen=True)
class Subject:
    """Where the tests import a function from.

    Attributes:
        report_name: ``path::qualname``.
        module: Dotted module name relative to the import root.
        qualname: ``name`` or ``Class.name``.
        import_root: Absolute import root of the file in the working tree.
        is_async: The tests run each call with ``asyncio.run``, as the
            harness did (task 29).
        is_method: An instance method: each test builds the instance from
            the case's constructor arguments, calls the method on it, and
            also checks the instance's state after the call (task 30).
    """

    report_name: str
    module: str
    qualname: str
    import_root: Path
    is_async: bool = False
    is_method: bool = False


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


def _call(subject: Subject, subject_name: str, finding: Finding) -> str:
    method = subject.qualname.partition(".")[2]
    target = f"{subject_name}.{method}" if method else subject_name
    if subject.is_method:
        target = f"instance.{subject.qualname.rpartition('.')[2]}"
    call = format_call(target, finding.case.args, finding.case.kwargs)
    return f"asyncio.run({call})" if subject.is_async else call


def _instance_line(subject_name: str, finding: Finding) -> str:
    # The class is the imported name; nested classes keep their path.
    owner = finding.function.partition("::")[2].rpartition(".")[0]
    class_path = subject_name + owner[len(owner.partition(".")[0]) :]
    case = finding.case
    constructor = format_call(class_path, case.init_args or (), case.init_kwargs)
    return f"    instance = {constructor}"


def literal_state(outcome: Outcome) -> tuple[bool, dict[str, object]]:
    """The base state as a dict of literals, when its text round-trips.

    Like literal_value(): only if ``ast.literal_eval`` reads the state text
    back and every attribute normalizes to the recorded value.
    """
    if outcome.state is None or outcome.state_repr is None:
        return False, {}
    try:
        values = ast.literal_eval(outcome.state_repr)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, {}
    if not isinstance(values, dict):
        return False, {}
    items = [
        [{"type": "str", "value": name}, normalize(values[name])]
        for name in sorted(values, key=str)
    ]
    rebuilt = json.loads(json.dumps({"type": "state", "items": items}))
    return rebuilt == outcome.state, values


def _state_lines(finding: Finding) -> list[str]:
    before = finding.before
    assert before is not None
    if before.state is None:
        return []
    is_literal, values = literal_state(before)
    if not is_literal:
        names = sorted(str(item[0]["value"]) for item in before.state["items"])
        return [
            "    # Weak check: the base state is not all literals, so only the",
            "    # attribute names are compared.",
            f"    assert sorted(_state(instance)) == {names!r}",
        ]
    if _uses_approx(values):
        return [f"    assert _state(instance) == pytest.approx({values!r}, {_APPROX})"]
    return [f"    assert _state(instance) == {values!r}"]


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


def _constructor_lines(subject_name: str, finding: Finding) -> list[str]:
    """Build the instance as the base did: the exception, or type and state."""
    before = finding.before
    assert before is not None
    instance = _instance_line(subject_name, finding)
    if before.kind == "exception":
        return _exception_lines(instance.removeprefix("    instance = "), before)
    return [
        instance,
        f"    assert _type_name(instance) == {before.type_name!r}",
        *_state_lines(finding),
    ]


def render_test(finding: Finding, subject_name: str, subject: Subject) -> str:
    """One test function for one finding that has a base outcome."""
    before = finding.before
    assert before is not None
    call = _call(subject, subject_name, finding)
    test_name = f"test_{subject.qualname.replace('.', '_')}_{finding.id}"
    body = (
        _exception_lines(call, before)
        if before.kind == "exception"
        else _return_lines(call, finding)
    )
    if is_constructor_finding(finding):  # task 38
        body = _constructor_lines(subject_name, finding)
    elif subject.is_method:
        instance = _instance_line(subject_name, finding)
        body = [instance, *body, *_state_lines(finding)]
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
    tests = [render_test(f, subject_name, subject) for f in findings]
    code = "\n\n\n".join(tests)
    header = [
        f"# Reproducing tests for {subject.report_name}.",
        f"# Generated by didibreak {version} from base commit",
        f"# {base_sha}.",
        "# Each test asserts what the base version did; a failing test shows a",
        "# behavior change. Safe to edit and move.",
        "",
    ]
    if subject.is_async:
        header.append("import asyncio")
        header.append("")
    if "pytest." in code:
        header.append("import pytest")
        header.append("")
    header.append(f"from {subject.module} import {imported}{alias}")
    helper = _TYPE_NAME_HELPER if "_type_name(" in code else ""
    helper += _STATE_HELPER if "_state(" in code else ""
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


def _subject(root: Path, report_name: str, is_async: bool, is_method: bool) -> Subject:
    path, _, qualname = report_name.partition("::")
    import_root = tree_import_root(root, path)
    module = module_name(path, import_root)
    return Subject(
        report_name, module, qualname, root / import_root, is_async, is_method
    )


def _shown(path: Path, root: Path) -> str:
    return (path.relative_to(root) if path.is_relative_to(root) else path).as_posix()


def finding_call(finding: Finding) -> str:
    """``path::qualname(args)`` as the text report shows a finding."""
    return case_call(finding.function, finding.case)


def write_tests(
    root: Path,
    output_dir: Path,
    findings: Sequence[Finding],
    version: str,
    base_sha: str,
    awaited: Collection[str] = frozenset(),
    methods: Collection[str] = frozenset(),
) -> WrittenTests:
    """Write one test file per function with findings into output_dir/tests.

    Files of functions without findings in this run are left alone; the
    file of a function with findings is replaced. ``awaited`` holds the
    report names of functions whose cases the harness ran with
    ``asyncio.run``; their tests do the same. ``methods`` holds the report
    names of instance methods; their tests build the instance first.

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
    subjects = [
        _subject(root, name, name in awaited, name in methods) for name in by_function
    ]
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
