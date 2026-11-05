"""Command-line interface: ``didibreak check``, ``didibreak init-agents``.

Flags and exit codes follow Detailed Design sections 1 and 10. Every flag
that has a config key is validated by ``config.validate`` so the CLI and
``[tool.didibreak]`` reject bad values with the same message.
"""

import argparse
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from didibreak import __version__
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
    Detection,
    SourceFile,
    detect_changed_functions,
)
from didibreak.gitdiff import (
    ChangedFiles,
    GitError,
    changed_python_files,
    read_base_file,
    repository_root,
    resolve_base,
)
from didibreak.harness import Case, HarnessSettings, Outcome
from didibreak.pipeline import Analysis, analyze, load_cases_file, tree_import_root

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130

AGENT_SNIPPET = """\
## Behavior check
After changing Python functions, run:
    didibreak check --intent "<the user's request in one sentence>" --format json
If any finding has label "unexpected", fix the code so that behavior is preserved,
then run the check again. Report "unclear" findings to the user instead of guessing.
"""


def exit_code_for(labels: Iterable[str], fail_on: str) -> int:
    """Map finding labels to the process exit code.

    Args:
        labels: Labels of all findings in the run.
        fail_on: ``unclear`` (fail on unexpected or unclear) or ``unexpected``.

    Returns:
        1 if any finding should fail the run, otherwise 0.
    """
    failing = {"unexpected"} if fail_on == "unexpected" else {"unexpected", "unclear"}
    return EXIT_FINDINGS if any(label in failing for label in labels) else EXIT_OK


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


def _report_excluded(excluded: Sequence[str], verbose: bool) -> None:
    # Owner decision (task 05 review): exclusions are never silent.
    if not excluded:
        return
    noun = "file" if len(excluded) == 1 else "files"
    print(f"{len(excluded)} {noun} excluded", file=sys.stderr)
    if verbose:
        for path in excluded:
            print(f"  excluded: {path}", file=sys.stderr)


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


def _report_detection(detection: Detection, max_functions: int, verbose: bool) -> None:
    for skipped in detection.skipped_files:
        print(f"skipped {skipped.path}: {skipped.reason}", file=sys.stderr)
    new = sum(1 for function in detection.functions if function.kind == "new")
    print(
        f"{len(detection.functions)} changed function(s) to check ({new} new)",
        file=sys.stderr,
    )
    if detection.skipped:
        print(
            f"{len(detection.skipped)} function(s) skipped: not testable in v0.1",
            file=sys.stderr,
        )
    if detection.limited:
        print(
            f"{len(detection.limited)} more not checked "
            f"(max_functions = {max_functions})",
            file=sys.stderr,
        )
    all_skipped = bool(detection.skipped) and not detection.functions
    if all_skipped:
        print(
            "Warning: checked 0 functions; all changed functions were skipped",
            file=sys.stderr,
        )
    if verbose or all_skipped:
        for function in detection.skipped:
            print(
                f"  skipped: {function.report_name} ({function.skip_reason})",
                file=sys.stderr,
            )
    if verbose:
        for function in detection.functions:
            print(f"  {function.kind}: {function.report_name}", file=sys.stderr)
        for function in detection.limited:
            print(f"  limit: {function.report_name}", file=sys.stderr)


def _analyze(
    config: Config,
    root: Path,
    base_sha: str,
    files: ChangedFiles,
    detection: Detection,
    cases: Mapping[str, Sequence[Case]],
) -> Analysis:
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
    return analyze(
        root, base_sha, detection.functions, base_paths, cases, settings, skip
    )


def _describe(outcome: Outcome | None) -> str:
    if outcome is None:
        return "(new function)"
    if outcome.kind == "exception":
        return f"raises {outcome.type_name}"
    return outcome.repr


def _report_analysis(analysis: Analysis) -> None:
    # Minimal listing on stderr until the text report (task 18).
    print(
        f"{analysis.cases_run} cases · {len(analysis.findings)} behavior "
        f"changes · {analysis.flaky_dropped} flaky dropped",
        file=sys.stderr,
    )
    for finding in analysis.findings:
        name, _, qualname = finding.function.rpartition("::")
        arguments = [*finding.case.args]
        arguments += [f"{key}={value}" for key, value in finding.case.kwargs.items()]
        label = (finding.label or "").upper().replace("_", "-")
        print(
            f"  {label:<13}{name}::{qualname}({', '.join(arguments)})\n"
            f"  {'':<13}before {_describe(finding.before)} → "
            f"after {_describe(finding.after)}",
            file=sys.stderr,
        )
    for function in analysis.skipped:
        print(
            f"  skipped: {function.report_name} ({function.skip_reason})",
            file=sys.stderr,
        )


def _run_check(arguments: argparse.Namespace) -> int:
    cli_values = {
        key: getattr(arguments, key) for key in CONFIG_KEYS if hasattr(arguments, key)
    }
    try:
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
    except (GitError, ConfigError, OSError) as error:
        print(f"didibreak: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    detection = detect_changed_functions(sources, config.max_functions)
    if config.format == "text":
        _report_excluded(files.excluded, verbose=arguments.verbose)
        _report_detection(detection, config.max_functions, verbose=arguments.verbose)
    if not detection.functions:
        if not detection.skipped:
            print(
                "Nothing to check: no changed Python functions compared with "
                f"{config.base}",
                file=sys.stderr,
            )
        return EXIT_OK
    if cases is None:
        # TODO(task 14): generate cases with the LLM.
        print("didibreak: the analysis is not implemented yet", file=sys.stderr)
        return exit_code_for([], config.fail_on)
    try:
        analysis = _analyze(config, root, base_sha, files, detection, cases)
    except (GitError, OSError) as error:
        print(f"didibreak: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if config.format == "text":
        _report_analysis(analysis)
    # TODO(task 18): print the JSON report for --format json.
    return exit_code_for(
        [finding.label for finding in analysis.findings if finding.label],
        config.fail_on,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the didibreak command line.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 no failing findings, 1 failing findings,
        2 tool or configuration error, 130 interrupted (Ctrl-C).
    """
    parser = build_parser()
    arguments = parser.parse_args(argv)
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
