"""Text helpers."""


def title_case(text):
    return " ".join(word.capitalize() for word in text.split())
