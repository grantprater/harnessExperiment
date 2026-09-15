"""Minimal restartable local runtime built on journals and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from reticle.runtime.contracts import SCHEMA_VERSION, TaskEnvelope, ToolResultEnvelope
from reticle.runtime.events import EventEnvelope, EventJournal, utc_now
from reticle.runtime.workspace import WorkspaceObservation, WorkspaceTracker
from reticle.runtime.scratch import ScratchPad
from reticle.storage.artifacts import ArtifactEnvelope, ArtifactStore, atomic_write_json


@dataclass(frozen=True)
class PendingOperationState:
    operation_id: str
    operation_kind: str
    classification: str
    replay_safe: bool
    evidence_event_ids: List[str]
    call_id: Optional[str] = None


@dataclass(frozen=True)
class RecoveryState:
    incomplete_operation_ids: List[str]
    truncated_journal_tail: bool
    pending_operations: List[PendingOperationState]


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
            pending_operations=self._classify_pending_operations(),
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

    def persist_task_contract(self, task: TaskEnvelope) -> None:
        existing = [
            event.payload.get("task") for event in self.journal.read_all()
            if event.kind == "task_contract" and event.payload.get("task", {}).get("task_id") == task.task_id
        ]
        value = task.to_dict()
        if existing:
            if existing[0] != value:
                raise ValueError(f"Task contract changed on resume for {task.task_id}")
            return
        self.journal.append("task_contract", {"task": value})

    def begin_action(self, operation_id: str, action: str, arguments: Dict[str, Any]) -> EventEnvelope:
        if operation_id in self.journal.operation_ids():
            raise ValueError(f"Operation ID was already used: {operation_id}")
        return self.journal.append(
            "action_intent",
            {
                "action": action,
                "arguments": arguments,
                "workspace_revision_at_intent": self.workspace.revision(),
            },
            operation_id=operation_id,
        )

    def mark_action_dispatched(self, operation_id: str, effect_class: str) -> EventEnvelope:
        pending = self.journal.incomplete_operations()
        if operation_id not in pending:
            raise ValueError(f"No incomplete action: {operation_id}")
        if any(
            event.operation_id == operation_id and event.kind == "action_dispatched"
            for event in self.journal.read_all()
        ):
            raise ValueError(f"Action was already dispatched: {operation_id}")
        return self.journal.append(
            "action_dispatched",
            {"effect_class": effect_class, "workspace_revision": self.workspace.revision()},
            operation_id=operation_id,
        )

    def abandon_not_started_action(self, operation_id: str, reason: str) -> EventEnvelope:
        state = next(
            (item for item in self._classify_pending_operations() if item.operation_id == operation_id),
            None,
        )
        if state is None or state.classification != "known_not_started":
            raise ValueError(f"Action is not known-not-started: {operation_id}")
        return self.journal.append(
            "action_abandoned", {"reason": reason}, operation_id=operation_id
        )

    def _classify_pending_operations(self) -> List[PendingOperationState]:
        events = self.journal.read_all()
        by_operation: Dict[str, List[EventEnvelope]] = {}
        for event in events:
            if event.operation_id:
                by_operation.setdefault(event.operation_id, []).append(event)
        transcript_call_ids: set[str] = set()
        for event in events:
            if event.kind != "transcript_message":
                continue
            try:
                message = json.loads(self.artifacts.read(event.payload["artifact_id"]).decode("utf-8"))
            except (KeyError, FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str):
                transcript_call_ids.add(call_id)

        states: List[PendingOperationState] = []
        for operation_id, operation_events in by_operation.items():
            intent = next((event for event in operation_events if event.kind == "action_intent"), None)
            model_intent = next(
                (event for event in operation_events if event.kind == "model_request_intent"), None
            )
            if intent is None and model_intent is not None:
                terminal = next(
                    (
                        event for event in events
                        if event.kind in {"model_call", "model_call_failed"}
                        and event.payload.get("attempt_id") == operation_id
                    ),
                    None,
                )
                if terminal is None:
                    states.append(PendingOperationState(
                        operation_id, "model_request", "unknown_external_outcome", False,
                        [event.event_id for event in operation_events], None,
                    ))
                continue
            if intent is None:
                continue
            dispatched = next((event for event in operation_events if event.kind == "action_dispatched"), None)
            outcome = next((event for event in operation_events if event.kind == "action_outcome"), None)
            abandoned = next((event for event in operation_events if event.kind == "action_abandoned"), None)
            if abandoned is not None:
                continue
            call_id = None
            if outcome is not None:
                value = outcome.payload.get("result", {}).get("call_id")
                call_id = value if isinstance(value, str) else None
            else:
                value = intent.payload.get("arguments", {}).get("call_id")
                call_id = value if isinstance(value, str) else None
            evidence = [event.event_id for event in operation_events]
            if outcome is not None:
                if call_id and self._assistant_called(events, call_id) and call_id not in transcript_call_ids:
                    states.append(PendingOperationState(
                        operation_id, str(intent.payload.get("action", "unknown")),
                        "known_complete_unpublished", True, evidence, call_id,
                    ))
                continue
            if dispatched is None:
                states.append(PendingOperationState(
                    operation_id, str(intent.payload.get("action", "unknown")),
                    "known_not_started", True, evidence, call_id,
                ))
                continue
            effect_class = str(dispatched.payload.get("effect_class", "unknown"))
            states.append(PendingOperationState(
                operation_id, str(intent.payload.get("action", "unknown")),
                "unknown_external_outcome", effect_class == "read_only", evidence, call_id,
            ))
        return sorted(states, key=lambda state: state.operation_id)

    def _assistant_called(self, events: List[EventEnvelope], call_id: str) -> bool:
        for event in events:
            if event.kind != "transcript_message":
                continue
            try:
                message = json.loads(self.artifacts.read(event.payload["artifact_id"]).decode("utf-8"))
            except (KeyError, FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            if any(call.get("id") == call_id for call in message.get("tool_calls", [])):
                return True
        return False

    def repair_completed_action_publications(self) -> List[str]:
        """Publish persisted tool outcomes missing from the transcript; never rerun actions."""
        from reticle.context.baseline import TranscriptStore

        repaired: List[str] = []
        events = self.journal.read_all()
        for state in self._classify_pending_operations():
            if state.classification != "known_complete_unpublished" or not state.call_id:
                continue
            outcome = next(
                event for event in events
                if event.operation_id == state.operation_id and event.kind == "action_outcome"
            )
            result = outcome.payload["result"]
            content = b""
            if result.get("stdout_ref"):
                content += self.artifacts.read(result["stdout_ref"])
            if result.get("stderr_ref"):
                if content:
                    content += b"\n"
                content += self.artifacts.read(result["stderr_ref"])
            message: Dict[str, Any] = {
                "role": "tool",
                "tool_call_id": state.call_id,
                "content": content.decode("utf-8", errors="replace"),
            }
            output = next(
                (
                    event for event in events
                    if event.kind == "tool_output" and event.payload.get("call_id") == state.call_id
                ),
                None,
            )
            if output is not None:
                message["_reticle_output"] = {
                    "handle": output.payload.get("handle"),
                    "tool": output.payload.get("tool"),
                    "status": result.get("status"),
                }
            TranscriptStore(self).append(message)
            self.journal.append("transcript_publication_repaired", {
                "operation_id": state.operation_id,
                "call_id": state.call_id,
                "outcome_event_id": outcome.event_id,
            })
            repaired.append(state.operation_id)
        self.recovery = RecoveryState(
            incomplete_operation_ids=sorted(self.journal.incomplete_operations()),
            truncated_journal_tail=self.journal.truncated_tail_detected,
            pending_operations=self._classify_pending_operations(),
        )
        return repaired

    @staticmethod
    def _normalized_assistant(message: Dict[str, Any], call_index: int) -> Dict[str, Any]:
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        calls = []
        for position, call in enumerate(message.get("tool_calls") or [], 1):
            function = call.get("function") or {}
            arguments = function.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            calls.append({
                "id": call.get("id") or f"call_{call_index}_{position}",
                "type": "function",
                "function": {"name": str(function.get("name") or ""), "arguments": arguments},
            })
        normalized: Dict[str, Any] = {"role": "assistant", "content": content or (None if calls else "")}
        if calls:
            normalized["tool_calls"] = calls
        if message.get("reasoning_details"):
            normalized["reasoning_details"] = message["reasoning_details"]
        return normalized

    def repair_model_response_publications(self) -> List[str]:
        """Publish durable provider responses that were not added to the transcript."""
        from reticle.context.baseline import TranscriptStore

        events = self.journal.read_all()
        transcript = TranscriptStore(self).load()
        published_attempts = {
            message.get("_reticle_attempt_id") for message in transcript
            if isinstance(message.get("_reticle_attempt_id"), str)
        }
        published_call_ids = {
            call.get("id")
            for message in transcript if message.get("role") == "assistant"
            for call in message.get("tool_calls", [])
        }
        published_text = {
            message.get("content") for message in transcript
            if message.get("role") == "assistant" and not message.get("tool_calls")
            and isinstance(message.get("content"), (str, type(None)))
        }
        repaired: List[str] = []
        for event in events:
            if event.kind != "model_call":
                continue
            raw = json.loads(self.artifacts.read(event.payload["response_artifact_id"]).decode("utf-8"))
            normalized = self._normalized_assistant(raw, int(event.payload.get("call_index", 1)))
            attempt_id = event.payload.get("attempt_id")
            if isinstance(attempt_id, str) and attempt_id in published_attempts:
                continue
            ids = {call.get("id") for call in normalized.get("tool_calls", [])}
            already_published = (
                bool(ids) and ids.issubset(published_call_ids)
            ) or (not ids and normalized.get("content") in published_text)
            if already_published:
                continue
            if isinstance(attempt_id, str):
                normalized["_reticle_attempt_id"] = attempt_id
            TranscriptStore(self).append(normalized)
            self.journal.append("model_response_publication_repaired", {
                "attempt_id": event.payload.get("attempt_id"),
                "model_call_event_id": event.event_id,
                "response_artifact_id": event.payload["response_artifact_id"],
            })
            published_call_ids.update(ids)
            if isinstance(attempt_id, str):
                published_attempts.add(attempt_id)
            if not ids:
                published_text.add(normalized.get("content"))
            repaired.append(str(event.payload.get("attempt_id", event.event_id)))
        return repaired

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
