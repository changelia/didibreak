"""Every stated precision figure carries its scope note (owner decision, task 22 b)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)
SCOPE_NOTE = (
    "7 libraries were chosen for literal-friendly",
    "model labels",
    "application code may score lower",
)


def blocks_with_precision(text: str) -> list[str]:
    """Paragraphs and list items that state the measured precision."""
    blocks = re.split(r"\n\s*\n|\n(?=- )", text)
    return [" ".join(block.split()) for block in blocks if "87%" in block]


def test_the_readme_and_limitations_state_the_precision() -> None:
    pages = [page.name for page in PAGES if blocks_with_precision(page.read_text())]

    assert {"README.md", "limitations.md"} <= set(pages)


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.name)
def test_every_precision_figure_has_the_scope_note(page: Path) -> None:
    for block in blocks_with_precision(page.read_text()):
        for part in SCOPE_NOTE:
            assert part in block, f"{page.name}: {block[:80]!r} lacks {part!r}"


def test_a_figure_without_the_note_is_caught() -> None:
    (block,) = blocks_with_precision("Precision is 87% on real code.\n")

    assert not all(part in block for part in SCOPE_NOTE)
