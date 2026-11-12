"""Command-line interface: ``didibreak check``, ``didibreak init-agents``.

Flags and exit codes follow Detailed Design sections 1 and 10. Every flag
that has a config key is validated by ``config.validate`` so the CLI and
``[tool.didibreak]`` reject bad values with the same message.
"""

import argparse
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from didibreak import __version__
from didibreak.compare import Finding
from didibreak.config import (
    CONFIG_KEYS,
    FAIL_ON,
    FORMATS,
    PROVIDERS,
    Config,
    ConfigError,
    build_config,
    find_pyproject,
    read_config_table,
    resolve_paths,
    validate,
)
from didibreak.functions import (
    ChangedFunction,
    Detection,
    SourceFile,
    detect_changed_functions,
)
from didibreak.gitdiff import (
    ChangedFiles,
    GitError,
    changed_python_files,
    commit_messages,
    read_base_file,
    repository_root,
    resolve_base,
)
from didibreak.harness import Case, HarnessSettings
from didibreak.intent import NO_INTENT_REASON, intent_text, mark_unclear
from didibreak.llm import create_client
from didibreak.llm.common import LLMAuthError, LLMModelError
from didibreak.llm.pricing import unknown_price_warning
from didibreak.llm_session import LLMSession, Plan
from didibreak.pipeline import (
    COST_LIMIT_REASON,
    INVALID_RESPONSE_REASON,
    REQUEST_REJECTED_PREFIX,
    TOKEN_LIMIT_REASON,
    UNAVAILABLE_REASON,
    Analysis,
    Generation,
    analyze,
    check_imports,
    load_cases_file,
    tree_import_root,
)
from didibreak.report import Report, ReportUsage, SkippedItem
from didibreak.report.json import render_json
from didibreak.report.pytest_writer import WrittenTests, write_tests
from didibreak.report.text import counted, header_lines, results_text

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130

# Detailed Design section 13 (owner decision Q8): Linux and macOS only; the
# harness needs Unix signals for its per-case timeouts.
UNSUPPORTED_PLATFORM_MESSAGE = (
    "didibreak: error: Windows is not supported; didibreak runs on Linux and "
    "macOS (it needs Unix signals for per-case timeouts); use WSL or a Linux "
    "container"
)

AGENT_SNIPPET = """\
## Behavior check
After changing Python functions, run:
    didibreak check --intent "<the user's request in one sentence>" --format json
If any finding has label "unexpected", fix the code so that behavior is preserved,
then run the check again. Report "unclear" findings to the user instead of guessing.
"new_function" findings do not fail the check; mention them to the user
and do not change code for them unless the user asks.
Exit code 2 means nothing could be checked (setup problem, provider down,
cost or token limit): report the error to the user.
If summary.functions_checked is 0, tell the user that nothing was checked and why.
Stop after 3 check rounds and report what is left.
"""


def exit_code_for(labels: Iterable[str], fail_on: str) -> int:
    """Map finding labels to the process exit code.

    Args:
        labels: Labels of all findings in the run.
        fail_on: ``unclear`` (fail on unexpected or unclear findings) or
            ``unexpected`` (fail on unexpected only). new_function findings
            never fail the run.

    Returns:
        1 if any finding should fail the run, otherwise 0.
    """
    # Owner decision 2026-11-09 (reverses 2026-11-06): new_function findings
    # are reported but never fail the run; tasks 21 and 21a found 53 of them
    # and none was a real bug.
    failing = {"unexpected"} if fail_on == "unexpected" else {"unexpected", "unclear"}
    return EXIT_FINDINGS if any(label in failing for label in labels) else EXIT_OK


# Skip reasons that mean something went wrong, not that the function is
# unsupported by design (owner decision 2026-11-11, task 35 review): when
# selected functions exist and none was checked for one of these, the run
# exits 2 instead of passing with nothing checked.
ERROR_SKIP_REASONS = (
    UNAVAILABLE_REASON,
    INVALID_RESPONSE_REASON,
    REQUEST_REJECTED_PREFIX.rstrip(),
    COST_LIMIT_REASON,
    TOKEN_LIMIT_REASON,
    "import failed",
    "import timed out",
    "import resolved outside tree",
    "function not found after import",
)
_LISTED_ERRORS = 3


