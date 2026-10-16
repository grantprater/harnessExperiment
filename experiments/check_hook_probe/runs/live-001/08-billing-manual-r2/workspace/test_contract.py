"""Comprehensive unit test suite for billing and checkout."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import unittest
from models import Cart, CartItem, PromoCode
from checkout import CheckoutService


class TestBillingPipeline(unittest.TestCase):
    def setUp(self):
        self.service = CheckoutService(inventory={"SKU-1": 100, "SKU-2": 50, "SKU-3": 20})

    def test_empty_cart_fails_validation(self):
        cart = Cart()
        with self.assertRaises(ValueError):
            self.service.process_order(cart, state="CA")

    def test_standard_order_without_discounts(self):
        cart = Cart()
        cart.add_item(CartItem(sku="SKU-1", name="Widget A", unit_price=25.0, quantity=2)) # $50.00
        # State WA: tax 6.5% of 50.00 = 3.25. Shipping = 15.0. Total = 68.25
        receipt = self.service.process_order(cart, state="WA")
        self.assertEqual(receipt.subtotal, 50.0)
        self.assertEqual(receipt.discount_amount, 0.0)
        self.assertEqual(receipt.tax_amount, 3.25)
        self.assertEqual(receipt.shipping_fee, 15.0)
        self.assertEqual(receipt.final_total, 68.25)

    def test_tax_free_state(self):
        cart = Cart()
        cart.add_item(CartItem(sku="SKU-1", name="Widget A", unit_price=100.0, quantity=1)) # $100.00
        # Oregon (OR) has 0% tax. Shipping = 15.0. Total = 115.00
        receipt = self.service.process_order(cart, state="OR")
        self.assertEqual(receipt.tax_amount, 0.0)
        self.assertEqual(receipt.final_total, 115.0)

    def test_free_shipping_threshold(self):
        cart = Cart()
        cart.add_item(CartItem(sku="SKU-2", name="Widget B", unit_price=80.0, quantity=2)) # $160.00
        # Oregon: 0% tax. Free shipping threshold is $150. Shipping = 0. Total = 160.00
        receipt = self.service.process_order(cart, state="OR")
        self.assertEqual(receipt.shipping_fee, 0.0)
        self.assertEqual(receipt.final_total, 160.0)

    def test_insufficient_stock_fails(self):
        cart = Cart()
        cart.add_item(CartItem(sku="SKU-3", name="Widget C", unit_price=10.0, quantity=999))
        with self.assertRaises(ValueError):
            self.service.process_order(cart, state="DE")

    def test_promo_discount_with_california_tax(self):
        """CRITICAL: Tax must be calculated on post-discount subtotal, not raw subtotal."""
        cart = Cart()
        cart.add_item(CartItem(sku="SKU-1", name="Widget A", unit_price=50.0, quantity=4)) # $200.00
        promo = PromoCode(code="FALL20", discount_percent=0.20, min_subtotal=100.0) # 20% off

        # Subtotal: $200.00
        # Discount (20%): $40.00 -> Taxable: $160.00
        # CA Tax (8.25% of $160.00): $13.20
        # Shipping (Over $150): $0.00
        # Expected Total: 160.00 + 13.20 = $173.20
        receipt = self.service.process_order(cart, state="CA", promo=promo)

        self.assertEqual(receipt.discount_amount, 40.0)
        self.assertEqual(receipt.taxable_amount, 160.0)
        self.assertEqual(
            receipt.tax_amount,
            13.20,
            f"Tax must be assessed on post-discount amount ($160 * 8.25% = $13.20). Got: {receipt.tax_amount}"
        )
        self.assertEqual(
            receipt.final_total,
            173.20,
            f"Final total mismatch: expected 173.20, got {receipt.final_total}"
        )


if __name__ == "__main__":
    unittest.main()
