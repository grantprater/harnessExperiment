"""Cache key normalization."""

def feed_key(tenant, status, page):
    """Build an immutable identity for a feed request."""
    return (page,)

def document_key(tenant, document_id):
    return ("document", tenant, document_id)

def cache_namespace(environment, version):
    return f"{environment}:v{version}"
