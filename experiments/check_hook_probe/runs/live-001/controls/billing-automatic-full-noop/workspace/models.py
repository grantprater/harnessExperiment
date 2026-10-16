"""Data models for the billing and order processing system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CartItem:
    sku: str
    name: str
    unit_price: float
    quantity: int

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


@dataclass
class PromoCode:
    code: str
    discount_percent: float
    min_subtotal: float = 0.0

    def is_eligible(self, subtotal: float) -> bool:
        return subtotal >= self.min_subtotal


@dataclass
class Cart:
    items: List[CartItem] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    def add_item(self, item: CartItem) -> None:
        self.items.append(item)


@dataclass
class OrderReceipt:
    order_id: str
    subtotal: float
    discount_amount: float
    taxable_amount: float
    tax_amount: float
    shipping_fee: float
    final_total: float
    state: str
    promo_code: Optional[str] = None
