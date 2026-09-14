from typing import Optional
from dataclasses import dataclass
import time


@dataclass
class KVEntry:
    key: str
    value: str
    expires_at: Optional[float] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Returns True if entry has an expiration timestamp and current time >= expires_at."""
        if self.expires_at is None:
            return False
        if now is None:
            now = time.time()
        return now >= self.expires_at
