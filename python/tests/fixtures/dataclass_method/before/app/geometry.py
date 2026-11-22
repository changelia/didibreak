"""Points on a grid (base version)."""

from dataclasses import dataclass


@dataclass
class Point:
    x: int
    y: int = 0

    def distance_to_origin(self) -> int:
        """Manhattan distance to (0, 0)."""
        return abs(self.x) + abs(self.y)
