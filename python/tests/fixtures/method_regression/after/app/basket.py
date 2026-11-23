"""A shopping basket (changed version)."""


class Basket:
    """Prices in cents."""

    def __init__(self, items: list[int]):
        self.items = list(items)

    def total(self, discount: int) -> int:
        """The sum of the items minus a discount in cents."""
        subtotal = sum(self.items)
        return max(0, subtotal - discount)
