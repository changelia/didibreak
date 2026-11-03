"""Tests for the temporary base worktree: contents, cleanup, and no side effects."""

import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.gitdiff import GitError, base_worktree, resolve_base


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Send didibreak's temporary folders to a known place to check cleanup."""
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def changed_repository(git_repository: GitRepository) -> GitRepository:
    git_repository.write("app.py", "VALUE = 'base'\n")
    git_repository.write("staged.py", "S = 1\n")
    git_repository.commit()
    git_repository.write("app.py", "VALUE = 'working tree'\n")
    git_repository.write("staged.py", "S = 2\n")
    git_repository.git("add", "staged.py")
    git_repository.write("untracked.py", "U = 1\n")
    return git_repository


def _worktree_count(repository: GitRepository) -> int:
    return repository.git("worktree", "list", "--porcelain").count("worktree ")


def _snapshot(repository: GitRepository) -> tuple[str, str, str]:
    return (
        repository.status(),
        repository.git("diff"),
        repository.git("diff", "--cached"),
    )


def test_worktree_contains_the_base_version(
    changed_repository: GitRepository, temp_root: Path
) -> None:
    base = resolve_base(changed_repository.path, "HEAD")

    with base_worktree(changed_repository.path, base) as tree:
        assert (tree / "app.py").read_text() == "VALUE = 'base'\n"
        assert (tree / "staged.py").read_text() == "S = 1\n"
        assert not (tree / "untracked.py").exists()


def test_worktree_is_removed_after_success(
    changed_repository: GitRepository, temp_root: Path
) -> None:
    base = resolve_base(changed_repository.path, "HEAD")

    with base_worktree(changed_repository.path, base) as tree:
        assert _worktree_count(changed_repository) == 2

    assert not tree.exists()
    assert _worktree_count(changed_repository) == 1
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_worktree_is_removed_after_an_error_or_ctrl_c(
    changed_repository: GitRepository, temp_root: Path, error: BaseException
) -> None:
    base = resolve_base(changed_repository.path, "HEAD")

    with pytest.raises(type(error)), base_worktree(changed_repository.path, base):
        raise error

    assert _worktree_count(changed_repository) == 1
    assert list(temp_root.iterdir()) == []


def test_worktree_is_removed_when_the_process_gets_sigint(
    changed_repository: GitRepository, tmp_path: Path
) -> None:
    script = (
        "import sys, time, pathlib\n"
        "from didibreak.gitdiff import base_worktree, resolve_base\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "with base_worktree(root, resolve_base(root, 'HEAD')) as tree:\n"
        "    print(tree, flush=True)\n"
        "    time.sleep(30)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(changed_repository.path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    tree = Path(process.stdout.readline().strip())
    assert tree.is_dir()

    process.send_signal(signal.SIGINT)
    process.wait(timeout=20)

    assert "KeyboardInterrupt" in (process.stderr.read() if process.stderr else "")
    assert not tree.exists()
    assert _worktree_count(changed_repository) == 1


def test_users_working_tree_and_index_are_not_modified(
    changed_repository: GitRepository, temp_root: Path
) -> None:
    before = _snapshot(changed_repository)
    base = resolve_base(changed_repository.path, "HEAD")

    with base_worktree(changed_repository.path, base) as tree:
        (tree / "app.py").write_text("changed inside the base tree\n")
        assert _snapshot(changed_repository) == before

    assert _snapshot(changed_repository) == before


def test_post_checkout_hook_does_not_run(
    changed_repository: GitRepository, temp_root: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "hook-ran"
    hook = changed_repository.path / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    base = resolve_base(changed_repository.path, "HEAD")

    with base_worktree(changed_repository.path, base):
        pass

    assert not marker.exists()


def test_unusable_base_is_an_error_and_leaves_nothing_behind(
    changed_repository: GitRepository, temp_root: Path
) -> None:
    with (
        pytest.raises(GitError, match="could not check out the base commit"),
        base_worktree(changed_repository.path, "0" * 40),
    ):
        pass

    assert _worktree_count(changed_repository) == 1
    assert list(temp_root.iterdir()) == []
