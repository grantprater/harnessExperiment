"""In-memory Key-Value store engine with TTL and snapshot support."""

from __future__ import annotations

import json
import time
from typing import Dict, Optional
from models import KVEntry


class KVStore:
    def __init__(self) -> None:
        self._store: Dict[str, KVEntry] = {}

    def set(self, key: str, value: str, ttl_seconds: Optional[float] = None) -> None:
        """Stores a key-value pair. If ttl_seconds is provided, sets expires_at to time.time() + ttl_seconds."""
        expires_at = None if ttl_seconds is None else time.time() + ttl_seconds
        self._store[key] = KVEntry(key, value, expires_at)
    def get(self, key: str) -> Optional[str]:
        """Returns the value for key. If key is missing or expired, removes it if expired and returns None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._store[key]
            return None
        return entry.value

    def delete(self, key: str) -> bool:
        """Deletes key from store. Returns True if deleted, False if key did not exist."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def export_json(self) -> str:
        """Returns a JSON string of all currently unexpired key -> value mappings."""
        data = {k: e.value for k, e in self._store.items() if not e.is_expired()}
        return json.dumps(data)

    def import_json(self, json_str: str) -> int:
        """Loads key -> value pairs from a JSON string into store. Returns count of loaded keys."""
        data = json.loads(json_str)
        for key, value in data.items():
            self._store[key] = KVEntry(key, value)
        return len(data)
