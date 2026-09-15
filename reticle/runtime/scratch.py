"""Arbitrary durable scratch content and discovery operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from reticle._schema import SCHEMA_VERSION
from reticle.runtime.events import EventJournal
from reticle.storage.artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ReferenceRecord,
    atomic_write_json,
)


@dataclass(frozen=True)
class ScratchRead:
    ref: str
    artifact: ArtifactEnvelope
    content: bytes
    start: int
    end: int
    exact: bool
    reference_version: Optional[int] = None


@dataclass(frozen=True)
class ScratchWrite:
    artifact: ArtifactEnvelope
    reference: ReferenceRecord


@dataclass(frozen=True)
class ScratchSearchHit:
    artifact_id: str
    reference_names: List[str]
    byte_offset: int
    preview: str


class ScratchPad:
    """Scratch is arbitrary bytes; labels and names are discovery metadata only."""

    def __init__(self, store: ArtifactStore, journal: EventJournal, state_path: str | Path):
        self.store = store
        self.journal = journal
        self.state_path = Path(state_path)

    def _state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": SCHEMA_VERSION, "pins": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported scratch state version: {value.get('schema_version')}")
        return value

    def write(
        self,
        name: str,
        content: bytes | str,
        expected_version: Optional[int] = None,
        media_type: str = "text/plain; charset=utf-8",
        labels: Optional[List[str]] = None,
    ) -> ScratchWrite:
        if not name or name.strip() != name:
            raise ValueError("Scratch name must be non-empty and have no surrounding whitespace")
        raw = content.encode("utf-8") if isinstance(content, str) else content
        event_id = self.journal.new_event_id()
        artifact = self.store.put(
            raw,
            media_type,
            event_id,
            labels=["scratch", *(labels or [])],
        )
        reference = self.store.update_reference(name, artifact.artifact_id, expected_version)
        self.journal.append(
            "scratch_write",
            {"artifact": artifact.to_dict(), "reference": reference.to_dict()},
            event_id=event_id,
        )
        return ScratchWrite(artifact, reference)

    def _resolve(self, ref: str) -> tuple[ArtifactEnvelope, Optional[ReferenceRecord]]:
        if ref.startswith("art_"):
            return self.store.get_envelope(ref), None
        reference = self.store.get_reference(ref)
        if reference is None:
            raise KeyError(f"Unknown scratch reference: {ref}")
        return self.store.get_envelope(reference.artifact_id), reference

    def read(self, ref: str, start: int = 0, end: Optional[int] = None) -> ScratchRead:
        artifact, reference = self._resolve(ref)
        content = self.store.read(artifact.artifact_id)
        resolved_end = len(content) if end is None else end
        if start < 0 or resolved_end < start or resolved_end > len(content):
            raise ValueError(f"Invalid byte range [{start}, {resolved_end}) for {len(content)} bytes")
        selected = content[start:resolved_end]
        return ScratchRead(
            ref=ref,
            artifact=artifact,
            content=selected,
            start=start,
            end=resolved_end,
            exact=start == 0 and resolved_end == len(content),
            reference_version=reference.version if reference else None,
        )

    def list(
        self, prefix: Optional[str] = None, labels: Optional[List[str]] = None
    ) -> List[ReferenceRecord]:
        records = self.store.list_references(prefix)
        if not labels:
            return records
        required = set(labels)
        return [
            record for record in records
            if required.issubset(self.store.get_envelope(record.artifact_id).labels)
        ]

    def search(
        self,
        query: str,
        scope: Optional[str] = None,
        limit: int = 20,
        preview_chars: int = 240,
    ) -> List[ScratchSearchHit]:
        if not query:
            raise ValueError("Search query must not be empty")
        references = self.store.list_references(scope)
        names_by_artifact: Dict[str, List[str]] = {}
        for reference in references:
            names_by_artifact.setdefault(reference.artifact_id, []).append(reference.name)
        hits: List[ScratchSearchHit] = []
        needle = query.encode("utf-8")
        for artifact_id, names in names_by_artifact.items():
            content = self.store.read(artifact_id)
            offset = content.find(needle)
            if offset < 0:
                continue
            excerpt = content[offset:offset + preview_chars].decode("utf-8", errors="replace")
            hits.append(ScratchSearchHit(artifact_id, names, offset, excerpt))
            if len(hits) >= limit:
                break
        return hits

    def pin(self, ref: str, priority: int = 0) -> None:
        artifact, reference = self._resolve(ref)
        state = self._state()
        state["pins"][ref] = {
            "priority": int(priority),
            "artifact_id": artifact.artifact_id,
            "reference_version": reference.version if reference else None,
        }
        atomic_write_json(self.state_path, state)
        self.journal.append("scratch_pin", {"ref": ref, **state["pins"][ref]})

    def unpin(self, ref: str) -> bool:
        state = self._state()
        existed = state["pins"].pop(ref, None) is not None
        if existed:
            atomic_write_json(self.state_path, state)
            self.journal.append("scratch_unpin", {"ref": ref})
        return existed

    def pins(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._state()["pins"])

    def forget(self, name: str, expected_version: Optional[int] = None) -> ReferenceRecord:
        record = self.store.forget_reference(name, expected_version)
        self.unpin(name)
        self.journal.append("scratch_forget", {"reference": record.to_dict()})
        return record
