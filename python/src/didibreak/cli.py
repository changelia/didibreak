"""Command-line interface for didibreak.

Only ``--version`` exists so far; the ``check`` and ``init-agents`` commands
from the Detailed Design are added by later tasks.
"""

import argparse
from collections.abc import Sequence

from didibreak import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="didibreak",
        description=(
            "Find unintended behavior changes in Python code changes "
            "by running the old and new versions side by side."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the didibreak command line.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = _build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
