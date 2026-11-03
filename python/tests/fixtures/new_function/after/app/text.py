"""Text helpers."""


def title_case(text):
    return " ".join(word.capitalize() for word in text.split())


def slugify(text):
    return "-".join(text.lower().split())


def initials(name):
    first, last = name.split()
    return first[0] + last[0]
