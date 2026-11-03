"""Tests for repository detection and base resolution."""

import subprocess
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.gitdiff import GitError, repository_root, resolve_base


def test_root_is_found_from_a_subdirectory(git_repository: GitRepository) -> None:
    subdirectory = git_repository.path / "src" / "app"
    subdirectory.mkdir(parents=True)

    assert repository_root(subdirectory).resolve() == git_repository.path.resolve()


def test_directory_outside_a_repository_is_an_error(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    with pytest.raises(GitError, match="is not inside a git repository"):
        repository_root(outside)


def test_missing_git_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(GitError, match="git is not installed"):
        repository_root(tmp_path)


def test_base_refs_resolve_to_commit_shas(git_repository: GitRepository) -> None:
    git_repository.write("app.py", "x = 1\n")
    first = git_repository.commit("first")
    git_repository.git("tag", "v1")
    git_repository.write("app.py", "x = 2\n")
    second = git_repository.commit("second")

    assert resolve_base(git_repository.path, "HEAD") == second
    assert resolve_base(git_repository.path, "HEAD~1") == first
    assert resolve_base(git_repository.path, "v1") == first
    assert resolve_base(git_repository.path, "main") == second


def test_unknown_ref_is_an_error(git_repository: GitRepository) -> None:
    git_repository.write("app.py", "x = 1\n")
    git_repository.commit()

    with pytest.raises(GitError, match="unknown base ref 'no-such-branch'"):
        resolve_base(git_repository.path, "no-such-branch")


def test_head_of_an_empty_repository_is_an_unknown_ref(
    git_repository: GitRepository,
) -> None:
    with pytest.raises(GitError, match="unknown base ref 'HEAD'"):
        resolve_base(git_repository.path, "HEAD")


def test_ref_beyond_a_shallow_clone_suggests_fetching_history(
    git_repository: GitRepository, tmp_path: Path
) -> None:
    for number in range(3):
        git_repository.write("app.py", f"x = {number}\n")
        git_repository.commit(f"commit {number}")
    clone = tmp_path / "shallow"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "1",
            f"file://{git_repository.path}",
            str(clone),
        ],
        check=True,
    )

    assert len(resolve_base(clone, "HEAD")) == 40
    with pytest.raises(GitError, match="shallow clone: fetch more history"):
        resolve_base(clone, "HEAD~1")
