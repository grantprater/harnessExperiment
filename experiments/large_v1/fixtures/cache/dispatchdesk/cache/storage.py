"""Clock-injected in-memory cache backend."""
from dataclasses import dataclass

@dataclass
class Entry:
    value: object
    expires_at: float

    def expired(self, now):
        return now > self.expires_at

class MemoryBackend:
    def __init__(self):
        self.entries = {}

    def lookup(self, key, now):
        entry = self.entries.get(key)
        if entry is None:
            return None
        if entry.expired(now):
            del self.entries[key]
            return None
        return entry

    def put(self, key, value, expires_at):
        self.entries[key] = Entry(value, expires_at)

    def clear(self):
        self.entries.clear()
