"""Temperatures (changed version): the unit can be given."""


class Temperature:
    def __init__(self, value: float, unit: str = "C"):
        self.celsius = value if unit == "C" else (value - 32) * 5 / 9

    def fahrenheit(self) -> float:
        return round(self.celsius * 9 / 5 + 32, 1)
