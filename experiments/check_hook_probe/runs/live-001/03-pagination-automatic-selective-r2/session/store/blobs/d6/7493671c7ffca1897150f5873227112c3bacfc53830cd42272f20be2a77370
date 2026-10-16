from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    """Return {'items': list[Record], 'total': matching count} without changing input."""
    selected = page_slice(ordered(records), page, page_size)
    selected = matching(selected, owner, status)
    return {"items": selected, "total": len(selected)}
