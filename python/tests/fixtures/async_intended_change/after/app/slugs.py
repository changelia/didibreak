"""Slugs for article titles (changed version)."""

import asyncio


async def slugify_title(title: str) -> str:
    """Return a lower-case slug with dashes between words, without "!"."""
    await asyncio.sleep(0)
    return "-".join(title.lower().replace("!", "").split())
