def matching(records, owner, status=None):
    """Select records belonging to owner and, when supplied, matching status."""
    return [r for r in records if r.owner == owner and (status is None or r.status == status)]

def ordered(records):
    """Newest first, with ascending id for identical timestamps."""
    return sorted(records, key=lambda r: (-r.created_at, r.id))

def page_slice(records, page, page_size):
    """Return a one-based page; reject nonpositive page or page_size."""
    if page <= 0 or page_size <= 0:
        raise ValueError("Positive page and size required")
    start = (page - 1) * page_size
    return records[start:start + page_size]
