from .models import Quote
from .pricing import merchandise_total, promotion_amount, sales_tax, shipping_charge

def quote_order(items, discount_percent=0.0, tax_rate=0.0):
    """Quote merchandise, promotion, tax, and post-promotion shipping."""
    subtotal = merchandise_total(items)
    discount = promotion_amount(subtotal, discount_percent)
    taxable = round(subtotal - discount, 2)
    tax = sales_tax(subtotal, tax_rate)
    shipping = shipping_charge(taxable)
    return Quote(subtotal, discount, taxable, tax, shipping,
                 round(taxable + tax + shipping, 2))
