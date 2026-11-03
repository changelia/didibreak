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
from didibreak.gitdiff import (
    GitError,
    changed_python_files,
    repository_root,
    resolve_base,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

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


def _run_check(arguments: argparse.Namespace) -> int:
    cli_values = {
        key: getattr(arguments, key) for key in CONFIG_KEYS if hasattr(arguments, key)
    }
    try:
        working_directory = Path.cwd()
        config = load_config(cli_values, working_directory)
        root = repository_root(working_directory)
        base_sha = resolve_base(root, config.base)
        files = changed_python_files(root, base_sha, config.exclude)
    except (GitError, ConfigError) as error:
        print(f"didibreak: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if config.format == "text":
        _report_excluded(files.excluded, verbose=arguments.verbose)
    if not files.changed:
        print(
            f"Nothing to check: no changed Python files compared with {config.base}",
            file=sys.stderr,
        )
        return EXIT_OK
    # TODO(task 06): detect changed functions and run the pipeline.
    print(
        f"didibreak: {len(files.changed)} changed Python file(s) compared with "
        f"{config.base}; the analysis is not implemented yet",
        file=sys.stderr,
    )
    return exit_code_for([], config.fail_on)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the didibreak command line.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 no failing findings, 1 failing findings,
        2 tool or configuration error.
    """
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "check":
        return _run_check(arguments)
    if arguments.command == "init-agents":
        print(AGENT_SNIPPET, end="")
        return EXIT_OK
    parser.print_help()
    return EXIT_OK
