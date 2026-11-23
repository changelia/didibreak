"""Execution harness: run cases against one function in one tree, in a subprocess.

The function is imported from the given tree only, in a fresh child process
started with the user's interpreter (Detailed Design sections 3 and 4). The
child is ``_harness_child.py``; parent and child exchange JSON files, never
pickle. Each case has its own timeout, and the parent kills a child that
outlives all of them.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from didibreak.arguments import case_problem, format_case_call

_CHILD_SCRIPT = Path(__file__).with_name("_harness_child.py")
# -s: no user site-packages. -P: the script's folder is not put on sys.path.
# -B: no __pycache__ written into the user's tree. Not -I (Detailed Design
# section 3): it implies -E, which also ignores PYTHONHASHSEED (verified on
# Python 3.12, 2026-11-04). child_environment() removes PYTHON* variables
# instead, which is what -E would do.
_INTERPRETER_FLAGS = ("-s", "-P", "-B")
# Variables removed from the child's environment, matched case-insensitively:
# names ending with one of the suffixes or containing one of the words.
# Broader than Detailed Design section 4 (*_API_KEY, *_TOKEN, *_SECRET), so
# that names such as AWS_SECRET_ACCESS_KEY are covered too.
# _PWD covers MYSQL_PWD; PASS covers PGPASSWORD, DB_PASS and SMTP_PASSWD;
# _PAT covers personal access tokens such as GH_PAT. _CREDENTIALS values are
# credentials or the path of a credentials file (audit 35a, finding 6;
# pre-launch review, finding 5).
SECRET_SUFFIXES = ("_KEY", "_PWD", "_PAT", "_CREDENTIALS")
SECRET_WORDS = ("PASS", "TOKEN", "SECRET", "APIKEY", "API_KEY")
# Connection strings and proxy settings are removed only when they carry a
# password (``postgres://user:pass@host/db``, ``http://user:pass@proxy:8080``);
# a plain DATABASE_URL stays, because the code under test may need it.
URL_SUFFIXES = ("_URL", "_URI", "_DSN", "_PROXY")
# Variables that tell libraries where to keep their caches, pointed at the
# child's scratch folder: a module that writes a cache while it is imported
# would otherwise be skipped as ``blocked: open`` (task 36 review). Names
# from each project's documentation: the XDG base directory specification,
# Matplotlib (MPLCONFIGDIR) and Numba (NUMBA_CACHE_DIR). HOME stays as it
# is: code reads far more than caches from it.
CACHE_VARIABLES = ("XDG_CACHE_HOME", "MPLCONFIGDIR", "NUMBA_CACHE_DIR")
# Matplotlib's cached list of the system fonts, one file per cache version.
MATPLOTLIB_FONT_LISTS = "fontlist-*.json"
# Extra time an async case may take to cancel its coroutine after a timeout
# (ASYNC_CLEANUP_SECONDS in _harness_child.py).
ASYNC_CLEANUP_SECONDS = 1.0
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
        init_args: Constructor arguments of a method case: the class is
            built with them and the method is called on the instance (task
            30). None for a function; ``()`` for a constructor without
            arguments.
        init_kwargs: Constructor keyword arguments of a method case.
    """

    args: tuple[str, ...]
    kwargs: Mapping[str, str] = field(default_factory=dict)
    rationale: str = ""
    init_args: tuple[str, ...] | None = None
    init_kwargs: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_method_case(self) -> bool:
        """Whether the case builds an instance before the call."""
        return self.init_args is not None


@dataclass(frozen=True)
class Target:
    """One function in one tree.

    Attributes:
        tree: Root of the tree (working tree or base worktree); the imported
            module must be inside it.
        import_root: Folder put first on ``sys.path``, inside ``tree``.
        module: Dotted module name relative to ``import_root``.
        qualname: ``name`` or ``Class.name``.
        is_async: Run the coroutine each call returns with ``asyncio.run``
            (task 29).
        is_method: ``qualname`` is ``Class.method`` of an instance method:
            each case builds an instance from its constructor arguments
            and calls the method on it (task 30).
    """

    tree: Path
    import_root: Path
    module: str
    qualname: str
    is_async: bool = False
    is_method: bool = False


def case_call(name: str, case: Case) -> str:
    """The case as one call, as every report prints it (format_case_call)."""
    return format_case_call(
        name, case.args, case.kwargs, case.init_args, case.init_kwargs
    )


