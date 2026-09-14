from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    selected = ordered(matching(records, owner, status))
    return {"items": page_slice(selected, page, page_size), "total": len(selected)}
