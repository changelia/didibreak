"""Tests for the testability rules and their user-facing skip reasons."""

import textwrap

import pytest

from didibreak.testability import OBVIOUS_IO, module_context, skip_reason


def _reason(
    source: str,
    function_type: str = "function",
    is_async: bool = False,
    qualname: str | None = None,
) -> str | None:
    """Skip reason of ``qualname`` (default: the first function in the module)."""
    context = module_context(textwrap.dedent(source))
    name = qualname or next(iter(context.functions))
    return skip_reason(context, name, function_type, is_async)


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
    assert set(OBVIOUS_IO) == {
        "calls",
        "modules",
        "path_methods",
        "database_receivers",
        "database_methods",
    }
    assert {"os.system", "os.popen", "os.exec*", "os.spawn*"} <= set(
        OBVIOUS_IO["calls"]
    )
    assert {"subprocess", "pty", "socket", "http.client"} <= set(OBVIOUS_IO["modules"])
    assert "session" in OBVIOUS_IO["database_receivers"]
    assert "commit" in OBVIOUS_IO["database_methods"]


@pytest.mark.parametrize(
    ("imports", "statement", "reason"),
    [
        ("from subprocess import run", "run(['ls'])", "obvious I/O: subprocess.run"),
        (
            "import subprocess as sp",
            "sp.Popen(['ls'])",
            "obvious I/O: subprocess.Popen",
        ),
        ("from os import remove", "remove(path)", "obvious I/O: os.remove"),
        ("from os import remove as rm", "rm(path)", "obvious I/O: os.remove"),
        ("import os as system", "system.remove(path)", "obvious I/O: os.remove"),
        ("from requests import Session", "Session()", "obvious I/O: requests.Session"),
        (
            "try:\n    from httpx import get\nexcept ImportError:\n    get = None",
            "get(path)",
            "obvious I/O: httpx.get",
        ),
    ],
)
def test_module_level_imports_and_aliases_are_resolved(
    imports: str, statement: str, reason: str
) -> None:
    source = f"{imports}\n\n\ndef work(path):\n    return {statement}\n"

    assert _reason(source, qualname="work") == reason


def test_function_level_aliases_are_resolved() -> None:
    source = """
        def work():
            from subprocess import check_output as out
            return out(["ls"])
    """

    assert _reason(source) == "obvious I/O: import subprocess"


def test_a_local_function_with_an_io_like_name_is_not_io() -> None:
    source = """
        def remove(items, item):
            return [i for i in items if i != item]


        def work(items):
            return remove(items, 1)
    """

    assert _reason(source, qualname="work") is None


@pytest.mark.parametrize(
    ("imports", "statement", "reason"),
    [
        ("import os", "os.unlink(path)", "obvious I/O: os.unlink"),
        ("import os", "os.rmdir(path)", "obvious I/O: os.rmdir"),
        ("import shutil as sh", "sh.rmtree(path)", "obvious I/O: shutil.rmtree"),
        ("import shutil", "shutil.move(path, path)", "obvious I/O: shutil.move"),
        ("import shutil", "shutil.copy2(path, path)", "obvious I/O: shutil.copy2"),
        (
            "from shutil import copytree",
            "copytree(path, path)",
            "obvious I/O: shutil.copytree",
        ),
        (
            "import urllib.request",
            "urllib.request.urlopen(path)",
            "obvious I/O: urllib.request.urlopen",
        ),
        (
            "from urllib.request import urlopen",
            "urlopen(path)",
            "obvious I/O: urllib.request.urlopen",
        ),
        ("import sqlite3", "sqlite3.connect(path)", "obvious I/O: sqlite3.connect"),
        (
            "from pathlib import Path",
            "Path(path).write_text('x')",
            "obvious I/O: pathlib.Path.write_text",
        ),
        (
            "from pathlib import Path",
            "Path(path).read_bytes()",
            "obvious I/O: pathlib.Path.read_bytes",
        ),
        ("", "path.unlink()", "obvious I/O: path.unlink"),
        ("", "path.mkdir(parents=True)", "obvious I/O: path.mkdir"),
        ("", "path.rmdir()", "obvious I/O: path.rmdir"),
        ("", "path.touch()", "obvious I/O: path.touch"),
        ("", "path.open()", "obvious I/O: path.open"),
    ],
)
def test_extended_io_list_is_detected(
    imports: str, statement: str, reason: str
) -> None:
    source = f"{imports}\n\n\ndef work(path):\n    return {statement}\n"

    assert _reason(source, qualname="work") == reason


@pytest.mark.parametrize(
    "statement",
    ["shutil.which('git')", "os.path.exists(path)", "urllib.parse.quote(path)"],
)
def test_harmless_functions_of_the_same_modules_are_not_io(statement: str) -> None:
    imports = "import os, shutil, urllib.parse"
    source = f"{imports}\n\n\ndef work(path):\n    return {statement}\n"

    assert _reason(source, qualname="work") is None


def test_io_in_a_same_module_helper_is_followed() -> None:
    source = """
        import subprocess


        def _git(*args):
            return subprocess.run(["git", *args])


        def repository_root():
            return _git("rev-parse")
    """

    assert _reason(source, qualname="repository_root") == (
        "obvious I/O: subprocess.run (via _git)"
    )


