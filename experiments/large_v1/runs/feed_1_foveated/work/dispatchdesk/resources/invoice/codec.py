"""JSON and flat-column codecs for invoice records."""
import json
from dataclasses import asdict
from .model import Record

def encode(record):
    return json.dumps(asdict(record), sort_keys=True)

def decode(payload):
    return Record(**json.loads(payload))

def encode_many(records):
    return json.dumps([asdict(record) for record in records], sort_keys=True)

def decode_many(payload):
    return [Record(**row) for row in json.loads(payload)]

def flatten(record):
    return asdict(record)


def name_column(records):
    """Extract a name column for export."""
    return [r.name for r in records]


def parse_name(value):
    """Coerce a typed name value."""
    return str(value)


def status_column(records):
    """Extract a status column for export."""
    return [r.status for r in records]


def parse_status(value):
    """Coerce a typed status value."""
    return str(value)


def amount_column(records):
    """Extract a amount column for export."""
    return [r.amount for r in records]


def parse_amount(value):
    """Coerce a typed amount value."""
    return float(value)


def quantity_column(records):
    """Extract a quantity column for export."""
    return [r.quantity for r in records]


def parse_quantity(value):
    """Coerce a typed quantity value."""
    return int(value)


def priority_column(records):
    """Extract a priority column for export."""
    return [r.priority for r in records]


def parse_priority(value):
    """Coerce a typed priority value."""
    return int(value)


def created_at_column(records):
    """Extract a created_at column for export."""
    return [r.created_at for r in records]


def parse_created_at(value):
    """Coerce a typed created_at value."""
    return int(value)


def updated_at_column(records):
    """Extract a updated_at column for export."""
    return [r.updated_at for r in records]


def parse_updated_at(value):
    """Coerce a typed updated_at value."""
    return int(value)


def region_column(records):
    """Extract a region column for export."""
    return [r.region for r in records]


def parse_region(value):
    """Coerce a typed region value."""
    return str(value)


def category_column(records):
    """Extract a category column for export."""
    return [r.category for r in records]


def parse_category(value):
    """Coerce a typed category value."""
    return str(value)


def archived_column(records):
    """Extract a archived column for export."""
    return [r.archived for r in records]


def parse_archived(value):
    """Coerce a typed archived value."""
    return bool(value)
