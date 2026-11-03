"""Tests for git repository detection."""

import subprocess
from pathlib import Path

import pytest

from didibreak.gitdiff import GitError, repository_root


def _init_repository(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_root_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "repo")
    subdirectory = repository / "src" / "app"
    subdirectory.mkdir(parents=True)

    assert repository_root(subdirectory).resolve() == repository.resolve()


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
