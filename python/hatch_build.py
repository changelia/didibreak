"""Hatch build hook that copies spec/prompts/ into the package before each build.

Runs for sdist, wheel and editable builds. When building from an extracted
sdist there is no spec/ folder next to the project; the sdist already contains
the copies, so the hook does nothing.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _load_sync_prompts(project_root: Path) -> ModuleType:
    script = project_root / "scripts" / "sync_prompts.py"
    module_spec = importlib.util.spec_from_file_location("sync_prompts", script)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class PromptCopyBuildHook(BuildHookInterface):
    """Copy the shared prompt templates into src/didibreak/prompts/."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Copy the prompts before Hatch collects the files to build."""
        project_root = Path(self.root)
        sync_prompts = _load_sync_prompts(project_root)
        if not sync_prompts.SPEC_PROMPTS.is_dir():
            return
        sync_prompts.copy_prompts(
            sync_prompts.SPEC_PROMPTS, sync_prompts.PACKAGE_PROMPTS
        )
