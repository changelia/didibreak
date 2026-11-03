"""Phone number helpers (base version)."""


def normalize_phone(raw):
    """Return a Georgian phone number in +995 format."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("995"):
        digits = digits[3:]
    return "+995" + digits
