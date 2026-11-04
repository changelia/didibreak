"""Execution harness: run cases against one function in one tree, in a subprocess.

The function is imported from the given tree only, in a fresh child process
started with the user's interpreter (Detailed Design sections 3 and 4). The
child is ``_harness_child.py``; parent and child exchange JSON files, never
pickle. Each case has its own timeout, and the parent kills a child that
outlives all of them.
"""

import ast
import contextlib
import json
import os
import signal
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CHILD_SCRIPT = Path(__file__).with_name("_harness_child.py")
# -s: no user site-packages. -P: the script's folder is not put on sys.path.
# -B: no __pycache__ written into the user's tree. Not -I (Detailed Design
# section 3): it implies -E, which also ignores PYTHONHASHSEED (verified on
# Python 3.12, 2026-11-04). child_environment() removes PYTHON* variables
# instead, which is what -E would do.
_INTERPRETER_FLAGS = ("-s", "-P", "-B")
# Extra time for interpreter start and import before the child is killed.
_KILL_GRACE_SECONDS = 5.0
PROCESS_EXITED_TYPE = "didibreak.ProcessExited"


@dataclass(frozen=True)
class Case:
    """Inputs for one call: Python literal expressions as source text.

    Attributes:
        args: Positional arguments, e.g. ``("'995 555 12 34 56'",)``.
        kwargs: Keyword arguments by name.
        rationale: Why the case was chosen; not used by the harness.
    """

    args: tuple[str, ...]
    kwargs: Mapping[str, str] = field(default_factory=dict)
    rationale: str = ""


@dataclass(frozen=True)
class Target:
    """One function in one tree.

    Attributes:
        tree: Root of the tree (working tree or base worktree); the imported
            module must be inside it.
        import_root: Folder put first on ``sys.path``, inside ``tree``.
        module: Dotted module name relative to ``import_root``.
        qualname: ``name`` or ``Class.name``.
    """

    tree: Path
    import_root: Path
    module: str
    qualname: str


@dataclass(frozen=True)
class Outcome:
    """What one case did (Detailed Design section 4).

    Attributes:
        kind: ``return``, ``exception`` or ``timeout``.
        type_name: Qualified type of the value or exception; empty for timeout.
        repr: ``repr`` of the value or exception, at most 2,000 characters.
        value: Normalized value for comparison; None when not representable.
        message: Exception message, at most 500 characters; None otherwise.
    """

    kind: str
    type_name: str
    repr: str
    value: Mapping[str, Any] | None = None
    message: str | None = None


@dataclass(frozen=True)
class HarnessSettings:
    """How to run the child process.

    Attributes:
        python: Interpreter that imports and runs the user's code.
        timeout: Per-case timeout in seconds.
    """

    python: str
    timeout: float


@dataclass(frozen=True)
class HarnessResult:
    """Outcomes in case order, or the reason the function could not be run."""

    outcomes: tuple[Outcome, ...]
    skip_reason: str | None = None


