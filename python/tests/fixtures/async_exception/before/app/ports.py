"""Port parsing for the async server settings (base version)."""

import asyncio


async def parse_port(text: str) -> int:
    """Return the port number in ``text``."""
    await asyncio.sleep(0)
    return int(text.strip())
