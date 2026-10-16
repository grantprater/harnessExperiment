from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    """Return {'items': list[Record], 'total': matching count} without changing input."""
    selected = matching(records, owner, status)
    items = page_slice(ordered(selected), page, page_size)
    return {"items": items, "total": len(selected)}
