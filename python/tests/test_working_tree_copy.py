import os
from pathlib import Path

from conftest import GitRepository

from didibreak.gitdiff import visible_files, working_tree_copy


def make_repository(git_repository: GitRepository) -> Path:
    git_repository.write(".gitignore", ".venv/\n*.log\n")
    git_repository.write("app/core.py", "VALUE = 1\n")
    git_repository.write("app/gone.py", "OLD = 1\n")
    git_repository.commit("base")
    git_repository.write("app/core.py", "VALUE = 2\n")  # modified
    git_repository.write("app/new.py", "NEW = 1\n")  # untracked
    git_repository.write("debug.log", "ignored\n")
    git_repository.write(".venv/lib.py", "ignored\n")
    git_repository.write(".didibreak/cache.json", "{}\n")
    (git_repository.path / "app/gone.py").unlink()  # deleted, still in the index
    return git_repository.path


def test_visible_files_are_tracked_and_untracked_but_not_ignored(
    git_repository: GitRepository,
) -> None:
    root = make_repository(git_repository)

    assert visible_files(root) == [
        ".didibreak/cache.json",
        ".gitignore",
        "app/core.py",
        "app/new.py",
    ]


def test_copy_has_the_working_tree_contents_and_is_removed_afterwards(
    git_repository: GitRepository,
) -> None:
    root = make_repository(git_repository)
    status = git_repository.status()

    with working_tree_copy(root, skip=[".didibreak"]) as tree:
        copied = sorted(
            path.relative_to(tree).as_posix()
            for path in tree.rglob("*")
            if path.is_file()
        )
        assert copied == [".gitignore", "app/core.py", "app/new.py"]
        assert (tree / "app/core.py").read_text() == "VALUE = 2\n"
        assert not (tree / ".git").exists()
        assert not tree.resolve().is_relative_to(root.resolve())
        (tree / "app/core.py").write_text("changed in the copy\n")

    assert not tree.exists()
    assert (root / "app/core.py").read_text() == "VALUE = 2\n"
    assert git_repository.status() == status


def test_symbolic_links_are_copied_as_links(git_repository: GitRepository) -> None:
    git_repository.write("app/real.py", "X = 1\n")
    os.symlink("real.py", git_repository.path / "app/alias.py")
    git_repository.commit("links")

    with working_tree_copy(git_repository.path) as tree:
        assert (tree / "app/alias.py").is_symlink()
        assert os.readlink(tree / "app/alias.py") == "real.py"
