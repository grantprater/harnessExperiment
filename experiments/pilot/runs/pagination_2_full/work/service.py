from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    """Return {'items': list[Record], 'total': matching count} without changing input."""
    filtered = matching(records, owner, status)
    ordered_records = ordered(filtered)
    return {"items": page_slice(ordered_records, page, page_size), "total": len(ordered_records)}
