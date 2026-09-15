"""Append-only event journal with conservative crash recovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
from uuid import uuid4

from reticle._schema import SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    sequence: int
    kind: str
    created_at: str
    payload: Dict[str, Any] = field(default_factory=dict)
    operation_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "EventEnvelope":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported event schema version: {value.get('schema_version')}")
        return cls(**value)


class EventJournal:
    """A process-local single writer for one append-only JSONL journal."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.RLock()
        events = self.read_all()
        self._next_sequence = events[-1].sequence + 1 if events else 1

    @property
    def truncated_tail_detected(self) -> bool:
        self.read_all()
        return self._truncated_tail_detected

    def new_event_id(self) -> str:
        return f"evt_{uuid4().hex}"

    def append(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        operation_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> EventEnvelope:
        with self._lock:
            if self._truncated_tail_detected:
                raise RuntimeError(
                    "Journal has an incomplete trailing record; reconcile it before appending"
                )
            event = EventEnvelope(
                event_id=event_id or self.new_event_id(),
                sequence=self._next_sequence,
                kind=kind,
                created_at=utc_now(),
                payload=payload or {},
                operation_id=operation_id,
            )
            encoded = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._next_sequence += 1
            return event

    def read_all(self) -> List[EventEnvelope]:
        with self._lock:
            events: List[EventEnvelope] = []
            self._truncated_tail_detected = False
            raw_lines = self.path.read_bytes().splitlines(keepends=True)
            for index, raw_line in enumerate(raw_lines):
                is_last = index == len(raw_lines) - 1
                if is_last and not raw_line.endswith((b"\n", b"\r")):
                    self._truncated_tail_detected = True
                    break
                try:
                    value = json.loads(raw_line.decode("utf-8"))
                    event = EventEnvelope.from_dict(value)
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError(f"Corrupt event journal at line {index + 1}: {exc}") from exc
                if event.sequence != len(events) + 1:
                    raise ValueError(
                        f"Non-contiguous event sequence at line {index + 1}: {event.sequence}"
                    )
                events.append(event)
            return events

    def incomplete_operations(self) -> Dict[str, EventEnvelope]:
        pending: Dict[str, EventEnvelope] = {}
        for event in self.read_all():
            if not event.operation_id:
                continue
            if event.kind == "action_intent":
                pending[event.operation_id] = event
            elif event.kind == "action_outcome":
                pending.pop(event.operation_id, None)
        return pending

    def operation_ids(self) -> set[str]:
        return {event.operation_id for event in self.read_all() if event.operation_id}
