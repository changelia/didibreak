"""The method_blocked fixture: the runtime guard stops a method (task 30).

Its expected.json documents no case, because the method never gets an
outcome; this test runs it with its own case and a marker file.
"""

import json
from pathlib import Path

import pytest
from fixture_repos import build_fixture_repository

from didibreak.cli import EXIT_OK, main


def test_a_method_that_starts_a_process_is_skipped_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture_repository("method_blocked", tmp_path / "repo")
    marker = tmp_path / "marker"
    case = {
        "function": "app/report.py::Report.publish",
        "init_args": ["'weekly'"],
        "args": [repr(str(marker))],
    }
    cases = fixture.repository.write("cases.json", json.dumps({"cases": [case]}))
    monkeypatch.chdir(fixture.repository.path)

    code = main(["check", "--cases-file", str(cases), "--format", "json"])

    summary = json.loads(capsys.readouterr().out)["summary"]
    assert code == EXIT_OK
    assert summary["functions_checked"] == 0
    assert summary["skipped"] == [
        {
            "function": "app/report.py::Report.publish",
            "reason": "blocked: subprocess.Popen (base version)",
        }
    ]
    assert not marker.exists()
