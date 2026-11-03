"""Git access: repository root, base resolution, changed files, base worktree.

All git calls run as subprocesses; this module is the only place that talks
to git. Nothing here writes to the user's working tree or index.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    """Git is missing or the directory is not usable; the message is user-facing."""


def _git(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitError(
            "git is not installed or not on PATH; install git and try again"
        ) from error


def repository_root(directory: Path) -> Path:
    """Return the top-level directory of the git repository containing ``directory``.

    Args:
        directory: Any directory inside the repository.

    Returns:
        The absolute repository root.

    Raises:
        GitError: If git is not installed or ``directory`` is not in a repository.
    """
    result = _git(directory, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise GitError(
            f"{directory} is not inside a git repository; run didibreak from "
            "within a git repository (or run `git init` first)"
        )
    return Path(result.stdout.strip())


def resolve_base(root: Path, ref: str) -> str:
    """Resolve the base ref to a full commit SHA.

    Args:
        root: Repository root.
        ref: Branch, tag, commit or expression such as ``HEAD~1``.

    Returns:
        The 40-character commit SHA.

    Raises:
        GitError: If the ref does not name a commit in this repository.
    """
    result = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if result.returncode == 0:
        return result.stdout.strip()
    message = (
        f"unknown base ref {ref!r}; use a branch, tag or commit that exists "
        "in this repository (see `git branch -a` and `git log`)"
    )
    shallow = _git(root, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow == "true":
        message += (
            ". This is a shallow clone: fetch more history first, e.g. "
            "`git fetch --unshallow`"
        )
    raise GitError(message)
