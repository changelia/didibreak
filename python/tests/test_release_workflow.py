"""release-python.yml stays consistent with the scripts and tag rules (task 23)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-python.yml"
pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="needs the full repository checkout"
)


def job(name: str) -> str:
    """The text of one job, up to the next job."""
    text = WORKFLOW.read_text()
    start = text.index(f"\n  {name}:\n")
    following = [
        text.index(f"\n  {other}:\n")
        for other in ("build", "smoke", "testpypi", "pypi")
        if text.index(f"\n  {other}:\n") > start
    ]
    return text[start : min(following, default=len(text))]


def test_scripts_named_in_the_workflow_exist() -> None:
    text = WORKFLOW.read_text()

    for script in ("scripts/check_dist.py", "scripts/package_smoke.py"):
        assert script in text
        assert (ROOT / "python" / script).is_file()


def test_pypi_runs_only_for_py_v_tags_and_testpypi_only_by_hand() -> None:
    assert 'tags: ["py-v*"]' in WORKFLOW.read_text()
    assert "startsWith(github.ref, 'refs/tags/py-v')" in job("pypi")
    assert "github.event_name == 'workflow_dispatch'" in job("testpypi")
    assert "https://test.pypi.org/legacy/" in job("testpypi")
    assert "repository-url" not in job("pypi")


def test_only_the_upload_jobs_get_an_oidc_token_and_an_environment() -> None:
    for name, environment in (("testpypi", "testpypi"), ("pypi", "pypi")):
        assert "id-token: write" in job(name)
        assert f"name: {environment}" in job(name)
    for name in ("build", "smoke"):
        assert "id-token" not in job(name)
        assert "environment" not in job(name)


def test_uploads_wait_for_the_smoke_test() -> None:
    assert "needs: smoke" in job("testpypi")
    assert "needs: smoke" in job("pypi")
    assert "needs: build" in job("smoke")
