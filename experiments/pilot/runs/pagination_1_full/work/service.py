from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    """Return {'items': list[Record], 'total': matching count} without changing input."""
    filtered = matching(records, owner, status)
    total = len(filtered)
    selected = page_slice(ordered(filtered), page, page_size)
    return {"items": selected, "total": total}
