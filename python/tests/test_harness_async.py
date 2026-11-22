"""Coroutine functions in the harness: one asyncio.run per case (task 29).

The event loop itself must run under the runtime I/O guard, while commands,
network access and writes outside the scratch folder from inside a
coroutine still end as ``blocked: <event>``; marker files prove that the
blocked operation never happened.
"""

import socketserver
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from didibreak.harness import Case, HarnessSettings, Target, run_cases

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)
SHORT = HarnessSettings(python=sys.executable, timeout=0.5)


def async_target(tree: Path, source: str, is_async: bool = True) -> Target:
    (tree / "mod.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return Target(tree, tree, "mod", "f", is_async=is_async)


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


def test_the_awaited_result_is_the_outcome(tmp_path: Path) -> None:
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(x):
            await asyncio.sleep(0)
            return x * 2
        """,
    )

    result = run_cases(target, [Case(("2",)), Case(("'ab'",))], SETTINGS)

    assert result.skip_reason is None  # the event loop itself is not blocked
    assert [(o.kind, o.repr, o.stable) for o in result.outcomes] == [
        ("return", "4", True),
        ("return", "'abab'", True),
    ]


def test_an_exception_inside_the_coroutine_is_the_outcome(tmp_path: Path) -> None:
    target = async_target(
        tmp_path,
        """
        async def f(port):
            if port == 0:
                raise ValueError("port must be 1-65535")
            return port
        """,
    )

    result = run_cases(target, [Case(("0",)), Case(("80",))], SETTINGS)

    first, second = result.outcomes
    assert (first.kind, first.type_name) == ("exception", "builtins.ValueError")
    assert first.message == "port must be 1-65535"
    assert (second.kind, second.repr) == ("return", "80")


HANGING = {
    "sleeping": "await asyncio.sleep(100)",
    "busy": "while True:\n        pass",
    "ignoring cancellation": (
        "while True:\n"
        "        try:\n"
        "            await asyncio.sleep(100)\n"
        "        except asyncio.CancelledError:\n"
        "            pass"
    ),
}


def hanging_module(body: str) -> str:
    return (
        "import asyncio\n\n\n"
        "async def f(x):\n"
        "    if x:\n"
        "        return 'done'\n"
        f"    {body}\n"
    )


@pytest.mark.parametrize("variant", list(HANGING))
def test_a_coroutine_that_never_finishes_times_out(
    tmp_path: Path, variant: str
) -> None:
    target = async_target(tmp_path, hanging_module(HANGING[variant]))
    started = time.monotonic()

    result = run_cases(target, [Case(("0",)), Case(("1",))], SHORT)

    # The case after the timeout still runs: the cleanup is bounded.
    assert [(o.kind, o.repr) for o in result.outcomes] == [
        ("timeout", "<timed out after 0.5 s>"),
        ("return", "'done'"),
    ]
    assert time.monotonic() - started < 10


def test_random_is_seeded_for_every_case(tmp_path: Path) -> None:
    target = async_target(
        tmp_path,
        """
        import random

        async def f(x):
            return random.random()
        """,
    )

    result = run_cases(target, [Case(("1",)), Case(("2",))], SETTINGS)

    first, second = result.outcomes
    assert first.stable and second.stable
    assert first.value == second.value


def test_tasks_left_running_do_not_leak_into_the_next_case(tmp_path: Path) -> None:
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(x):
            asyncio.get_running_loop().create_task(asyncio.sleep(100))
            return len(asyncio.all_tasks())
        """,
    )

    result = run_cases(target, [Case(("1",)), Case(("2",))], SETTINGS)

    # One new event loop per case: its own task and the one it started.
    assert [o.repr for o in result.outcomes] == ["2", "2"]


def test_without_the_flag_the_coroutine_is_not_awaited(tmp_path: Path) -> None:
    target = async_target(tmp_path, "async def f(x):\n    return x\n", is_async=False)

    result = run_cases(target, [Case(("1",))], SETTINGS)

    assert result.outcomes[0].type_name == "builtins.coroutine"


def test_a_decorator_that_returns_a_plain_value_is_recorded_as_is(
    tmp_path: Path,
) -> None:
    target = async_target(
        tmp_path,
        """
        def cached(function):
            def wrapper(x):
                return "cached"
            return wrapper

        @cached
        async def f(x):
            return x
        """,
    )

    result = run_cases(target, [Case(("1",))], SETTINGS)

    assert result.outcomes[0].repr == "'cached'"


def test_a_subprocess_from_a_coroutine_is_blocked(tmp_path: Path, marker: Path) -> None:
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(name):
            process = await asyncio.create_subprocess_shell("touch " + name)
            return await process.wait()
        """,
    )

    result = run_cases(target, [Case((repr(str(marker)),))], SETTINGS)

    assert result.skip_reason == "blocked: subprocess.Popen"
    assert not marker.exists()


def test_a_write_outside_the_scratch_folder_from_a_coroutine_is_blocked(
    tmp_path: Path, marker: Path
) -> None:
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(path):
            await asyncio.sleep(0)
            with open(path, "w") as file:
                file.write("x")
        """,
    )

    result = run_cases(target, [Case((repr(str(marker)),))], SETTINGS)

    assert result.skip_reason == "blocked: open"
    assert not marker.exists()


@pytest.fixture
def listener(marker: Path) -> Iterator[int]:
    """A local TCP server that creates the marker when a connection arrives."""

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            marker.touch()

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_a_connection_from_a_coroutine_is_blocked(
    tmp_path: Path, marker: Path, listener: int
) -> None:
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            return 1
        """,
    )

    result = run_cases(target, [Case((str(listener),))], SETTINGS)

    assert result.skip_reason == "blocked: socket.connect"
    time.sleep(0.2)  # give a connection that got through time to arrive
    assert not marker.exists()


def test_a_name_lookup_from_a_coroutine_is_blocked(tmp_path: Path) -> None:
    # The event loop runs getaddrinfo in a worker thread; the audit hook
    # sees every thread.
    target = async_target(
        tmp_path,
        """
        import asyncio

        async def f(host):
            return await asyncio.get_running_loop().getaddrinfo(host, 80)
        """,
    )

    result = run_cases(target, [Case(("'localhost'",))], SETTINGS)

    assert result.skip_reason == "blocked: socket.getaddrinfo"
