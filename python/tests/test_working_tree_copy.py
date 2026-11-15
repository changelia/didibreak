import os
from pathlib import Path

from conftest import GitRepository

from didibreak.gitdiff import points_into, visible_files, working_tree_copy


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


def test_absolute_links_into_the_repository_are_not_copied(
    git_repository: GitRepository, tmp_path: Path
) -> None:
    # Audit 35a, finding 7: writes through such a link reached the real file.
    real = git_repository.write("data/real.txt", "original\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("shared\n")
    os.symlink(real, git_repository.path / "data/absolute_inside.txt")
    os.symlink(outside, git_repository.path / "data/absolute_outside.txt")
    os.symlink("real.txt", git_repository.path / "data/relative.txt")
    git_repository.commit("links")

    with working_tree_copy(git_repository.path) as tree:
        assert not (tree / "data/absolute_inside.txt").exists()
        assert not (tree / "data/absolute_inside.txt").is_symlink()
        assert (tree / "data/absolute_outside.txt").is_symlink()
        assert os.readlink(tree / "data/relative.txt") == "real.txt"
        assert (tree / "data/real.txt").read_text() == "original\n"


def test_an_absolute_link_into_the_repository_through_another_path_is_found(
    git_repository: GitRepository, tmp_path: Path
) -> None:
    real = git_repository.write("real.txt", "x\n")
    link = git_repository.path / "link.txt"
    # A path with "..", still inside the repository once resolved.
    os.symlink(git_repository.path / "data" / ".." / real.name, link)

    copy = tmp_path / "copy"
    assert points_into(link, git_repository.path, copy / "link.txt")
    assert not points_into(real, git_repository.path, copy / "real.txt")  # no link


def test_a_looping_absolute_link_is_left_out_of_the_copy(
    git_repository: GitRepository, tmp_path: Path
) -> None:
    # Pre-launch review, finding 8 (35c regression): resolving the loop
    # raised RuntimeError and ended the run with a traceback.
    git_repository.write("app/core.py", "VALUE = 1\n")
    loop = git_repository.path / "loop"
    os.symlink(loop, loop)
    first, second = git_repository.path / "first", git_repository.path / "second"
    os.symlink(second, first)
    os.symlink(first, second)

    assert points_into(loop, git_repository.path, tmp_path / "copy" / "loop")
    with working_tree_copy(git_repository.path) as tree:
        assert (tree / "app/core.py").read_text() == "VALUE = 1\n"
        assert not (tree / "loop").is_symlink()
        assert not (tree / "first").is_symlink()
        assert not (tree / "second").is_symlink()


def test_a_relative_link_that_climbs_back_into_the_repository_is_not_copied(
    git_repository: GitRepository,
) -> None:
    # Pre-launch review, finding 10: with enough "../" a relative link
    # reaches the real repository from the copy too, and a write through
    # it changed the user's file.
    root = git_repository.path
    git_repository.write("data/real.txt", "original\n")
    climb = "/".join([".."] * 40) + str(root.resolve())
    os.symlink(f"{climb}/data/real.txt", root / "rel_link.txt")
    os.symlink(f"{climb}/data", root / "rel_dir")
    os.symlink(f"../{climb}/data/real.txt", root / "data/deep_link.txt")
    os.symlink("data/real.txt", root / "plain_link.txt")
    os.symlink("data", root / "plain_dir")

    with working_tree_copy(root) as tree:
        assert not (tree / "rel_link.txt").is_symlink()
        assert not (tree / "rel_dir").is_symlink()
        assert not (tree / "data/deep_link.txt").is_symlink()
        assert os.readlink(tree / "plain_link.txt") == "data/real.txt"
        assert os.readlink(tree / "plain_dir") == "data"
        (tree / "plain_link.txt").write_text("written through the copy\n")
        (tree / "plain_dir" / "new_file.txt").write_text("new\n")

    assert (root / "data/real.txt").read_text() == "original\n"
    assert sorted(path.name for path in (root / "data").iterdir()) == [
        "deep_link.txt",
        "real.txt",
    ]


def test_a_relative_loop_inside_the_copy_is_copied_as_a_link(
    git_repository: GitRepository,
) -> None:
    git_repository.write("app/core.py", "VALUE = 1\n")
    os.symlink("self", git_repository.path / "self")

    with working_tree_copy(git_repository.path) as tree:
        assert os.readlink(tree / "self") == "self"
