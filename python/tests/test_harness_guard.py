"""The runtime I/O guard in the harness: every bypass of the pre-launch review.

Each function below was run with its case input before the guard
(evaluation/review-prelaunch.md, findings 1, 2 and 7). Now the function is
skipped with ``blocked: <event>`` and the marker file is never created.
"""

import http.server
import sys
import textwrap
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from didibreak.harness import Case, HarnessSettings, Target, check_import, run_cases

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)


def write_tree(tree: Path, files: dict[str, str]) -> Target:
    for name, text in files.items():
        (tree / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return Target(tree=tree, import_root=tree, module="mod", qualname="f")


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


def touch(marker: Path) -> str:
    return f"__import__('os').system('touch {marker}')"


VARIANTS = {
    "eval": "def f(text):\n    return eval(text)\n",
    "exec": "def f(text):\n    exec(text)\n",
    "alias": """
        import os

        def f(name):
            run = os.system
            return run("touch " + name)
        """,
    "class": """
        import os

        class Runner:
            def __init__(self, command):
                self.command = command

            def go(self):
                return os.system(self.command)

        def f(name):
            return Runner("touch " + name).go()
        """,
    "bare decorator": """
        import os

        def audit(function):
            def wrapper(name):
                os.system("touch " + name)
                return function(name)
            return wrapper

        @audit
        def f(name):
            return name
        """,
}


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_a_command_is_blocked_whatever_the_route(
    variant: str, tmp_path: Path, marker: Path
) -> None:
    target = write_tree(tmp_path, {"mod.py": VARIANTS[variant]})
    argument = touch(marker) if variant in ("eval", "exec") else str(marker)

    result = run_cases(target, [Case((repr(argument),))], SETTINGS)

    assert result.skip_reason == "blocked: os.system"
    assert not marker.exists()


def test_pickle_loads_cannot_run_a_command(tmp_path: Path, marker: Path) -> None:
    payload = b"cos\nsystem\n(S'touch " + str(marker).encode() + b"'\ntR."
    target = write_tree(
        tmp_path,
        {"mod.py": "import pickle\n\ndef f(blob):\n    return pickle.loads(blob)\n"},
    )

    result = run_cases(target, [Case((repr(payload),))], SETTINGS)

    assert result.skip_reason == "blocked: os.system"
    assert not marker.exists()


def test_a_write_in_a_helper_module_is_blocked(tmp_path: Path, marker: Path) -> None:
    target = write_tree(
        tmp_path,
        {
            "helpers.py": "def save(path, text):\n    open(path, 'w').write(text)\n",
            "mod.py": "import helpers\n\ndef f(path):\n    helpers.save(path, 'x')\n",
        },
    )

    result = run_cases(target, [Case((repr(str(marker)),))], SETTINGS)

    assert result.skip_reason == "blocked: open"
    assert not marker.exists()


def test_path_replace_cannot_overwrite_a_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "report.txt").write_text("report")
    (data / "other.txt").write_text("other")
    target = write_tree(
        tmp_path,
        {
            "mod.py": f"""
            from pathlib import Path

            def f(name):
                Path({str(data / "report.txt")!r}).replace({str(data)!r} + '/' + name)
            """
        },
    )

    result = run_cases(target, [Case(("'other.txt'",))], SETTINGS)

    assert result.skip_reason == "blocked: os.rename"
    assert (data / "other.txt").read_text() == "other"
    assert (data / "report.txt").exists()


@pytest.fixture
def server(marker: Path) -> Iterator[str]:
    """A local HTTP server that creates the marker when anything reaches it."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            marker.touch()
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()
    httpd.server_close()


def test_a_network_module_cannot_connect(
    tmp_path: Path, marker: Path, server: str
) -> None:
    # xmlrpc is not in the static I/O table: only the runtime guard stops it.
    target = write_tree(
        tmp_path,
        {
            "mod.py": """
            import xmlrpc.client

            def f(url):
                return xmlrpc.client.ServerProxy(url).ping()
            """
        },
    )

    result = run_cases(target, [Case((repr(server),))], SETTINGS)

    assert result.skip_reason is not None
    assert result.skip_reason.startswith("blocked: socket.")
    assert not marker.exists()


def test_a_write_at_import_time_is_blocked_before_any_case(
    tmp_path: Path, marker: Path
) -> None:
    target = write_tree(
        tmp_path, {"mod.py": f"open({str(marker)!r}, 'w')\n\ndef f():\n    return 1\n"}
    )

    assert check_import(target, SETTINGS) == "blocked: open"
    assert not marker.exists()


def test_temporary_files_still_work(tmp_path: Path) -> None:
    target = write_tree(
        tmp_path,
        {
            "mod.py": """
            import tempfile
            from pathlib import Path

            def f(text):
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder, "copy.txt")
                    path.write_text(text)
                    return path.read_text().upper()
            """
        },
    )

    result = run_cases(target, [Case(("'abc'",))], SETTINGS)

    assert result.skip_reason is None
    assert result.outcomes[0].repr == "'ABC'"