@dataclass(frozen=True)
class Outcome:
    """What one case did (Detailed Design section 4).

    Attributes:
        kind: ``return``, ``exception`` or ``timeout``.
        type_name: Qualified type of the value or exception; empty for timeout.
        repr: ``repr`` of the value or exception, at most 2,000 characters.
        value: Normalized value for comparison; None when not representable.
        message: Exception message, at most 500 characters; None otherwise.
        stable: False when the second run of the case gave a different
            outcome; such cases are dropped as flaky.
        state: For a method case, the instance's attributes after the call,
            normalized (``{"type": "state", "items": [[name, node], ...]}``;
            an attribute that cannot be normalized is ``{"type": "opaque",
            "class": ...}``); None for functions and timeouts (task 30).
        state_repr: The same attributes as text, at most 2,000 characters.
        construction_failed: The constructor raised (``kind`` is
            ``exception`` and ``type_name`` its type); the method never ran.
    """

    kind: str
    type_name: str
    repr: str
    value: Mapping[str, Any] | None = None
    message: str | None = None
    stable: bool = True
    state: Mapping[str, Any] | None = None
    state_repr: str | None = None
    construction_failed: bool = False


@dataclass(frozen=True)
class HarnessSettings:
    """How to run the child process.

    Attributes:
        python: Interpreter that imports and runs the user's code.
        timeout: Per-case timeout in seconds.
        api_key_env: Name of the variable holding the LLM API key; removed
            from the child's environment whatever its name.
    """

    python: str
    timeout: float
    api_key_env: str | None = None


@dataclass(frozen=True)
class HarnessResult:
    """Outcomes in case order, or the reason the function could not be run."""

    outcomes: tuple[Outcome, ...]
    skip_reason: str | None = None


