"""Analysis pipeline: run the cases of each changed function on both versions.

Wires the base worktree, a temporary copy of the working tree, the harness
and the comparison rules together for ``didibreak check``. Cases come from
the hidden developer option ``--cases-file`` until LLM case generation
exists (task 14).
"""

import ast
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from didibreak.config import ConfigError
from didibreak.harness import Case


def _case(item: object, number: int) -> tuple[str, Case]:
    where = f"case {number}"
    if not isinstance(item, dict):
        raise ValueError(f"{where}: expected an object")
    function = item.get("function")
    if not isinstance(function, str) or "::" not in function:
        raise ValueError(f'{where}: "function" must be "path/to/file.py::name"')
    args = item.get("args", [])
    kwargs = item.get("kwargs", {})
    rationale = item.get("rationale", "")
    if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        raise ValueError(f'{where}: "args" must be a list of strings')
    if not (
        isinstance(kwargs, dict) and all(isinstance(v, str) for v in kwargs.values())
    ):
        raise ValueError(f'{where}: "kwargs" must map names to strings')
    if not isinstance(rationale, str):
        raise ValueError(f'{where}: "rationale" must be a string')
    for text in (*args, *kwargs.values()):
        try:
            ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            raise ValueError(f"{where}: not a Python literal: {text!r}") from None
    return function, Case(tuple(args), dict(kwargs), rationale)


def load_cases_file(path: Path) -> Mapping[str, tuple[Case, ...]]:
    """Read cases from a JSON file (hidden developer option ``--cases-file``).

    The format is the case-generation schema (Detailed Design section 5.1)
    with a ``function`` key per case::

        {"cases": [{"function": "app/phone.py::normalize_phone",
                    "args": ["'995 555 12 34 56'"], "kwargs": {},
                    "rationale": "country code without plus"}]}

    Args:
        path: The JSON file.

    Returns:
        Cases by report name, in file order.

    Raises:
        ConfigError: If the file cannot be read or is not valid; the message
            names the file and the case.
    """
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"cases file {path}: cannot read it: {error}") from None
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ConfigError(f'cases file {path}: expected {{"cases": [...]}}')
    cases: dict[str, list[Case]] = {}
    for number, item in enumerate(data["cases"], start=1):
        try:
            function, case = _case(item, number)
        except ValueError as error:
            raise ConfigError(f"cases file {path}: {error}") from None
        cases.setdefault(function, []).append(case)
    return {function: tuple(items) for function, items in cases.items()}
