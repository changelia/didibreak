"""Tokens."""

import uuid


def make_token(prefix):
    return f"{prefix.upper()}-{uuid.uuid4().hex[:8]}"
