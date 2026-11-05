import textwrap

from didibreak.functions import SourceFile, detect_changed_functions
from didibreak.testability import explicitly_raised, module_context


def raised(source: str, qualname: str = "f", module: str = "app.m") -> set[str]:
    context = module_context(textwrap.dedent(source))
    return set(explicitly_raised(qualname, context, module))


def test_builtin_exceptions_raised_in_the_body() -> None:
    source = """\
        def f(x):
            if not x:
                raise ValueError("empty")
            if x < 0:
                raise TypeError
            return x
        """
    assert raised(source) == {"builtins.ValueError", "builtins.TypeError"}


def test_classes_of_the_same_module_get_the_module_name() -> None:
    source = """\
        class InvalidAge(ValueError):
            pass

        class Errors:
            class Bad(Exception):
                pass

        def f(x):
            if x:
                raise InvalidAge(x)
            raise Errors.Bad()
        """
    assert raised(source, module="app.ages") == {
        "app.ages.InvalidAge",
        "app.ages.Errors.Bad",
    }


def test_imported_exceptions_are_resolved_through_aliases() -> None:
    source = """\
        import app.errors as errors
        from app.errors import Missing as Gone

        def f(x):
            if x:
                raise errors.Invalid(x)
            raise Gone from None
        """
    assert raised(source) == {"app.errors.Invalid", "app.errors.Missing"}


def test_raises_in_same_module_callees_count_transitively() -> None:
    source = """\
        def f(x):
            return _check(x)

        def _check(x):
            return _range(x)

        def _range(x):
            if x > 100:
                raise OverflowError
            return x

        def unrelated():
            raise KeyError
        """
    assert raised(source) == {"builtins.OverflowError"}


def test_bare_raise_and_implicit_exceptions_are_not_explicit() -> None:
    source = """\
        def f(name):
            try:
                first, last = name.split()
            except ValueError:
                raise
            return first[0] + last[0]
        """
    assert raised(source) == set()


def test_detection_records_raised_types_of_the_current_version() -> None:
    old = b"def f(x):\n    return x\n"
    new = b"def f(x):\n    if x is None:\n        raise ValueError\n    return x\n"

    detection = detect_changed_functions(
        [SourceFile("app/m.py", old, new)], max_functions=10
    )

    assert detection.functions[0].raised_types == {"builtins.ValueError"}
