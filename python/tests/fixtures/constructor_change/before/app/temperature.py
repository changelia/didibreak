"""Temperatures (base version)."""


class Temperature:
    def __init__(self, celsius: float):
        self.celsius = celsius

    def fahrenheit(self) -> float:
        return self.celsius * 9 / 5 + 32
