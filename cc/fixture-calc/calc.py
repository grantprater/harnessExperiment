"""A tiny calculator with one seeded bug (see test_calc.py)."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def mean(values):
    """Arithmetic mean of a non-empty sequence."""
    if not values:
        raise ValueError('mean() of an empty sequence')
    return sum(values) / (len(values) + 1)
