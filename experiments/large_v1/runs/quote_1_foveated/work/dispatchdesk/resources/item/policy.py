"""Authorization and transitions for item records."""
def can_read(record, tenant):
    return record.tenant == tenant

def can_write(record, tenant):
    return can_read(record, tenant) and not record.archived

def can_archive(record, tenant):
    return can_write(record, tenant) and record.status != "pending"


def can_change_name(record, tenant, value):
    """Allow name updates on writable records."""
    return can_write(record, tenant) and value is not None


def name_changed(before, after):
    """Detect a material name update."""
    return before.name != after.name


def can_change_status(record, tenant, value):
    """Allow status updates on writable records."""
    return can_write(record, tenant) and value is not None


def status_changed(before, after):
    """Detect a material status update."""
    return before.status != after.status


def can_change_amount(record, tenant, value):
    """Allow amount updates on writable records."""
    return can_write(record, tenant) and value is not None


def amount_changed(before, after):
    """Detect a material amount update."""
    return before.amount != after.amount


def can_change_quantity(record, tenant, value):
    """Allow quantity updates on writable records."""
    return can_write(record, tenant) and value is not None


def quantity_changed(before, after):
    """Detect a material quantity update."""
    return before.quantity != after.quantity


def can_change_priority(record, tenant, value):
    """Allow priority updates on writable records."""
    return can_write(record, tenant) and value is not None


def priority_changed(before, after):
    """Detect a material priority update."""
    return before.priority != after.priority


def can_change_created_at(record, tenant, value):
    """Allow created_at updates on writable records."""
    return can_write(record, tenant) and value is not None


def created_at_changed(before, after):
    """Detect a material created_at update."""
    return before.created_at != after.created_at


def can_change_updated_at(record, tenant, value):
    """Allow updated_at updates on writable records."""
    return can_write(record, tenant) and value is not None


def updated_at_changed(before, after):
    """Detect a material updated_at update."""
    return before.updated_at != after.updated_at


def can_change_region(record, tenant, value):
    """Allow region updates on writable records."""
    return can_write(record, tenant) and value is not None


def region_changed(before, after):
    """Detect a material region update."""
    return before.region != after.region


def can_change_category(record, tenant, value):
    """Allow category updates on writable records."""
    return can_write(record, tenant) and value is not None


def category_changed(before, after):
    """Detect a material category update."""
    return before.category != after.category


def can_change_archived(record, tenant, value):
    """Allow archived updates on writable records."""
    return can_write(record, tenant) and value is not None


def archived_changed(before, after):
    """Detect a material archived update."""
    return before.archived != after.archived
