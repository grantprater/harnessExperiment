from dataclasses import dataclass

@dataclass(frozen=True)
class LineItem:
    sku: str
    quantity: int
    unit_price: float

@dataclass(frozen=True)
class Quote:
    subtotal: float
    discount: float
    taxable: float
    tax: float
    shipping: float
    total: float
