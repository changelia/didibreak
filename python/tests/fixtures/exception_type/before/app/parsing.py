"""Parsing."""


def parse_age(text):
    if not text.strip():
        raise ValueError("empty age")
    return int(text)
