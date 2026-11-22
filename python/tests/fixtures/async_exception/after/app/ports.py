"""Port parsing for the async server settings (changed version)."""

import asyncio


async def parse_port(text: str) -> int:
    """Return the port number in ``text``."""
    await asyncio.sleep(0)
    port = int(text.strip())
    if not 0 < port < 65536:
        raise ValueError("port out of range")
    return port
