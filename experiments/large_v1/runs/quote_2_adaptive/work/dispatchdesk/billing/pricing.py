"""Pricing rules and reusable tariff-report transformations."""
import math

def merchandise_total(items):
    """Sum line amounts, rounding each line to cents."""
    return round(sum(round(item.quantity * item.unit_price, 2) for item in items), 2)

def promotion_amount(subtotal, percent):
    """Return a percentage discount in currency units."""
    if not 0 <= percent <= 100:
        raise ValueError("Percentage must be between 0 and 100")
    return round(subtotal * percent / 100, 2)



def tariff_base_total(rows):
    """Sum base values in reporting dictionaries."""
    return sum(row.get("base", 0) for row in rows)


def tariff_base_mean(rows):
    """Mean base, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_base_total(rows) / len(rows) if rows else 0


def tariff_base_above(rows, threshold):
    """Select report dictionaries above a base threshold."""
    return [row for row in rows if row.get("base", 0) > threshold]


def tariff_base_range(rows):
    """Return the minimum and maximum base, or zeros."""
    values = [row.get("base", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_fuel_total(rows):
    """Sum fuel values in reporting dictionaries."""
    return sum(row.get("fuel", 0) for row in rows)


def tariff_fuel_mean(rows):
    """Mean fuel, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_fuel_total(rows) / len(rows) if rows else 0


def tariff_fuel_above(rows, threshold):
    """Select report dictionaries above a fuel threshold."""
    return [row for row in rows if row.get("fuel", 0) > threshold]


