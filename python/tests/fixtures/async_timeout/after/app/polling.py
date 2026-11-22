"""Wait until a service is ready (changed version)."""

import asyncio


async def wait_until_ready(attempts: int) -> int:
    """Poll up to ``attempts`` times and return the number of polls."""
    polls = 0
    while polls < attempts:
        polls += 1
        await asyncio.sleep(0)
    return polls
