"""LLM clients: thin httpx clients for OpenAI-compatible APIs and Anthropic.

Both clients take messages and a JSON schema and return the parsed JSON
object with its token usage (``common.LLMClient``). The LLM proposes inputs
and labels findings; it never supplies code that is executed.
"""

from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from didibreak.config import (
    PRESETS,
    Config,
    ConfigError,
    api_key_variable,
    read_api_key,
)
from didibreak.llm.anthropic import DEFAULT_BASE_URL as ANTHROPIC_BASE_URL
from didibreak.llm.anthropic import AnthropicClient
from didibreak.llm.common import ClientSettings
from didibreak.llm.openai_compat import OpenAICompatibleClient

# Cheapest current models with structured output, checked in the official
# docs on 2026-11-06 (task 12, Q4); see docs/providers-and-costs.md.
DEFAULT_MODELS = {"openai": "gpt-6-luna", "anthropic": "claude-haiku-5-5"}
# Presets (task 34) use the OpenAI-compatible client with these URLs, from
# the services' docs (checked 2026-11-11): openrouter.ai/docs/quickstart,
# docs.ollama.com/api/openai-compatibility, lmstudio.ai/docs (port 1234).
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": ANTHROPIC_BASE_URL,
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}


# Provider inferred from the standard key variables when none is configured
# (owner decision 2026-11-06, task 13 review), in Spec usage order.
_PROVIDER_KEYS = (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"))


def resolve_provider(config: Config, environment: Mapping[str, str]) -> str:
    """The configured provider, or the one whose API key variable is set.

    Args:
        config: The effective configuration; an explicit provider wins.
        environment: Environment variables.

    Returns:
        A name from config.PROVIDERS; only ``openai`` and ``anthropic`` are
        inferred.

    Raises:
        ConfigError: No provider is configured and both or neither of
            OPENAI_API_KEY and ANTHROPIC_API_KEY are set.
    """
    if config.provider is not None:
        return config.provider
    found = [
        provider for provider, variable in _PROVIDER_KEYS if environment.get(variable)
    ]
    if len(found) == 1:
        return found[0]
    if found:
        reason = "both OPENAI_API_KEY and ANTHROPIC_API_KEY are set"
    else:
        reason = "neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is set"
    raise ConfigError(
        f"cannot choose an LLM provider: {reason}; set provider (openai, "
        "anthropic, openrouter, ollama or lmstudio) in [tool.didibreak] of "
        "pyproject.toml or pass --provider; openrouter, ollama and lmstudio "
        "also need model"
    )


def output_limit_parameter(provider: str, base_url: str) -> str | None:
    """The request field that caps a reply's output, where the server documents it.

    Checked in each service's docs on 2026-11-11 (audit 35a): OpenAI and
    OpenRouter document ``max_completion_tokens`` (OpenAI's ``max_tokens`` does
    not work with reasoning models); Ollama and LM Studio document only
    ``max_tokens``. Anthropic always sends ``max_tokens`` in its own client.
    Any other OpenAI-compatible server gets no cap, since an unknown field
    may be rejected.

    Args:
        provider: The resolved provider.
        base_url: The API base URL.

    Returns:
        The field name, or None.
    """
    host = urlparse(base_url).hostname
    if provider in ("ollama", "lmstudio"):
        return "max_tokens"
    if provider == "openrouter" or host == "openrouter.ai":
        return "max_completion_tokens"
    if provider == "openai" and host == "api.openai.com":
        return "max_completion_tokens"
    return None


def client_settings(config: Config, environment: Mapping[str, str]) -> ClientSettings:
    """Resolve provider, model, base URL and API key from the configuration.

    Args:
        config: The effective configuration.
        environment: Environment variables holding the API key.

    Returns:
        Settings for the provider's client.

    Raises:
        ConfigError: No provider can be chosen (resolve_provider), no model
            applies (a preset or a non-default ``base_url`` has no default
            model), or the API key is missing.
    """
    provider = resolve_provider(config, environment)
    config = replace(config, provider=provider)
    default_url = DEFAULT_BASE_URLS[provider]
    base_url = config.base_url or default_url
    model = config.model
    if model is None:
        if provider in PRESETS:
            raise ConfigError(
                f"set model: the {provider} preset has no default model, "
                "because model names differ per service; pass --model or set "
                "model in [tool.didibreak]"
            )
        if base_url.rstrip("/") != default_url.rstrip("/"):
            raise ConfigError(
                f"set model: base_url {base_url} is not the {provider} "
                "default, so there is no default model"
            )
        model = DEFAULT_MODELS[provider]
    return ClientSettings(
        model=model,
        base_url=base_url,
        api_key=read_api_key(config, environment),
        api_key_variable=api_key_variable(config),
        temperature=config.temperature,
        output_limit_parameter=output_limit_parameter(provider, base_url),
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
    if resolve_provider(config, environment) == "anthropic":
        return AnthropicClient(settings, transport)
    return OpenAICompatibleClient(settings, transport)
