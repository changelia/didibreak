"""Tokens."""

import uuid


def make_token(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
