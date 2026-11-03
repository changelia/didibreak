"""Limits."""


def clamp( value,low,high ):
    """Keep value between low and high."""
    # max/min keep the value inside the range
    return max(
        low,
        min(value, high),
    )
