"""Workspace revision tracking and version-checked atomic writes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Optional

from reticle.storage.artifacts import atomic_write_bytes


class StaleWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceObservation:
    path: str
    content: bytes
    content_hash: str
    workspace_revision: str


class WorkspaceTracker:
    def __init__(self, root: str | Path, excluded_root: Optional[str | Path] = None):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.root}")
        self.excluded_root = Path(excluded_root).resolve() if excluded_root else None

    def _resolve(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {relative_path}") from exc
        return path

    def _is_excluded(self, path: Path) -> bool:
        if self.excluded_root is None:
            return False
        try:
            path.resolve().relative_to(self.excluded_root)
            return True
        except ValueError:
            return False

    def revision(self) -> str:
        digest = hashlib.sha256()
        files = sorted(
            path for path in self.root.rglob("*")
            if path.is_file() and not self._is_excluded(path)
        )
        for path in files:
            relative = path.relative_to(self.root).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return f"sha256:{digest.hexdigest()}"

    def read(self, relative_path: str) -> WorkspaceObservation:
        path = self._resolve(relative_path)
        for _ in range(3):
            before = self.revision()
            content = path.read_bytes()
            after = self.revision()
            if before == after:
                return WorkspaceObservation(
                    path=relative_path,
                    content=content,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    workspace_revision=after,
                )
        raise RuntimeError(f"Workspace changed repeatedly while reading: {relative_path}")

    def write(
        self,
        relative_path: str,
        content: bytes,
        expected_workspace_revision: Optional[str] = None,
        expected_content_hash: Optional[str] = None,
    ) -> tuple[str, str]:
        before = self.revision()
        if expected_workspace_revision is not None and expected_workspace_revision != before:
            raise StaleWorkspaceError(
                f"Workspace revision is {before}, expected {expected_workspace_revision}"
            )
        path = self._resolve(relative_path)
        current = path.read_bytes() if path.exists() else None
        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
        if expected_content_hash is not None and expected_content_hash != current_hash:
            raise StaleWorkspaceError(
                f"File '{relative_path}' hash is {current_hash}, expected {expected_content_hash}"
            )
        atomic_write_bytes(path, content)
        return before, self.revision()
