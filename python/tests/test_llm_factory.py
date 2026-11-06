from dataclasses import replace

import pytest

from didibreak.config import Config, ConfigError
from didibreak.llm import (
    DEFAULT_MODELS,
    client_settings,
    create_client,
    resolve_provider,
)
from didibreak.llm.anthropic import AnthropicClient
from didibreak.llm.openai_compat import OpenAICompatibleClient

ENV = {"OPENAI_API_KEY": "sk-openai", "ANTHROPIC_API_KEY": "sk-ant"}


def test_default_models_are_the_verified_cheap_models() -> None:
    assert DEFAULT_MODELS == {"openai": "gpt-6-luna", "anthropic": "claude-haiku-5-5"}


def test_openai_defaults() -> None:
    settings = client_settings(Config(provider="openai"), ENV)

    assert (settings.model, settings.base_url) == (
        "gpt-6-luna",
        "https://api.openai.com/v1",
    )
    assert (settings.api_key, settings.api_key_variable) == (
        "sk-openai",
        "OPENAI_API_KEY",
    )
    assert settings.temperature is None


def test_anthropic_defaults() -> None:
    settings = client_settings(Config(provider="anthropic"), ENV)

    assert (settings.model, settings.base_url) == (
        "claude-haiku-5-5",
        "https://api.anthropic.com",
    )
    assert settings.api_key == "sk-ant"


@pytest.mark.parametrize(
    ("environment", "provider"),
    [
        ({"OPENAI_API_KEY": "sk-openai"}, "openai"),
        ({"ANTHROPIC_API_KEY": "sk-ant"}, "anthropic"),
        ({"OPENAI_API_KEY": "sk-openai", "ANTHROPIC_API_KEY": ""}, "openai"),
    ],
)
def test_provider_is_inferred_from_the_only_key_set(
    environment: dict[str, str], provider: str
) -> None:
    assert resolve_provider(Config(), environment) == provider
    assert client_settings(Config(), environment).model == DEFAULT_MODELS[provider]


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        (ENV, "both OPENAI_API_KEY and ANTHROPIC_API_KEY are set"),
        ({}, "neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is set"),
    ],
)
def test_both_or_neither_key_needs_an_explicit_provider(
    environment: dict[str, str], reason: str
) -> None:
    with pytest.raises(ConfigError) as info:
        client_settings(Config(), environment)

    assert reason in str(info.value)
    assert 'set provider = "openai" or "anthropic"' in str(info.value)


def test_explicit_provider_wins_over_the_environment() -> None:
    only_openai = {"OPENAI_API_KEY": "sk-openai"}

    assert resolve_provider(Config(provider="anthropic"), only_openai) == "anthropic"
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        client_settings(Config(provider="anthropic"), only_openai)


def test_other_openai_compatible_services_need_a_model() -> None:
    config = Config(provider="openai", base_url="https://openrouter.ai/api/v1")

    with pytest.raises(
        ConfigError, match=r"set model: base_url https://openrouter\.ai/api/v1"
    ):
        client_settings(config, ENV)

    chosen = client_settings(replace(config, model="openai/gpt-6-luna"), ENV)
    assert chosen.model == "openai/gpt-6-luna"


def test_default_base_url_with_a_trailing_slash_keeps_the_default_model() -> None:
    config = Config(provider="openai", base_url="https://api.openai.com/v1/")

    assert client_settings(config, ENV).model == "gpt-6-luna"


def test_missing_key_names_the_variable() -> None:
    with pytest.raises(
        ConfigError, match="set the environment variable ANTHROPIC_API_KEY"
    ):
        client_settings(Config(provider="anthropic"), {})


def test_local_server_without_key() -> None:
    config = Config(
        provider="openai",
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        api_key_env="",
    )

    settings = client_settings(config, {})

    assert settings.api_key is None


def test_configured_temperature_reaches_the_client() -> None:
    settings = client_settings(Config(provider="openai", temperature=1.0), ENV)

    assert settings.temperature == 1.0


def test_client_type_follows_the_provider() -> None:
    with create_client(Config(provider="openai"), ENV) as openai:
        assert isinstance(openai, OpenAICompatibleClient)
    with create_client(Config(provider="anthropic"), ENV) as anthropic:
        assert isinstance(anthropic, AnthropicClient)
    assert "sk-openai" not in repr(openai.settings)


def test_inferred_anthropic_gets_the_anthropic_client() -> None:
    with create_client(Config(), {"ANTHROPIC_API_KEY": "sk-ant"}) as client:
        assert isinstance(client, AnthropicClient)
        assert client.settings.model == "claude-haiku-5-5"
