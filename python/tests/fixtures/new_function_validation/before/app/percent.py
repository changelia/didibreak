"""Percent helpers."""


def clamp_percent(value):
    return max(0, min(100, value))
