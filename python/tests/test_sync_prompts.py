"""Tests for copying spec/prompts/ into the package and detecting stale copies."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_prompts.py"


def _load_script() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("sync_prompts", SCRIPT)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


sync_prompts = _load_script()


@pytest.fixture
def spec_dir(tmp_path: Path) -> Path:
    spec = tmp_path / "spec"
    (spec / "nested").mkdir(parents=True)
    (spec / "README.md").write_text("folder description")
    (spec / "cases.txt").write_text("prompt_version: 1\n")
    (spec / "nested" / "intent.txt").write_text("prompt_version: 1\n")
    return spec


def test_copy_includes_templates_and_skips_readme(
    spec_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"

    sync_prompts.copy_prompts(spec_dir, copy)

    copied = sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*.*"))
    assert copied == ["cases.txt", "nested/intent.txt"]
    assert sync_prompts.find_differences(spec_dir, copy) == []


def test_copy_removes_files_no_longer_in_spec(spec_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "old.txt").write_text("removed from spec")

    sync_prompts.copy_prompts(spec_dir, copy)

    assert not (copy / "old.txt").exists()


def test_differences_report_missing_extra_and_changed_files(
    spec_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    sync_prompts.copy_prompts(spec_dir, copy)
    (copy / "cases.txt").write_text("edited copy")
    (copy / "nested" / "intent.txt").unlink()
    (copy / "extra.txt").write_text("only in copy")

    differences = sync_prompts.find_differences(spec_dir, copy)

    assert differences == [
        "content differs: cases.txt",
        "not in spec/prompts: extra.txt",
        "missing from package copy: nested/intent.txt",
    ]


def test_missing_copy_folder_is_reported(spec_dir: Path, tmp_path: Path) -> None:
    differences = sync_prompts.find_differences(spec_dir, tmp_path / "absent")

    assert differences == [
        "missing from package copy: cases.txt",
        "missing from package copy: nested/intent.txt",
    ]


@pytest.mark.skipif(
    not sync_prompts.SPEC_PROMPTS.is_dir(),
    reason=(
        f"{sync_prompts.SPEC_PROMPTS} not found: this test needs the full "
        "repository checkout (e.g. it cannot run from an unpacked sdist)"
    ),
)
def test_repository_package_copy_matches_spec() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
