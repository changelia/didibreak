"""The README "Change the model" recipes load with the config code (task 27)."""

import re
from pathlib import Path

import pytest

from didibreak.config import ConfigError, build_config, read_config_table
from didibreak.llm import client_settings
from didibreak.llm.pricing import LOCAL, prices_from_config, required_price

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)
ENVIRONMENT = {"OPENAI_API_KEY": "placeholder", "OPENROUTER_API_KEY": "placeholder"}


def recipes(page: Path) -> list[str]:
    """The TOML blocks of the page's "Change the model" section."""
    text = page.read_text(encoding="utf-8")
    section = re.search(r"## Change the model\n(.*?)\n## ", text + "\n## ", re.DOTALL)
    assert section, f"{page.name} has no Change the model section"
    return re.findall(r"```toml\n(.*?)```", section.group(1), re.DOTALL)


def price_source(recipe: str, tmp_path: Path) -> str:
    """Load a recipe like ``check`` does and return where its price comes from."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(recipe, encoding="utf-8")
    config = build_config(read_config_table(pyproject), {})
    settings = client_settings(config, ENVIRONMENT)
    price = required_price(
        settings.model, settings.base_url, prices_from_config(config.prices)
    )
    return price.source


def test_both_readmes_show_the_same_three_recipes() -> None:
    root = recipes(ROOT / "README.md")

    assert len(root) == 3
    assert recipes(ROOT / "python" / "README.md") == root


@pytest.mark.parametrize("index", range(3))
def test_recipe_loads_and_has_a_price(index: int, tmp_path: Path) -> None:
    recipe = recipes(ROOT / "README.md")[index]

    source = price_source(recipe, tmp_path)

    assert source == (LOCAL if "localhost" in recipe else "prices setting")


def test_a_paid_model_without_a_price_stops(tmp_path: Path) -> None:
    recipe = recipes(ROOT / "README.md")[0]
    without_price = recipe.split("[tool.didibreak.prices]")[0]

    with pytest.raises(ConfigError, match="max_cost cannot be enforced"):
        price_source(without_price, tmp_path)
