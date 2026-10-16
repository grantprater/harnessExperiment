"""Unit test contract for the Key-Value store."""

import sys
import time
import unittest
from pathlib import Path

# Ensure local imports resolve
sys.path.insert(0, str(Path(__file__).parent))

from models import KVEntry
from engine import KVStore


class TestKVStore(unittest.TestCase):
    def setUp(self):
        self.store = KVStore()

    def test_basic_set_and_get(self):
        self.store.set("user:101", "Alice")
        self.assertEqual(self.store.get("user:101"), "Alice")
        self.assertIsNone(self.store.get("missing_key"))

    def test_delete_key(self):
        self.store.set("temp", "value")
        self.assertTrue(self.store.delete("temp"))
        self.assertFalse(self.store.delete("temp")) # Second delete returns False
        self.assertIsNone(self.store.get("temp"))

    def test_ttl_expiration(self):
        # Short TTL of 0.1 seconds
        self.store.set("ephemeral", "flash_data", ttl_seconds=0.1)
        self.assertEqual(self.store.get("ephemeral"), "flash_data")
        time.sleep(0.15)
        # Should now be expired and return None
        self.assertIsNone(self.store.get("ephemeral"))

    def test_models_is_expired_method(self):
        now = 1000.0
        active_entry = KVEntry(key="k1", value="v1", expires_at=1050.0)
        expired_entry = KVEntry(key="k2", value="v2", expires_at=950.0)
        permanent_entry = KVEntry(key="k3", value="v3", expires_at=None)

        self.assertFalse(active_entry.is_expired(now=now))
        self.assertTrue(expired_entry.is_expired(now=now))
        self.assertFalse(permanent_entry.is_expired(now=now))

    def test_json_export_and_import(self):
        self.store.set("k1", "v1")
        self.store.set("k2", "v2")
        self.store.set("k_expired", "old", ttl_seconds=0.05)
        time.sleep(0.08)

        json_export = self.store.export_json()
        
        # Fresh store instance imports exported snapshot
        new_store = KVStore()
        count = new_store.import_json(json_export)

        self.assertEqual(count, 2)
        self.assertEqual(new_store.get("k1"), "v1")
        self.assertEqual(new_store.get("k2"), "v2")
        self.assertIsNone(new_store.get("k_expired"))


if __name__ == "__main__":
    unittest.main()
