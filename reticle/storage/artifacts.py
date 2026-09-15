"""Immutable blobs and atomic mutable references for durable runtime state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Dict, List, Optional
from uuid import uuid4

from reticle._schema import SCHEMA_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    encoded = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write_bytes(path, encoded)


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_id: str
    content_hash: str
    media_type: str
    byte_length: int
    created_at: str
    producer_event_id: str
    parent_artifact_ids: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ArtifactEnvelope":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported artifact schema version: {value.get('schema_version')}")
        return cls(**value)


@dataclass(frozen=True)
class ReferenceRecord:
    name: str
    artifact_id: str
    version: int
    updated_at: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StaleReferenceError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        self.metadata_dir = self.root / "artifacts"
        self.references_path = self.root / "references.json"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._reference_lock = threading.Lock()
        self._blob_lock = threading.Lock()

    def put(
        self,
        content: bytes,
        media_type: str,
        producer_event_id: str,
        parent_artifact_ids: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
    ) -> ArtifactEnvelope:
        content_hash = hashlib.sha256(content).hexdigest()
        blob_path = self.blob_dir / content_hash[:2] / content_hash[2:]
        with self._blob_lock:
            if blob_path.exists():
                existing = blob_path.read_bytes()
                if hashlib.sha256(existing).hexdigest() != content_hash:
                    raise ValueError(f"Existing blob failed integrity check: {content_hash}")
            else:
                atomic_write_bytes(blob_path, content)
        artifact = ArtifactEnvelope(
            artifact_id=f"art_{uuid4().hex}",
            content_hash=content_hash,
            media_type=media_type,
            byte_length=len(content),
            created_at=_utc_now(),
            producer_event_id=producer_event_id,
            parent_artifact_ids=list(parent_artifact_ids or []),
            labels=list(labels or []),
        )
        atomic_write_json(self.metadata_dir / f"{artifact.artifact_id}.json", artifact.to_dict())
        return artifact

    def get_envelope(self, artifact_id: str) -> ArtifactEnvelope:
        if not artifact_id.startswith("art_") or not artifact_id[4:].isalnum():
            raise ValueError(f"Invalid artifact ID: {artifact_id}")
        path = self.metadata_dir / f"{artifact_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(f"Unknown artifact: {artifact_id}") from exc
        return ArtifactEnvelope.from_dict(value)

    def read(self, artifact_id: str) -> bytes:
        envelope = self.get_envelope(artifact_id)
        blob_path = self.blob_dir / envelope.content_hash[:2] / envelope.content_hash[2:]
        try:
            content = blob_path.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Artifact blob unavailable: {artifact_id}") from exc
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != envelope.content_hash or len(content) != envelope.byte_length:
            raise ValueError(f"Artifact integrity check failed: {artifact_id}")
        return content

    def _read_references(self) -> Dict[str, Dict[str, Any]]:
        if not self.references_path.exists():
            return {}
        value = json.loads(self.references_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported reference index version: {value.get('schema_version')}")
        return value.get("references", {})

    def get_reference(self, name: str) -> Optional[ReferenceRecord]:
        value = self._read_references().get(name)
        return ReferenceRecord(**value) if value else None

    def list_references(self, prefix: Optional[str] = None) -> List[ReferenceRecord]:
        records = [ReferenceRecord(**value) for value in self._read_references().values()]
        if prefix is not None:
            records = [record for record in records if record.name.startswith(prefix)]
        return sorted(records, key=lambda record: record.name)

    def list_artifacts(self, labels: Optional[List[str]] = None) -> List[ArtifactEnvelope]:
        required = set(labels or [])
        artifacts: List[ArtifactEnvelope] = []
        for path in sorted(self.metadata_dir.glob("art_*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            artifact = ArtifactEnvelope.from_dict(value)
            if required.issubset(artifact.labels):
                artifacts.append(artifact)
        return artifacts

    def update_reference(
        self,
        name: str,
        artifact_id: str,
        expected_version: Optional[int] = None,
    ) -> ReferenceRecord:
        self.get_envelope(artifact_id)
        with self._reference_lock:
            references = self._read_references()
            current = references.get(name)
            current_version = current["version"] if current else 0
            if expected_version is not None and expected_version != current_version:
                raise StaleReferenceError(
                    f"Reference '{name}' is version {current_version}, expected {expected_version}"
                )
            record = ReferenceRecord(
                name=name,
                artifact_id=artifact_id,
                version=current_version + 1,
                updated_at=_utc_now(),
            )
            references[name] = record.to_dict()
            atomic_write_json(
                self.references_path,
                {"schema_version": SCHEMA_VERSION, "references": references},
            )
            return record

    def read_reference(self, name: str) -> bytes:
        reference = self.get_reference(name)
        if reference is None:
            raise KeyError(f"Unknown reference: {name}")
        return self.read(reference.artifact_id)

    def forget_reference(
        self,
        name: str,
        expected_version: Optional[int] = None,
    ) -> ReferenceRecord:
        """Remove a mutable name while leaving its immutable artifact intact."""
        with self._reference_lock:
            references = self._read_references()
            value = references.get(name)
            if value is None:
                raise KeyError(f"Unknown reference: {name}")
            record = ReferenceRecord(**value)
            if expected_version is not None and record.version != expected_version:
                raise StaleReferenceError(
                    f"Reference '{name}' is version {record.version}, expected {expected_version}"
                )
            del references[name]
            atomic_write_json(
                self.references_path,
                {"schema_version": SCHEMA_VERSION, "references": references},
            )
            return record
