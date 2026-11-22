"""Slugs for article titles (base version)."""

import asyncio


async def slugify_title(title: str) -> str:
    """Return a lower-case slug with dashes between words."""
    await asyncio.sleep(0)
    return "-".join(title.lower().split())
