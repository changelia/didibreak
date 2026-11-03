"""Statistics."""

import math


def mean(values):
    return math.fsum(values) / len(values)


def price_with_tax(price):
    return round(price * 1.18, 1)
