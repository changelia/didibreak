"""Price formatting for the shop's async API (changed version)."""

import asyncio


async def format_price(cents: int) -> str:
    """Return a price such as ``$1,000.00`` for an amount in cents."""
    await asyncio.sleep(0)  # stands in for a currency lookup
    return f"${abs(cents) / 100:,.2f}"
