"""Cross-process exclusive writer ownership for a durable session."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import BinaryIO, Optional

from reticle.runtime.events import utc_now
from reticle.storage.artifacts import atomic_write_json


class SessionOwnedError(RuntimeError):
    pass


class SessionWriterLock:
    """Hold one non-blocking OS file lock for the lifetime of a controller run."""

    def __init__(self, session_dir: str | Path):
        root = Path(session_dir)
        self.lock_path = root / "writer.lock"
        self.owner_path = root / "writer-owner.json"
        self._stream: Optional[BinaryIO] = None
        self.owner_id: Optional[str] = None

    def _try_lock(self, stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SessionOwnedError(self._owner_message()) from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SessionOwnedError(self._owner_message()) from exc

    def _unlock(self, stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _owner_message(self) -> str:
        try:
            owner = json.loads(self.owner_path.read_text(encoding="utf-8"))
            return f"Session already has an active writer: {owner.get('owner_id', 'unknown')}"
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return "Session already has an active writer"

    def acquire(self, owner_id: str) -> "SessionWriterLock":
        if self._stream is not None:
            raise RuntimeError("Writer lock is already held by this object")
        if not owner_id:
            raise ValueError("owner_id must not be empty")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.lock_path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        try:
            self._try_lock(stream)
        except Exception:
            stream.close()
            raise
        self._stream = stream
        self.owner_id = owner_id
        atomic_write_json(self.owner_path, {
            "owner_id": owner_id,
            "pid": os.getpid(),
            "acquired_at": utc_now(),
        })
        return self

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            try:
                self.owner_path.unlink()
            except FileNotFoundError:
                pass
            self._unlock(stream)
        finally:
            stream.close()
            self._stream = None
            self.owner_id = None

    def __enter__(self) -> "SessionWriterLock":
        if self._stream is None:
            raise RuntimeError("Call acquire(owner_id) before entering the writer lock")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
