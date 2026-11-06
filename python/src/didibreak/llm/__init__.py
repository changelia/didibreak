"""LLM clients: thin httpx clients for OpenAI-compatible APIs and Anthropic.

Both clients take messages and a JSON schema and return the parsed JSON
object with its token usage (``common.LLMClient``). The LLM proposes inputs
and labels findings; it never supplies code that is executed.
"""

from collections.abc import Mapping

import httpx

from didibreak.config import Config, ConfigError, api_key_variable, read_api_key
from didibreak.llm.anthropic import DEFAULT_BASE_URL as ANTHROPIC_BASE_URL
from didibreak.llm.anthropic import AnthropicClient
from didibreak.llm.common import ClientSettings
from didibreak.llm.openai_compat import OpenAICompatibleClient

# Cheapest current models with structured output, checked in the official
# docs on 2026-11-06 (task 12, Q4); see docs/providers-and-costs.md.
DEFAULT_MODELS = {"openai": "gpt-6-luna", "anthropic": "claude-haiku-5-5"}
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": ANTHROPIC_BASE_URL,
}


def client_settings(config: Config, environment: Mapping[str, str]) -> ClientSettings:
    """Resolve provider, model, base URL and API key from the configuration.

    Args:
        config: The effective configuration.
        environment: Environment variables holding the API key.

    Returns:
        Settings for the provider's client.

    Raises:
        ConfigError: No provider is set, no model applies (a non-default
            ``base_url`` has no default model), or the API key is missing.
    """
    if config.provider is None:
        raise ConfigError(
            'no LLM provider configured: set provider = "openai" or "anthropic" '
            "in [tool.didibreak] of pyproject.toml, or pass --provider"
        )
    default_url = DEFAULT_BASE_URLS[config.provider]
    base_url = config.base_url or default_url
    model = config.model
    if model is None:
        if base_url.rstrip("/") != default_url.rstrip("/"):
            raise ConfigError(
                f"set model: base_url {base_url} is not the {config.provider} "
                "default, so there is no default model"
            )
        model = DEFAULT_MODELS[config.provider]
    return ClientSettings(
        model=model,
        base_url=base_url,
        api_key=read_api_key(config, environment),
        api_key_variable=api_key_variable(config),
        temperature=config.temperature,
    )


def create_client(
    config: Config,
    environment: Mapping[str, str],
    transport: httpx.BaseTransport | None = None,
) -> OpenAICompatibleClient | AnthropicClient:
    """Create the client for the configured provider.

    Args:
        config: The effective configuration.
        environment: Environment variables holding the API key.
        transport: Replacement transport for tests; None for real HTTP.

    Returns:
        A client; close it after use (it is a context manager).

    Raises:
        ConfigError: See client_settings().
    """
    settings = client_settings(config, environment)
    if config.provider == "anthropic":
        return AnthropicClient(settings, transport)
    return OpenAICompatibleClient(settings, transport)