def nothing_checked_error(
    report: Report, selected: Sequence[ChangedFunction]
) -> str | None:
    """The exit-2 message when no selected function could be checked, or None.

    Args:
        report: The run's report.
        selected: Functions chosen for checking (after the testability rules).

    Returns:
        A one-line message naming up to three functions and their reasons
        when nothing was checked and at least one selected function was
        skipped for an error; None otherwise, also when every selected
        function was skipped by design (for example ``no valid cases``).
    """
    if report.functions_checked or not selected:
        return None
    names = {function.report_name for function in selected}
    errors = [
        item
        for item in report.skipped
        if item.function in names and item.reason.startswith(ERROR_SKIP_REASONS)
    ]
    if not errors:
        return None
    listed = "; ".join(f"{i.function} ({i.reason})" for i in errors[:_LISTED_ERRORS])
    more = len(errors) - _LISTED_ERRORS
    listed += f"; and {more} more" if more > 0 else ""
    return (
        f"no changed function could be checked: {listed}. Fix the cause "
        "(provider, limits or imports) and run again"
    )


def _flag_value(key: str, convert: Callable[[str], object]) -> Callable[[str], object]:
    def parse(text: str) -> object:
        try:
            raw = convert(text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                f"{key}: invalid value {text!r}"
            ) from error
        try:
            return validate(key, raw)
        except ConfigError as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    return parse


# (flag, config key, conversion from text, metavar, help)
_CONFIG_FLAGS: tuple[tuple[str, str, Callable[[str], object], str, str], ...] = (
    ("--base", "base", str, "REF", "version to compare against (default: HEAD)"),
    ("--intent", "intent", str, "TEXT", "what the change was supposed to do"),
    ("--format", "format", str, "|".join(FORMATS), "report format (default: text)"),
    (
        "--fail-on",
        "fail_on",
        str,
        "|".join(FAIL_ON),
        "labels that fail the run (default: unclear)",
    ),
    ("--max-functions", "max_functions", int, "N", "max functions (default: 10)"),
    ("--cases", "cases", int, "N", "cases per function, 1-50 (default: 12)"),
    ("--refine-rounds", "refine_rounds", int, "N", "extra rounds, 0-3 (default: 1)"),
    ("--max-cost", "max_cost", float, "USD", "cost limit per run (default: 0.50)"),
    (
        "--max-tokens",
        "max_tokens",
        int,
        "N",
        "input + output token limit per run (default: 200000)",
    ),
    ("--timeout", "timeout", float, "SECONDS", "per-case timeout (default: 10)"),
    ("--provider", "provider", str, "|".join(PROVIDERS), "LLM provider"),
    ("--model", "model", str, "NAME", "model name"),
    ("--base-url", "base_url", str, "URL", "OpenAI-compatible endpoint"),
    ("--python", "python", str, "PATH", "interpreter that runs your code"),
    ("--output-dir", "output_dir", str, "PATH", "output folder (default: .didibreak)"),
)


