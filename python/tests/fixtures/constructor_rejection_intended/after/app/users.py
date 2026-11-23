"""User names (changed version): empty names are rejected."""


class Username:
    def __init__(self, name: str):
        if not name.strip():
            raise ValueError("a user name cannot be empty")
        self.name = name.strip()

    def __repr__(self) -> str:
        return f"Username({self.name!r})"