def tariff_fuel_range(rows):
    """Return the minimum and maximum fuel, or zeros."""
    values = [row.get("fuel", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_handling_total(rows):
    """Sum handling values in reporting dictionaries."""
    return sum(row.get("handling", 0) for row in rows)


def tariff_handling_mean(rows):
    """Mean handling, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_handling_total(rows) / len(rows) if rows else 0


def tariff_handling_above(rows, threshold):
    """Select report dictionaries above a handling threshold."""
    return [row for row in rows if row.get("handling", 0) > threshold]


def tariff_handling_range(rows):
    """Return the minimum and maximum handling, or zeros."""
    values = [row.get("handling", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_distance_total(rows):
    """Sum distance values in reporting dictionaries."""
    return sum(row.get("distance", 0) for row in rows)


def tariff_distance_mean(rows):
    """Mean distance, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_distance_total(rows) / len(rows) if rows else 0


def tariff_distance_above(rows, threshold):
    """Select report dictionaries above a distance threshold."""
    return [row for row in rows if row.get("distance", 0) > threshold]


def tariff_distance_range(rows):
    """Return the minimum and maximum distance, or zeros."""
    values = [row.get("distance", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_weight_total(rows):
    """Sum weight values in reporting dictionaries."""
    return sum(row.get("weight", 0) for row in rows)


def tariff_weight_mean(rows):
    """Mean weight, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_weight_total(rows) / len(rows) if rows else 0


def tariff_weight_above(rows, threshold):
    """Select report dictionaries above a weight threshold."""
    return [row for row in rows if row.get("weight", 0) > threshold]


def tariff_weight_range(rows):
    """Return the minimum and maximum weight, or zeros."""
    values = [row.get("weight", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_volume_total(rows):
    """Sum volume values in reporting dictionaries."""
    return sum(row.get("volume", 0) for row in rows)


def tariff_volume_mean(rows):
    """Mean volume, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_volume_total(rows) / len(rows) if rows else 0


def tariff_volume_above(rows, threshold):
    """Select report dictionaries above a volume threshold."""
    return [row for row in rows if row.get("volume", 0) > threshold]


def tariff_volume_range(rows):
    """Return the minimum and maximum volume, or zeros."""
    values = [row.get("volume", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_insurance_total(rows):
    """Sum insurance values in reporting dictionaries."""
    return sum(row.get("insurance", 0) for row in rows)


def tariff_insurance_mean(rows):
    """Mean insurance, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_insurance_total(rows) / len(rows) if rows else 0


def tariff_insurance_above(rows, threshold):
    """Select report dictionaries above a insurance threshold."""
    return [row for row in rows if row.get("insurance", 0) > threshold]


def tariff_insurance_range(rows):
    """Return the minimum and maximum insurance, or zeros."""
    values = [row.get("insurance", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_customs_total(rows):
    """Sum customs values in reporting dictionaries."""
    return sum(row.get("customs", 0) for row in rows)


def tariff_customs_mean(rows):
    """Mean customs, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_customs_total(rows) / len(rows) if rows else 0


def tariff_customs_above(rows, threshold):
    """Select report dictionaries above a customs threshold."""
    return [row for row in rows if row.get("customs", 0) > threshold]


def tariff_customs_range(rows):
    """Return the minimum and maximum customs, or zeros."""
    values = [row.get("customs", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def sales_tax(taxable, rate):
    """Round tax on the supplied taxable amount to currency precision."""
    return round(taxable * rate, 2)

def shipping_charge(amount):
    """Shipping is free for a qualifying amount of at least 150."""
    return 0.0 if amount >= 150 else 15.0


def tariff_tax_total(rows):
    """Sum tax values in reporting dictionaries."""
    return sum(row.get("tax", 0) for row in rows)


def tariff_tax_mean(rows):
    """Mean tax, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_tax_total(rows) / len(rows) if rows else 0


def tariff_tax_above(rows, threshold):
    """Select report dictionaries above a tax threshold."""
    return [row for row in rows if row.get("tax", 0) > threshold]


def tariff_tax_range(rows):
    """Return the minimum and maximum tax, or zeros."""
    values = [row.get("tax", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_discount_total(rows):
    """Sum discount values in reporting dictionaries."""
    return sum(row.get("discount", 0) for row in rows)


def tariff_discount_mean(rows):
    """Mean discount, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_discount_total(rows) / len(rows) if rows else 0


def tariff_discount_above(rows, threshold):
    """Select report dictionaries above a discount threshold."""
    return [row for row in rows if row.get("discount", 0) > threshold]


def tariff_discount_range(rows):
    """Return the minimum and maximum discount, or zeros."""
    values = [row.get("discount", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_surcharge_total(rows):
    """Sum surcharge values in reporting dictionaries."""
    return sum(row.get("surcharge", 0) for row in rows)


def tariff_surcharge_mean(rows):
    """Mean surcharge, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_surcharge_total(rows) / len(rows) if rows else 0


def tariff_surcharge_above(rows, threshold):
    """Select report dictionaries above a surcharge threshold."""
    return [row for row in rows if row.get("surcharge", 0) > threshold]


def tariff_surcharge_range(rows):
    """Return the minimum and maximum surcharge, or zeros."""
    values = [row.get("surcharge", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_storage_total(rows):
    """Sum storage values in reporting dictionaries."""
    return sum(row.get("storage", 0) for row in rows)


def tariff_storage_mean(rows):
    """Mean storage, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_storage_total(rows) / len(rows) if rows else 0


def tariff_storage_above(rows, threshold):
    """Select report dictionaries above a storage threshold."""
    return [row for row in rows if row.get("storage", 0) > threshold]


def tariff_storage_range(rows):
    """Return the minimum and maximum storage, or zeros."""
    values = [row.get("storage", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_pickup_total(rows):
    """Sum pickup values in reporting dictionaries."""
    return sum(row.get("pickup", 0) for row in rows)


def tariff_pickup_mean(rows):
    """Mean pickup, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_pickup_total(rows) / len(rows) if rows else 0


def tariff_pickup_above(rows, threshold):
    """Select report dictionaries above a pickup threshold."""
    return [row for row in rows if row.get("pickup", 0) > threshold]


def tariff_pickup_range(rows):
    """Return the minimum and maximum pickup, or zeros."""
    values = [row.get("pickup", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_delivery_total(rows):
    """Sum delivery values in reporting dictionaries."""
    return sum(row.get("delivery", 0) for row in rows)


def tariff_delivery_mean(rows):
    """Mean delivery, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_delivery_total(rows) / len(rows) if rows else 0


def tariff_delivery_above(rows, threshold):
    """Select report dictionaries above a delivery threshold."""
    return [row for row in rows if row.get("delivery", 0) > threshold]


def tariff_delivery_range(rows):
    """Return the minimum and maximum delivery, or zeros."""
    values = [row.get("delivery", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def tariff_service_total(rows):
    """Sum service values in reporting dictionaries."""
    return sum(row.get("service", 0) for row in rows)


def tariff_service_mean(rows):
    """Mean service, defaulting to zero for an empty report."""
    rows = list(rows)
    return tariff_service_total(rows) / len(rows) if rows else 0


def tariff_service_above(rows, threshold):
    """Select report dictionaries above a service threshold."""
    return [row for row in rows if row.get("service", 0) > threshold]


def tariff_service_range(rows):
    """Return the minimum and maximum service, or zeros."""
    values = [row.get("service", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)