def _add_config_flags(check: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps flags the user did not give out of the namespace, so the
    # config file and defaults apply to them.
    for flag, key, convert, metavar, help_text in _CONFIG_FLAGS:
        check.add_argument(
            flag,
            dest=key,
            type=_flag_value(key, convert),
            default=argparse.SUPPRESS,
            metavar=metavar,
            help=help_text,
        )
    check.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=argparse.SUPPRESS,
        help="ignore and do not write the case cache",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for all commands.

    Returns:
        The top-level parser with the ``check`` and ``init-agents`` commands.
    """
    parser = argparse.ArgumentParser(
        prog="didibreak",
        description=(
            "Find unintended behavior changes in Python code changes "
            "by running the old and new versions side by side."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    check = commands.add_parser(
        "check", help="compare changed functions with the base version"
    )
    _add_config_flags(check)
    check.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    verbosity = check.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", dest="verbose", action="store_true", help="verbose progress"
    )
    verbosity.add_argument("-q", dest="quiet", action="store_true", help="errors only")
    # Hidden developer option (Detailed Design section 1).
    check.add_argument("--cases-file", metavar="PATH", help=argparse.SUPPRESS)

    commands.add_parser("init-agents", help="print an AGENTS.md / CLAUDE.md snippet")
    return parser


def load_config(cli_values: Mapping[str, object], working_directory: Path) -> Config:
    """Find the repository and its pyproject.toml, then apply CLI overrides.

    Args:
        cli_values: Validated values of the config flags the user gave.
        working_directory: Directory didibreak was started in.

    Returns:
        The effective configuration.

    Raises:
        GitError: If git is missing or the directory is not in a repository.
        ConfigError: If pyproject.toml or a value in it is invalid.
    """
    root = repository_root(working_directory)
    pyproject = find_pyproject(working_directory, stop=root)
    file_values = read_config_table(pyproject) if pyproject else {}
    config = build_config(file_values, resolve_paths(cli_values, working_directory))
    # The default output folder is not tied to a file or flag: keep it at the
    # repository root wherever didibreak is started.
    if not Path(config.output_dir).is_absolute():
        config = replace(config, output_dir=str(root / config.output_dir))
    return config


def load_source_files(
    root: Path, base_sha: str, files: ChangedFiles
) -> list[SourceFile]:
    """Read both versions of every changed and deleted file.

    Args:
        root: Repository root.
        base_sha: Base commit.
        files: Result of changed_python_files().

    Returns:
        One SourceFile per changed or deleted file, with its import root.

    Raises:
        GitError: If a base version cannot be read.
        OSError: If a working-tree file cannot be read.
    """
    sources = [
        SourceFile(
            path=item.path,
            old_source=(
                read_base_file(root, base_sha, item.old_path) if item.old_path else None
            ),
            new_source=(root / item.path).read_bytes(),
            import_root=tree_import_root(root, item.path),
        )
        for item in files.changed
    ]
    sources += [
        SourceFile(
            path,
            read_base_file(root, base_sha, path),
            None,
            import_root=tree_import_root(root, path),
        )
        for path in files.deleted
    ]
    return sources


def _money(amount: float) -> str:
    # Two decimals for limits like $0.50; more below a cent, so a tiny limit
    # does not show as $0.00.
    return f"${amount:.2f}" if amount >= 0.01 or amount == 0 else f"${amount:.6f}"


def _print_estimate(
    plan: Plan, session: LLMSession, functions: int, stream: TextIO
) -> None:
    estimate, model, max_cost = (
        plan.estimate,
        session.settings.model,
        session.config.max_cost,
    )
    usage = estimate.usage
    tokens = f"~{usage.input_tokens:,} input + ~{usage.output_tokens:,} output tokens"
    if session.local:
        cost = ", cost $0 (local)"
    elif session.unpriced:
        cost = f", cost unknown (limit {session.config.max_tokens:,} tokens)"
    else:
        cost = f", ~${estimate.cost_usd or 0:.4f} (limit {_money(max_cost)})"
    if plan.refinement or plan.labelling:
        parts = [str(plan.initial)]
        if plan.refinement:
            parts.append(f"up to {plan.refinement} refinement")
        if plan.labelling:
            parts.append(f"{plan.labelling} labelling")
        calls = f"up to {counted(plan.calls, 'LLM call')} ({' + '.join(parts)})"
    else:
        calls = counted(plan.calls, "LLM call")
    print(f"Estimated: {calls} with {model}, {tokens}{cost}", file=stream)
    if not session.local and (estimate.cost_usd or 0) > max_cost:
        print(
            "The estimate is above max_cost: functions after the limit are skipped.",
            file=stream,
        )
    if usage.input_tokens + usage.output_tokens > session.config.max_tokens:
        print(
            "The estimate is above max_tokens "
            f"({session.config.max_tokens:,}): functions after the limit are "
            "skipped.",
            file=stream,
        )
    cached = functions - plan.initial
    if cached:
        print(f"{cached} function(s) use cached cases", file=stream)


def _confirmed(arguments: argparse.Namespace, config: Config) -> bool:
    # Detailed Design section 1: --yes is implied by --format json and by a
    # stdin that is not a terminal.
    if arguments.yes or config.format == "json" or not sys.stdin.isatty():
        return True
    print("Continue? [Y/n] ", end="", file=sys.stderr, flush=True)
    answer = sys.stdin.readline()
    if not answer:  # end of input
        return False
    return answer.strip().lower() in ("", "y", "yes")


@dataclass(frozen=True)
class _LLMCases:
    """What the LLM contributed to a run, for the listing.

    Attributes:
        generation: First-round cases and skips, with the usage, cost and
            invalid cases of all rounds.
        local: The model runs on this machine (cost 0).
        refinement_skipped: Functions whose refinement could not be done.
        refined: Functions that got refinement cases.
        refinement_cases: Refinement cases run.
    """

    generation: Generation
    local: bool = False
    refinement_skipped: tuple[ChangedFunction, ...] = ()
    refined: int = 0
    refinement_cases: int = 0


def _start_llm(
    config: Config,
    functions: Sequence[ChangedFunction],
    arguments: argparse.Namespace,
    intent: str | None,
) -> LLMSession | None:
    """Plan the LLM requests, show the estimate, ask; None when declined.

    Raises:
        ConfigError: Missing provider, model or key (exit 2, before any
            request).
    """

    def factory(config: Config, environment: Mapping[str, str]) -> object:
        return create_client(config, environment)  # looked up at call time

    session = LLMSession.open(config, os.environ, factory)
    plan = session.plan(functions, intent)
    if not plan.calls:
        return session  # every case is cached
    if session.unpriced:
        # Printed even with -q: a cost limit the user may rely on is off.
        warning = unknown_price_warning(session.settings.model, config.max_tokens)
        print(warning, file=sys.stderr, flush=True)
    if not arguments.quiet:
        # Part of the text report; in JSON mode stdout holds only the report.
        stream = sys.stdout if config.format == "text" else sys.stderr
        _print_estimate(plan, session, len(functions), stream)
        stream.flush()
    return session if _confirmed(arguments, config) else None


def _merge(first: Analysis, second: Analysis) -> Analysis:
    runs = dict(first.runs)
    for name, more in second.runs.items():
        runs[name] = (*runs.get(name, ()), *more)
    checked = (*first.checked, *(f for f in second.checked if f not in first.checked))
    return Analysis(
        findings=(*first.findings, *second.findings),
        checked=checked,
        skipped=(*first.skipped, *second.skipped),
        cases_run=first.cases_run + second.cases_run,
        flaky_dropped=first.flaky_dropped + second.flaky_dropped,
        timeouts_dropped=first.timeouts_dropped + second.timeouts_dropped,
        runs=runs,
        type_mismatch_dropped=first.type_mismatch_dropped
        + second.type_mismatch_dropped,
    )


@dataclass(frozen=True)
class _Refinement:
    analysis: Analysis
    skipped: tuple[ChangedFunction, ...]
    invalid: int
    refined: int
    cases: int


# Runs the given functions with the given cases on both versions.
_RunCases = Callable[
    [Sequence[ChangedFunction], Mapping[str, Sequence[Case]]], Analysis
]


def _refine(session: LLMSession, run: _RunCases, analysis: Analysis) -> _Refinement:
    """Refinement rounds for functions whose cases found no difference."""
    found = {finding.function for finding in analysis.findings}
    stopped: dict[str, ChangedFunction] = {}
    refined: set[str] = set()
    invalid = cases = 0
    for round_number in range(1, session.config.refine_rounds + 1):
        quiet = [
            f
            for f in analysis.checked
            if f.report_name not in found and f.report_name not in stopped
        ]
        if not quiet:
            break
        generation = session.cases(quiet, round_number, analysis.runs)
        invalid += generation.invalid_cases_dropped
        stopped.update((f.report_name, f) for f in generation.skipped)
        ready = [f for f in quiet if f.report_name in generation.cases]
        if not ready:
            break
        more = run(ready, generation.cases)
        analysis = _merge(analysis, more)
        found |= {finding.function for finding in more.findings}
        refined |= {f.report_name for f in ready}
        cases += more.cases_run
    return _Refinement(analysis, tuple(stopped.values()), invalid, len(refined), cases)


def _check_with_llm(
    session: LLMSession,
    functions: Sequence[ChangedFunction],
    run: _RunCases,
    intent: str | None,
) -> tuple[Analysis, _LLMCases]:
    """First cases, comparison, refinement rounds (task 16), labels (task 17)."""
    first = session.cases(functions)
    with_cases = [f for f in functions if f.report_name in first.cases]
    refinement = _refine(session, run, run(with_cases, first.cases))
    findings = session.label(refinement.analysis.findings, intent, NO_INTENT_REASON)
    budget = session.budget
    totals = replace(
        first,
        invalid_cases_dropped=first.invalid_cases_dropped + refinement.invalid,
        usage=budget.usage,
        cost_usd=None if budget.price is None else budget.cost,
    )
    llm = _LLMCases(
        totals,
        session.local,
        refinement.skipped,
        refinement.refined,
        refinement.cases,
    )
    return replace(refinement.analysis, findings=findings), llm


@dataclass(frozen=True)
class _Trees:
    """How the base and current trees are built and run for one check."""

    settings: HarnessSettings
    base_paths: Mapping[str, str]
    skip: Sequence[str]


def _trees(config: Config, root: Path, files: ChangedFiles) -> _Trees:
    settings = HarnessSettings(
        python=config.python or sys.executable,
        timeout=config.timeout,
        api_key_env=config.api_key_env or None,
    )
    output_dir = Path(config.output_dir)
    skip = (
        [output_dir.relative_to(root).as_posix()]
        if output_dir.is_relative_to(root)
        else []
    )
    base_paths = {item.path: item.old_path for item in files.changed if item.old_path}
    return _Trees(settings, base_paths, skip)


def _analyze(
    config: Config,
    root: Path,
    base_sha: str,
    files: ChangedFiles,
    functions: Sequence[ChangedFunction],
    cases: Mapping[str, Sequence[Case]],
) -> Analysis:
    trees = _trees(config, root, files)
    return analyze(
        root, base_sha, functions, trees.base_paths, cases, trees.settings, trees.skip
    )


def _importable(
    config: Config,
    root: Path,
    base_sha: str,
    files: ChangedFiles,
    functions: Sequence[ChangedFunction],
) -> tuple[tuple[ChangedFunction, ...], tuple[ChangedFunction, ...]]:
    # Before any LLM request (task 21a): an unimportable module costs nothing.
    trees = _trees(config, root, files)
    return check_imports(
        root, base_sha, functions, trees.base_paths, trees.settings, trees.skip
    )


def _skipped(functions: Sequence[ChangedFunction]) -> list[SkippedItem]:
    return [SkippedItem(f.report_name, f.skip_reason or "") for f in functions]


def _skipped_items(
    detection: Detection, generation: Generation | None, analysis: Analysis
) -> tuple[SkippedItem, ...]:
    """Everything not checked, in report order: files, rules, limit, LLM, runs."""
    return (
        *(SkippedItem(f.path, f.reason) for f in detection.skipped_files),
        *_skipped(detection.skipped),
        *(SkippedItem(f.report_name, "limit") for f in detection.limited),
        *_skipped(generation.skipped if generation else ()),
        *_skipped(analysis.skipped),
    )


def _report_usage(llm_cases: _LLMCases | None) -> ReportUsage:
    """Tokens and cost of the run's LLM calls; a local model costs 0."""
    if llm_cases is None:
        return ReportUsage()
    tokens = llm_cases.generation.usage
    cost = llm_cases.generation.cost_usd if tokens.calls else 0.0
    return ReportUsage(
        tokens.calls,
        tokens.input_tokens,
        tokens.output_tokens,
        tokens.reasoning_tokens,
        0.0 if llm_cases.local else cost,
        llm_cases.local,
    )


def _build_report(
    config: Config,
    base_sha: str,
    intent: str | None,
    detection: Detection,
    analysis: Analysis,
    llm_cases: _LLMCases | None,
) -> Report:
    generation = llm_cases.generation if llm_cases else None
    return Report(
        version=__version__,
        base_ref=config.base,
        base_sha=base_sha,
        intent=intent,
        findings=analysis.findings,
        functions_checked=len(analysis.checked),
        cases_run=analysis.cases_run,
        flaky_dropped=analysis.flaky_dropped,
        invalid_cases_dropped=generation.invalid_cases_dropped if generation else 0,
        type_mismatch_dropped=analysis.type_mismatch_dropped,
        skipped=_skipped_items(detection, generation, analysis),
        removed=detection.removed,
        usage=_report_usage(llm_cases),
        refined=llm_cases.refined if llm_cases else 0,
        refinement_cases=llm_cases.refinement_cases if llm_cases else 0,
        refinement_skipped=tuple(
            _skipped(llm_cases.refinement_skipped if llm_cases else ())
        ),
    )


def _write_tests(
    config: Config, root: Path, base_sha: str, findings: Sequence[Finding]
) -> WrittenTests:
    # The report is still useful without the tests: warn and go on.
    try:
        return write_tests(
            root, Path(config.output_dir), findings, __version__, base_sha
        )
    except OSError as error:
        print(
            f"didibreak: warning: could not write the reproducing tests: {error}",
            file=sys.stderr,
        )
        return WrittenTests(tuple(findings), (), ())


def _print_report(report: Report, config: Config, llm: bool) -> None:
    if config.format == "json":
        sys.stdout.write(render_json(report))
        return
    # Colors only on a terminal and without NO_COLOR (Detailed Design 7).
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    sys.stdout.write(results_text(report, color=color, llm=llm))


CASES_FILE_REASON = "intent labelling needs the LLM, which --cases-file runs do not use"


def _intent(config: Config, root: Path, base_sha: str) -> str | None:
    # The commits in base..HEAD are part of the change, so their messages
    # describe its intent (owner decision 2026-11-07); against HEAD there
    # are none.
    return intent_text(config.intent, commit_messages(root, base_sha))


@dataclass(frozen=True)
class _Run:
    """What a check run knows before any function is executed.

    Attributes:
        config: The effective configuration.
        root: Repository root.
        base_sha: Base commit.
        files: Changed, deleted and excluded Python files.
        detection: Changed functions, selected and skipped.
        cases: Cases from ``--cases-file``, or None for the LLM.
    """

    config: Config
    root: Path
    base_sha: str
    files: ChangedFiles
    detection: Detection
    cases: Mapping[str, tuple[Case, ...]] | None


def _prepare(arguments: argparse.Namespace) -> _Run:
    """Load the configuration, the base, the changed files and functions.

    Raises:
        GitError, ConfigError, OSError: Setup problems (exit 2).
    """
    cli_values = {
        key: getattr(arguments, key) for key in CONFIG_KEYS if hasattr(arguments, key)
    }
    working_directory = Path.cwd()
    config = load_config(cli_values, working_directory)
    cases = (
        load_cases_file(working_directory / arguments.cases_file)
        if arguments.cases_file
        else None
    )
    root = repository_root(working_directory)
    base_sha = resolve_base(root, config.base)
    files = changed_python_files(root, base_sha, config.exclude)
    sources = load_source_files(root, base_sha, files)
    detection = detect_changed_functions(sources, config.max_functions)
    return _Run(config, root, base_sha, files, detection, cases)


def _print_header(run: _Run, verbose: bool) -> None:
    header = header_lines(
        __version__,
        run.config.base,
        run.base_sha,
        run.files.excluded,
        run.detection,
        run.config.max_functions,
        verbose,
    )
    print("\n".join(header), flush=True)


_EMPTY = Analysis((), (), (), 0, 0, 0)


def _report_nothing_to_check(run: _Run) -> int:
    """No function was selected: say so and print the (empty) report."""
    if run.config.format == "text" and not run.detection.skipped:
        print(
            "Nothing to check: no changed Python functions compared with "
            f"{run.config.base}"
        )
    report = _build_report(run.config, run.base_sha, None, run.detection, _EMPTY, None)
    _print_report(report, run.config, llm=False)
    return EXIT_OK


def _run_cases_function(run: _Run) -> _RunCases:
    def run_cases(
        selected: Sequence[ChangedFunction], chosen: Mapping[str, Sequence[Case]]
    ) -> Analysis:
        return _analyze(run.config, run.root, run.base_sha, run.files, selected, chosen)

    return run_cases


def _analyse_cases_file(
    run: _Run, cases: Mapping[str, Sequence[Case]], intent: str | None
) -> Analysis:
    """Run the --cases-file cases; findings stay unclear (no LLM labels)."""
    analysis = _run_cases_function(run)(run.detection.functions, cases)
    reason = CASES_FILE_REASON if intent else NO_INTENT_REASON
    return replace(analysis, findings=mark_unclear(analysis.findings, reason))


def _analyse_with_llm(
    run: _Run, arguments: argparse.Namespace, intent: str | None
) -> tuple[Analysis, _LLMCases | None] | None:
    """Import check, LLM cases, comparison, labels; None when cancelled."""
    config, root, base_sha, files = run.config, run.root, run.base_sha, run.files
    functions, unimportable = _importable(
        config, root, base_sha, files, run.detection.functions
    )
    analysis, llm_cases = _EMPTY, None
    if functions:
        session = _start_llm(config, functions, arguments, intent)
        if session is None:
            return None
        with session:
            analysis, llm_cases = _check_with_llm(
                session, functions, _run_cases_function(run), intent
            )
    return replace(analysis, skipped=(*unimportable, *analysis.skipped)), llm_cases


def _finish(
    run: _Run, intent: str | None, analysis: Analysis, llm_cases: _LLMCases | None
) -> int:
    """Write the reproducing tests, print the report, return the exit code."""
    config = run.config
    tests = _write_tests(config, run.root, run.base_sha, analysis.findings)
    analysis = replace(analysis, findings=tests.findings)
    report = replace(
        _build_report(config, run.base_sha, intent, run.detection, analysis, llm_cases),
        test_files=tests.files,
        no_tests=tuple(SkippedItem(call, reason) for call, reason in tests.not_written),
    )
    _print_report(report, config, llm=llm_cases is not None)
    problem = nothing_checked_error(report, run.detection.functions)
    if problem is not None:
        print(f"didibreak: error: {problem}", file=sys.stderr)
        return EXIT_ERROR
    return exit_code_for(
        [finding.label for finding in analysis.findings if finding.label],
        config.fail_on,
    )


def _run_check(arguments: argparse.Namespace) -> int:
    try:
        run = _prepare(arguments)
    except (GitError, ConfigError, OSError) as error:
        print(f"didibreak: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if run.config.format == "text":
        _print_header(run, arguments.verbose)
    if not run.detection.functions:
        return _report_nothing_to_check(run)
    intent = _intent(run.config, run.root, run.base_sha)
    result: tuple[Analysis, _LLMCases | None] | None
    try:
        if run.cases is not None:
            result = _analyse_cases_file(run, run.cases, intent), None
        else:
            result = _analyse_with_llm(run, arguments, intent)
    except (ConfigError, LLMAuthError, LLMModelError, GitError, OSError) as error:
        print(f"didibreak: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if result is None:
        print("Cancelled: no LLM request was sent.", file=sys.stderr)
        return EXIT_OK
    return _finish(run, intent, *result)


def is_supported_platform(platform: str) -> bool:
    """Whether didibreak runs on this platform (``sys.platform`` value).

    Args:
        platform: A ``sys.platform`` value such as ``linux`` or ``win32``.

    Returns:
        False on Windows, True elsewhere.
    """
    return platform != "win32"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the didibreak command line.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 no failing findings, 1 failing findings,
        2 tool or configuration error (also for a command on Windows,
        before any work), 130 interrupted (Ctrl-C).
    """
    parser = build_parser()
    # --help and --version end inside parse_args and run no user code, so
    # they work on Windows too (owner decision 2026-11-11, task 34 review).
    arguments = parser.parse_args(argv)
    if arguments.command is not None and not is_supported_platform(sys.platform):
        print(UNSUPPORTED_PLATFORM_MESSAGE, file=sys.stderr)
        return EXIT_ERROR
    if arguments.command == "check":
        try:
            return _run_check(arguments)
        except KeyboardInterrupt:
            # Worktree, copy and child processes are cleaned up by their
            # context managers and finally blocks on the way out.
            print("didibreak: interrupted", file=sys.stderr)
            return EXIT_INTERRUPTED
    if arguments.command == "init-agents":
        print(AGENT_SNIPPET, end="")
        return EXIT_OK
    parser.print_help()
    return EXIT_OK
