"""The README pages say what didibreak is and is not (task 27)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)
READMES = ["README.md", "python/README.md"]
IS_AND_IS_NOT = (
    "an extra check next to your tests",
    "a production safety net",
    "cannot prove that no other input changed",
)
ISOLATION = (
    "For code you did not write",
    "run didibreak inside a container or a CI job",
)


def flat(text: str) -> str:
    """Text with line breaks and block-quote markers folded into spaces."""
    return " ".join(text.replace("\n> ", "\n").split())


def missing(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Phrases that do not appear in the folded text."""
    folded = flat(text)
    return [phrase for phrase in phrases if phrase not in folded]


@pytest.mark.parametrize("page", READMES)
def test_readme_says_what_didibreak_is_and_is_not(page: str) -> None:
    assert missing((ROOT / page).read_text(encoding="utf-8"), IS_AND_IS_NOT) == []


@pytest.mark.parametrize("page", [*READMES, "docs/safety.md"])
def test_page_recommends_isolation_for_code_you_did_not_write(page: str) -> None:
    assert missing((ROOT / page).read_text(encoding="utf-8"), ISOLATION) == []


def test_a_line_broken_over_a_quote_still_counts() -> None:
    text = (
        "> For code you did not write,\n> run didibreak inside a container or a CI job."
    )

    assert missing(text, ISOLATION) == []


def test_a_page_without_the_lines_is_caught() -> None:
    assert missing("Run didibreak on your changes.", ISOLATION) == list(ISOLATION)
