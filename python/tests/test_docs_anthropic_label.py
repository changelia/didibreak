"""Anthropic is labelled experimental until it is live-verified (owner, 2026-11-10)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABEL = "experimental, not live-verified"
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)


@pytest.mark.parametrize("page", ["README.md", "docs/providers-and-costs.md"])
def test_page_labels_anthropic_support_experimental(page: str) -> None:
    lines = (ROOT / page).read_text().splitlines()

    labelled = [line for line in lines if "anthropic" in line.lower() and LABEL in line]
    assert labelled, f"{page} does not label Anthropic as {LABEL!r}"


def test_the_default_model_row_carries_the_label() -> None:
    text = (ROOT / "docs/providers-and-costs.md").read_text()

    assert f"| `anthropic` ({LABEL}) | `claude-haiku-5-5` |" in text
