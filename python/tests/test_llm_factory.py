from dataclasses import replace

import pytest

from didibreak.config import Config, ConfigError
from didibreak.llm import DEFAULT_MODELS, client_settings, create_client
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


def test_missing_provider_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match='set provider = "openai" or "anthropic"'):
        client_settings(Config(), ENV)


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
