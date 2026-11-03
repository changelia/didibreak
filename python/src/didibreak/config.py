"""Configuration: defaults, ``[tool.didibreak]`` in pyproject.toml, CLI overrides.

Precedence (Detailed Design section 1): CLI flag > ``[tool.didibreak]`` >
built-in default. Every key is validated the same way wherever it comes from,
so the CLI and the config file produce identical error messages.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

FORMATS = ("text", "json")
FAIL_ON = ("unclear", "unexpected")
PROVIDERS = ("openai", "anthropic")


class ConfigError(Exception):
    """A configuration value or file is invalid; the message is user-facing."""


@dataclass(frozen=True)
class Config:
    """Settings that can come from ``[tool.didibreak]`` or CLI flags.

    ``None`` means "not set": the provider, model and base URL get their
    values later from the LLM layer, ``python`` defaults to the interpreter
    running didibreak.
    """

    base: str = "HEAD"
    intent: str | None = None
    format: str = "text"
    fail_on: str = "unclear"
    max_functions: int = 10
    cases: int = 12
    refine_rounds: int = 1
    max_cost: float = 0.50
    timeout: float = 10.0
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    python: str | None = None
    output_dir: str = ".didibreak"
    no_cache: bool = False
    exclude: tuple[str, ...] = field(default_factory=tuple)
    api_key_env: str | None = None


def _string(key: str, value: object) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string, got {value!r}")
    return value


def _non_empty_string(key: str, value: object) -> str:
    text = _string(key, value)
    if not text.strip():
        raise ConfigError(f"{key} must not be empty")
    return text


def _choice(choices: tuple[str, ...]) -> Callable[[str, object], str]:
    def check(key: str, value: object) -> str:
        if value not in choices:
            allowed = ", ".join(choices)
            raise ConfigError(f"{key} must be one of {allowed}; got {value!r}")
        return _string(key, value)

    return check


def _integer(minimum: int, maximum: int | None) -> Callable[[str, object], int]:
    def check(key: str, value: object) -> int:
        # bool is a subclass of int; `true` is not a valid count.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{key} must be an integer, got {value!r}")
        if value < minimum or (maximum is not None and value > maximum):
            upper = "" if maximum is None else f" and <= {maximum}"
            raise ConfigError(f"{key} must be >= {minimum}{upper}; got {value}")
        return value

    return check


def _positive_number(key: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{key} must be a number, got {value!r}")
    if value <= 0:
        raise ConfigError(f"{key} must be greater than 0; got {value}")
    return float(value)


def _boolean(key: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false, got {value!r}")
    return value


def _url(key: str, value: object) -> str:
    text = _string(key, value)
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"{key} must be an http(s) URL, got {text!r}")
    return text


def _glob_list(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of glob patterns (strings)")
    return tuple(value)


_VALIDATORS: dict[str, Callable[[str, object], object]] = {
    "base": _non_empty_string,
    "intent": _string,
    "format": _choice(FORMATS),
    "fail_on": _choice(FAIL_ON),
    "max_functions": _integer(1, None),
    "cases": _integer(1, 50),
    "refine_rounds": _integer(0, 3),
    "max_cost": _positive_number,
    "timeout": _positive_number,
    "provider": _choice(PROVIDERS),
    "model": _non_empty_string,
    "base_url": _url,
    "python": _non_empty_string,
    "output_dir": _non_empty_string,
    "no_cache": _boolean,
    "exclude": _glob_list,
    # An empty string disables the API key check (local servers).
    "api_key_env": _string,
}

CONFIG_KEYS = tuple(_VALIDATORS)


def validate(key: str, value: object) -> object:
    """Validate one setting and return it in its stored form.

    Args:
        key: Config key name (snake_case).
        value: Raw value from the config file or a converted CLI flag.

    Returns:
        The validated value.

    Raises:
        ConfigError: If the key is unknown or the value is invalid.
    """
    validator = _VALIDATORS.get(key)
    if validator is None:
        allowed = ", ".join(CONFIG_KEYS)
        raise ConfigError(f"unknown key {key!r}; allowed keys: {allowed}")
    return validator(key, value)
