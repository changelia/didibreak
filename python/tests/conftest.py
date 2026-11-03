"""Shared fixtures: tiny git repositories created inside each test."""

import subprocess
from pathlib import Path

import pytest


class GitRepository:
    """A throwaway git repository with helpers to write files and commit."""

    def __init__(self, path: Path) -> None:
        """Create an empty repository with a fixed identity at ``path``."""
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *arguments: str) -> str:
        """Run git in the repository and return its stdout."""
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def write(self, relative_path: str, text: str) -> Path:
        """Write a file, creating parent folders."""
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, message: str = "change") -> str:
        """Stage everything, commit, and return the commit SHA."""
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def status(self) -> str:
        """Porcelain status including untracked files, for before/after checks."""
        return self.git("status", "--porcelain=v2", "--untracked-files=all")


@pytest.fixture
def git_repository(tmp_path: Path) -> GitRepository:
    return GitRepository(tmp_path / "repo")
