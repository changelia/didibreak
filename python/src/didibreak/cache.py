"""Case cache: LLM-generated cases stored by what produced them (Detailed Design §9).

Files live in ``<output_dir>/cache/cases/<key>.json``. The key is a SHA-256
of the prompt version, provider, model, number of cases, both sources of the
function and the round number, so any change to them asks the LLM again.
Only accepted cases are stored; outcomes and labels are always recomputed.
Cached cases are checked again on load: a damaged or edited file can only
make didibreak ask the LLM again, never run code.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from didibreak.arguments import case_problem
from didibreak.functions import ChangedFunction
from didibreak.harness import Case

CACHE_FORMAT = 1
# didibreak's output folder ignores itself, so the user's own .gitignore is
# never edited.
GITIGNORE_TEXT = "# Created by didibreak: everything in this folder is generated.\n*\n"


@dataclass(frozen=True)
class CaseCache:
    """The case cache of one run.

    Attributes:
        output_dir: didibreak's output folder (``output_dir`` setting).
        provider: Resolved provider name.
        model: Model name.
        prompt_version: Version of the case generation prompt.
    """

    output_dir: Path
    provider: str
    model: str
    prompt_version: int

    @property
    def folder(self) -> Path:
        """Where the cache files are."""
        return self.output_dir / "cache" / "cases"

    def key(self, function: ChangedFunction, count: int, round_number: int = 0) -> str:
        """The cache key of one function's cases (hex SHA-256)."""
        material = {
            "format": CACHE_FORMAT,
            "prompt_version": self.prompt_version,
            "provider": self.provider,
            "model": self.model,
            "cases": count,
            "old_source": function.old_source,
            "new_source": function.new_source,
            "round": round_number,
        }
        text = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def load(
        self, function: ChangedFunction, count: int, round_number: int = 0
    ) -> tuple[Case, ...] | None:
        """Cached cases, or None when there are none or the file is unusable."""
        path = self.folder / f"{self.key(function, count, round_number)}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _cases_from_json(data)

    def store(
        self,
        function: ChangedFunction,
        count: int,
        cases: tuple[Case, ...],
        round_number: int = 0,
    ) -> bool:
        """Write cases to the cache; False when the folder cannot be written."""
        path = self.folder / f"{self.key(function, count, round_number)}.json"
        data = {
            "format": CACHE_FORMAT,
            "function": function.report_name,
            "cases": [
                {
                    "args": list(c.args),
                    "kwargs": dict(c.kwargs),
                    "rationale": c.rationale,
                }
                for c in cases
            ],
        }
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            ignore_output_dir(self.output_dir)
            _write_atomically(path, json.dumps(data, indent=2))
        except OSError:
            return False  # a cache that cannot be written only costs a new call
        return True


def ignore_output_dir(output_dir: Path) -> None:
    """Create the output folder's own ``.gitignore`` if it is missing.

    Raises:
        OSError: The file cannot be written.
    """
    ignore = output_dir / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE_TEXT, encoding="utf-8")


def _write_atomically(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _case_from_json(item: Any) -> Case | None:
    if not isinstance(item, dict):
        return None
    args, kwargs, rationale = (
        item.get("args"),
        item.get("kwargs"),
        item.get("rationale"),
    )
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        return None
    if case_problem(args, kwargs) is not None:
        return None
    return Case(
        tuple(args), dict(kwargs), rationale if isinstance(rationale, str) else ""
    )


def _cases_from_json(data: Any) -> tuple[Case, ...] | None:
    if not isinstance(data, dict) or data.get("format") != CACHE_FORMAT:
        return None
    items = data.get("cases")
    if not isinstance(items, list) or not items:
        return None
    cases = [_case_from_json(item) for item in items]
    if any(case is None for case in cases):
        return None
    return tuple(case for case in cases if case is not None)
