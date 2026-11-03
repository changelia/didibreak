"""Tests for extracting function definitions from one version of a file."""

import pytest

from didibreak.functions import decode_source, definitions, module_name

SOURCE = """\
import os


def top(value):
    \"\"\"Docstring.\"\"\"
    return value


class Box:
    @staticmethod
    def make():
        return Box()

    @classmethod
    def build(cls):
        return cls()

    def size(self):
        def helper():
            return 1

        return helper()

    async def load(self):
        return None

    class Inner:
        def hidden(self):
            return 0
"""


def test_module_functions_and_class_methods_are_found() -> None:
    found = definitions(SOURCE)

    assert {name: (d.function_type, d.is_async) for name, d in found.items()} == {
        "top": ("function", False),
        "Box.make": ("staticmethod", False),
        "Box.build": ("classmethod", False),
        "Box.size": ("method", False),
        "Box.load": ("method", True),
    }


def test_definition_source_includes_decorators_and_is_dedented() -> None:
    make = definitions(SOURCE)["Box.make"]

    assert make.line == 10
    assert make.source == "@staticmethod\ndef make():\n    return Box()\n"


def test_fingerprint_ignores_formatting_comments_and_docstrings() -> None:
    plain = definitions("def f(a, b):\n    return a + b\n")["f"]
    styled = definitions(
        'def f( a,b ):\n    """Add."""\n    # sum\n    return (a +\n        b)\n'
    )["f"]
    different = definitions("def f(a, b):\n    return a - b\n")["f"]

    assert plain.fingerprint == styled.fingerprint
    assert plain.fingerprint != different.fingerprint


def test_redefined_name_keeps_the_last_definition() -> None:
    found = definitions("def f():\n    return 1\n\n\ndef f():\n    return 2\n")

    assert found["f"].source == "def f():\n    return 2\n"


def test_syntax_error_is_raised() -> None:
    with pytest.raises(SyntaxError):
        definitions("def broken(:\n")


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("app/utils/phone.py", "app.utils.phone"),
        ("src/pkg/core.py", "pkg.core"),
        ("pkg/__init__.py", "pkg"),
        ("script.py", "script"),
    ],
)
def test_module_names_follow_the_import_root(path: str, module: str) -> None:
    assert module_name(path) == module


def test_source_with_coding_declaration_is_decoded() -> None:
    content = "# -*- coding: latin-1 -*-\nNAME = 'café'\n".encode("latin-1")

    assert "café" in decode_source(content)
