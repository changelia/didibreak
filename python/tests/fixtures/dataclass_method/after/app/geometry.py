"""Points on a grid (changed version)."""

from dataclasses import dataclass


@dataclass
class Point:
    x: int
    y: int = 0

    def distance_to_origin(self) -> int:
        """Manhattan distance to (0, 0)."""
        return self.x + self.y