def child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return the environment for the child process.

    Args:
        environment: The parent's environment.

    Returns:
        A copy without ``PYTHON*`` variables, so ``PYTHONPATH`` and similar
        settings cannot change what is imported.
    """
    return {
        name: value
        for name, value in environment.items()
        if not name.startswith("PYTHON")
    }


def _check_literals(cases: Sequence[Case]) -> None:
    for case in cases:
        for text in (*case.args, *case.kwargs.values()):
            try:
                ast.literal_eval(text)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                raise ValueError(
                    f"case argument is not a Python literal: {text!r}"
                ) from None


def _outcome(record: Mapping[str, Any]) -> Outcome:
    return Outcome(
        kind=record["kind"],
        type_name=record["type_name"],
        repr=record["repr"],
        value=record.get("value"),
        message=record.get("message"),
    )


def _read_records(path: Path) -> list[dict[str, Any]]:
    # A child killed while writing leaves a partial last line; ignore it.
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [
        json.loads(line) for line in text.splitlines(keepends=True) if line[-1:] == "\n"
    ]


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    # The child leads its own process group; this also ends processes it started.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


@dataclass(frozen=True)
class _ChildRun:
    records: list[dict[str, Any]]
    killed: bool
    exit_code: int


def _start_child(
    target: Target,
    cases: Sequence[Case],
    settings: HarnessSettings,
    environment: Mapping[str, str],
    folder: Path,
) -> _ChildRun:
    request = folder / "request.json"
    results = folder / "results.jsonl"
    results.unlink(missing_ok=True)
    request.write_text(
        json.dumps(
            {
                "tree": str(target.tree),
                "import_root": str(target.import_root),
                "module": target.module,
                "qualname": target.qualname,
                "timeout": settings.timeout,
                "cases": [
                    {"args": list(case.args), "kwargs": dict(case.kwargs)}
                    for case in cases
                ],
            }
        ),
        encoding="utf-8",
    )
    working_directory = folder / "cwd"
    working_directory.mkdir(exist_ok=True)
    process = subprocess.Popen(
        [
            settings.python,
            *_INTERPRETER_FLAGS,
            str(_CHILD_SCRIPT),
            str(request),
            str(results),
        ],
        cwd=working_directory,
        env=child_environment(environment),
        stdin=subprocess.DEVNULL,
        # The user's prints must not reach didibreak's output.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    killed = False
    try:
        process.wait(timeout=settings.timeout * len(cases) + _KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        killed = True
    finally:
        _kill_group(process)
        process.wait()
    return _ChildRun(_read_records(results), killed, process.returncode)


def _timeout(settings: HarnessSettings) -> Outcome:
    return Outcome("timeout", "", f"<timed out after {settings.timeout:g} s>")


def _process_exited(exit_code: int) -> Outcome:
    text = f"the process exited with code {exit_code} during the case"
    return Outcome("exception", PROCESS_EXITED_TYPE, f"<{text}>", message=text)


def run_cases(
    target: Target,
    cases: Sequence[Case],
    settings: HarnessSettings,
    environment: Mapping[str, str] | None = None,
) -> HarnessResult:
    """Run every case against the target function in a child process.

    A case that crashes the child (for example ``os._exit``) is recorded as a
    ``didibreak.ProcessExited`` exception, and a new child runs the remaining
    cases. If the child outlives all case timeouts, the unfinished cases are
    timeouts.

    Args:
        target: The function and the tree to import it from.
        cases: Inputs to run, in order.
        settings: Interpreter and per-case timeout.
        environment: Parent environment to derive the child's from; defaults
            to ``os.environ``.

    Returns:
        One outcome per case, or a skip reason (``import failed: <Type>``,
        ``import resolved outside tree``, ``import timed out``, ``function not
        found after import``).

    Raises:
        ValueError: If a case argument is not a Python literal.
    """
    _check_literals(cases)
    parent_environment = os.environ if environment is None else environment
    outcomes: list[Outcome] = []
    with tempfile.TemporaryDirectory(prefix="didibreak-harness-") as folder:
        while len(outcomes) < len(cases):
            remaining = cases[len(outcomes) :]
            run = _start_child(
                target, remaining, settings, parent_environment, Path(folder)
            )
            if not run.records:
                reason = (
                    "import timed out"
                    if run.killed
                    else (f"import failed: process exited with code {run.exit_code}")
                )
                return HarnessResult((), reason)
            header, *records = run.records
            if "skip_reason" in header:
                return HarnessResult((), header["skip_reason"])
            outcomes.extend(_outcome(record) for record in records)
            if len(records) == len(remaining):
                break
            if run.killed:
                outcomes.extend(_timeout(settings) for _ in remaining[len(records) :])
                break
            outcomes.append(_process_exited(run.exit_code))
    return HarnessResult(tuple(outcomes))
