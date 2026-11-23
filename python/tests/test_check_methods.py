"""check on instance methods: built, called, state compared (task 30)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepository

from didibreak.cli import EXIT_FINDINGS, EXIT_OK, main

BANK = """\
class Account:
    def __init__(self, balance: int):
        if balance < 0:
            raise ValueError("negative balance")
        self.balance = balance

    def deposit(self, amount: int) -> None:
        self.balance += amount
"""


def change(
    repository: GitRepository,
    before: str,
    after: str,
    cases: list[Any],
    method: str = "deposit",
) -> str:
    repository.write("app/bank.py", before)
    repository.commit("base")
    repository.write("app/bank.py", after)
    items = [{"function": f"app/bank.py::Account.{method}", **case} for case in cases]
    return str(repository.write("cases.json", json.dumps({"cases": items})))


def run(capsys: pytest.CaptureFixture[str], cases: str) -> tuple[int, dict[str, Any]]:
    code = main(["check", "--cases-file", cases, "--format", "json"])
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, report


def test_a_change_only_in_the_state_after_the_call_is_found(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = BANK.replace("self.balance += amount", "self.balance += abs(amount)")
    cases = change(
        git_repository,
        BANK,
        after,
        [{"args": ["-50"], "init_args": ["100"]}, {"args": ["5"], "init_args": ["1"]}],
    )
    monkeypatch.chdir(git_repository.path)

    code, report = run(capsys, cases)

    assert code == EXIT_FINDINGS
    (finding,) = report["findings"]
    assert finding["init_args"] == ["100"]
    assert finding["before"]["repr"] == finding["after"]["repr"] == "None"
    assert finding["before"]["state"] == "{'balance': 50}"
    assert finding["after"]["state"] == "{'balance': 150}"
    assert report["summary"]["functions_checked"] == 1
    assert report["schema_version"] == 2


def test_the_reproducing_test_checks_the_state(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = BANK.replace("self.balance += amount", "self.balance += abs(amount)")
    cases = change(
        git_repository, BANK, after, [{"args": ["-50"], "init_args": ["100"]}]
    )
    monkeypatch.chdir(git_repository.path)
    _, report = run(capsys, cases)
    test_file = git_repository.path / report["findings"][0]["test_file"]
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]

    on_change = subprocess.run(command, cwd=test_file.parent, capture_output=True)
    git_repository.write("app/bank.py", BANK)
    on_base = subprocess.run(command, cwd=test_file.parent, capture_output=True)

    assert "instance = Account(100)" in test_file.read_text()
    assert "assert _state(instance) == {'balance': 50}" in test_file.read_text()
    assert on_change.returncode == 1
    assert on_base.returncode == 0


def test_a_case_whose_instance_cannot_be_built_is_dropped_and_counted(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = BANK.replace("self.balance += amount", "self.balance += amount * 2")
    cases = change(
        git_repository,
        BANK,
        after,
        [{"args": ["1"], "init_args": ["-1"]}, {"args": ["1"], "init_args": ["0"]}],
    )
    monkeypatch.chdir(git_repository.path)

    code, report = run(capsys, cases)

    assert code == EXIT_FINDINGS
    assert report["summary"]["construction_dropped"] == 1
    assert [f["init_args"] for f in report["findings"]] == [["0"]]


def test_a_method_whose_instance_is_never_built_is_skipped(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = BANK.replace("self.balance += amount", "self.balance -= amount")
    cases = change(git_repository, BANK, after, [{"args": ["1"], "init_args": ["-1"]}])
    monkeypatch.chdir(git_repository.path)

    code, report = run(capsys, cases)

    assert code == EXIT_OK  # skipped by design, like other skip reasons
    assert report["summary"]["skipped"] == [
        {
            "function": "app/bank.py::Account.deposit",
            "reason": "construction failed: ValueError",
        }
    ]


def test_a_constructor_change_with_no_common_arguments_says_so(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = BANK.replace(
        "def __init__(self, balance: int):",
        "def __init__(self, balance: int, fee: int):",
    ).replace("self.balance += amount", "self.balance += amount - 1")
    cases = change(
        git_repository,
        BANK,
        after,
        [{"args": ["1"], "init_args": ["1"]}, {"args": ["1"], "init_args": ["1", "2"]}],
    )
    monkeypatch.chdir(git_repository.path)

    _, report = run(capsys, cases)

    reasons = {
        item["function"]: item["reason"] for item in report["summary"]["skipped"]
    }
    assert reasons == {
        "app/bank.py::Account.__init__": "dunder method",
        "app/bank.py::Account.deposit": (
            "constructor changed: no constructor arguments work in both versions"
        ),
    }


def test_a_method_case_without_constructor_arguments_builds_with_none(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = "class Counter:\n    def __init__(self):\n        self.n = 0\n\n"
    before += "    def bump(self):\n        self.n += 1\n"
    git_repository.write("app/bank.py", before)
    git_repository.commit("base")
    git_repository.write("app/bank.py", before.replace("self.n += 1", "self.n += 2"))
    items = [{"function": "app/bank.py::Counter.bump", "args": []}]
    cases = str(git_repository.write("cases.json", json.dumps({"cases": items})))
    monkeypatch.chdir(git_repository.path)

    code, report = run(capsys, cases)

    assert code == EXIT_FINDINGS
    assert report["findings"][0]["init_args"] == []
    assert report["findings"][0]["after"]["state"] == "{'n': 2}"


def test_a_property_is_skipped_and_a_blocked_constructor_too(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    marker = tmp_path / "marker"
    source = (
        "import importlib\n\n"
        "class Box:\n"
        "    def __init__(self):\n"
        f"        importlib.import_module('os').system('touch {marker}')\n\n"
        "    @property\n"
        "    def size(self):\n        return 1\n\n"
        "    def name(self):\n        return 'box'\n"
    )
    git_repository.write("app/bank.py", source)
    git_repository.commit("base")
    git_repository.write(
        "app/bank.py", source.replace("return 1", "return 2").replace("'box'", "'bin'")
    )
    items = [{"function": "app/bank.py::Box.name", "args": [], "init_args": []}]
    cases = str(git_repository.write("cases.json", json.dumps({"cases": items})))
    monkeypatch.chdir(git_repository.path)

    _, report = run(capsys, cases)

    assert report["summary"]["skipped"] == [
        {"function": "app/bank.py::Box.size", "reason": "property"},
        {
            "function": "app/bank.py::Box.name",
            "reason": "blocked: os.system (base version)",
        },
    ]
    assert not marker.exists()


STRICT = BANK.replace("if balance < 0:", "if balance <= 0:")


def test_one_constructor_finding_for_several_methods_of_the_class(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    extra = (
        "\n    def withdraw(self, amount: int) -> None:\n"
        "        self.balance -= amount\n"
    )
    after = STRICT.replace("self.balance += amount", "self.balance += amount * 2")
    git_repository.write("app/bank.py", BANK + extra)
    git_repository.commit("base")
    git_repository.write("app/bank.py", after + extra.replace("-=", "-= 2 *"))
    items = [
        {"function": f"app/bank.py::Account.{name}", "args": ["1"], "init_args": ["0"]}
        for name in ("deposit", "withdraw")
    ]
    cases = str(git_repository.write("cases.json", json.dumps({"cases": items})))
    monkeypatch.chdir(git_repository.path)

    _, report = run(capsys, cases)

    assert [f["function"] for f in report["findings"]] == [
        "app/bank.py::Account.__init__"
    ]


def test_a_method_case_finds_a_constructor_that_now_rejects_its_arguments(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after = STRICT.replace("self.balance += amount", "self.balance += amount * 2")
    cases = change(git_repository, BANK, after, [{"args": ["1"], "init_args": ["0"]}])
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", cases]) == EXIT_FINDINGS

    out = capsys.readouterr().out
    assert "app/bank.py::Account(0)" in out
    assert "state before {'balance': 0} → after -" in out
    assert "app/bank.py::Account.deposit (construction failed: ValueError)" in out
    text = (
        git_repository.path / ".didibreak/tests/test_Account___init__.py"
    ).read_text()
    assert "    instance = Account(0)\n    assert _type_name(instance) ==" in text
    assert "    assert _state(instance) == {'balance': 0}" in text
