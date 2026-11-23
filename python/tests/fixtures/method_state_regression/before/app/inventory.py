"""Stock counts (base version)."""


class Inventory:
    def __init__(self, counts: dict[str, int]):
        self.counts = dict(counts)

    def add(self, name: str, count: int) -> None:
        """Add ``count`` items of ``name`` to the stock."""
        self.counts[name] = self.counts.get(name, 0) + count
