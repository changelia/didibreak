"""Phone number helpers (current version)."""


def normalize_phone(raw):
    """Return a phone number in E.164 format; international numbers keep their code."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.strip().startswith("+"):
        return "+" + digits
    return "+995" + digits
