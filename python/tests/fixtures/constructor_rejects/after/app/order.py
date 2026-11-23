"""Orders (changed version): a clearer error message."""


class Order:
    def __init__(self, quantity: int):
        if quantity <= 0:
            raise ValueError(f"quantity must not be negative, got {quantity}")
        self.quantity = quantity

    def __repr__(self) -> str:
        return f"Order({self.quantity!r})"
