"""Percent helpers."""


class OutOfRange(ValueError):
    """A percentage above 100."""


def clamp_percent(value):
    return max(0, min(100, value))


def parse_percent(text):
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    digits = text.strip().removesuffix("%")
    if not digits.isdecimal():
        raise ValueError(f"not a percentage: {text!r}")
    return _check_range(int(digits))


def _check_range(value):
    if value > 100:
        raise OutOfRange(value)
    return value
