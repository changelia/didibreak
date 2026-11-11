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
    assert "set provider (openai, anthropic, openrouter, ollama or lmstudio)" in str(
        info.value
    )


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


PRESET_ENV = {"OPENROUTER_API_KEY": "sk-or"}


@pytest.mark.parametrize(
    ("provider", "base_url", "key", "variable"),
    [
        ("openrouter", "https://openrouter.ai/api/v1", "sk-or", "OPENROUTER_API_KEY"),
        ("ollama", "http://localhost:11434/v1", None, None),
        ("lmstudio", "http://localhost:1234/v1", None, None),
    ],
)
def test_presets_fill_base_url_and_key_variable(
    provider: str, base_url: str, key: str | None, variable: str | None
) -> None:
    settings = client_settings(Config(provider=provider, model="m"), PRESET_ENV)

    assert (settings.base_url, settings.api_key) == (base_url, key)
    assert settings.api_key_variable == variable
    assert isinstance(
        create_client(Config(provider=provider, model="m"), PRESET_ENV),
        OpenAICompatibleClient,
    )


@pytest.mark.parametrize("provider", ["openrouter", "ollama", "lmstudio"])
def test_presets_need_a_model(provider: str) -> None:
    with pytest.raises(ConfigError, match=f"the {provider} preset has no default"):
        client_settings(Config(provider=provider), PRESET_ENV)


def test_explicit_base_url_and_key_variable_override_the_preset() -> None:
    config = Config(
        provider="ollama",
        model="m",
        base_url="http://127.0.0.1:9999/v1",
        api_key_env="MY_KEY",
    )

    settings = client_settings(config, {"MY_KEY": "k"})

    assert (settings.base_url, settings.api_key) == ("http://127.0.0.1:9999/v1", "k")


def test_openrouter_preset_without_its_key_names_the_variable() -> None:
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        client_settings(Config(provider="openrouter", model="m"), {})


def test_presets_are_never_inferred_from_the_environment() -> None:
    with pytest.raises(ConfigError, match="neither OPENAI_API_KEY"):
        resolve_provider(Config(), PRESET_ENV)
