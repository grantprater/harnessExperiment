from .query import select_events, order_events, take_page

def list_events(events, tenant, status=None, page=1, page_size=20):
    """Return items and total for a tenant-scoped event feed."""
    selected = select_events(events, tenant, status)
    ordered = order_events(selected)
    items = take_page(ordered, page, page_size)
    return {"items": items, "total": len(selected)}
