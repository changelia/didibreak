"""The built-in price table in pricing.py must match providers-and-costs.md."""

from pathlib import Path

import pytest

from didibreak.llm.pricing import BUILT_IN_PRICES, PRICES_CHECKED

DOC = Path(__file__).resolve().parents[2] / "docs" / "providers-and-costs.md"

pytestmark = pytest.mark.skipif(
    not DOC.is_file(),
    reason=f"{DOC} not found: this test needs the full repository checkout",
)


def number(value: float | None) -> str:
    return f"{value:.2f}"


def test_every_built_in_price_is_documented_with_its_source() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert f"checked in the official\ndocs on {PRICES_CHECKED}" in text
    for model, price in BUILT_IN_PRICES.items():
        row = next(
            line for line in text.splitlines() if line.startswith(f"| `{model}` |")
        )
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[1:4] == [
            number(price.input),
            number(price.cached_input),
            number(price.output),
        ]
        assert f"{price.long_prompt_tokens:,}" in cells[4]
        long_prices = (price.long_input, price.long_cached_input, price.long_output)
        assert " / ".join(number(value) for value in long_prices) in cells[4]
        assert price.source in cells[5]
