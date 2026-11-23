"""Case arguments: Python literal source text, checked and printed one way.

Cases reach the harness from LLM replies, the case cache, the hidden
``--cases-file`` option and the harness's own check. All of them use
case_problem(), so "the LLM supplies data, never code" (Spec, Safety) is
the same rule everywhere (audit 35a, finding 11). An accepted case is stored
in its normal form (normalized_case), and all reports print a call with
format_call(). Standard library only: no didibreak imports, so any module
can use it without an import cycle.
"""

import ast
import keyword
from collections.abc import Mapping, Sequence
from typing import Any

# Longer arguments are rejected: they bloat prompts, reports and the
# harness request without making a case more useful.
MAX_ARGUMENT_LENGTH = 2000


def normal_form(text: str) -> str:
    """One spelling of a literal: no comment, standard spacing and quotes.

    ``ast.literal_eval`` ignores a comment and extra white space, so
    ``2  # the smallest even prime`` is a valid argument; pasted into a
    call it swallowed the rest of the line and broke the generated test
    file (pre-launch review, finding 12). The normal form is what
    ``ast.unparse`` prints for the parsed expression, e.g. ``2``.

    Args:
        text: Argument source text that ``ast.literal_eval`` accepts.

    Returns:
        Source text with the same value that is safe inside a call.

    Raises:
        SyntaxError, ValueError, RecursionError, MemoryError: The text is
            not an expression.
    """
    # ast.literal_eval also skips leading spaces and tabs.
    return ast.unparse(ast.parse(text.lstrip(" \t"), mode="eval"))


def literal_problem(text: object) -> str | None:
    """Why ``text`` is not an acceptable argument, or None when it is.

    Args:
        text: Proposed argument source text.

    Returns:
        A short reason: not a string, too long (as written or in its normal
        form), or not a Python literal (``ast.literal_eval`` fails); None
        for a valid argument.
    """
    if not isinstance(text, str):
        return f"not a string: {text!r}"
    if len(text) > MAX_ARGUMENT_LENGTH:
        return f"longer than {MAX_ARGUMENT_LENGTH} characters"
    try:
        ast.literal_eval(text)
        normal = normal_form(text)
        ast.literal_eval(normal)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return f"not a Python literal: {text!r}"
    if len(normal) > MAX_ARGUMENT_LENGTH:
        return f"longer than {MAX_ARGUMENT_LENGTH} characters"
    return None


def is_literal(text: object) -> bool:
    """Whether text is a Python literal of acceptable length (data, not code)."""
    return literal_problem(text) is None


def keyword_name_problem(name: object) -> str | None:
    """Why ``name`` cannot be a keyword argument name, or None when it can."""
    if isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name):
        return None
    return f"unusable keyword name {name!r}"


def case_problem(args: Sequence[object], kwargs: Mapping[Any, object]) -> str | None:
    """The first reason a case's arguments are not acceptable, or None.

    Args:
        args: Positional argument source texts.
        kwargs: Keyword argument source texts by name (names are checked
            too, so they may be any value read from JSON).

    Returns:
        A reason from literal_problem() or keyword_name_problem(), or None.
    """
    for text in args:
        if (problem := literal_problem(text)) is not None:
            return problem
    for name, text in kwargs.items():
        problem = keyword_name_problem(name) or literal_problem(text)
        if problem is not None:
            return problem
    return None


def normalized_case(
    args: Sequence[str], kwargs: Mapping[str, str]
) -> tuple[tuple[str, ...], dict[str, str]]:
    """The arguments of an accepted case in their normal form.

    Every entry point stores this form, so reports, reproducing tests, the
    cache and prompts all show the same safe text.

    Args:
        args: Positional argument source texts that passed case_problem().
        kwargs: Keyword argument source texts that passed case_problem().

    Returns:
        The positional and keyword arguments after normal_form().
    """
    return (
        tuple(normal_form(text) for text in args),
        {name: normal_form(text) for name, text in kwargs.items()},
    )


def _call_argument(text: str) -> str:
    # Defensive: a case built without the entry points is still printed as
    # one expression; text that is no expression at all is shown as it is.
    try:
        return normal_form(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return text


def format_call(name: str, args: Sequence[str], kwargs: Mapping[str, str]) -> str:
    """``name(arg, key=value)`` with every argument in its normal form."""
    arguments = [
        *(_call_argument(text) for text in args),
        *(f"{key}={_call_argument(value)}" for key, value in kwargs.items()),
    ]
    return f"{name}({', '.join(arguments)})"


def format_case_call(
    name: str,
    args: Sequence[str],
    kwargs: Mapping[str, str],
    init_args: Sequence[str] | None = None,
    init_kwargs: Mapping[str, str] | None = None,
) -> str:
    """A case as one call: ``name(...)``, or ``Owner(...).method(...)``.

    Args:
        name: The function, ``Class.method`` or ``path::Class.method``.
        args: Positional arguments of the call.
        kwargs: Keyword arguments of the call.
        init_args: Constructor arguments of a method case (task 30); None
            for a function, where the call is printed as format_call().
        init_kwargs: Constructor keyword arguments of a method case.

    Returns:
        For a method case, the constructor call on the class followed by the
        method call, e.g. ``app/bank.py::Account(100).deposit(-5)``; for
        ``Class.__init__`` only the constructor call (task 38).
    """
    if init_args is None:
        return format_call(name, args, kwargs)
    owner, _, method = name.rpartition(".")
    instance = format_call(owner, init_args, init_kwargs or {})
    if method == "__init__":
        return instance
    return f"{instance}.{format_call(method, args, kwargs)}"
