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
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        """Returns the value for key. If key is missing or expired, removes it if expired and returns None."""
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        """Deletes key from store. Returns True if deleted, False if key did not exist."""
        raise NotImplementedError

    def export_json(self) -> str:
        """Returns a JSON string of all currently unexpired key -> value mappings."""
        raise NotImplementedError

    def import_json(self, json_str: str) -> int:
        """Loads key -> value pairs from a JSON string into store. Returns count of loaded keys."""
        raise NotImplementedError
