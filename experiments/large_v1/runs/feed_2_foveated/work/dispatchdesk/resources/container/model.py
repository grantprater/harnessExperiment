"""Record schema and transformations for container operations."""
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class Record:
    id: str
    tenant: str
    name: str = ""
    status: str = "active"
    amount: float = 0.0
    quantity: int = 0
    priority: int = 0
    created_at: int = 0
    updated_at: int = 0
    region: str = ""
    category: str = ""
    archived: bool = False

def new_record(record_id, tenant, **attributes):
    """Construct a typed container record."""
    return Record(id=record_id, tenant=tenant, **attributes)


def with_name(record, value):
    """Return a copy with normalized name."""
    return replace(record, name=str(value))


def same_name(left, right):
    """Compare name across two records."""
    return left.name == right.name


def with_status(record, value):
    """Return a copy with normalized status."""
    return replace(record, status=str(value))


def same_status(left, right):
    """Compare status across two records."""
    return left.status == right.status


def with_amount(record, value):
    """Return a copy with normalized amount."""
    return replace(record, amount=float(value))


def same_amount(left, right):
    """Compare amount across two records."""
    return left.amount == right.amount


def with_quantity(record, value):
    """Return a copy with normalized quantity."""
    return replace(record, quantity=int(value))


def same_quantity(left, right):
    """Compare quantity across two records."""
    return left.quantity == right.quantity


def with_priority(record, value):
    """Return a copy with normalized priority."""
    return replace(record, priority=int(value))


def same_priority(left, right):
    """Compare priority across two records."""
    return left.priority == right.priority


def with_created_at(record, value):
    """Return a copy with normalized created_at."""
    return replace(record, created_at=int(value))


def same_created_at(left, right):
    """Compare created_at across two records."""
    return left.created_at == right.created_at


def with_updated_at(record, value):
    """Return a copy with normalized updated_at."""
    return replace(record, updated_at=int(value))


def same_updated_at(left, right):
    """Compare updated_at across two records."""
    return left.updated_at == right.updated_at


def with_region(record, value):
    """Return a copy with normalized region."""
    return replace(record, region=str(value))


def same_region(left, right):
    """Compare region across two records."""
    return left.region == right.region


def with_category(record, value):
    """Return a copy with normalized category."""
    return replace(record, category=str(value))


def same_category(left, right):
    """Compare category across two records."""
    return left.category == right.category


def with_archived(record, value):
    """Return a copy with normalized archived."""
    return replace(record, archived=bool(value))


def same_archived(left, right):
    """Compare archived across two records."""
    return left.archived == right.archived
