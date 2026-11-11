"""The README "Change the model" recipes load with the config code (tasks 27, 34)."""

import re
from pathlib import Path

import pytest

from didibreak.config import build_config, read_config_table
from didibreak.llm import client_settings
from didibreak.llm.pricing import LOCAL, prices_from_config, run_price

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(), reason="needs the full repository checkout"
)
ENVIRONMENT = {"OPENAI_API_KEY": "placeholder", "OPENROUTER_API_KEY": "placeholder"}
PRICES = "[tool.didibreak.prices]"


def blocks(page: Path) -> list[str]:
    """The TOML blocks of the page's "Change the model" section."""
    text = page.read_text(encoding="utf-8")
    section = re.search(r"## Change the model\n(.*?)\n## ", text + "\n## ", re.DOTALL)
    assert section, f"{page.name} has no Change the model section"
    return re.findall(r"```toml\n(.*?)```", section.group(1), re.DOTALL)


def recipes() -> list[str]:
    """The model setups, without the prices block."""
    return [block for block in blocks(ROOT / "README.md") if PRICES not in block]


def prices_block() -> str:
    (block,) = [block for block in blocks(ROOT / "README.md") if PRICES in block]
    return block


def price_source(recipe: str, tmp_path: Path) -> str | None:
    """Load a recipe like ``check`` does and return where its price comes from."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(recipe, encoding="utf-8")
    config = build_config(read_config_table(pyproject), {})
    settings = client_settings(config, ENVIRONMENT)
    price = run_price(
        settings.model, settings.base_url, prices_from_config(config.prices)
    )
    return None if price is None else price.source


def test_both_readmes_show_the_same_recipes() -> None:
    root = blocks(ROOT / "README.md")

    assert len(recipes()) == 3
    assert blocks(ROOT / "python" / "README.md") == root


@pytest.mark.parametrize(
    ("index", "provider"), [(0, None), (1, "openrouter"), (2, "ollama")]
)
def test_recipes_use_the_presets(index: int, provider: str | None) -> None:
    recipe = recipes()[index]

    assert (f'provider = "{provider}"' in recipe) is (provider is not None)
    assert "base_url" not in recipe
    assert "api_key_env" not in recipe


@pytest.mark.parametrize("index", [0, 1])
def test_paid_recipes_run_without_a_price_and_get_one_from_the_block(
    index: int, tmp_path: Path
) -> None:
    recipe = recipes()[index]

    assert price_source(recipe, tmp_path) is None
    assert price_source(recipe + "\n" + prices_block(), tmp_path) == "prices setting"


def test_local_recipe_costs_nothing(tmp_path: Path) -> None:
    assert price_source(recipes()[2], tmp_path) == LOCAL
