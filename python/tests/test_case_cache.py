import json
from dataclasses import replace
from pathlib import Path

import pytest

from didibreak.cache import GITIGNORE_TEXT, CaseCache
from didibreak.functions import ChangedFunction
from didibreak.harness import Case

FUNCTION = ChangedFunction(
    file="app/m.py",
    module="app.m",
    qualname="f",
    kind="changed",
    function_type="function",
    is_async=False,
    line=1,
    old_source="def f(x):\n    return x\n",
    new_source="def f(x):\n    return x + 1\n",
)
CASES = (Case(("1",), {"strict": "True"}, "one"), Case(("'a'",), {}, "two"))


def cache(tmp_path: Path, **changes: object) -> CaseCache:
    base = CaseCache(tmp_path / ".didibreak", "openai", "gpt-6-luna", 1)
    return replace(base, **changes)  # type: ignore[arg-type]


def test_stored_cases_load_back(tmp_path: Path) -> None:
    store = cache(tmp_path)

    assert store.load(FUNCTION, 12) is None
    assert store.store(FUNCTION, 12, CASES)
    assert store.load(FUNCTION, 12) == CASES
    assert len(list(store.folder.glob("*.json"))) == 1


def test_key_is_stable_and_changes_with_every_input(tmp_path: Path) -> None:
    store = cache(tmp_path)
    key = store.key(FUNCTION, 12)

    assert key == cache(tmp_path).key(FUNCTION, 12)
    others = {
        cache(tmp_path, prompt_version=2).key(FUNCTION, 12),
        cache(tmp_path, provider="anthropic").key(FUNCTION, 12),
        cache(tmp_path, model="gpt-6.1-terra").key(FUNCTION, 12),
        store.key(FUNCTION, 13),
        store.key(replace(FUNCTION, old_source="def f(x):\n    return 0\n"), 12),
        store.key(replace(FUNCTION, new_source="def f(x):\n    return 2\n"), 12),
        store.key(FUNCTION, 12, round_number=1),
    }
    assert key not in others
    assert len(others) == 7


def test_output_folder_ignores_itself(tmp_path: Path) -> None:
    store = cache(tmp_path)

    store.store(FUNCTION, 12, CASES)

    assert (store.output_dir / ".gitignore").read_text() == GITIGNORE_TEXT


def test_an_existing_gitignore_is_kept(tmp_path: Path) -> None:
    store = cache(tmp_path)
    store.output_dir.mkdir(parents=True)
    (store.output_dir / ".gitignore").write_text("mine\n")

    store.store(FUNCTION, 12, CASES)

    assert (store.output_dir / ".gitignore").read_text() == "mine\n"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps({"format": 99, "cases": []}),
        json.dumps({"format": 1, "cases": []}),
        json.dumps({"format": 1, "cases": [{"args": "1", "kwargs": {}}]}),
        json.dumps(
            {"format": 1, "cases": [{"args": ["__import__('os')"], "kwargs": {}}]}
        ),
        json.dumps({"format": 1, "cases": [{"args": [], "kwargs": {"a b": "1"}}]}),
    ],
)
def test_damaged_or_edited_files_are_ignored(tmp_path: Path, content: str) -> None:
    store = cache(tmp_path)
    store.folder.mkdir(parents=True)
    (store.folder / f"{store.key(FUNCTION, 12)}.json").write_text(content)

    assert store.load(FUNCTION, 12) is None


def test_unwritable_cache_folder_is_not_an_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the folder should be")
    store = CaseCache(blocker, "openai", "gpt-6-luna", 1)

    assert store.store(FUNCTION, 12, CASES) is False
