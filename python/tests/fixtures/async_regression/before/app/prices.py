"""Price formatting for the shop's async API (base version)."""

import asyncio


async def format_price(cents: int) -> str:
    """Return a price such as ``$2.50`` for an amount in cents."""
    await asyncio.sleep(0)  # stands in for a currency lookup
    return f"${cents / 100:.2f}"
