"""Tests for the built-package content checks in scripts/check_dist.py."""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_dist.py"
DIST_INFO = "didibreak-1.0.dist-info"
SDIST_ROOT = "didibreak-1.0"
GOOD_PKG_INFO = "Metadata-Version: 2.4\nName: didibreak\nLicense-File: LICENSE\n"


def _load_script() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("check_dist", SCRIPT)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


check_dist = _load_script()


def _write_wheel(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")
    return path


def _write_sdist(path: Path, files: dict[str, str]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8")
            member = tarfile.TarInfo(f"{SDIST_ROOT}/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


@pytest.fixture
def good_wheel(tmp_path: Path) -> Path:
    return _write_wheel(
        tmp_path / "didibreak-1.0-py3-none-any.whl",
        [
            "didibreak/__init__.py",
            "didibreak/prompts/cases.txt",
            f"{DIST_INFO}/METADATA",
            f"{DIST_INFO}/licenses/LICENSE",
        ],
    )


@pytest.fixture
def good_sdist(tmp_path: Path) -> Path:
    return _write_sdist(
        tmp_path / "didibreak-1.0.tar.gz",
        {
            "PKG-INFO": GOOD_PKG_INFO,
            "LICENSE": "MIT",
            "src/didibreak/__init__.py": "",
        },
    )


def test_correct_wheel_and_sdist_pass(good_wheel: Path, good_sdist: Path) -> None:
    assert check_dist.check_wheel(good_wheel) == []
    assert check_dist.check_sdist(good_sdist) == []
    assert check_dist.main([str(good_wheel.parent)]) == 0


def test_wheel_with_foreign_files_and_no_license_fails(tmp_path: Path) -> None:
    wheel = _write_wheel(
        tmp_path / "bad.whl", ["didibreak/__init__.py", "spec/report.schema.json"]
    )

    assert check_dist.check_wheel(wheel) == [
        "unexpected file in wheel: spec/report.schema.json",
        "wheel has no .dist-info/licenses/LICENSE",
    ]


def test_sdist_with_docs_and_no_license_fails(tmp_path: Path) -> None:
    sdist = _write_sdist(
        tmp_path / "bad.tar.gz",
        {"PKG-INFO": "Name: didibreak\n", "docs/index.md": ""},
    )

    assert check_dist.check_sdist(sdist) == [
        "unexpected file in sdist: docs/index.md",
        "sdist has no LICENSE",
        "sdist PKG-INFO has no 'License-File: LICENSE'",
    ]


def test_folder_without_exactly_one_of_each_archive_fails(
    good_wheel: Path, tmp_path: Path
) -> None:
    assert check_dist.main([str(tmp_path)]) == 1
