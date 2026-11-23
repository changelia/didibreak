"""Orders (base version)."""


class Order:
    def __init__(self, quantity: int):
        if quantity < 0:
            raise ValueError("quantity is negative")
        self.quantity = quantity

    def __repr__(self) -> str:
        return f"Order({self.quantity!r})"
