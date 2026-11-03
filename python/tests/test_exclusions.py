"""Tests for default and user file exclusions."""

import pytest
from conftest import GitRepository

from didibreak.gitdiff import (
    DEFAULT_EXCLUDES,
    changed_python_files,
    is_excluded,
    resolve_base,
)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "app/tests/helpers.py",
        "test_app.py",
        "app/user_test.py",
        "conftest.py",
        "app/migrations/0001_initial.py",
        "alembic/versions/abc_add_table.py",
        "setup.py",
        "docs/conf.py",
    ],
)
def test_default_exclusions_match(path: str) -> None:
    assert is_excluded(path, DEFAULT_EXCLUDES)


@pytest.mark.parametrize(
    "path",
    [
        "app/core.py",
        "app/testing.py",
        "contest.py",
        "app/latest_tests.py",
        "mydocs/x.py",
    ],
)
def test_ordinary_files_are_not_excluded(path: str) -> None:
    assert not is_excluded(path, DEFAULT_EXCLUDES)


def test_user_patterns_with_a_slash_match_the_whole_path() -> None:
    assert is_excluded("scripts/tool.py", ["scripts/*"])
    assert is_excluded("scripts/sub/tool.py", ["scripts/*"])
    assert not is_excluded("app/scripts/tool.py", ["scripts/*"])


def test_user_patterns_without_a_slash_match_the_file_name() -> None:
    assert is_excluded("app/settings_local.py", ["settings_*.py"])


def test_excluded_files_are_left_out_of_changed_files(
    git_repository: GitRepository,
) -> None:
    for path in ("app/core.py", "tests/test_core.py", "scripts/run.py"):
        git_repository.write(path, "x = 1\n")
    git_repository.commit()
    for path in ("app/core.py", "tests/test_core.py", "scripts/run.py"):
        git_repository.write(path, "x = 2\n")

    base = resolve_base(git_repository.path, "HEAD")
    result = changed_python_files(git_repository.path, base, exclude=["scripts/*"])

    assert [item.path for item in result.changed] == ["app/core.py"]
    assert result.excluded == ("scripts/run.py", "tests/test_core.py")
