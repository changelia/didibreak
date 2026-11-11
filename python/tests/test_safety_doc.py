"""The credential rule in harness.py must be documented in safety.md."""

from pathlib import Path

import pytest

from didibreak.harness import SECRET_SUFFIXES, SECRET_WORDS, URL_SUFFIXES

DOC = Path(__file__).resolve().parents[2] / "docs" / "safety.md"

pytestmark = pytest.mark.skipif(
    not DOC.is_file(),
    reason=f"{DOC} not found: this test needs the full repository checkout",
)


def test_every_credential_pattern_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")

    missing = [
        name
        for name in (*SECRET_SUFFIXES, *SECRET_WORDS, *URL_SUFFIXES)
        if f"`{name}`" not in text
    ]

    assert missing == []
