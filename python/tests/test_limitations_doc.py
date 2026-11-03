"""The obvious-I/O list in OBVIOUS_IO must be documented in limitations.md."""

from pathlib import Path

import pytest

from didibreak.testability import OBVIOUS_IO

DOC = Path(__file__).resolve().parents[2] / "docs" / "limitations.md"

pytestmark = pytest.mark.skipif(
    not DOC.is_file(),
    reason=f"{DOC} not found: this test needs the full repository checkout",
)


def test_every_obvious_io_name_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")

    missing = [
        name
        for names in OBVIOUS_IO.values()
        for name in names
        if f"`{name}`" not in text
    ]

    assert missing == []
