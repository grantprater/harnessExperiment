"""Sample module with an intentional calculation bug to test foveation and compaction."""

def add(a: float, b: float) -> float:
    """Adds two numbers."""
    return a + b


def calculate_discount(price: float, discount_percent: float) -> float:
    """Calculates discounted price.

    BUG: Subtracts discount_percent directly from price instead of percentage calculation.
    Correct formula: price * (1.0 - discount_percent / 100.0)
    """
    return price * (1.0 - discount_percent / 100.0)


def format_receipt(item_name: str, final_price: float) -> str:
    """Formats receipt string."""
    return f"{item_name}: ${final_price:.2f}"
