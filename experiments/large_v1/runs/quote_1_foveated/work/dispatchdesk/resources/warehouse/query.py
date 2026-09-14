"""Tenant-scoped warehouse query helpers."""
def for_tenant(records, tenant):
    return [r for r in records if r.tenant == tenant]

def by_id(records, record_id):
    return next((r for r in records if r.id == record_id), None)

def active(records):
    return [r for r in records if not r.archived]


def with_name(records, value):
    """Filter records by exact name."""
    return [r for r in records if r.name == value]


def order_by_name(records):
    """Stable ascending sort by name and id."""
    return sorted(records, key=lambda r: (r.name, r.id))


def with_status(records, value):
    """Filter records by exact status."""
    return [r for r in records if r.status == value]


def order_by_status(records):
    """Stable ascending sort by status and id."""
    return sorted(records, key=lambda r: (r.status, r.id))


def with_amount(records, value):
    """Filter records by exact amount."""
    return [r for r in records if r.amount == value]


def order_by_amount(records):
    """Stable ascending sort by amount and id."""
    return sorted(records, key=lambda r: (r.amount, r.id))


def with_quantity(records, value):
    """Filter records by exact quantity."""
    return [r for r in records if r.quantity == value]


def order_by_quantity(records):
    """Stable ascending sort by quantity and id."""
    return sorted(records, key=lambda r: (r.quantity, r.id))


def with_priority(records, value):
    """Filter records by exact priority."""
    return [r for r in records if r.priority == value]


def order_by_priority(records):
    """Stable ascending sort by priority and id."""
    return sorted(records, key=lambda r: (r.priority, r.id))


def with_created_at(records, value):
    """Filter records by exact created_at."""
    return [r for r in records if r.created_at == value]


def order_by_created_at(records):
    """Stable ascending sort by created_at and id."""
    return sorted(records, key=lambda r: (r.created_at, r.id))


def with_updated_at(records, value):
    """Filter records by exact updated_at."""
    return [r for r in records if r.updated_at == value]


def order_by_updated_at(records):
    """Stable ascending sort by updated_at and id."""
    return sorted(records, key=lambda r: (r.updated_at, r.id))


def with_region(records, value):
    """Filter records by exact region."""
    return [r for r in records if r.region == value]


def order_by_region(records):
    """Stable ascending sort by region and id."""
    return sorted(records, key=lambda r: (r.region, r.id))


def with_category(records, value):
    """Filter records by exact category."""
    return [r for r in records if r.category == value]


def order_by_category(records):
    """Stable ascending sort by category and id."""
    return sorted(records, key=lambda r: (r.category, r.id))


def with_archived(records, value):
    """Filter records by exact archived."""
    return [r for r in records if r.archived == value]


def order_by_archived(records):
    """Stable ascending sort by archived and id."""
    return sorted(records, key=lambda r: (r.archived, r.id))
