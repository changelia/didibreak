"""didibreak init-agents: prints the Spec snippet and never edits files (task 20)."""

import subprocess
import sys
from pathlib import Path

import pytest

from didibreak.cli import EXIT_OK, main

# The agent snippet exactly as written in the Spec ("Agent snippet").
SPEC_SNIPPET = """## Behavior check
After changing Python functions, run:
    didibreak check --intent "<the user's request in one sentence>" --format json
If any finding has label "unexpected", fix the code so that behavior is preserved,
then run the check again. Report "unclear" findings to the user instead of guessing.
"""


def test_output_is_the_spec_snippet(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init-agents"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == SPEC_SNIPPET
    assert captured.err == ""


def test_agent_files_are_never_created_or_edited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "AGENTS.md").write_text("# Agents\n")
    (tmp_path / "CLAUDE.md").write_text("# Claude\n")
    monkeypatch.chdir(tmp_path)

    assert main(["init-agents"]) == EXIT_OK

    assert sorted(p.name for p in tmp_path.iterdir()) == ["AGENTS.md", "CLAUDE.md"]
    assert (tmp_path / "AGENTS.md").read_text() == "# Agents\n"
    assert (tmp_path / "CLAUDE.md").read_text() == "# Claude\n"


def test_works_outside_a_git_repository_without_any_key(tmp_path: Path) -> None:
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, "-m", "didibreak", "init-agents"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == SPEC_SNIPPET
    assert list(tmp_path.iterdir()) == []


def test_extra_arguments_are_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["init-agents", "AGENTS.md"])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: AGENTS.md" in capsys.readouterr().err
