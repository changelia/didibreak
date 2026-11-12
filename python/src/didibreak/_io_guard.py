"""Runtime I/O guard of the harness child: an audit hook (PEP 578).

_harness_child.py loads this file by its path and installs the guard before
it imports the user's module. Like the child, it uses only the standard
library and nothing from didibreak.

The hook sees the audit events that the interpreter and the standard
library raise, and stops the events in BLOCKED_EVENTS: running commands and
starting processes, network access, loading native code, and changing
files outside the child's scratch folder. Reading files stays allowed.
Python has no way to remove an audit hook, so user code cannot switch it
off. User code can catch the exception, so the first blocked event is also
recorded, and the harness skips the function with ``blocked: <event>``.

This is defence in depth, not a sandbox: a C extension that does its own
I/O raises no event, and a few calls raise none (``os.mkfifo``,
``os.mknod``, ``os.setxattr``, ``_posixsubprocess.fork_exec``). A container
is the real isolation (docs/safety.md).
"""

import contextlib
import os
import sys
from collections.abc import Callable
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl exists on Linux and macOS
    fcntl = None  # type: ignore[assignment]

# A path argument of an event: (its index, index of its dir_fd or None).
PathArgument = tuple[int, int | None]

# Audit event -> None when it is always blocked, or the path arguments that
# must all lie inside the scratch folder. "open" counts only when it writes.
BLOCKED_EVENTS: dict[str, tuple[PathArgument, ...] | None] = {
    # Running commands and starting or signalling processes.
    "os.system": None,
    "os.exec": None,
    "os.spawn": None,
    "os.posix_spawn": None,
    "os.fork": None,
    "os.forkpty": None,
    "subprocess.Popen": None,
    "os.kill": None,
    "os.killpg": None,
    # Network.
    "socket.connect": None,
    "socket.bind": None,
    "socket.sendto": None,
    "socket.sendmsg": None,
    "socket.getaddrinfo": None,
    "socket.gethostbyname": None,
    "socket.gethostbyaddr": None,
    "socket.getnameinfo": None,
    "socket.sethostname": None,
    # Loading native code (ctypes itself is imported before the hook).
    "ctypes.dlopen": None,
    "ctypes.dlsym": None,
    "ctypes.dlsym/handle": None,
    "sqlite3.load_extension": None,
    # Changing files and folders: allowed inside the scratch folder.
    "open": ((0, None),),
    "os.remove": ((0, 1),),
    "os.rmdir": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),  # also os.replace
    "os.mkdir": ((0, 2),),
    "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),),
    "os.chflags": ((0, None),),
    "os.link": ((0, 2), (1, 3)),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
    "sqlite3.connect": ((0, None),),
}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_IN_MEMORY_DATABASES = (":memory:", b":memory:", "")


class Blocked(BaseException):
    """Raised into user code for a blocked event.

    A BaseException, so that ``except Exception`` in user code does not
    hide it.
    """


def _fd_path(fd: int) -> str | None:
    """The path of an open file descriptor, or None if it cannot be found."""
    try:
        if sys.platform == "darwin" and fcntl is not None:
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return os.fsdecode(raw.split(b"\0", 1)[0])
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def _absolute(path: Any, dir_fd: Any) -> str | None:
    if isinstance(path, int):  # a file descriptor
        return _fd_path(path)
    text = os.fsdecode(path)
    if os.path.isabs(text):
        return text
    # A missing or negative dir_fd means the working directory.
    if not isinstance(dir_fd, int) or dir_fd < 0:
        return os.path.join(os.getcwd(), text)
    folder = _fd_path(dir_fd)
    return None if folder is None else os.path.join(folder, text)


def is_inside(path: Any, dir_fd: Any, root: str) -> bool:
    """Whether a path argument resolves inside ``root`` (a real path).

    Symbolic links are followed, so a link inside ``root`` that points out
    of it counts as outside. A path that cannot be resolved is outside.
    """
    try:
        absolute = _absolute(path, dir_fd)
    except (TypeError, ValueError):
        return False
    if absolute is None:
        return False
    real = os.path.realpath(absolute)
    return real == root or real.startswith(root + os.sep)


def _writes(args: tuple[Any, ...]) -> bool:
    mode, flags = args[1], args[2]
    if isinstance(flags, int) and flags & _WRITE_FLAGS:
        return True
    return isinstance(mode, str) and any(letter in mode for letter in "wax+")


def is_blocked(event: str, args: tuple[Any, ...], root: str) -> bool:
    """Whether the guard stops an audit event.

    Args:
        event: Audit event name, e.g. ``os.system``.
        args: The event's arguments.
        root: Real path of the scratch folder, where changing files is
            allowed.

    Returns:
        True when the event is in BLOCKED_EVENTS and not allowed.
    """
    if event not in BLOCKED_EVENTS:
        return False
    paths = BLOCKED_EVENTS[event]
    if paths is None:
        return True
    if event == "open" and not _writes(args):
        return False
    if event == "sqlite3.connect" and args[0] in _IN_MEMORY_DATABASES:
        return False
    return not all(
        is_inside(args[index], None if fd is None else args[fd], root)
        for index, fd in paths
    )


def install(scratch: str) -> Callable[[], str | None]:
    """Install the guard for the rest of this process.

    Args:
        scratch: Folder where the code under test may change files (the
            child's working directory and temporary folder).

    Returns:
        A function that names the first blocked event, or returns None.
    """
    # Importing ctypes loads the interpreter's own symbols (ctypes.dlopen);
    # after this, loading native code is blocked.
    with contextlib.suppress(ImportError):
        import ctypes  # noqa: F401
    root = os.path.realpath(scratch)
    first: list[str] = []

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in BLOCKED_EVENTS and is_blocked(event, args, root):
            if not first:
                first.append(event)
            raise Blocked(event)

    sys.addaudithook(hook)
    return lambda: first[0] if first else None
