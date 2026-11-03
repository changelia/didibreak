"""Git access: repository root, base resolution, changed files, base worktree.

All git calls run as subprocesses; this module is the only place that talks
to git. Nothing here writes to the user's working tree or index.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """Git is missing or the directory is not usable; the message is user-facing."""


@dataclass(frozen=True)
class ChangedFile:
    """A Python file that differs between the base commit and the working tree.

    Attributes:
        path: Repository-relative POSIX path in the working tree.
        old_path: Path at the base commit; None when the file is new.
        status: ``modified``, ``added``, ``renamed`` or ``untracked``.
    """

    path: str
    old_path: str | None
    status: str


@dataclass(frozen=True)
class ChangedFiles:
    """Changed Python files, sorted by path, plus deleted ones (ignored in v0.1)."""

    changed: tuple[ChangedFile, ...]
    deleted: tuple[str, ...]


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


def parse_name_status(output: str) -> tuple[list[ChangedFile], list[str]]:
    """Parse ``git diff --name-status -z -M`` output into changed and deleted paths.

    Args:
        output: NUL-separated output: status, path, and a second path for
            renames and copies.

    Returns:
        Changed files (any extension) and deleted paths, in git's order.
    """
    fields = output.split("\0")
    changed: list[ChangedFile] = []
    deleted: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        kind = status[0]
        if kind in "RC":
            old_path, new_path = fields[index + 1], fields[index + 2]
            index += 3
            if kind == "R":
                changed.append(ChangedFile(new_path, old_path, "renamed"))
            else:
                changed.append(ChangedFile(new_path, None, "added"))
            continue
        path = fields[index + 1]
        index += 2
        if kind == "D":
            deleted.append(path)
        elif kind == "A":
            changed.append(ChangedFile(path, None, "added"))
        else:  # M, T (type change), U (unmerged)
            changed.append(ChangedFile(path, path, "modified"))
    return changed, deleted


def _is_python(path: str | None) -> bool:
    return path is not None and path.endswith(".py")


def changed_python_files(root: Path, base_sha: str) -> ChangedFiles:
    """List Python files changed between the base commit and the working tree.

    Staged and unstaged changes count; untracked files (not ignored by
    .gitignore) are included. Changes inside submodules are not listed: git
    reports a submodule only as its folder path.

    Args:
        root: Repository root.
        base_sha: Base commit from resolve_base().

    Returns:
        The changed and deleted Python files.

    Raises:
        GitError: If git fails.
    """
    diff = _git(root, "diff", "--name-status", "-z", "-M", base_sha, "--")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for result in (diff, untracked):
        if result.returncode != 0:
            raise GitError(f"git failed: {result.stderr.strip()}")

    changed, deleted = parse_name_status(diff.stdout)
    changed += [
        ChangedFile(path, None, "untracked")
        for path in untracked.stdout.split("\0")
        if path
    ]
    python_files: list[ChangedFile] = []
    for item in changed:
        old_is_python = _is_python(item.old_path)
        if not _is_python(item.path):
            # A Python file renamed to another extension is gone as Python code.
            if item.status == "renamed" and item.old_path and old_is_python:
                deleted.append(item.old_path)
        elif item.status == "renamed" and not old_is_python:
            # Renamed from a non-Python file: there is no Python base version.
            python_files.append(ChangedFile(item.path, None, "added"))
        else:
            python_files.append(item)
    return ChangedFiles(
        changed=tuple(sorted(python_files, key=lambda item: item.path)),
        deleted=tuple(sorted(path for path in deleted if _is_python(path))),
    )
