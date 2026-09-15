"""Authorized, stable paging and literal search over durable session history."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence

from reticle.runtime.events import EventEnvelope
from reticle.runtime.session import LocalRuntime


MODEL_VISIBLE_KINDS = {
    "action_intent",
    "action_outcome",
    "checkpoint",
    "observation",
    "observation_view",
    "scratch_forget",
    "scratch_pin",
    "scratch_unpin",
    "scratch_write",
    "tool_output",
    "transcript_message",
}
RETRIEVAL_TOOLS = {"history", "search_history", "read_artifact", "read_output", "search_output"}
SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "cookie", "credential", "credentials",
    "password", "secret", "token",
}
DENIED_ARTIFACT_LABELS = {"controller-only", "credential", "credentials", "evaluator", "secret"}


@dataclass(frozen=True)
class HistoryPage:
    records: List[Dict[str, Any]]
    next_cursor: Optional[str]
    high_water_sequence: int
    scanned_events: int
    visible_events: int
    truncated: bool
    scope: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": self.records,
            "next_cursor": self.next_cursor,
            "high_water_sequence": self.high_water_sequence,
            "scanned_events": self.scanned_events,
            "visible_events": self.visible_events,
            "truncated": self.truncated,
            "scope": self.scope,
        }


@dataclass
class _CallIndex:
    """Links each tool call's events across the whole session up to a high-water mark.

    Built from every event, not just the requested window, so a record's tool, path, and
    status (and whether it belongs to a retrieval call) never depend on page boundaries.
    """

    actions: Dict[str, str] = field(default_factory=dict)
    paths: Dict[str, str] = field(default_factory=dict)
    statuses: Dict[str, str] = field(default_factory=dict)
    outputs: Dict[str, EventEnvelope] = field(default_factory=dict)
    artifact_ids: Dict[str, List[str]] = field(default_factory=dict)
    operation_calls: Dict[str, str] = field(default_factory=dict)
    operation_actions: Dict[str, str] = field(default_factory=dict)
    operation_paths: Dict[str, str] = field(default_factory=dict)
    observation_calls: Dict[int, str] = field(default_factory=dict)

    def call_for(self, event: EventEnvelope) -> Optional[str]:
        if event.kind in {"action_intent", "action_outcome"} and event.operation_id:
            return self.operation_calls.get(str(event.operation_id))
        if event.kind == "tool_output":
            call_id = event.payload.get("call_id")
            return call_id if isinstance(call_id, str) else None
        if event.kind == "observation":
            return self.observation_calls.get(event.sequence)
        return None


def _index_calls(events: Sequence[EventEnvelope]) -> _CallIndex:
    index = _CallIndex()
    handle_calls: Dict[str, str] = {}
    outcome_refs: Dict[str, List[str]] = {}
    operation_observations: Dict[str, List[EventEnvelope]] = {}
    handle_observations: List[tuple[str, EventEnvelope]] = []
    open_operation: Optional[str] = None
    for event in events:
        payload = event.payload
        operation = str(event.operation_id) if event.operation_id else None
        if event.kind == "action_intent" and operation:
            open_operation = operation
            index.operation_actions[operation] = str(payload.get("action", "unknown"))
            wrapper = payload.get("arguments", {})
            if isinstance(wrapper, dict):
                call_id = wrapper.get("call_id")
                arguments = wrapper.get("arguments")
                if isinstance(call_id, str):
                    index.operation_calls[operation] = call_id
                if isinstance(arguments, dict) and isinstance(arguments.get("path"), str):
                    index.operation_paths[operation] = arguments["path"]
        elif event.kind == "action_outcome" and operation:
            if open_operation == operation:
                open_operation = None
            result = payload.get("result", {})
            call_id = result.get("call_id")
            if isinstance(call_id, str):
                index.operation_calls.setdefault(operation, call_id)
                if isinstance(result.get("status"), str):
                    index.statuses[call_id] = result["status"]
                outcome_refs[call_id] = [
                    item
                    for item in [result.get("stdout_ref"), result.get("stderr_ref"), *(result.get("output_refs") or [])]
                    if isinstance(item, str)
                ]
        elif event.kind == "tool_output":
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                index.outputs[call_id] = event
                if isinstance(payload.get("handle"), str):
                    handle_calls[payload["handle"]] = call_id
        elif event.kind == "observation":
            labels = payload.get("artifact", {}).get("labels") or []
            if len(labels) >= 3 and labels[0] == "tool-output":
                handle_observations.append((str(labels[2]), event))
            elif open_operation:
                # Workspace observations carry no call reference; they occur inside the call.
                operation_observations.setdefault(open_operation, []).append(event)

    for operation, call_id in index.operation_calls.items():
        index.actions[call_id] = index.operation_actions.get(operation, "unknown")
        if operation in index.operation_paths:
            index.paths[call_id] = index.operation_paths[operation]
        for event in operation_observations.get(operation, []):
            index.observation_calls[event.sequence] = call_id
    for handle, event in handle_observations:
        if handle in handle_calls:
            index.observation_calls[event.sequence] = handle_calls[handle]
    observation_artifacts: Dict[str, List[Any]] = {}
    linked_observations = [
        *(item for _, item in handle_observations),
        *(item for items in operation_observations.values() for item in items),
    ]
    for event in linked_observations:
        owner = index.observation_calls.get(event.sequence)
        if owner is not None:
            observation_artifacts.setdefault(owner, []).append(
                event.payload.get("artifact", {}).get("artifact_id")
            )
    for call_id, event in index.outputs.items():
        # The tool name is authoritative: `run` is journaled as an `execute` intent.
        index.actions[call_id] = str(event.payload.get("tool", index.actions.get(call_id, "unknown")))
        linked = [event.payload.get("artifact_id"), *outcome_refs.get(call_id, []), *observation_artifacts.get(call_id, [])]
        index.artifact_ids[call_id] = list(dict.fromkeys(item for item in linked if isinstance(item, str)))
    return index


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.casefold() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _redact_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Redact a transcript message, including JSON-encoded tool-call argument strings."""
    public = {key: value for key, value in message.items() if not key.startswith("_")}
    calls = public.get("tool_calls")
    if isinstance(calls, list):
        redacted_calls = []
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed = None
                if parsed is not None:
                    arguments = json.dumps(_redact(parsed), sort_keys=True, ensure_ascii=False)
                    call = {**call, "function": {**function, "arguments": arguments}}
            redacted_calls.append(call)
        public["tool_calls"] = redacted_calls
    return _redact(public)


