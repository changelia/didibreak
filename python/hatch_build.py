"""Hatch hooks that copy shared repository files into the Python project.

- The metadata hook copies the root LICENSE to python/LICENSE. It must run in
  the metadata phase: Hatch resolves ``license-files`` when it builds the
  metadata, before any build hook runs.
- The build hook copies spec/prompts/ into src/didibreak/prompts/ before each
  sdist, wheel and editable build.

When building from an extracted sdist there is no repository around the
project; the sdist already contains both copies, so the hooks leave them as
they are.
"""

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.metadata.plugin.interface import MetadataHookInterface


def _load_sync_prompts(project_root: Path) -> ModuleType:
    script = project_root / "scripts" / "sync_prompts.py"
    module_spec = importlib.util.spec_from_file_location("sync_prompts", script)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class LicenseCopyMetadataHook(MetadataHookInterface):
    """Copy the repository LICENSE so ``license-files`` can find it."""

    PLUGIN_NAME = "custom"

    def update(self, metadata: dict[str, Any]) -> None:
        """Copy the license; the metadata itself is left unchanged."""
        project_root = Path(self.root)
        repository_license = project_root.parent / "LICENSE"
        if repository_license.is_file():
            shutil.copyfile(repository_license, project_root / "LICENSE")


class PromptCopyBuildHook(BuildHookInterface):
    """Copy the shared prompt templates into src/didibreak/prompts/."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Copy the prompts before Hatch collects the files to build."""
        sync_prompts = _load_sync_prompts(Path(self.root))
        if sync_prompts.SPEC_PROMPTS.is_dir():
            sync_prompts.copy_prompts(
                sync_prompts.SPEC_PROMPTS, sync_prompts.PACKAGE_PROMPTS
            )