def has_password(url: str) -> bool:
    """Whether a URL carries a password (``scheme://user:password@host``)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return bool(parts.scheme and parts.netloc and parts.password)


def is_secret_variable(name: str, value: str = "") -> bool:
    """Whether an environment variable looks like it holds a credential.

    Args:
        name: Variable name, matched ignoring case.
        value: Its value; needed for ``*_URL``, ``*_URI``, ``*_DSN`` and
            ``*_PROXY`` names, which count only when the URL carries a
            password.

    Returns:
        True when the variable should not reach the user's code.
    """
    upper = name.upper()
    if upper.endswith(SECRET_SUFFIXES) or any(word in upper for word in SECRET_WORDS):
        return True
    return upper.endswith(URL_SUFFIXES) and has_password(value)


def child_environment(
    environment: Mapping[str, str], api_key_env: str | None = None
) -> dict[str, str]:
    """Return the environment for the child process.

    Args:
        environment: The parent's environment.
        api_key_env: Name of the API key variable to remove as well.

    Returns:
        A copy without ``PYTHON*`` variables (so ``PYTHONPATH`` and similar
        settings cannot change what is imported) and without credentials,
        plus ``PYTHONHASHSEED=0`` and ``TZ=UTC`` for repeatable results.
    """
    kept = {
        name: value
        for name, value in environment.items()
        if not name.startswith("PYTHON")
        and not is_secret_variable(name, value)
        and name != api_key_env
    }
    kept.update(PYTHONHASHSEED="0", TZ="UTC")
    return kept


def _check_literals(cases: Sequence[Case]) -> None:
    # Defensive: every entry point already checks with the same rule.
    for case in cases:
        problem = case_problem(case.args, case.kwargs) or case_problem(
            case.init_args or (), case.init_kwargs
        )
        if problem is not None:
            raise ValueError(f"invalid case argument: {problem}")


def _outcome(record: Mapping[str, Any]) -> Outcome:
    return Outcome(
        kind=record["kind"],
        type_name=record["type_name"],
        repr=record["repr"],
        value=record.get("value"),
        message=record.get("message"),
        state=record.get("state"),
        state_repr=record.get("state_repr"),
        construction_failed=bool(record.get("construction_failed", False)),
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


def _case_request(case: Case) -> dict[str, Any]:
    request: dict[str, Any] = {"args": list(case.args), "kwargs": dict(case.kwargs)}
    if case.init_args is not None:
        request["init_args"] = list(case.init_args)
        request["init_kwargs"] = dict(case.init_kwargs)
    return request


def _write_request(
    path: Path, target: Target, cases: Sequence[Case], timeout: float, scratch: Path
) -> None:
    """The JSON file the child reads: where the function is and the cases."""
    request = {
        "scratch": str(scratch),
        "tree": str(target.tree),
        "import_root": str(target.import_root),
        "module": target.module,
        "qualname": target.qualname,
        "is_async": target.is_async,
        "is_method": target.is_method,
        "timeout": timeout,
        "cases": [_case_request(case) for case in cases],
    }
    path.write_text(json.dumps(request), encoding="utf-8")


def matplotlib_cache_folder(environment: Mapping[str, str]) -> Path | None:
    """Folder where Matplotlib keeps its font list for this user.

    Follows Matplotlib's documented rule: ``MPLCONFIGDIR`` when set;
    otherwise ``$XDG_CACHE_HOME/matplotlib`` (``~/.cache/matplotlib``) on
    Linux and FreeBSD, and ``~/.matplotlib`` elsewhere.

    Args:
        environment: The parent's environment variables.

    Returns:
        The folder, which may not exist, or None when it cannot be known.
    """
    configured = environment.get("MPLCONFIGDIR")
    if configured:
        return Path(configured)
    home = environment.get("HOME")
    if sys.platform.startswith(("linux", "freebsd")):
        cache = environment.get("XDG_CACHE_HOME")
        if cache:
            return Path(cache, "matplotlib")
        return Path(home, ".cache", "matplotlib") if home else None
    return Path(home, ".matplotlib") if home else None


def _copy_matplotlib_font_lists(
    environment: Mapping[str, str], destination: Path
) -> None:
    # With an empty MPLCONFIGDIR, importing matplotlib.pyplot lists the
    # system fonts with a command (fc-list, system_profiler), which the I/O
    # guard blocks. The user's existing font lists make that unnecessary.
    # Best effort: without them the module is skipped as before.
    source = matplotlib_cache_folder(environment)
    if source is None:
        return
    try:
        for font_list in source.glob(MATPLOTLIB_FONT_LISTS):
            if font_list.is_file():
                shutil.copy(font_list, destination / font_list.name)
    except OSError:
        return


def scratch_environment(
    scratch: Path, environment: Mapping[str, str]
) -> dict[str, str]:
    """Variables that send temporary files and caches into the scratch folder.

    Args:
        scratch: The child's working directory, where the runtime I/O guard
            allows changes.
        environment: The parent's environment variables, used to find the
            user's Matplotlib font lists.

    Returns:
        ``TMPDIR`` (the folder itself, for ``tempfile``) and one existing
        subfolder per name in CACHE_VARIABLES. The ``MPLCONFIGDIR`` folder
        starts with a copy of the user's Matplotlib font lists, if any.
    """
    variables = {"TMPDIR": str(scratch)}
    for name in CACHE_VARIABLES:
        folder = scratch / ".didibreak-caches" / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        variables[name] = str(folder)
    _copy_matplotlib_font_lists(environment, Path(variables["MPLCONFIGDIR"]))
    return variables


def _spawn(
    settings: HarnessSettings,
    environment: Mapping[str, str],
    request: Path,
    results: Path,
    working_directory: Path,
) -> subprocess.Popen[bytes]:
    """Start the child in its own session, with no terminal and no output."""
    return subprocess.Popen(
        [
            settings.python,
            *_INTERPRETER_FLAGS,
            str(_CHILD_SCRIPT),
            str(request),
            str(results),
        ],
        cwd=working_directory,
        # The working directory is the scratch folder of the I/O guard, and
        # also the temporary and cache folder of the code under test.
        env={
            **child_environment(environment, settings.api_key_env),
            **scratch_environment(working_directory, environment),
        },
        stdin=subprocess.DEVNULL,
        # The user's prints must not reach didibreak's output.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_or_kill(process: subprocess.Popen[bytes], seconds: float) -> bool:
    """Wait for the child; kill its process group in any case.

    Returns:
        True when the child outlived ``seconds`` and was killed.
    """
    try:
        process.wait(timeout=seconds)
        return False
    except subprocess.TimeoutExpired:
        return True
    finally:
        _kill_group(process)
        process.wait()


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
    working_directory = folder / "cwd"
    working_directory.mkdir(exist_ok=True)
    _write_request(request, target, cases, settings.timeout, working_directory)
    process = _spawn(settings, environment, request, results, working_directory)
    # An import check runs no case but still gets one timeout to import. An
    # async case that times out also gets its cleanup time.
    per_case = settings.timeout + (ASYNC_CLEANUP_SECONDS if target.is_async else 0)
    limit = per_case * max(len(cases), 1) + _KILL_GRACE_SECONDS
    killed = _wait_or_kill(process, limit)
    return _ChildRun(_read_records(results), killed, process.returncode)


def _timeout(settings: HarnessSettings) -> Outcome:
    return Outcome("timeout", "", f"<timed out after {settings.timeout:g} s>")


def _process_exited(exit_code: int) -> Outcome:
    text = f"the process exited with code {exit_code} during the case"
    return Outcome("exception", PROCESS_EXITED_TYPE, f"<{text}>", message=text)


def _import_ended_reason(run: _ChildRun) -> str:
    if run.killed:
        return "import timed out"
    return f"import failed: process exited with code {run.exit_code}"


def _run_once(
    target: Target,
    cases: Sequence[Case],
    settings: HarnessSettings,
    environment: Mapping[str, str],
) -> HarnessResult:
    outcomes: list[Outcome] = []
    with tempfile.TemporaryDirectory(prefix="didibreak-harness-") as folder:
        while len(outcomes) < len(cases):
            remaining = cases[len(outcomes) :]
            run = _start_child(target, remaining, settings, environment, Path(folder))
            if not run.records:  # the child ended before the import finished
                return HarnessResult((), _import_ended_reason(run))
            header, *records = run.records
            if "skip_reason" in header:
                return HarnessResult((), header["skip_reason"])
            if records and "skip_reason" in records[-1]:  # a blocked case
                return HarnessResult((), records[-1]["skip_reason"])
            outcomes.extend(_outcome(record) for record in records)
            if len(records) == len(remaining):
                break
            if run.killed:
                outcomes.extend(_timeout(settings) for _ in remaining[len(records) :])
                break
            outcomes.append(_process_exited(run.exit_code))
    return HarnessResult(tuple(outcomes))


def check_import(
    target: Target,
    settings: HarnessSettings,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Import the target's module in a child process without calling anything.

    Used before any LLM request (task 21a), so a function whose module cannot
    be imported costs no tokens.

    Args:
        target: The function and the tree to import it from.
        settings: Interpreter and timeout (one timeout for the import).
        environment: Parent environment; defaults to ``os.environ``.

    Returns:
        None when the function was found after import, else the skip reason
        ``run_cases`` would give.
    """
    parent = os.environ if environment is None else environment
    with tempfile.TemporaryDirectory(prefix="didibreak-harness-") as folder:
        run = _start_child(target, (), settings, parent, Path(folder))
    if not run.records:
        return _import_ended_reason(run)
    reason = run.records[0].get("skip_reason")
    return None if reason is None else str(reason)


def _result_key(outcome: Outcome) -> tuple[object, ...]:
    return (outcome.kind, outcome.type_name, outcome.value, outcome.state)


def run_cases(
    target: Target,
    cases: Sequence[Case],
    settings: HarnessSettings,
    environment: Mapping[str, str] | None = None,
) -> HarnessResult:
    """Run every case twice against the target function, in child processes.

    Each run is a separate child process (Detailed Design section 4). An
    outcome is ``stable`` when both runs agree on kind, type and normalized
    value; ``repr`` and messages may contain memory addresses and are not
    compared. The outcomes returned are those of the first run.

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
        found after import``, or ``blocked: <event>`` when the import or a
        case tried an operation the runtime I/O guard stops).

    Raises:
        ValueError: If a case argument is not a Python literal.
    """
    _check_literals(cases)
    parent = os.environ if environment is None else environment
    first = _run_once(target, cases, settings, parent)
    if first.skip_reason is not None:
        return first
    second = _run_once(target, cases, settings, parent)
    if second.skip_reason is not None:
        return second
    return HarnessResult(
        tuple(
            replace(outcome, stable=_result_key(outcome) == _result_key(again))
            for outcome, again in zip(first.outcomes, second.outcomes, strict=True)
        )
    )
