from .query import select_events, order_events, take_page

def list_events(events, tenant, status=None, page=1, page_size=20):
    """Return items and total for a tenant-scoped event feed."""
    matching = select_events(order_events(events), tenant, status)
    selected = take_page(matching, page, page_size)
    return {"items": selected, "total": len(matching)}
