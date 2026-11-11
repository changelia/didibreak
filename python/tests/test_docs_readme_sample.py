"""The PyPI page shows the same recorded run as the root README (task 26)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)


def recorded_run(page: Path) -> str:
    """The text block that starts with the didibreak header line."""
    blocks = re.findall(r"```text\n(didibreak .*?)```", page.read_text(), re.DOTALL)
    assert len(blocks) == 1, f"{page.name}: expected one recorded run"
    return blocks[0]


def test_pypi_readme_shows_the_root_readme_run() -> None:
    root = recorded_run(ROOT / "README.md")

    assert recorded_run(ROOT / "python" / "README.md") == root
    assert root.startswith("didibreak 0.1.0 · working tree vs HEAD")


def test_getting_started_records_the_same_released_version() -> None:
    page = (ROOT / "docs" / "getting-started-python.md").read_text()

    assert "0.1.0.dev0" not in page
    assert "didibreak 0.1.0 · working tree vs HEAD (94fdbfd8ff0b)" in page


RECORDED_PAGES = [
    "README.md",
    "CONTRIBUTING.md",
    "python/README.md",
    *sorted(str(page.relative_to(ROOT)) for page in (ROOT / "docs").glob("*.md")),
]


def development_versions(text: str) -> list[str]:
    """Version strings of unreleased didibreak builds (task 27)."""
    return re.findall(r"didibreak \d+\.\d+\.\d+\.dev\d+", text)


@pytest.mark.parametrize("page", RECORDED_PAGES)
def test_recorded_output_comes_from_a_released_version(page: str) -> None:
    assert development_versions((ROOT / page).read_text()) == []


def test_a_development_header_is_caught() -> None:
    text = "didibreak 0.1.0.dev0 · working tree vs HEAD (9d74d2b028c7)"

    assert development_versions(text) == ["didibreak 0.1.0.dev0"]
