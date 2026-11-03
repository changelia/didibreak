"""Tests for configuration defaults, validation, file loading and precedence."""

import pytest

from didibreak.config import CONFIG_KEYS, Config, ConfigError, validate


def test_defaults_match_detailed_design() -> None:
    config = Config()

    assert (config.base, config.format, config.fail_on) == ("HEAD", "text", "unclear")
    assert (config.max_functions, config.cases, config.refine_rounds) == (10, 12, 1)
    assert (config.max_cost, config.timeout) == (0.50, 10.0)
    assert config.output_dir == ".didibreak"
    assert config.provider is None
    assert config.model is None


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("cases", 0, "cases must be >= 1 and <= 50; got 0"),
        ("cases", 51, "cases must be >= 1 and <= 50; got 51"),
        ("refine_rounds", 4, "refine_rounds must be >= 0 and <= 3; got 4"),
        ("max_functions", True, "max_functions must be an integer, got True"),
        ("timeout", 0, "timeout must be greater than 0; got 0"),
        ("max_cost", "cheap", "max_cost must be a number, got 'cheap'"),
        ("format", "xml", "format must be one of text, json; got 'xml'"),
        ("fail_on", "all", "fail_on must be one of unclear, unexpected"),
        ("provider", "gemini", "provider must be one of openai, anthropic"),
        ("base_url", "localhost:11434", "base_url must be an http(s) URL"),
        ("exclude", "tests/*", "exclude must be a list of glob patterns"),
        ("no_cache", "yes", "no_cache must be true or false, got 'yes'"),
        ("base", "  ", "base must not be empty"),
    ],
)
def test_invalid_values_are_rejected_with_the_rule(
    key: str, value: object, message: str
) -> None:
    with pytest.raises(ConfigError) as info:
        validate(key, value)

    assert message in str(info.value)


def test_every_config_field_has_a_validator() -> None:
    assert set(CONFIG_KEYS) == set(Config.__dataclass_fields__)
