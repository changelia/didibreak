"""The runtime I/O guard: which audit events it stops (pre-launch review 1, 2, 7).

is_blocked() is tested in this process. install() adds an audit hook that
can never be removed, so it is only ever called in a child process.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from didibreak import _io_guard
from didibreak._io_guard import BLOCKED_EVENTS, is_blocked, is_inside

GUARD_FILE = Path(_io_guard.__file__)


@pytest.fixture
def root(tmp_path: Path) -> str:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return os.path.realpath(scratch)


@pytest.mark.parametrize(
    "event",
    [
        "os.system",
        "os.exec",
        "subprocess.Popen",
        "os.fork",
        "os.kill",
        "socket.connect",
        "socket.getaddrinfo",
        "ctypes.dlopen",
    ],
)
def test_commands_processes_network_and_native_code_are_always_blocked(
    event: str, root: str
) -> None:
    assert BLOCKED_EVENTS[event] is None
    assert is_blocked(event, ("anything",), root)


@pytest.mark.parametrize("event", ["import", "exec", "os.listdir", "os.chdir"])
def test_other_events_pass(event: str, root: str) -> None:
    assert not is_blocked(event, ("x",), root)


def test_reading_any_file_is_allowed(root: str) -> None:
    assert not is_blocked("open", ("/etc/hosts", "r", os.O_RDONLY), root)
    assert not is_blocked("open", ("/etc/hosts", None, os.O_RDONLY), root)


@pytest.mark.parametrize(
    "mode, flags",
    [
        ("w", os.O_WRONLY | os.O_CREAT),
        ("a", os.O_APPEND),
        ("r+", os.O_RDWR),
        (None, os.O_WRONLY | os.O_CREAT),  # os.open
    ],
)
def test_writing_is_allowed_only_inside_the_scratch_folder(
    mode: str | None, flags: int, root: str, tmp_path: Path
) -> None:
    outside = str(tmp_path / "outside.txt")
    assert is_blocked("open", (outside, mode, flags), root)
    assert not is_blocked("open", (os.path.join(root, "f.txt"), mode, flags), root)


def test_a_symbolic_link_out_of_the_scratch_folder_counts_as_outside(
    root: str, tmp_path: Path
) -> None:
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", os.path.join(root, "link"))

    assert not is_inside(os.path.join(root, "link", "f"), None, root)


def test_a_relative_path_is_resolved_from_the_working_directory(
    root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(root)
    assert is_inside("new.txt", -1, root)
    assert not is_inside("../new.txt", None, root)


def test_a_dir_fd_path_is_resolved_from_its_folder(root: str, tmp_path: Path) -> None:
    inside = os.open(root, os.O_RDONLY)
    outside = os.open(tmp_path, os.O_RDONLY)
    try:
        assert not is_blocked("os.remove", ("f", inside), root)
        assert is_blocked("os.remove", ("f", outside), root)
    finally:
        os.close(inside)
        os.close(outside)


def test_a_rename_needs_both_paths_inside(root: str, tmp_path: Path) -> None:
    inside = os.path.join(root, "a")
    outside = str(tmp_path / "b")
    assert is_blocked("os.rename", (outside, inside, -1, -1), root)
    assert is_blocked("os.rename", (inside, outside, -1, -1), root)
    assert not is_blocked("os.rename", (inside, inside + "2", -1, -1), root)


def test_an_in_memory_database_is_allowed(root: str, tmp_path: Path) -> None:
    assert not is_blocked("sqlite3.connect", (":memory:",), root)
    assert is_blocked("sqlite3.connect", (str(tmp_path / "app.db"),), root)


def run_guarded(code: str, scratch: Path, cwd: Path) -> str:
    """Install the guard in a new interpreter, run ``code``, return stdout."""
    script = textwrap.dedent(
        f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("guard", {str(GUARD_FILE)!r})
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        blocked = guard.install({str(scratch)!r})
        """
    ) + textwrap.dedent(code)
    done = subprocess.run(
        # -B as in the harness: writing __pycache__ outside the scratch folder
        # would be blocked (seen on a fresh CI runner without cached bytecode).
        [sys.executable, "-B", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TMPDIR": str(scratch)},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_user_code_cannot_hide_a_blocked_call(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    output = run_guarded(
        f"""
        import os
        try:
            os.system("touch {marker}")
        except BaseException as error:
            print("caught", type(error).__name__)
        print("first", blocked())
        """,
        tmp_path,
        tmp_path,
    )

    assert not marker.exists()
    assert output.split("\n")[:2] == ["caught Blocked", "first os.system"]


def test_temporary_files_and_folders_work_in_the_scratch_folder(
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output = run_guarded(
        """
        import pathlib, shutil, sqlite3, tempfile
        with tempfile.TemporaryDirectory() as folder:
            pathlib.Path(folder, "sub").mkdir()
            pathlib.Path(folder, "sub", "f.txt").write_text("x")
        pathlib.Path("out.txt").write_text("relative paths land in the scratch folder")
        shutil.rmtree(tempfile.mkdtemp())
        sqlite3.connect(":memory:").execute("select 1")
        print("blocked:", blocked())
        """,
        scratch,
        scratch,
    )

    assert output.strip() == "blocked: None"
    assert (scratch / "out.txt").exists()


def test_the_hook_cannot_be_removed(tmp_path: Path) -> None:
    # sys has no API to remove an audit hook; adding another changes nothing.
    marker = tmp_path / "ran"
    output = run_guarded(
        f"""
        import sys
        sys.addaudithook(lambda event, args: None)
        try:
            open({str(marker)!r}, "w")
        except BaseException:
            pass
        print(blocked())
        """,
        tmp_path / "missing-scratch",
        tmp_path,
    )

    assert not marker.exists()
    assert output.strip() == "open"
