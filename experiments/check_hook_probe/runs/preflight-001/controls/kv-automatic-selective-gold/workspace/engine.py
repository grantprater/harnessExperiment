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
        if ttl_seconds is not None:
            self._store[key] = KVEntry(key, value, time.time() + ttl_seconds)
        else:
            self._store[key] = KVEntry(key, value)

    def get(self, key: str) -> Optional[str]:
        """Returns the value for key. If key is missing or expired, removes it if expired and returns None."""
        if key not in self._store:
            return None
        entry = self._store[key]
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
        unexpired = {k: v.value for k, v in self._store.items() if not v.is_expired()}
        return json.dumps(unexpired)

    def import_json(self, json_str: str) -> int:
        """Loads key -> value pairs from a JSON string into store. Returns count of loaded keys."""
        data = json.loads(json_str)
        count = 0
        for key, value in data.items():
            self.set(key, value)
            count += 1
        return count
