"""Tests for the testability rules and their user-facing skip reasons."""

import textwrap

import pytest

from didibreak.testability import OBVIOUS_IO, skip_reason


def _reason(
    source: str, function_type: str = "function", is_async: bool = False
) -> str | None:
    return skip_reason(textwrap.dedent(source), function_type, is_async)


def test_pure_function_is_not_skipped() -> None:
    source = """
        def normalize(text, *, upper=False):
            cleaned = " ".join(text.split())
            return cleaned.upper() if upper else cleaned
    """

    assert _reason(source) is None


@pytest.mark.parametrize("function_type", ["staticmethod", "classmethod"])
def test_static_and_class_methods_are_testable(function_type: str) -> None:
    source = f"""
        @{function_type}
        def parse(value):
            return int(value)
    """

    assert _reason(source, function_type) is None


def test_async_function_is_skipped() -> None:
    assert _reason("async def f():\n    return 1\n", is_async=True) == "async function"


def test_instance_method_is_skipped() -> None:
    assert _reason("def size(self):\n    return 1\n", "method") == "instance method"


@pytest.mark.parametrize(
    "body", ["yield 1", "yield from range(3)", "x = yield", "return [(yield)]"]
)
def test_generator_is_skipped(body: str) -> None:
    assert _reason(f"def numbers():\n    {body}\n") == "generator"


def test_yield_in_a_nested_function_does_not_make_a_generator() -> None:
    source = """
        def make():
            def inner():
                yield 1
            return list(inner())
    """

    assert _reason(source) is None


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("open(path).read()", "obvious I/O: open"),
        ("subprocess.run(['ls'])", "obvious I/O: subprocess.run"),
        ("requests.get(url)", "obvious I/O: requests.get"),
        ("httpx.post(url)", "obvious I/O: httpx.post"),
        ("socket.socket()", "obvious I/O: socket.socket"),
        ("os.remove(path)", "obvious I/O: os.remove"),
        ("session.commit()", "obvious I/O: session.commit"),
        ("self.db.session.add(user)", "obvious I/O: self.db.session.add"),
        ("cursor.execute('select 1')", "obvious I/O: cursor.execute"),
        ("import subprocess", "obvious I/O: import subprocess"),
        ("from requests import get", "obvious I/O: import requests"),
        ("client = httpx", "obvious I/O: httpx"),
    ],
)
def test_obvious_io_is_skipped_with_the_name_as_written(
    statement: str, reason: str
) -> None:
    assert _reason(f"def work(path, url, user):\n    {statement}\n") == reason


def test_io_in_a_nested_helper_counts() -> None:
    source = """
        def outer(path):
            def read():
                return open(path).read()
            return read()
    """

    assert _reason(source) == "obvious I/O: open"


@pytest.mark.parametrize(
    "statement",
    [
        "items.add(1)",  # a set, not a database session
        "text.execute",  # attribute access is not a call
        "opened = path",  # name contains 'open' but is not a call to open
        "os.path.join(a, b)",
    ],
)
def test_similar_looking_code_is_not_io(statement: str) -> None:
    assert _reason(f"def f(items, text, path, a, b):\n    {statement}\n") is None


def test_first_rule_wins_async_before_instance_method() -> None:
    source = "async def fetch(self):\n    return open('x')\n"

    assert _reason(source, "method", is_async=True) == "async function"


def test_io_list_is_one_constant_with_the_task_categories() -> None:
    assert set(OBVIOUS_IO["calls"]) == {"open", "os.remove"}
    assert set(OBVIOUS_IO["modules"]) == {"subprocess", "requests", "httpx", "socket"}
    assert "session" in OBVIOUS_IO["database_receivers"]
    assert "commit" in OBVIOUS_IO["database_methods"]
