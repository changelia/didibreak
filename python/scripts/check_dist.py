"""Check the contents of the built wheel and sdist in a dist/ folder.

The packages must contain only the Python package (no spec/, docs/ or JS
files, except the copied prompts) and must ship the license. CI runs this
after ``uv build``; it uses only the standard library.
"""

import argparse
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

_FORBIDDEN_SDIST_FOLDERS = ("spec/", "docs/", "js/")


def check_wheel(wheel: Path) -> list[str]:
    """List problems in a wheel; empty when it is correct.

    Args:
        wheel: Path to the ``.whl`` file.

    Returns:
        One human-readable line per problem.
    """
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    problems = [
        f"unexpected file in wheel: {name}"
        for name in names
        if not name.startswith("didibreak/") and ".dist-info/" not in name
    ]
    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        problems.append("wheel has no .dist-info/licenses/LICENSE")
    return problems


def check_sdist(sdist: Path) -> list[str]:
    """List problems in an sdist; empty when it is correct.

    Args:
        sdist: Path to the ``.tar.gz`` file.

    Returns:
        One human-readable line per problem.
    """
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        pkg_info = next((m for m in members if m.name.endswith("/PKG-INFO")), None)
        metadata = ""
        if pkg_info is not None:
            extracted = archive.extractfile(pkg_info)
            if extracted is not None:
                metadata = extracted.read().decode("utf-8")
    # Member names start with the "<name>-<version>/" folder.
    relative_names = [m.name.partition("/")[2] for m in members]
    problems = [
        f"unexpected file in sdist: {name}"
        for name in relative_names
        if name.startswith(_FORBIDDEN_SDIST_FOLDERS)
    ]
    if "LICENSE" not in relative_names:
        problems.append("sdist has no LICENSE")
    if "License-File: LICENSE" not in metadata.splitlines():
        problems.append("sdist PKG-INFO has no 'License-File: LICENSE'")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the single wheel and sdist in the given folder.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        0 when both archives are correct, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist_dir", type=Path, help="folder written by uv build")
    arguments = parser.parse_args(argv)

    wheels = sorted(arguments.dist_dir.glob("*.whl"))
    sdists = sorted(arguments.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(
            f"Expected one wheel and one sdist in {arguments.dist_dir}, "
            f"found {len(wheels)} and {len(sdists)}.",
            file=sys.stderr,
        )
        return 1

    problems = check_wheel(wheels[0]) + check_sdist(sdists[0])
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"OK: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
