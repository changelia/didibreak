"""Configuration: defaults, ``[tool.didibreak]`` in pyproject.toml, CLI overrides.

Precedence (Detailed Design section 1): CLI flag > ``[tool.didibreak]`` >
built-in default. Every key is validated the same way wherever it comes from,
so the CLI and the config file produce identical error messages.
"""

import os
import shutil
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FORMATS = ("text", "json")
FAIL_ON = ("unclear", "unexpected")
PROVIDERS = ("openai", "anthropic")

_DEFAULT_API_KEY_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


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

# Keys holding filesystem paths; relative values are resolved by resolve_paths().
PATH_KEYS = ("python", "output_dir")


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


def find_pyproject(start: Path, stop: Path) -> Path | None:
    """Find the nearest pyproject.toml from ``start`` up to ``stop``.

    Args:
        start: Directory to start in (the current directory).
        stop: Last directory to look in (the git repository root).

    Returns:
        The path of the nearest pyproject.toml, or None if there is none.
    """
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
        if directory == stop:
            break
    return None


def _resolve_python(value: str, base_directory: Path) -> str:
    # Owner decision (task 05 review): a bare name such as "python3" is looked
    # up on PATH; anything with a path separator follows the path rule.
    if "/" not in value and os.sep not in value:
        found = shutil.which(value)
        if found is None:
            raise ConfigError(
                f"python interpreter {value!r} was not found on PATH; "
                "give its full path or install it"
            )
        return found
    path = Path(value) if Path(value).is_absolute() else base_directory / value
    if not path.is_file():
        raise ConfigError(
            f"python interpreter {str(path)!r} does not exist; check the path"
        )
    return str(path)


def resolve_paths(
    values: Mapping[str, object], base_directory: Path
) -> dict[str, object]:
    """Make path values absolute and find the ``python`` interpreter.

    Owner decisions (task 04 and 05 reviews): relative paths from
    pyproject.toml are relative to that file's directory, relative paths from
    CLI flags to the working directory. A ``python`` value without a path
    separator is looked up on PATH.

    Args:
        values: Validated config values.
        base_directory: Directory that relative paths are relative to.

    Returns:
        A copy of ``values`` with absolute paths for the keys in PATH_KEYS.

    Raises:
        ConfigError: If the ``python`` interpreter cannot be found.
    """
    resolved = dict(values)
    python = resolved.get("python")
    if isinstance(python, str):
        resolved["python"] = _resolve_python(python, base_directory)
    output_dir = resolved.get("output_dir")
    if isinstance(output_dir, str) and not Path(output_dir).is_absolute():
        resolved["output_dir"] = str(base_directory / output_dir)
    return resolved


def read_config_table(pyproject: Path) -> dict[str, object]:
    """Read and validate ``[tool.didibreak]`` from a pyproject.toml.

    Args:
        pyproject: Path to the file.

    Returns:
        The validated keys present in the table, with relative paths resolved
        against the file's directory; empty if there is no table.

    Raises:
        ConfigError: If the file is not valid TOML or a key is invalid.
    """
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{pyproject} is not valid TOML: {error}") from error
    tool = document.get("tool", {})
    table = tool.get("didibreak", {}) if isinstance(tool, dict) else {}
    if not isinstance(table, dict):
        raise ConfigError(f"[tool.didibreak] in {pyproject} must be a table")
    values: dict[str, object] = {}
    for key, value in table.items():
        try:
            values[key] = validate(key, value)
        except ConfigError as error:
            raise ConfigError(f"[tool.didibreak] in {pyproject}: {error}") from error
    try:
        return resolve_paths(values, pyproject.parent)
    except ConfigError as error:
        raise ConfigError(f"[tool.didibreak] in {pyproject}: {error}") from error


def build_config(
    file_values: Mapping[str, object], cli_values: Mapping[str, object]
) -> Config:
    """Combine validated values: CLI flags override the file, which overrides defaults.

    Args:
        file_values: Validated values from ``[tool.didibreak]``.
        cli_values: Validated values of the CLI flags the user gave.

    Returns:
        The effective configuration.
    """
    merged: dict[str, Any] = {**file_values, **cli_values}
    return Config(**merged)


def api_key_variable(config: Config) -> str | None:
    """Name the environment variable that holds the provider's API key.

    Args:
        config: The effective configuration.

    Returns:
        ``api_key_env`` if set and non-empty, otherwise the provider's standard
        variable. None when no key is needed (``api_key_env = ""``) or no
        provider is configured.
    """
    if config.api_key_env is not None:
        return config.api_key_env or None
    if config.provider is None:
        return None
    return _DEFAULT_API_KEY_VARIABLES[config.provider]


def read_api_key(config: Config, environment: Mapping[str, str]) -> str | None:
    """Read the API key from the environment.

    Args:
        config: The effective configuration.
        environment: Environment variables, usually ``os.environ``.

    Returns:
        The key, or None when no key is needed.

    Raises:
        ConfigError: If a key is needed but the variable is missing or empty.
    """
    variable = api_key_variable(config)
    if variable is None:
        return None
    key = environment.get(variable, "")
    if not key:
        raise ConfigError(
            f"missing API key: set the environment variable {variable}, "
            'or set api_key_env = "" for a local server that needs no key'
        )
    return key
