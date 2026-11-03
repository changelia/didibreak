"""Limits."""


def clamp(value, low, high):
    return max(low, min(value, high))
