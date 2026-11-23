"""User names (base version)."""


class Username:
    def __init__(self, name: str):
        self.name = name.strip()

    def __repr__(self) -> str:
        return f"Username({self.name!r})"