def _cursor_encode(value: Dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(cursor: str) -> Dict[str, Any]:
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid history cursor") from exc
    if not isinstance(value, dict):
        raise ValueError("Invalid history cursor")
    return value


class SessionQueryService:
    """Expose only session evidence that is authorized for the model-facing history API."""

    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        if limit < 1 or limit > 100:
            raise ValueError("History limit must be between 1 and 100")
        return limit

    def _read_text(self, artifact_id: Optional[str]) -> str:
        if not artifact_id:
            return ""
        try:
            return self.runtime.artifacts.read(artifact_id).decode("utf-8", errors="replace")
        except (KeyError, FileNotFoundError, ValueError):
            return "[artifact unavailable]"

    def _record(
        self, event: EventEnvelope, index: _CallIndex, collapse_calls: bool
    ) -> Optional[Dict[str, Any]]:
        if event.kind not in MODEL_VISIBLE_KINDS:
            return None
        call_id = index.call_for(event)
        if call_id is not None and index.actions.get(call_id) in RETRIEVAL_TOOLS:
            return None
        # One record per call: its tool_output stands for the intent, outcome, and observations.
        if collapse_calls and call_id in index.outputs and event.kind != "tool_output":
            return None
        payload = event.payload
        record: Dict[str, Any] = {
            "sequence": event.sequence,
            "event_id": event.event_id,
            "kind": event.kind,
            "created_at": event.created_at,
        }
        text = ""
        source = event.kind
        status: Optional[str] = None
        artifact_ids: List[str] = []
        output_handle: Optional[str] = None
        operation = str(event.operation_id) if event.operation_id else ""
        path: Optional[str] = index.paths.get(call_id) if call_id else index.operation_paths.get(operation)

        if event.kind == "action_intent":
            action = str(payload.get("action", "unknown"))
            if action in RETRIEVAL_TOOLS:
                return None
            source = action
            text = json.dumps(_redact(payload.get("arguments", {})), sort_keys=True, ensure_ascii=False)
            status = "intent"
        elif event.kind == "action_outcome":
            action = index.operation_actions.get(operation, "unknown")
            if action in RETRIEVAL_TOOLS:
                return None
            result = payload.get("result", {})
            source = action
            status = str(result.get("status", "unknown"))
            text = str(result.get("preview", ""))
            artifact_ids = [
                item for item in [result.get("stdout_ref"), result.get("stderr_ref"), *(result.get("output_refs") or [])]
                if isinstance(item, str)
            ]
        elif event.kind == "tool_output":
            source = str(payload.get("tool", "unknown"))
            if source in RETRIEVAL_TOOLS:
                return None
            artifact_id = payload.get("artifact_id")
            artifact_ids = index.artifact_ids.get(str(call_id), [])
            text = self._read_text(artifact_id)
            output_handle = payload.get("handle") if isinstance(payload.get("handle"), str) else None
            status = index.statuses.get(str(call_id))
        elif event.kind == "transcript_message":
            artifact_id = payload.get("artifact_id")
            message_text = self._read_text(artifact_id)
            try:
                message = json.loads(message_text)
            except json.JSONDecodeError:
                message = {"content": message_text}
            role = str(message.get("role", payload.get("role", "unknown")))
            calls = message.get("tool_calls") or []
            call_names = {
                str((call.get("function") or {}).get("name", ""))
                for call in calls if isinstance(call, dict)
            }
            result_call = message.get("tool_call_id")
            if call_names and call_names.issubset(RETRIEVAL_TOOLS):
                return None
            if isinstance(result_call, str):
                if index.actions.get(result_call) in RETRIEVAL_TOOLS:
                    return None
                if collapse_calls and result_call in index.outputs:
                    return None
            source = role
            text = json.dumps(_redact_message(message), sort_keys=True, ensure_ascii=False)
            # Search uses this redacted projection. Do not authorize the raw transcript
            # blob, which can contain structured credentials removed above.
        elif event.kind in {"observation", "scratch_write"}:
            artifact = payload.get("artifact", {})
            labels = artifact.get("labels") or []
            if DENIED_ARTIFACT_LABELS.intersection(str(label).casefold() for label in labels):
                return None
            if len(labels) >= 2 and labels[0] == "tool-output" and labels[1] in RETRIEVAL_TOOLS:
                return None
            artifact_id = artifact.get("artifact_id")
            artifact_ids = [artifact_id] if isinstance(artifact_id, str) else []
            source = ":".join(str(label) for label in labels) or event.kind
            text = self._read_text(artifact_id)
        elif event.kind == "observation_view":
            artifact_id = payload.get("view_artifact", {}).get("artifact_id")
            artifact_ids = [artifact_id] if isinstance(artifact_id, str) else []
            source = str(payload.get("rendering", {}).get("source_kind", "observation_view"))
            text = self._read_text(artifact_id)
        else:
            text = json.dumps(_redact(payload), sort_keys=True, ensure_ascii=False)

        record.update({"source": source, "status": status, "text": text})
        if artifact_ids:
            record["artifact_ids"] = artifact_ids
        if output_handle:
            record["output_handle"] = output_handle
        if path:
            record["path"] = path
        return record

    @staticmethod
    def _snippet(text: str, query: str, limit: int = 320) -> str:
        position = text.casefold().find(query.casefold())
        if position < 0:
            return text[:limit]
        start = max(0, position - limit // 3)
        end = min(len(text), start + limit)
        return text[start:end]

    def _visible_records(
        self,
        scoped: Sequence[EventEnvelope],
        context: Sequence[EventEnvelope],
        kinds: Optional[Iterable[str]] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        requested = set(kinds or MODEL_VISIBLE_KINDS)
        denied = requested - MODEL_VISIBLE_KINDS
        if denied:
            raise PermissionError(f"History kind(s) are controller-only: {', '.join(sorted(denied))}")
        index = _index_calls(context)
        # Collapse only when the canonical tool_output record is part of the requested kinds.
        collapse_calls = "tool_output" in requested
        records = [
            record
            for event in scoped
            if event.kind in requested
            for record in [self._record(event, index, collapse_calls)]
            if record is not None
        ]
        if source is not None:
            records = [record for record in records if record["source"] == source]
        return records

    def history(
        self,
        *,
        after_sequence: int = 0,
        before_sequence: Optional[int] = None,
        kinds: Optional[Iterable[str]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
        as_of_sequence: Optional[int] = None,
    ) -> HistoryPage:
        limit = self._bounded_limit(limit)
        events = self.runtime.journal.read_all()
        latest = events[-1].sequence if events else 0
        signature = hashlib.sha256(json.dumps({
            "mode": "history", "kinds": sorted(kinds or []), "before": before_sequence,
        }, sort_keys=True).encode()).hexdigest()
        if cursor:
            state = _cursor_decode(cursor)
            if state.get("mode") != "history" or state.get("signature") != signature:
                raise ValueError("History cursor does not match this query")
            high_water = int(state["high_water"])
            after_sequence = int(state["after_sequence"])
        else:
            high_water = min(latest, as_of_sequence) if as_of_sequence is not None else latest
        upper = min(high_water, before_sequence - 1) if before_sequence is not None else high_water
        context = [event for event in events if event.sequence <= high_water]
        scoped = [event for event in context if after_sequence < event.sequence <= upper]
        visible = self._visible_records(scoped, context, kinds)
        page_records = []
        for record in visible[:limit]:
            item = dict(record)
            full_text = item.pop("text")
            item["snippet"] = full_text[:320]
            item["text_truncated"] = len(full_text) > 320
            page_records.append(item)
        truncated = len(visible) > limit
        next_cursor = None
        if truncated:
            next_cursor = _cursor_encode({
                "mode": "history", "signature": signature, "high_water": high_water,
                "after_sequence": page_records[-1]["sequence"],
            })
        return HistoryPage(
            page_records,
            next_cursor,
            high_water,
            len(scoped),
            len(visible),
            truncated,
            {"kinds": sorted(kinds or MODEL_VISIBLE_KINDS), "source": None},
        )

    def search(
        self,
        query: str,
        *,
        kinds: Optional[Iterable[str]] = None,
        source: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
        as_of_sequence: Optional[int] = None,
    ) -> HistoryPage:
        if not query:
            raise ValueError("History search query must not be empty")
        limit = self._bounded_limit(limit)
        events = self.runtime.journal.read_all()
        latest = events[-1].sequence if events else 0
        signature = hashlib.sha256(json.dumps({
            "mode": "search", "query": query, "kinds": sorted(kinds or []), "source": source,
        }, sort_keys=True).encode()).hexdigest()
        after_sequence = 0
        if cursor:
            state = _cursor_decode(cursor)
            if state.get("mode") != "search" or state.get("signature") != signature:
                raise ValueError("History cursor does not match this search")
            high_water = int(state["high_water"])
            after_sequence = int(state["after_sequence"])
        else:
            high_water = min(latest, as_of_sequence) if as_of_sequence is not None else latest
        context = [event for event in events if event.sequence <= high_water]
        scoped = [event for event in context if after_sequence < event.sequence]
        visible = self._visible_records(scoped, context, kinds, source)
        matches = []
        for record in visible:
            if query.casefold() not in record["text"].casefold():
                continue
            match = dict(record)
            match["snippet"] = self._snippet(match.pop("text"), query)
            matches.append(match)
        page_records = matches[:limit]
        truncated = len(matches) > limit
        next_cursor = None
        if truncated:
            next_cursor = _cursor_encode({
                "mode": "search", "signature": signature, "high_water": high_water,
                "after_sequence": page_records[-1]["sequence"],
            })
        return HistoryPage(
            page_records,
            next_cursor,
            high_water,
            len(scoped),
            len(visible),
            truncated,
            {"kinds": sorted(kinds or MODEL_VISIBLE_KINDS), "source": source, "query": query},
        )

    def authorized_artifact_ids(self) -> set[str]:
        events = self.runtime.journal.read_all()
        records = self._visible_records(events, events)
        allowed = {
            artifact_id
            for record in records
            for artifact_id in record.get("artifact_ids", [])
        }
        for reference in self.runtime.artifacts.list_references():
            envelope = self.runtime.artifacts.get_envelope(reference.artifact_id)
            if "scratch" in envelope.labels:
                allowed.add(reference.artifact_id)
        return allowed

    def read_artifact(
        self, artifact_id: str, *, start_byte: int = 0, end_byte: Optional[int] = None
    ) -> Dict[str, Any]:
        if artifact_id not in self.authorized_artifact_ids():
            raise PermissionError(f"Artifact is unavailable or not authorized for this session view: {artifact_id}")
        envelope = self.runtime.artifacts.get_envelope(artifact_id)
        content = self.runtime.artifacts.read(artifact_id)
        end = len(content) if end_byte is None else end_byte
        if start_byte < 0 or end < start_byte or end > len(content):
            raise ValueError(f"Invalid byte range [{start_byte}, {end}) for {len(content)} bytes")
        selected = content[start_byte:end]
        return {
            "artifact_id": artifact_id,
            "media_type": envelope.media_type,
            "source_bytes": len(content),
            "range": [start_byte, end],
            "truncated": start_byte != 0 or end != len(content),
            "content": selected.decode("utf-8", errors="replace"),
        }
