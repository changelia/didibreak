"""Copy the shared prompt templates from spec/prompts/ into the Python package.

spec/prompts/ is the single source of the prompt templates; the package ships a
copy in src/didibreak/prompts/ so it never reads files outside its own folder at
runtime. The Hatch build hook (hatch_build.py) calls copy_prompts() before every
build. Run this script directly to refresh the copy, or with --check to fail
when the copy is out of date.

Uses only the standard library so it runs both in the build environment and in
the development environment.
"""

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent
SPEC_PROMPTS = PYTHON_ROOT.parent / "spec" / "prompts"
PACKAGE_PROMPTS = PYTHON_ROOT / "src" / "didibreak" / "prompts"

# Describes the spec folder for contributors; not a prompt template.
_NOT_COPIED = frozenset({"README.md"})


def _prompt_files(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    files: dict[str, bytes] = {}
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory).as_posix()
        if path.is_file() and name not in _NOT_COPIED:
            files[name] = path.read_bytes()
    return files


def find_differences(source: Path, copy: Path) -> list[str]:
    """List every way the copy differs from the source prompt folder.

    Args:
        source: The spec prompt folder.
        copy: The packaged copy.

    Returns:
        One human-readable line per difference; empty when the copy is current.
    """
    expected = _prompt_files(source)
    actual = _prompt_files(copy)
    differences: list[str] = []
    for name in sorted(expected.keys() | actual.keys()):
        if name not in actual:
            differences.append(f"missing from package copy: {name}")
        elif name not in expected:
            differences.append(f"not in spec/prompts: {name}")
        elif expected[name] != actual[name]:
            differences.append(f"content differs: {name}")
    return differences


def copy_prompts(source: Path, destination: Path) -> None:
    """Replace the destination folder with a fresh copy of the prompt files.

    Args:
        source: The spec prompt folder.
        destination: The packaged copy; deleted and recreated.
    """
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name, content in _prompt_files(source).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main(argv: Sequence[str] | None = None) -> int:
    """Copy or check the packaged prompt templates.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        0 on success, 1 when ``--check`` finds differences.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not copy; exit 1 if the package copy differs from spec/prompts",
    )
    arguments = parser.parse_args(argv)

    if not arguments.check:
        copy_prompts(SPEC_PROMPTS, PACKAGE_PROMPTS)
        print(f"Copied {SPEC_PROMPTS} to {PACKAGE_PROMPTS}")
        return 0

    differences = find_differences(SPEC_PROMPTS, PACKAGE_PROMPTS)
    if differences:
        for difference in differences:
            print(difference, file=sys.stderr)
        print(
            "Prompt copies are out of date. Refresh them with: "
            "uv run python scripts/sync_prompts.py",
            file=sys.stderr,
        )
        return 1
    print("Prompt copies match spec/prompts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
