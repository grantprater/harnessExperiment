"""Minimal restartable local runtime built on journals and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from reticle.runtime.contracts import SCHEMA_VERSION, ToolResultEnvelope
from reticle.runtime.events import EventEnvelope, EventJournal, utc_now
from reticle.runtime.workspace import WorkspaceObservation, WorkspaceTracker
from reticle.runtime.scratch import ScratchPad
from reticle.storage.artifacts import ArtifactEnvelope, ArtifactStore, atomic_write_json


@dataclass(frozen=True)
class RecoveryState:
    incomplete_operation_ids: List[str]
    truncated_journal_tail: bool


class LocalRuntime:
    """Single-controller runtime for durable local operations.

    This class records intent and outcome but does not automatically replay an
    incomplete operation after restart.
    """

    def __init__(self, session_dir: str | Path, workspace_dir: Optional[str | Path] = None):
        self.session_dir = Path(session_dir).resolve()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.configuration_path = self.session_dir / "session.json"
        configured_workspace = self._load_or_create_configuration(workspace_dir)
        self.workspace = WorkspaceTracker(configured_workspace, excluded_root=self.session_dir)
        self.artifacts = ArtifactStore(self.session_dir / "store")
        self.journal = EventJournal(self.session_dir / "events.jsonl")
        self.scratch = ScratchPad(
            self.artifacts, self.journal, self.session_dir / "scratch-state.json"
        )
        self.checkpoint_path = self.session_dir / "checkpoint.json"
        self.recovery = RecoveryState(
            incomplete_operation_ids=sorted(self.journal.incomplete_operations()),
            truncated_journal_tail=self.journal.truncated_tail_detected,
        )

    def _load_or_create_configuration(self, workspace_dir: Optional[str | Path]) -> Path:
        if self.configuration_path.exists():
            value = json.loads(self.configuration_path.read_text(encoding="utf-8"))
            if value.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"Unsupported session version: {value.get('schema_version')}")
            configured = Path(value["workspace_root"]).resolve()
            if workspace_dir is not None and Path(workspace_dir).resolve() != configured:
                raise ValueError(
                    f"Session workspace is {configured}, not {Path(workspace_dir).resolve()}"
                )
            return configured
        if workspace_dir is None:
            raise ValueError("workspace_dir is required when creating a session")
        configured = Path(workspace_dir).resolve()
        if not configured.is_dir():
            raise ValueError(f"Workspace is not a directory: {configured}")
        atomic_write_json(
            self.configuration_path,
            {"schema_version": SCHEMA_VERSION, "workspace_root": str(configured)},
        )
        return configured

    def begin_action(self, operation_id: str, action: str, arguments: Dict[str, Any]) -> EventEnvelope:
        if operation_id in self.journal.operation_ids():
            raise ValueError(f"Operation ID was already used: {operation_id}")
        return self.journal.append(
            "action_intent",
            {"action": action, "arguments": arguments},
            operation_id=operation_id,
        )

    def complete_action(
        self,
        operation_id: str,
        result: ToolResultEnvelope,
    ) -> EventEnvelope:
        pending = self.journal.incomplete_operations()
        if operation_id not in pending:
            raise ValueError(f"No incomplete action: {operation_id}")
        return self.journal.append(
            "action_outcome",
            {"result": result.to_dict()},
            operation_id=operation_id,
        )

    def record_tool_result(
        self,
        operation_id: str,
        call_id: str,
        status: str,
        workspace_revision_before: str,
        workspace_revision_after: str,
        stdout: Optional[bytes] = None,
        stderr: Optional[bytes] = None,
        output_artifact_ids: Optional[List[str]] = None,
        exit_code: Optional[int] = None,
        duration_ms: int = 0,
        usage: Optional[Dict[str, Any]] = None,
        error_kind: Optional[str] = None,
        retry_hint: Optional[str] = None,
        preview_limit: int = 2_000,
    ) -> ToolResultEnvelope:
        if self.journal.truncated_tail_detected:
            raise RuntimeError("Cannot record a result while the journal tail is incomplete")
        if operation_id not in self.journal.incomplete_operations():
            raise ValueError(f"No incomplete action: {operation_id}")
        event_id = self.journal.new_event_id()
        stdout_ref = None
        stderr_ref = None
        if stdout is not None:
            stdout_ref = self.artifacts.put(
                stdout, "text/plain", event_id, labels=["tool-stdout", call_id]
            ).artifact_id
        if stderr is not None:
            stderr_ref = self.artifacts.put(
                stderr, "text/plain", event_id, labels=["tool-stderr", call_id]
            ).artifact_id
        preview_bytes = b""
        if stdout:
            preview_bytes += stdout
        if stderr:
            if preview_bytes:
                preview_bytes += b"\n"
            preview_bytes += stderr
        preview_truncated = len(preview_bytes) > preview_limit
        preview = preview_bytes[:preview_limit].decode("utf-8", errors="replace")
        if preview_truncated:
            preview += f"\n[truncated: {len(preview_bytes) - preview_limit} bytes omitted]"
        result = ToolResultEnvelope(
            call_id=call_id,
            status=status,
            workspace_revision_before=workspace_revision_before,
            workspace_revision_after=workspace_revision_after,
            exit_code=exit_code,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            output_refs=list(output_artifact_ids or []),
            preview=preview,
            preview_truncated=preview_truncated,
            duration_ms=duration_ms,
            usage=dict(usage or {}),
            error_kind=error_kind,
            retry_hint=retry_hint,
        )
        self.journal.append(
            "action_outcome",
            {"result": result.to_dict()},
            operation_id=operation_id,
            event_id=event_id,
        )
        return result

    def record_observation(
        self,
        content: bytes,
        media_type: str = "application/octet-stream",
        labels: Optional[List[str]] = None,
        name: Optional[str] = None,
        expected_reference_version: Optional[int] = None,
    ) -> ArtifactEnvelope:
        if self.journal.truncated_tail_detected:
            raise RuntimeError("Cannot record an observation while the journal tail is incomplete")
        event_id = self.journal.new_event_id()
        artifact = self.artifacts.put(
            content,
            media_type=media_type,
            producer_event_id=event_id,
            labels=labels,
        )
        reference = None
        if name is not None:
            reference = self.artifacts.update_reference(
                name, artifact.artifact_id, expected_version=expected_reference_version
            )
        payload: Dict[str, Any] = {"artifact": artifact.to_dict()}
        if reference is not None:
            payload["reference"] = reference.to_dict()
        self.journal.append("observation", payload, event_id=event_id)
        return artifact

    def observe_file(self, relative_path: str) -> tuple[WorkspaceObservation, ArtifactEnvelope]:
        observation = self.workspace.read(relative_path)
        artifact = self.record_observation(
            observation.content,
            media_type="application/octet-stream",
            labels=["workspace-observation", relative_path],
        )
        return observation, artifact

    def checkpoint(self) -> Dict[str, Any]:
        workspace_revision = self.workspace.revision()
        incomplete = sorted(self.journal.incomplete_operations())
        checkpoint_event = self.journal.append(
            "checkpoint",
            {
                "workspace_revision": workspace_revision,
                "incomplete_operation_ids": incomplete,
            },
        )
        value = {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "last_event_sequence": checkpoint_event.sequence,
            "workspace_revision": workspace_revision,
            "incomplete_operation_ids": incomplete,
        }
        atomic_write_json(self.checkpoint_path, value)
        return value

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        if not self.checkpoint_path.exists():
            return None
        value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported checkpoint version: {value.get('schema_version')}")
        return value
