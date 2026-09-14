from .query import select_events, order_events, take_page

def list_events(events, tenant, status=None, page=1, page_size=20):
    """Return items and total for a tenant-scoped event feed."""
    selected = select_events(take_page(order_events(events), page, page_size), tenant, status)
    return {"items": selected, "total": len(selected)}
