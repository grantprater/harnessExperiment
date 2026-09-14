"""Pricing and tax calculation service."""

from __future__ import annotations

from typing import Dict, Optional
from models import Cart, PromoCode


STATE_TAX_RATES: Dict[str, float] = {
    "CA": 0.0825,  # 8.25%
    "NY": 0.08875, # 8.875%
    "TX": 0.0625,  # 6.25%
    "WA": 0.065,   # 6.5%
    "OR": 0.0,     # No sales tax
    "DE": 0.0,     # No sales tax
}

DEFAULT_TAX_RATE = 0.05
FREE_SHIPPING_THRESHOLD = 150.0
STANDARD_SHIPPING_FEE = 15.0


def get_tax_rate(state: str) -> float:
    """Returns state sales tax rate."""
    return STATE_TAX_RATES.get(state.upper(), DEFAULT_TAX_RATE)


def calculate_volume_discount(subtotal: float) -> float:
    """Applies tiered volume discount."""
    if subtotal >= 500.0:
        return 0.10  # 10% off
    elif subtotal >= 300.0:
        return 0.05  # 5% off
    return 0.0


def calculate_shipping(subtotal: float) -> float:
    """Free shipping over $150, otherwise flat fee."""
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0.0
    return STANDARD_SHIPPING_FEE


def compute_discount_amount(
    subtotal: float,
    promo: Optional[PromoCode] = None
) -> float:
    """Calculates total discount dollars from volume or promo code."""
    discount_pct = 0.0
    if promo and promo.is_eligible(subtotal):
        discount_pct = max(discount_pct, promo.discount_percent)
    else:
        discount_pct = max(discount_pct, calculate_volume_discount(subtotal))

    return round(subtotal * discount_pct, 2)


def calculate_final_bill(
    cart: Cart,
    state: str,
    promo: Optional[PromoCode] = None
) -> Dict[str, float]:
    """Computes full breakdown: subtotal, discount, tax, shipping, final total.

    Rule: Sales tax must only be assessed on the post-discount taxable amount.
    """
    subtotal = cart.subtotal
    discount_amount = compute_discount_amount(subtotal, promo)
    discounted_subtotal = round(subtotal - discount_amount, 2)

    tax_rate = get_tax_rate(state)

    # BUG IS HERE: tax_amount is being computed on raw subtotal instead of discounted_subtotal!
    tax_amount = round(subtotal * tax_rate, 2)

    shipping_fee = calculate_shipping(discounted_subtotal)
    final_total = round(discounted_subtotal + tax_amount + shipping_fee, 2)

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "taxable_amount": discounted_subtotal,
        "tax_amount": tax_amount,
        "shipping_fee": shipping_fee,
        "final_total": final_total,
    }
