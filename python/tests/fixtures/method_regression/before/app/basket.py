"""A shopping basket (base version)."""


class Basket:
    """Prices in cents."""

    def __init__(self, items: list[int]):
        self.items = list(items)

    def total(self, discount: int) -> int:
        """The sum of the items minus a discount in cents."""
        return sum(self.items) - discount
