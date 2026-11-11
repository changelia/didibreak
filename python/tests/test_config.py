"""Tests for configuration defaults, validation, file loading and precedence."""

from pathlib import Path

import pytest

from didibreak.cli import build_parser
from didibreak.config import (
    CONFIG_KEYS,
    Config,
    ConfigError,
    api_key_variable,
    build_config,
    find_pyproject,
    read_api_key,
    read_config_table,
    validate,
)


def test_defaults_match_detailed_design() -> None:
    config = Config()

    assert (config.base, config.format, config.fail_on) == ("HEAD", "text", "unclear")
    assert (config.max_functions, config.cases, config.refine_rounds) == (10, 12, 1)
    assert (config.max_cost, config.timeout) == (0.50, 10.0)
    assert config.max_tokens == 200_000
    assert config.output_dir == ".didibreak"
    assert config.provider is None
    assert config.model is None
    assert config.temperature is None


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("cases", 0, "cases must be >= 1 and <= 50; got 0"),
        ("cases", 51, "cases must be >= 1 and <= 50; got 51"),
        ("refine_rounds", 4, "refine_rounds must be >= 0 and <= 3; got 4"),
        ("max_functions", True, "max_functions must be an integer, got True"),
        ("timeout", 0, "timeout must be greater than 0; got 0"),
        ("max_cost", "cheap", "max_cost must be a number, got 'cheap'"),
        ("max_tokens", 0, "max_tokens must be >= 1; got 0"),
        ("max_tokens", 1.5, "max_tokens must be an integer, got 1.5"),
        ("format", "xml", "format must be one of text, json; got 'xml'"),
        ("fail_on", "all", "fail_on must be one of unclear, unexpected"),
        ("provider", "gemini", "provider must be one of openai, anthropic"),
        ("base_url", "localhost:11434", "base_url must be an http(s) URL"),
        ("exclude", "tests/*", "exclude must be a list of glob patterns"),
        ("no_cache", "yes", "no_cache must be true or false, got 'yes'"),
        ("base", "  ", "base must not be empty"),
        ("temperature", 2.5, "temperature must be >= 0 and <= 2; got 2.5"),
        ("temperature", "low", "temperature must be a number, got 'low'"),
    ],
)
def test_invalid_values_are_rejected_with_the_rule(
    key: str, value: object, message: str
) -> None:
    with pytest.raises(ConfigError) as info:
        validate(key, value)

    assert message in str(info.value)


def test_temperature_is_read_from_the_config_file(tmp_path: Path) -> None:
    path = _write_pyproject(tmp_path, "[tool.didibreak]\ntemperature = 0\n")

    assert read_config_table(path) == {"temperature": 0.0}


def test_temperature_has_no_cli_flag() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["check", "--temperature", "0"])


def test_every_config_field_has_a_validator() -> None:
    assert set(CONFIG_KEYS) == set(Config.__dataclass_fields__)


def _write_pyproject(directory: Path, body: str) -> Path:
    path = directory / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_overrides_file_and_file_overrides_defaults() -> None:
    config = build_config(
        file_values={"cases": 20, "max_functions": 3},
        cli_values={"cases": 5},
    )

    assert config.cases == 5
    assert config.max_functions == 3
    assert config.refine_rounds == 1


def test_config_table_is_read_and_validated(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        '[tool.didibreak]\nprovider = "anthropic"\nmax_cost = 2\n'
        'exclude = ["scripts/*"]\nno_cache = true\n',
    )

    values = read_config_table(pyproject)

    assert values == {
        "provider": "anthropic",
        "max_cost": 2.0,
        "exclude": ("scripts/*",),
        "no_cache": True,
    }


def test_pyproject_without_table_gives_no_values(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, '[project]\nname = "app"\n')

    assert read_config_table(pyproject) == {}


def test_unknown_key_names_the_key_and_the_file(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "[tool.didibreak]\ncases_per_function = 3\n")

    with pytest.raises(ConfigError, match="unknown key 'cases_per_function'") as info:
        read_config_table(pyproject)

    assert str(pyproject) in str(info.value)
    assert "allowed keys: base, intent" in str(info.value)


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "[tool.didibreak\n")

    with pytest.raises(ConfigError, match="is not valid TOML"):
        read_config_table(pyproject)


def test_nearest_pyproject_is_found_up_to_the_stop_directory(tmp_path: Path) -> None:
    root_file = _write_pyproject(tmp_path, "")
    package = tmp_path / "python" / "src"
    package.mkdir(parents=True)
    package_file = _write_pyproject(tmp_path / "python", "")

    assert find_pyproject(package, stop=tmp_path) == package_file
    assert find_pyproject(tmp_path, stop=tmp_path) == root_file


def test_missing_pyproject_gives_none(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    (repository / "app").mkdir(parents=True)
    _write_pyproject(tmp_path, "")  # outside the repository: must not be used

    assert find_pyproject(repository / "app", stop=repository) is None


@pytest.mark.parametrize(
    ("config", "variable"),
    [
        (Config(provider="openai"), "OPENAI_API_KEY"),
        (Config(provider="anthropic"), "ANTHROPIC_API_KEY"),
        (Config(provider="openai", api_key_env="OPENROUTER_KEY"), "OPENROUTER_KEY"),
        (Config(provider="openai", api_key_env=""), None),
        (Config(), None),
    ],
)
def test_api_key_variable_follows_provider_and_override(
    config: Config, variable: str | None
) -> None:
    assert api_key_variable(config) == variable


def test_api_key_is_read_from_the_environment() -> None:
    config = Config(provider="anthropic")

    assert read_api_key(config, {"ANTHROPIC_API_KEY": "secret"}) == "secret"


def test_missing_api_key_names_the_variable() -> None:
    with pytest.raises(
        ConfigError, match="set the environment variable OPENAI_API_KEY"
    ):
        read_api_key(Config(provider="openai"), {"OPENAI_API_KEY": ""})


FILE_WITH_URL = {
    "model": "m",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
}


def test_cli_preset_drops_base_url_and_key_variable_from_the_file() -> None:
    config = build_config(FILE_WITH_URL, {"provider": "ollama"})

    assert (config.provider, config.model) == ("ollama", "m")
    assert (config.base_url, config.api_key_env) == (None, None)


def test_cli_values_still_override_a_cli_preset() -> None:
    cli = {"provider": "ollama", "base_url": "http://127.0.0.1:1/v1"}

    config = build_config(FILE_WITH_URL, cli)

    assert (config.base_url, config.api_key_env) == ("http://127.0.0.1:1/v1", None)


@pytest.mark.parametrize(
    ("file_provider", "cli"),
    [
        ("ollama", {"provider": "ollama"}),  # the file names the same preset
        ("ollama", {}),  # preset and URL at the same level
        (None, {"provider": "openai"}),  # not a preset
    ],
)
def test_file_url_is_kept_unless_a_higher_level_chooses_another_preset(
    file_provider: str | None, cli: dict[str, object]
) -> None:
    file_values = dict(FILE_WITH_URL)
    if file_provider:
        file_values["provider"] = file_provider

    config = build_config(file_values, cli)

    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.api_key_env == "OPENROUTER_API_KEY"
