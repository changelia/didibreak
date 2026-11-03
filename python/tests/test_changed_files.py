"""Tests for listing changed Python files between the base and the working tree."""

from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.gitdiff import (
    ChangedFile,
    GitError,
    changed_python_files,
    parse_name_status,
    read_base_file,
    resolve_base,
)


def _changes(repository: GitRepository, ref: str = "HEAD") -> list[tuple[str, ...]]:
    base = resolve_base(repository.path, ref)
    result = changed_python_files(repository.path, base)
    return [(f.path, str(f.old_path), f.status) for f in result.changed]


def test_parse_name_status_handles_every_status() -> None:
    output = "M\0a.py\0D\0gone.py\0R087\0old.py\0new.py\0A\0add.py\0C100\0x.py\0y.py\0"

    changed, deleted = parse_name_status(output)

    assert changed == [
        ChangedFile("a.py", "a.py", "modified"),
        ChangedFile("new.py", "old.py", "renamed"),
        ChangedFile("add.py", None, "added"),
        ChangedFile("y.py", None, "added"),
    ]
    assert deleted == ["gone.py"]


def test_parse_name_status_of_no_changes_is_empty() -> None:
    assert parse_name_status("") == ([], [])


def test_uncommitted_staged_and_unstaged_changes_are_listed(
    git_repository: GitRepository,
) -> None:
    git_repository.write("app/a.py", "x = 1\n")
    git_repository.write("app/b.py", "y = 1\n")
    git_repository.commit()
    git_repository.write("app/a.py", "x = 2\n")
    git_repository.write("app/b.py", "y = 2\n")
    git_repository.git("add", "app/b.py")

    assert _changes(git_repository) == [
        ("app/a.py", "app/a.py", "modified"),
        ("app/b.py", "app/b.py", "modified"),
    ]


def test_committed_branch_is_compared_with_main(git_repository: GitRepository) -> None:
    git_repository.write("app.py", "x = 1\n")
    git_repository.commit("base")
    git_repository.git("switch", "-q", "-c", "feature")
    git_repository.write("app.py", "x = 2\n")
    git_repository.commit("feature work")

    assert _changes(git_repository, "main") == [("app.py", "app.py", "modified")]
    assert _changes(git_repository, "HEAD") == []


def test_untracked_new_file_is_listed_but_ignored_files_are_not(
    git_repository: GitRepository,
) -> None:
    git_repository.write(".gitignore", "build/\n")
    git_repository.commit()
    git_repository.write("new_module.py", "def f():\n    return 1\n")
    git_repository.write("build/generated.py", "x = 1\n")

    assert _changes(git_repository) == [("new_module.py", "None", "untracked")]


def test_deleted_file_is_reported_separately_not_as_changed(
    git_repository: GitRepository,
) -> None:
    git_repository.write("keep.py", "x = 1\n")
    git_repository.write("gone.py", "y = 1\n")
    git_repository.commit()
    (git_repository.path / "gone.py").unlink()

    base = resolve_base(git_repository.path, "HEAD")
    result = changed_python_files(git_repository.path, base)

    assert result.changed == ()
    assert result.deleted == ("gone.py",)


def test_renamed_file_keeps_its_old_path(git_repository: GitRepository) -> None:
    body = "".join(f"def f{n}():\n    return {n}\n" for n in range(10))
    git_repository.write("old_name.py", body)
    git_repository.commit()
    git_repository.git("mv", "old_name.py", "new_name.py")

    assert _changes(git_repository) == [("new_name.py", "old_name.py", "renamed")]


def test_non_python_files_are_ignored(git_repository: GitRepository) -> None:
    git_repository.write("README.md", "a\n")
    git_repository.write("app.py", "x = 1\n")
    git_repository.commit()
    git_repository.write("README.md", "b\n")
    git_repository.write("notes.txt", "new\n")

    assert _changes(git_repository) == []


def test_changes_inside_a_submodule_are_not_listed(
    git_repository: GitRepository, tmp_path: Path
) -> None:
    library = GitRepository(tmp_path / "library")
    library.write("lib.py", "def g():\n    return 1\n")
    library.commit()
    git_repository.write("app.py", "x = 1\n")
    git_repository.git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(library.path),
        "libs/library",
    )
    git_repository.commit()
    (git_repository.path / "libs/library/lib.py").write_text("def g():\n    return 2\n")
    git_repository.write("app.py", "x = 2\n")

    assert _changes(git_repository) == [("app.py", "app.py", "modified")]


def test_renames_across_extensions_become_added_or_deleted(
    git_repository: GitRepository,
) -> None:
    body = "".join(f"value_{n} = {n}\n" for n in range(10))
    git_repository.write("script.txt", body)
    git_repository.write("module.py", body.replace("value", "other"))
    git_repository.commit()
    git_repository.git("mv", "script.txt", "script.py")
    git_repository.git("mv", "module.py", "module.txt")

    base = resolve_base(git_repository.path, "HEAD")
    result = changed_python_files(git_repository.path, base)

    assert result.changed == (ChangedFile("script.py", None, "added"),)
    assert result.deleted == ("module.py",)


def test_base_file_content_is_read_without_checkout(
    git_repository: GitRepository,
) -> None:
    git_repository.write("app.py", "VALUE = 'base'\n")
    base = git_repository.commit()
    git_repository.write("app.py", "VALUE = 'current'\n")

    assert read_base_file(git_repository.path, base, "app.py") == b"VALUE = 'base'\n"


def test_reading_a_file_missing_at_base_is_an_error(
    git_repository: GitRepository,
) -> None:
    git_repository.write("app.py", "x = 1\n")
    base = git_repository.commit()

    with pytest.raises(GitError, match=r"new\.py does not exist at base commit"):
        read_base_file(git_repository.path, base, "new.py")
