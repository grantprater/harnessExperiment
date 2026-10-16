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
        return self._store.pop(key, None) is not None

    def export_json(self) -> str:
        """Returns a JSON string of all currently unexpired key -> value mappings."""
        now = time.time()
        return json.dumps({key: entry.value for key, entry in self._store.items()
                           if not entry.is_expired(now)})

    def import_json(self, json_str: str) -> int:
        """Loads key -> value pairs from a JSON string into store. Returns count of loaded keys."""
        snapshot = json.loads(json_str)
        if not isinstance(snapshot, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in snapshot.items()
        ):
            raise ValueError("Snapshot must be an object mapping string keys to string values")
        for key, value in snapshot.items():
            self.set(key, value)
        return len(snapshot)
