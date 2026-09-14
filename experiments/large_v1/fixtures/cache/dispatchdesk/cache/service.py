"""Caching facade for materialized event feeds."""
import time
from .keys import feed_key
from .storage import MemoryBackend

class FeedCache:
    def __init__(self, ttl=30.0, clock=None):
        self.ttl = ttl
        self.clock = clock or time.time
        self.backend = MemoryBackend()

    def get(self, tenant, status, page, loader):
        """Reuse a matching unexpired entry, otherwise call loader()."""
        now = self.clock()
        key = feed_key(tenant, status, page)
        entry = self.backend.lookup(key, now)
        if entry is not None:
            return entry.value
        value = loader()
        self.backend.put(key, value, now + self.ttl)
        return value
