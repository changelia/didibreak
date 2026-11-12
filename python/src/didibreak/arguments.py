"""Case arguments: Python literal source text, checked and printed one way.

Cases reach the harness from LLM replies, the case cache, the hidden
``--cases-file`` option and the harness's own check. All of them use
case_problem(), so "the LLM supplies data, never code" (Spec, Safety) is
the same rule everywhere (audit 35a, finding 11), and all reports print a
call with format_call(). Standard library only: no didibreak imports, so
any module can use it without an import cycle.
"""

import ast
import keyword
from collections.abc import Mapping, Sequence
from typing import Any

# Longer arguments are rejected: they bloat prompts, reports and the
# harness request without making a case more useful.
MAX_ARGUMENT_LENGTH = 2000


def literal_problem(text: object) -> str | None:
    """Why ``text`` is not an acceptable argument, or None when it is.

    Args:
        text: Proposed argument source text.

    Returns:
        A short reason: not a string, too long, or not a Python literal
        (``ast.literal_eval`` fails); None for a valid argument.
    """
    if not isinstance(text, str):
        return f"not a string: {text!r}"
    if len(text) > MAX_ARGUMENT_LENGTH:
        return f"longer than {MAX_ARGUMENT_LENGTH} characters"
    try:
        ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return f"not a Python literal: {text!r}"
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


def format_call(name: str, args: Sequence[str], kwargs: Mapping[str, str]) -> str:
    """``name(arg, key=value)`` with the arguments as written in the case."""
    arguments = [*args, *(f"{key}={value}" for key, value in kwargs.items())]
    return f"{name}({', '.join(arguments)})"
