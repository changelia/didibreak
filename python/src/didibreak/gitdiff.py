"""Git access: repository root, base resolution, changed files, base worktree.

All git calls run as subprocesses; this module is the only place that talks
to git. Nothing here writes to the user's working tree or index.
"""

import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

# Default exclusions (owner decision Q9, Detailed Design section 2).
DEFAULT_EXCLUDES = (
    "tests/",
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "migrations/",
    "alembic/versions/",
    "setup.py",
    "docs/",
)


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
    """Changed Python files, sorted by path.

    Attributes:
        changed: Files to check.
        deleted: Deleted Python files (ignored in v0.1).
        excluded: Changed Python files left out by exclusion patterns.
    """

    changed: tuple[ChangedFile, ...]
    deleted: tuple[str, ...]
    excluded: tuple[str, ...]


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
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        message += (
            ". The repository has no commits yet: commit your code first so "
            "there is a base version to compare with"
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


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    """Tell whether a repository-relative path matches any exclusion pattern.

    Pattern forms:

    - ending in ``/`` (``tests/``, ``alembic/versions/``): the folder at any depth;
    - containing ``/`` (``scripts/*``): glob against the whole path;
    - otherwise (``test_*.py``): glob against the file name.

    Args:
        path: Repository-relative POSIX path.
        patterns: Exclusion patterns.

    Returns:
        True if the path is excluded.
    """
    name = PurePosixPath(path).name
    for pattern in patterns:
        if pattern.endswith("/"):
            if f"/{pattern}" in f"/{path}":
                return True
        elif "/" in pattern:
            if fnmatchcase(path, pattern):
                return True
        elif fnmatchcase(name, pattern):
            return True
    return False


def _is_python(path: str | None) -> bool:
    return path is not None and path.endswith(".py")


def changed_python_files(
    root: Path, base_sha: str, exclude: Sequence[str] = ()
) -> ChangedFiles:
    """List Python files changed between the base commit and the working tree.

    Staged and unstaged changes count; untracked files (not ignored by
    .gitignore) are included. Changes inside submodules are not listed: git
    reports a submodule only as its folder path.

    Args:
        root: Repository root.
        base_sha: Base commit from resolve_base().
        exclude: User patterns, applied after DEFAULT_EXCLUDES.

    Returns:
        The changed, deleted and excluded Python files.

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
    patterns = (*DEFAULT_EXCLUDES, *exclude)
    python_files: list[ChangedFile] = []
    excluded: list[str] = []
    for item in changed:
        if is_excluded(item.path, patterns):
            if _is_python(item.path):
                excluded.append(item.path)
            continue
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
        deleted=tuple(
            sorted(
                path
                for path in deleted
                if _is_python(path) and not is_excluded(path, patterns)
            )
        ),
        excluded=tuple(sorted(excluded)),
    )


def read_base_file(root: Path, base_sha: str, path: str) -> bytes:
    """Read a file's content at the base commit without checking it out.

    Args:
        root: Repository root.
        base_sha: Base commit.
        path: Repository-relative POSIX path at the base commit.

    Returns:
        The raw file content.

    Raises:
        GitError: If the file does not exist at the base commit.
    """
    try:
        result = subprocess.run(
            ["git", "cat-file", "blob", f"{base_sha}:{path}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitError(
            "git is not installed or not on PATH; install git and try again"
        ) from error
    if result.returncode != 0:
        raise GitError(f"{path} does not exist at base commit {base_sha[:12]}")
    return result.stdout


@contextmanager
def base_worktree(root: Path, base_sha: str) -> Iterator[Path]:
    """Check out the base commit in a temporary git worktree.

    The worktree lives in a new temporary folder, is detached (no branch is
    created) and is removed on success, on error and on Ctrl-C. Git hooks are
    disabled while it is created: ``git worktree add`` would otherwise run the
    user's post-checkout hook. The user's working tree and index are not
    touched; git only records the worktree under ``.git/worktrees`` until it
    is removed.

    Args:
        root: Repository root.
        base_sha: Commit to check out.

    Yields:
        Path of the checked-out base tree.

    Raises:
        GitError: If the worktree cannot be created.
    """
    temporary = Path(tempfile.mkdtemp(prefix="didibreak-base-"))
    tree = temporary / "tree"
    no_hooks = temporary / "no-hooks"
    no_hooks.mkdir()
    try:
        result = _git(
            root,
            "-c",
            f"core.hooksPath={no_hooks}",
            "worktree",
            "add",
            "--detach",
            "--quiet",
            str(tree),
            base_sha,
        )
        if result.returncode != 0:
            raise GitError(
                f"could not check out the base commit {base_sha[:12]} in a "
                f"temporary worktree: {result.stderr.strip()}"
            )
        yield tree
    finally:
        _remove_worktree(root, tree)
        shutil.rmtree(temporary, ignore_errors=True)


def _remove_worktree(root: Path, tree: Path) -> None:
    # Fails harmlessly when the worktree was never created.
    _git(root, "worktree", "remove", "--force", str(tree))


def visible_files(root: Path) -> list[str]:
    """Files git sees in the working tree: tracked and untracked, not ignored.

    Args:
        root: Repository root.

    Returns:
        Sorted repository-relative POSIX paths of files that exist; tracked
        files deleted from the working tree are left out.

    Raises:
        GitError: If git cannot list the files.
    """
    result = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        raise GitError(
            f"could not list the working tree files: {result.stderr.strip()}"
        )
    paths = {path for path in result.stdout.split("\0") if path}
    return sorted(
        path for path in paths if (root / path).is_file() or (root / path).is_symlink()
    )


@contextmanager
def working_tree_copy(root: Path, skip: Sequence[str] = ()) -> Iterator[Path]:
    """Copy the working tree to a temporary folder (Spec, Safety).

    The current version runs from this copy, never from the user's working
    tree. Only files git sees are copied (visible_files), so ``.git``,
    ignored files and virtual environments stay out. Symbolic links are
    copied as links. The copy is removed on success, on error and on Ctrl-C.

    Args:
        root: Repository root.
        skip: Repository-relative folders not to copy, e.g. the output folder.

    Yields:
        Path of the copied tree.

    Raises:
        GitError: If git cannot list the files.
        OSError: If a file cannot be copied.
    """
    temporary = Path(tempfile.mkdtemp(prefix="didibreak-current-"))
    tree = temporary / "tree"
    try:
        prefixes = tuple(f"{folder.rstrip('/')}/" for folder in skip)
        for path in visible_files(root):
            if path.startswith(prefixes):
                continue
            destination = tree / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / path, destination, follow_symlinks=False)
        tree.mkdir(exist_ok=True)
        yield tree
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def commit_messages(root: Path, base_sha: str) -> list[str]:
    """Messages of the commits in base..HEAD, newest first.

    Args:
        root: Repository root.
        base_sha: The base commit; its own message is not included.

    Returns:
        Non-empty messages without surrounding whitespace; empty when HEAD is
        the base or git cannot list the commits.
    """
    result = _git(root, "log", "--format=%B%x00", f"{base_sha}..HEAD", "--")
    if result.returncode != 0:
        return []
    return [text.strip() for text in result.stdout.split("\0") if text.strip()]


def commit_message(root: Path, ref: str = "HEAD") -> str | None:
    """The full message of a commit, or None if it cannot be read.

    Args:
        root: Repository root.
        ref: Commit to read.

    Returns:
        The message without surrounding whitespace, or None.
    """
    result = _git(root, "log", "-1", "--format=%B", ref, "--")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
