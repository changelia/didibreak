"""The comparison tolerances in compare.py must be documented in how-it-works.md."""

from pathlib import Path

import pytest

from didibreak.compare import FLOAT_ABSOLUTE_TOLERANCE, FLOAT_RELATIVE_TOLERANCE

DOC = Path(__file__).resolve().parents[2] / "docs" / "how-it-works.md"

pytestmark = pytest.mark.skipif(
    not DOC.is_file(),
    reason=f"{DOC} not found: this test needs the full repository checkout",
)


def written(value: float) -> str:
    return repr(value).replace("e-0", "e-")  # 1e-09 is written 1e-9


def test_float_tolerances_are_documented_with_their_values() -> None:
    text = " ".join(DOC.read_text(encoding="utf-8").split())

    assert f"rel_tol={written(FLOAT_RELATIVE_TOLERANCE)}" in text
    assert f"abs_tol={written(FLOAT_ABSOLUTE_TOLERANCE)}" in text
    assert "`FLOAT_RELATIVE_TOLERANCE`" in text
    assert "`FLOAT_ABSOLUTE_TOLERANCE`" in text
