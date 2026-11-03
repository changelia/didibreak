"""Import roots found from pyproject.toml files in a real repository layout."""

from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.cli import load_source_files
from didibreak.functions import detect_changed_functions
from didibreak.gitdiff import (
    ChangedFile,
    ChangedFiles,
    GitError,
    changed_python_files,
    repository_root,
    resolve_base,
)

FUNCTION = "def run():\n    return {}\n"


def _modules(repository: GitRepository) -> dict[str, str]:
    base = resolve_base(repository.path, "HEAD")
    files = changed_python_files(repository.path, base)
    sources = load_source_files(repository.path, base, files)
    detection = detect_changed_functions(sources, max_functions=50)
    return {function.file: function.module for function in detection.functions}


def test_monorepo_layout_like_this_repository(git_repository: GitRepository) -> None:
    git_repository.write("python/pyproject.toml", "[project]\nname = 'pkg'\n")
    paths = ["python/src/pkg/cli.py", "python/scripts/tool.py", "docs_helper.py"]
    for path in paths:
        git_repository.write(path, FUNCTION.format(1))
    git_repository.commit()
    for path in paths:
        git_repository.write(path, FUNCTION.format(2))

    assert _modules(git_repository) == {
        "docs_helper.py": "docs_helper",
        "python/scripts/tool.py": "scripts.tool",
        "python/src/pkg/cli.py": "pkg.cli",
    }


def test_nearest_pyproject_wins_and_root_src_layout_still_works(
    git_repository: GitRepository,
) -> None:
    git_repository.write("pyproject.toml", "[project]\nname = 'root'\n")
    git_repository.write("services/api/pyproject.toml", "[project]\nname = 'api'\n")
    paths = ["src/core/model.py", "services/api/src/api/main.py"]
    for path in paths:
        git_repository.write(path, FUNCTION.format(1))
    git_repository.commit()
    for path in paths:
        git_repository.write(path, FUNCTION.format(2))

    assert _modules(git_repository) == {
        "services/api/src/api/main.py": "api.main",
        "src/core/model.py": "core.model",
    }


def test_this_repository_maps_its_package_to_didibreak() -> None:
    here = Path(__file__).resolve()
    try:
        root = repository_root(here.parent)
        base = resolve_base(root, "HEAD")
    except GitError:
        pytest.skip("needs the didibreak git checkout")
    path = "python/src/didibreak/cli.py"
    if not (root / path).is_file():
        pytest.skip("needs the didibreak git checkout")
    files = ChangedFiles(
        changed=(ChangedFile(path, path, "modified"),), deleted=(), excluded=()
    )

    [source] = load_source_files(root, base, files)

    assert source.import_root == "python/src"
