"""Smoke-test the built wheel and sdist, each in a fresh virtual environment.

For each package in DIST_DIR: create a new venv, ``pip install`` the file,
then run ``didibreak --version``, ``didibreak init-agents`` and one
``didibreak check`` on a tiny git repository against a fake
OpenAI-compatible server on 127.0.0.1. The server answers with fixed cases,
so no API key is needed and nothing is spent. Standard library only. From
python/ (task 23):

    uv build
    python scripts/package_smoke.py dist
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_SOURCE = (
    "def clamp_percent(value: int) -> int:\n"
    '    """Clamp a percentage to 0..100."""\n'
    "    return max(0, min(100, value))\n"
)
# The change loses the lower bound: -5 now stays -5 instead of becoming 0.
CHANGED_SOURCE = BASE_SOURCE.replace("max(0, min(100, value))", "min(100, value)")
CASES = [["-5"], ["50"], ["150"]]
FUNCTION = "calc.py::clamp_percent"


class _FakeProvider(BaseHTTPRequestHandler):
    """Answers every chat completion with the fixed cases."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        cases = [{"args": args, "kwargs": [], "rationale": "smoke"} for args in CASES]
        body = json.dumps(
            {
                "model": "fake-model",
                "choices": [
                    {
                        "message": {"content": json.dumps({"cases": cases})},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the smoke output short."""


@contextmanager
def fake_provider() -> Iterator[str]:
    """Run the fake server on a free local port; yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True)


def make_repository(path: Path) -> Path:
    """A git repository whose working tree breaks ``clamp_percent``."""
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Smoke")
    _git(path, "config", "user.email", "smoke@example.com")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "pyproject.toml").write_text('[tool.didibreak]\napi_key_env = ""\n')
    (path / "calc.py").write_text(BASE_SOURCE)
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "Add clamp_percent")
    (path / "calc.py").write_text(CHANGED_SOURCE)
    return path


def _run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, capture_output=True, text=True, timeout=300
    )


def check_report(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Problems in the JSON report of the smoke ``check``; empty when correct."""
    if result.returncode != 1:
        return [f"check exited {result.returncode}, expected 1: {result.stderr}"]
    report = json.loads(result.stdout)
    findings = [
        (f["function"], f["args"], f["before"]["repr"], f["after"]["repr"])
        for f in report["findings"]
    ]
    problems = []
    if findings != [(FUNCTION, ["-5"], "0", "-5")]:
        problems.append(f"unexpected findings: {findings}")
    if report["usage"]["calls"] != 1 or report["usage"]["cost_usd"] != 0:
        problems.append(f"unexpected usage: {report['usage']}")
    return problems


def run_checks(didibreak: Sequence[str], version: str, folder: Path) -> list[str]:
    """Run the three commands with ``didibreak``; list the problems found."""
    problems = []
    shown = _run([*didibreak, "--version"], folder).stdout.strip()
    if shown != f"didibreak {version}":
        problems.append(f"--version printed {shown!r}, expected {version}")
    if "## Behavior check" not in _run([*didibreak, "init-agents"], folder).stdout:
        problems.append("init-agents did not print the snippet")
    repository = make_repository(folder / "repo")
    with fake_provider() as base_url:
        options = ["--format", "json", "--provider", "openai", "--base-url", base_url]
        result = _run([*didibreak, "check", *options, "--model", "fake"], repository)
    problems += check_report(result)
    return problems


def smoke_package(package: Path, version: str, python: str) -> list[str]:
    """Install ``package`` into a new venv and run the checks with it."""
    with tempfile.TemporaryDirectory(prefix="didibreak-smoke-") as temporary:
        folder = Path(temporary)
        _run([python, "-m", "venv", str(folder / "venv")], folder).check_returncode()
        pip = [str(folder / "venv" / "bin" / "python"), "-m", "pip", "install"]
        options = ["-q", "--disable-pip-version-check"]
        installed = _run([*pip, *options, str(package.resolve())], folder)
        if installed.returncode != 0:
            return [f"pip install failed: {installed.stderr.strip()}"]
        command = [str(folder / "venv" / "bin" / "didibreak")]
        return run_checks(command, version, folder)


def packages(dist_dir: Path) -> tuple[Path, Path, str]:
    """The single wheel and sdist in ``dist_dir`` and their version."""
    wheels = sorted(dist_dir.glob("didibreak-*.whl"))
    sdists = sorted(dist_dir.glob("didibreak-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"expected one wheel and one sdist in {dist_dir}")
    version = wheels[0].name.split("-")[1]
    return wheels[0], sdists[0], version


def main(argv: Sequence[str] | None = None) -> int:
    """Smoke-test both packages; 0 when every check passes."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist_dir", type=Path, help="folder written by uv build")
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter for the new venvs"
    )
    options = parser.parse_args(argv)
    wheel, sdist, version = packages(options.dist_dir)
    failed = False
    for package in (wheel, sdist):
        problems = smoke_package(package, version, options.python)
        print(f"{package.name}: {'FAIL' if problems else 'ok'}")
        for problem in problems:
            print(f"  {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
