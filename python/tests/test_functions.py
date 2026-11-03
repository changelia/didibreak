"""Tests for changed-function detection over two versions of each file."""

import pytest

from didibreak.functions import (
    ChangedFunction,
    SkippedFile,
    SourceFile,
    detect_changed_functions,
)

BASE = b"""\
def normalize(text):
    return text.strip()


def unchanged(value):
    return value * 2


class Phone:
    @staticmethod
    def clean(number):
        return number.replace(" ", "")

    @classmethod
    def parse(cls, raw):
        return cls()

    def format(self):
        return "x"

    async def fetch(self):
        return 1


def removed_later():
    return 0
"""


def _detect(
    old: bytes | None, new: bytes | None, path: str = "app/phone.py", limit: int = 10
) -> list[ChangedFunction]:
    detection = detect_changed_functions([SourceFile(path, old, new)], limit)
    return list(detection.functions)


def _names(functions: list[ChangedFunction]) -> list[tuple[str, str]]:
    return [(function.qualname, function.kind) for function in functions]


def test_unchanged_file_has_no_changed_functions() -> None:
    assert _detect(BASE, BASE) == []


def test_formatting_only_change_is_not_a_change() -> None:
    reformatted = BASE.replace(
        b"    return text.strip()\n",
        b"    # a new comment\n    return (\n        text.strip()\n    )\n",
    ).replace(b"def unchanged(value):", b"def unchanged( value ):")

    assert _detect(BASE, reformatted) == []


def test_docstring_only_change_is_not_a_change() -> None:
    documented = BASE.replace(
        b"def normalize(text):\n", b'def normalize(text):\n    """Strip text."""\n'
    )

    assert _detect(BASE, documented) == []


def test_body_change_is_changed_and_keeps_both_sources() -> None:
    changed = BASE.replace(b"return text.strip()", b"return text.strip().lower()")

    [function] = _detect(BASE, changed)

    assert (function.qualname, function.kind) == ("normalize", "changed")
    assert function.old_source == "def normalize(text):\n    return text.strip()\n"
    assert function.new_source == (
        "def normalize(text):\n    return text.strip().lower()\n"
    )
    assert function.report_name == "app/phone.py::normalize"


def test_method_qualified_names_types_and_dedented_source() -> None:
    changed = (
        BASE.replace(b'.replace(" ", "")', b'.replace("-", "")')
        .replace(b"return cls()", b"return cls(raw)")
        .replace(b'return "x"', b'return "y"')
        .replace(b"return 1", b"return 2")
    )

    detection = detect_changed_functions(
        [SourceFile("app/phone.py", BASE, changed)], max_functions=10
    )
    functions = list(detection.functions)

    assert [(f.module, f.qualname, f.function_type, f.is_async) for f in functions] == [
        ("app.phone", "Phone.clean", "staticmethod", False),
        ("app.phone", "Phone.parse", "classmethod", False),
    ]
    assert [(f.qualname, f.skip_reason) for f in detection.skipped] == [
        ("Phone.format", "instance method"),
        ("Phone.fetch", "async function"),
    ]
    assert functions[0].new_source.startswith("@staticmethod\ndef clean(number):")
    assert functions[0].line == 10


def test_untestable_functions_do_not_count_toward_the_limit() -> None:
    source = (
        b"def gen():\n    yield 1\n\n\n"
        b"def first():\n    return 1\n\n\n"
        b"def second():\n    return 2\n"
    )

    detection = detect_changed_functions(
        [SourceFile("app.py", None, source)], max_functions=1
    )

    assert [f.qualname for f in detection.functions] == ["first"]
    assert [(f.qualname, f.skip_reason) for f in detection.skipped] == [
        ("gen", "generator")
    ]
    assert [(f.qualname, f.skip_reason) for f in detection.limited] == [
        ("second", "limit")
    ]


def test_new_file_makes_every_function_new() -> None:
    functions = _detect(None, BASE)

    assert _names(functions)[:2] == [("normalize", "new"), ("unchanged", "new")]
    assert all(function.old_source is None for function in functions)


def test_added_function_is_new() -> None:
    extended = BASE + b"\n\ndef added():\n    return 1\n"

    assert _names(_detect(BASE, extended)) == [("added", "new")]


def test_nested_functions_and_classes_are_not_candidates() -> None:
    old = b"def outer():\n    def inner():\n        return 1\n    return inner\n"
    new = old.replace(b"return 1", b"return 2")
    old_class = b"class A:\n    class B:\n        def m(self):\n            return 1\n"

    assert _names(_detect(old, new)) == [("outer", "changed")]
    assert _detect(old_class, old_class.replace(b"return 1", b"return 2")) == []


def test_removed_and_deleted_functions_are_listed() -> None:
    without = BASE.replace(b"\n\ndef removed_later():\n    return 0\n", b"")

    detection = detect_changed_functions(
        [
            SourceFile("app/phone.py", BASE, without),
            SourceFile("app/gone.py", b"def old():\n    return 1\n", None),
        ],
        max_functions=10,
    )

    assert detection.functions == ()
    assert detection.removed == ("app/gone.py::old", "app/phone.py::removed_later")


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (BASE, b"def broken(:\n", "syntax error in the current version, line 1"),
        (b"def broken(:\n", BASE, "syntax error in the base version, line 1"),
        (BASE, b"\xff\xfe not utf-8", "cannot read the current version"),
        (BASE, b"x = 1\0\n", "the current version"),
    ],
)
def test_unparsable_file_is_skipped_with_a_reason(
    old: bytes, new: bytes, reason: str
) -> None:
    detection = detect_changed_functions(
        [SourceFile("bad.py", old, new), SourceFile("good.py", None, BASE)], 10
    )

    [skipped] = detection.skipped_files
    assert isinstance(skipped, SkippedFile)
    assert skipped.path == "bad.py"
    assert reason in skipped.reason
    assert "line None" not in skipped.reason
    assert {function.file for function in detection.functions} == {"good.py"}


def test_max_functions_keeps_the_first_by_file_then_line() -> None:
    two = b"def first():\n    return 1\n\n\ndef second():\n    return 2\n"
    files = [
        SourceFile("b/module.py", None, two),
        SourceFile("a/module.py", None, two),
    ]

    detection = detect_changed_functions(files, max_functions=3)
    reversed_detection = detect_changed_functions(files[::-1], max_functions=3)

    assert [f.report_name for f in detection.functions] == [
        "a/module.py::first",
        "a/module.py::second",
        "b/module.py::first",
    ]
    assert [(f.report_name, f.skip_reason) for f in detection.limited] == [
        ("b/module.py::second", "limit")
    ]
    assert reversed_detection == detection
