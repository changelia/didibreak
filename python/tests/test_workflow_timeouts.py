"""Every CI and release job has a time limit (owner decision 2026-11-10)."""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
FILES = sorted(WORKFLOWS.glob("*.yml")) if WORKFLOWS.is_dir() else []
pytestmark = pytest.mark.skipif(not FILES, reason="needs the full repository checkout")


def jobs_without_timeout(text: str) -> list[str]:
    """Names of jobs (two-space keys under ``jobs:``) with no timeout-minutes."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z0-9_-]*):\n", body, flags=re.MULTILINE)
    jobs = dict(zip(parts[1::2], parts[2::2], strict=True))
    return [
        name
        for name, job in jobs.items()
        if not re.search(r"^    timeout-minutes: \d+$", job, re.MULTILINE)
    ]


@pytest.mark.parametrize("workflow", FILES, ids=lambda path: path.name)
def test_every_job_has_a_timeout(workflow: Path) -> None:
    assert jobs_without_timeout(workflow.read_text()) == []


def test_a_job_without_a_timeout_is_found() -> None:
    text = (
        "on: push\njobs:\n"
        "  a:\n    runs-on: x\n    timeout-minutes: 5\n"
        "  b:\n    runs-on: x\n"
    )

    assert jobs_without_timeout(text) == ["b"]
