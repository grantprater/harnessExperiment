from .query import select_events, order_events, take_page

def list_events(events, tenant, status=None, page=1, page_size=20):
    """Return items and total for a tenant-scoped event feed."""
    selected = order_events(select_events(events, tenant, status))
    return {"items": take_page(selected, page, page_size), "total": len(selected)}
