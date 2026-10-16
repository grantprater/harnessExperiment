"""Checkout pipeline service."""

from __future__ import annotations

import uuid
from typing import Dict, Optional
from models import Cart, CartItem, OrderReceipt, PromoCode
from pricing import calculate_final_bill


class CheckoutService:
    def __init__(self, inventory: Optional[Dict[str, int]] = None):
        self.inventory = inventory if inventory is not None else {}
        self.orders_history: Dict[str, OrderReceipt] = {}

    def validate_cart(self, cart: Cart) -> None:
        if not cart.items:
            raise ValueError("Cannot checkout an empty cart.")
        
        for item in cart.items:
            if item.sku in self.inventory:
                available = self.inventory[item.sku]
                if available < item.quantity:
                    raise ValueError(
                        f"Insufficient stock for SKU {item.sku}: requested {item.quantity}, available {available}."
                    )

    def process_order(
        self,
        cart: Cart,
        state: str,
        promo: Optional[PromoCode] = None
    ) -> OrderReceipt:
        """Runs validation, pricing, inventory deduction, and returns receipt."""
        self.validate_cart(cart)
        
        bill = calculate_final_bill(cart=cart, state=state, promo=promo)
        
        # Deduct inventory
        for item in cart.items:
            if item.sku in self.inventory:
                self.inventory[item.sku] -= item.quantity

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        receipt = OrderReceipt(
            order_id=order_id,
            subtotal=bill["subtotal"],
            discount_amount=bill["discount_amount"],
            taxable_amount=bill["taxable_amount"],
            tax_amount=bill["tax_amount"],
            shipping_fee=bill["shipping_fee"],
            final_total=bill["final_total"],
            state=state,
            promo_code=promo.code if promo else None
        )

        self.orders_history[order_id] = receipt
        return receipt
