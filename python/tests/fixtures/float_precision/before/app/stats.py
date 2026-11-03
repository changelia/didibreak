"""Statistics."""


def mean(values):
    return sum(values) / len(values)


def price_with_tax(price):
    return round(price * 1.18, 2)
