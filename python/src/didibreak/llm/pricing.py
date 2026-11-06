"""Model prices and the cost of LLM calls.

The built-in table holds only prices checked in the provider's official docs,
each with its source; ``PRICES_CHECKED`` is the date they were checked. A
model that is not in the table and not in the user's ``prices`` setting has
no price: didibreak then shows tokens only and never guesses a cost.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from didibreak.llm.common import TokenUsage

PRICES_CHECKED = "2026-11-06"
_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    """USD per million tokens for one model.

    Attributes:
        input: Input tokens.
        output: Output tokens (reasoning tokens included; they are billed as
            output).
        cached_input: Input tokens read from the provider's cache; None means
            the input price.
        long_prompt_tokens: Requests whose prompt is longer than this use the
            ``long_*`` prices for the whole request; None when the model has
            one price.
        long_input: Input price for long prompts.
        long_output: Output price for long prompts.
        long_cached_input: Cached input price for long prompts.
        source: Where the price comes from.
    """

    input: float
    output: float
    cached_input: float | None = None
    long_prompt_tokens: int | None = None
    long_input: float | None = None
    long_output: float | None = None
    long_cached_input: float | None = None
    source: str = ""


# Checked in the official docs on PRICES_CHECKED (task 12/15): only the
# default models; other models need the `prices` setting for a cost.
BUILT_IN_PRICES: dict[str, Price] = {
    "gpt-6-luna": Price(
        input=0.10,
        output=0.50,
        cached_input=0.01,
        long_prompt_tokens=272_000,
        long_input=0.20,
        long_output=0.75,
        long_cached_input=0.02,
        source="https://developers.openai.com/api/docs/models/gpt-6-luna",
    ),
    "claude-haiku-5-5": Price(
        input=0.10,
        output=0.50,
        cached_input=0.01,
        long_prompt_tokens=100_000,
        long_input=0.50,
        long_output=2.50,
        long_cached_input=0.05,
        source="https://platform.claude.com/docs/en/about-claude/pricing",
    ),
}


def prices_from_config(
    table: Mapping[str, Mapping[str, float]] | None,
) -> dict[str, Price]:
    """Prices from the ``prices`` setting (validated by config.validate)."""
    return {
        model: Price(
            input=entry["input"],
            output=entry["output"],
            cached_input=entry.get("cached_input"),
            source="prices setting",
        )
        for model, entry in (table or {}).items()
    }


def price_for(model: str, overrides: Mapping[str, Price] | None = None) -> Price | None:
    """The price of a model: the user's ``prices`` first, then the built-in table."""
    if overrides and model in overrides:
        return overrides[model]
    return BUILT_IN_PRICES.get(model)


def cost_usd(usage: TokenUsage, price: Price) -> float:
    """Cost of the calls in ``usage``.

    The long-prompt tier is chosen from the average prompt size per call,
    since usage may cover a retry of the same request.

    Args:
        usage: Tokens of one or more calls of the same request.
        price: The model's price.

    Returns:
        US dollars.
    """
    calls = max(usage.calls, 1)
    long_prompt = (
        price.long_prompt_tokens is not None
        and usage.input_tokens / calls > price.long_prompt_tokens
    )
    input_price = price.long_input if long_prompt and price.long_input else price.input
    output_price = (
        price.long_output if long_prompt and price.long_output else price.output
    )
    cached_price = price.long_cached_input if long_prompt else price.cached_input
    if cached_price is None:
        cached_price = input_price
    cached = min(usage.cached_input_tokens, usage.input_tokens)
    total = (
        (usage.input_tokens - cached) * input_price
        + cached * cached_price
        + usage.output_tokens * output_price
    )
    return total / _PER_MILLION
