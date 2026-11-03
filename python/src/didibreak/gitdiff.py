"""Git access: repository detection (base resolution and worktrees follow in task 05).

All git calls run as subprocesses; this module is the only place that talks
to git.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    """Git is missing or the directory is not usable; the message is user-facing."""


def repository_root(directory: Path) -> Path:
    """Return the top-level directory of the git repository containing ``directory``.

    Args:
        directory: Any directory inside the repository.

    Returns:
        The absolute repository root.

    Raises:
        GitError: If git is not installed or ``directory`` is not in a repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitError(
            "git is not installed or not on PATH; install git and try again"
        ) from error
    if result.returncode != 0:
        raise GitError(
            f"{directory} is not inside a git repository; run didibreak from "
            "within a git repository (or run `git init` first)"
        )
    return Path(result.stdout.strip())