def test_helpers_are_followed_transitively_and_through_class_methods() -> None:
    source = """
        import shutil


        def _remove(path):
            shutil.rmtree(path)


        class Cleaner:
            @staticmethod
            def wipe(path):
                return _remove(path)

            @classmethod
            def reset(cls, path):
                return cls.wipe(path)


        def clean(path):
            return Cleaner.reset(path)
    """

    assert _reason(source, qualname="clean") == (
        "obvious I/O: shutil.rmtree (via _remove)"
    )


def test_recursive_and_mutually_recursive_helpers_terminate() -> None:
    source = """
        def even(n):
            return True if n == 0 else odd(n - 1)


        def odd(n):
            return False if n == 0 else even(n - 1)
    """

    assert _reason(source, qualname="even") is None


def test_calls_into_other_modules_are_not_followed() -> None:
    source = """
        from helpers import save


        def store(value):
            return save(value)
    """

    assert _reason(source, qualname="store") is None


# Audit 35a, finding 1: these were run with LLM inputs before 0.1.4.
@pytest.mark.parametrize(
    ("imports", "statement", "reason"),
    [
        # Running commands and processes.
        ("import os", "os.system('echo ' + path)", "obvious I/O: os.system"),
        ("import os", "os.popen(path).read()", "obvious I/O: os.popen"),
        ("import os", "os.execvp(path, [path])", "obvious I/O: os.execvp"),
        ("import os", "os.spawnlp(0, path, path)", "obvious I/O: os.spawnlp"),
        ("import os", "os.posix_spawn(path, [], {})", "obvious I/O: os.posix_spawn"),
        ("import os", "os.kill(1, 9)", "obvious I/O: os.kill"),
        ("from os import system", "system(path)", "obvious I/O: os.system"),
        ("import pty", "pty.spawn(path)", "obvious I/O: pty.spawn"),
        (
            "import asyncio",
            "asyncio.create_subprocess_shell(path)",
            "obvious I/O: asyncio.create_subprocess_shell",
        ),
        # Changing files and folders.
        ("import os", "os.rename(path, path)", "obvious I/O: os.rename"),
        ("import os", "os.replace(path, path)", "obvious I/O: os.replace"),
        ("import os", "os.makedirs(path)", "obvious I/O: os.makedirs"),
        ("import os", "os.mkdir(path)", "obvious I/O: os.mkdir"),
        ("import os", "os.chmod(path, 0)", "obvious I/O: os.chmod"),
        ("import os", "os.truncate(path, 0)", "obvious I/O: os.truncate"),
        ("import shutil", "shutil.chown(path)", "obvious I/O: shutil.chown"),
        ("import io", "io.open(path)", "obvious I/O: io.open"),
        (
            "from pathlib import Path",
            "Path(path).rename('x')",
            "obvious I/O: pathlib.Path.rename",
        ),
        ("", "path.chmod(0)", "obvious I/O: path.chmod"),
        ("", "path.symlink_to('x')", "obvious I/O: path.symlink_to"),
        # Network and database clients.
        (
            "import http.client",
            "http.client.HTTPSConnection(path)",
            "obvious I/O: http.client.HTTPSConnection",
        ),
        (
            "from http import client",
            "client.HTTPConnection(path)",
            "obvious I/O: http.client.HTTPConnection",
        ),
        ("import smtplib", "smtplib.SMTP(path)", "obvious I/O: smtplib.SMTP"),
        ("import ftplib", "ftplib.FTP(path)", "obvious I/O: ftplib.FTP"),
        (
            "import urllib3",
            "urllib3.request('GET', path)",
            "obvious I/O: urllib3.request",
        ),
        ("import psycopg", "psycopg.connect(path)", "obvious I/O: psycopg.connect"),
        ("import pymysql", "pymysql.connect(path)", "obvious I/O: pymysql.connect"),
        (
            "import mysql.connector",
            "mysql.connector.connect(path)",
            "obvious I/O: mysql.connector.connect",
        ),
        ("import redis", "redis.Redis(path)", "obvious I/O: redis.Redis"),
        ("import boto3", "boto3.client('s3')", "obvious I/O: boto3.client"),
        (
            "from sqlalchemy import create_engine",
            "create_engine(path)",
            "obvious I/O: sqlalchemy.create_engine",
        ),
    ],
)
def test_commands_file_changes_and_clients_are_io(
    imports: str, statement: str, reason: str
) -> None:
    source = f"{imports}\n\n\ndef work(path):\n    return {statement}\n"

    assert _reason(source, qualname="work") == reason


@pytest.mark.parametrize(
    ("imports", "statement"),
    [
        ("from http import HTTPStatus", "HTTPStatus.OK"),
        ("import http", "http.HTTPStatus(200)"),
        ("", "path.replace('a', 'b')"),  # str.replace, not Path.replace
        ("import os", "os.path.join(path, 'x')"),
        ("import os", "os.getcwd()"),
    ],
)
def test_names_next_to_io_modules_are_not_io(imports: str, statement: str) -> None:
    source = f"{imports}\n\n\ndef work(path):\n    return {statement}\n"

    assert _reason(source, qualname="work") is None
