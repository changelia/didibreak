import re
from pathlib import Path

import pytest

from didibreak.config import ConfigError, read_config_table, validate
from didibreak.llm.common import TokenUsage
from didibreak.llm.pricing import (
    BUILT_IN_PRICES,
    LOCAL_PRICE,
    PRICES_CHECKED,
    Price,
    cost_usd,
    is_local,
    price_for,
    prices_from_config,
    required_price,
)


def test_built_in_prices_are_the_verified_default_models_with_sources() -> None:
    assert set(BUILT_IN_PRICES) == {"gpt-6-luna", "claude-haiku-5-5"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", PRICES_CHECKED)
    for price in BUILT_IN_PRICES.values():
        assert price.source.startswith("https://")
        assert (price.input, price.output) == (0.10, 0.50)


def test_unknown_model_has_no_price() -> None:
    assert price_for("some-local-model") is None


def test_configured_price_wins_and_adds_models() -> None:
    overrides = prices_from_config(
        {
            "gpt-6-luna": {"input": 1.0, "output": 2.0},
            "llama": {"input": 0.0, "output": 0.0},
        }
    )

    assert price_for("gpt-6-luna", overrides) == Price(
        1.0, 2.0, source="prices setting"
    )
    assert price_for("llama", overrides) == Price(0.0, 0.0, source="prices setting")
    assert (
        price_for("claude-haiku-5-5", overrides) == BUILT_IN_PRICES["claude-haiku-5-5"]
    )


def test_cost_counts_output_including_reasoning_tokens() -> None:
    # Task 12 live call: 213 prompt, 537 completion tokens (399 reasoning).
    usage = TokenUsage(213, 537, 399, 0, 1)

    cost = cost_usd(usage, BUILT_IN_PRICES["gpt-6-luna"])

    assert cost == pytest.approx((213 * 0.10 + 537 * 0.50) / 1_000_000)


def test_cached_input_tokens_use_the_cached_price() -> None:
    usage = TokenUsage(1000, 0, None, 400, 1)

    cost = cost_usd(usage, BUILT_IN_PRICES["gpt-6-luna"])

    assert cost == pytest.approx((600 * 0.10 + 400 * 0.01) / 1_000_000)


def test_long_prompts_use_the_long_prices() -> None:
    haiku = BUILT_IN_PRICES["claude-haiku-5-5"]

    short = cost_usd(TokenUsage(100_000, 1000, None, 0, 1), haiku)
    long = cost_usd(TokenUsage(100_001, 1000, None, 0, 1), haiku)
    two_calls = cost_usd(TokenUsage(150_000, 1000, None, 0, 2), haiku)  # 75k each

    assert short == pytest.approx((100_000 * 0.10 + 1000 * 0.50) / 1_000_000)
    assert long == pytest.approx((100_001 * 0.50 + 1000 * 2.50) / 1_000_000)
    assert two_calls == pytest.approx((150_000 * 0.10 + 1000 * 0.50) / 1_000_000)


def test_prices_setting_is_read_from_pyproject(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        '[tool.didibreak.prices]\n"my-model" = { input = 0.5, output = 1.5 }\n',
        encoding="utf-8",
    )

    assert read_config_table(path) == {
        "prices": {"my-model": {"input": 0.5, "output": 1.5}}
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("cheap", "must be a table of model"),
        ({"m": {"input": 1}}, "prices.m: prices must be a table"),
        ({"m": {"input": 1, "output": 1, "total": 2}}, "unknown field 'total'"),
        ({"m": {"input": -1, "output": 1}}, "prices.m.input must be >= 0"),
        ({"m": {"input": "x", "output": 1}}, "prices.m.input must be a number"),
    ],
)
def test_invalid_prices_are_rejected(value: object, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        validate("prices", value)


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:1234/v1", True),
        ("https://api.openai.com/v1", False),
        ("http://192.168.1.5:11434/v1", False),
        ("https://localhost.example.com/v1", False),
    ],
)
def test_local_endpoints_are_localhost_and_127_0_0_1(url: str, local: bool) -> None:
    assert is_local(url) is local


def test_required_price_prefers_a_known_price_then_local_zero() -> None:
    overrides = prices_from_config({"llama": {"input": 0.2, "output": 0.4}})

    assert (
        required_price("gpt-6-luna", "https://api.openai.com/v1")
        == BUILT_IN_PRICES["gpt-6-luna"]
    )
    assert required_price("llama", "http://localhost:11434/v1", overrides).input == 0.2
    assert required_price("llama", "http://localhost:11434/v1") == LOCAL_PRICE


def test_unpriced_remote_model_is_a_configuration_error() -> None:
    with pytest.raises(
        ConfigError, match=r'add it in pyproject.toml: \[tool.didibreak.prices\] "x"'
    ):
        required_price("x", "https://openrouter.ai/api/v1")
