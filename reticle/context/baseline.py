"""Bounded recent transcript policy with exact, persisted manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, Iterable, List, Optional, Protocol

from reticle._schema import SCHEMA_VERSION
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime


# Space reserved inside a view budget for the retrieval note.
VIEW_NOTE_RESERVE_BYTES = 320


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _estimate_tokens(byte_length: int) -> int:
    return (byte_length + 3) // 4


def _kb(byte_length: int) -> str:
    return f"{byte_length / 1000:.1f} KB"


def render_output_view(text: str, handle: str, budget: int, tail_heavy: bool) -> tuple[str, Dict[str, Any]]:
    """Render a bounded, line-based view of a tool output and say exactly how to get the rest.

    Whole lines are shown from the start, or mostly from the end for command output
    (summaries such as pytest's come last). The note names the output handle, what was
    shown, and the read_output call that returns the next omitted lines.
    """
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        return text, {"rendering": "full", "source_bytes": len(raw)}
    lines = text.splitlines(keepends=True)
    total = len(lines)
    content_budget = max(0, budget - VIEW_NOTE_RESERVE_BYTES)
    head_budget = content_budget // 4 if tail_heavy else content_budget
    head: List[str] = []
    used = 0
    for line in lines:
        size = len(line.encode("utf-8"))
        if used + size > head_budget:
            break
        head.append(line)
        used += size
    tail: List[str] = []
    used_tail = 0
    if tail_heavy:
        for line in reversed(lines[len(head):]):
            size = len(line.encode("utf-8"))
            if used + used_tail + size > content_budget:
                break
            tail.append(line)
            used_tail += size
        tail.reverse()

    if not head and not tail:
        prefix = raw[:content_budget].decode("utf-8", errors="ignore")
        shown = len(prefix.encode("utf-8"))
        note = (
            f"[output {handle}: line 1 alone is {_kb(len(lines[0].encode('utf-8')))}; showing its first "
            f"{_kb(shown)} of {_kb(len(raw))}. More: read_output(id=\"{handle}\", start_byte={shown}, "
            f"end_byte={shown + max(content_budget, 1)})]"
        )
        return f"{prefix}\n{note}", {
            "rendering": "byte-prefix", "output_handle": handle, "shown_bytes": [0, shown], "source_bytes": len(raw),
        }

    first_omitted = len(head) + 1
    tail_start = total - len(tail) + 1
    last_omitted = tail_start - 1 if tail else total
    page = max(1, len(head) or len(tail))
    next_last = min(last_omitted, first_omitted + page - 1)
    if tail and head:
        shown = f"lines 1-{len(head)} and {tail_start}-{total}"
    elif tail:
        shown = f"lines {tail_start}-{total}"
    else:
        shown = f"lines 1-{len(head)}"
    body = "".join(head)
    if tail:
        if body and not body.endswith("\n"):
            body += "\n"
        body += f"[... lines {first_omitted}-{last_omitted} omitted ...]\n" + "".join(tail)
    if not body.endswith("\n"):
        body += "\n"
    note = (
        f"[output {handle}: showing {shown} of {total} ({_kb(used + used_tail)} of {_kb(len(raw))}). "
        f"More: read_output(id=\"{handle}\", start_line={first_omitted}, end_line={next_last}); "
        f"find text: search_output(id=\"{handle}\", query=\"...\")]"
    )
    return body + note, {
        "rendering": "line-view", "output_handle": handle, "shown": shown, "total_lines": total,
        "omitted_lines": [first_omitted, last_omitted], "source_bytes": len(raw),
    }


@dataclass(frozen=True)
class ContextManifest:
    policy_version: str
    task_id: str
    max_context_bytes: int
    materialized_request_artifact_id: str
    materialized_request_hash: str
    selected_items: List[Dict[str, Any]]
    message_order: List[str]
    selected_tool_schemas: List[Dict[str, Any]]
    token_estimate: int
    request_bytes: int = 0
    omitted_items: List[Dict[str, Any]] = field(default_factory=list)
    pin_overflow: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    provider_hidden_context: str = "unavailable"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextBuildResult:
    messages: List[Dict[str, Any]]
    tools: List[Dict[str, Any]]
    manifest: ContextManifest
    over_budget: bool


class TranscriptStore:
    """Persist provider messages exactly, independently of rendered context."""

    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime

    def append(self, message: Dict[str, Any]) -> str:
        raw = _encoded(message)
        event_id = self.runtime.journal.new_event_id()
        artifact = self.runtime.artifacts.put(
            raw,
            "application/json",
            event_id,
            labels=["transcript-message", str(message.get("role", "unknown"))],
        )
        self.runtime.journal.append(
            "transcript_message",
            {"artifact_id": artifact.artifact_id, "role": message.get("role")},
            event_id=event_id,
        )
        return artifact.artifact_id

    def load(self, as_of_sequence: Optional[int] = None) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        for event in self.runtime.journal.read_all():
            if as_of_sequence is not None and event.sequence > as_of_sequence:
                break
            if event.kind != "transcript_message":
                continue
            raw = self.runtime.artifacts.read(event.payload["artifact_id"])
            message = json.loads(raw.decode("utf-8"))
            # Private provenance travels only as far as context construction and
            # is stripped from the provider request below.
            message["_reticle_artifact_id"] = event.payload["artifact_id"]
            messages.append(message)
        return messages


class ContextPolicy(Protocol):
    policy_version: str

    def build(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        transcript: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        diagnostics: Optional[List[str]] = None,
    ) -> ContextBuildResult: ...


class BaselineContextPolicy:
    policy_version = "bounded-recent-v2"

    def __init__(
        self,
        tool_preview_bytes: int = 512,
        pin_preview_bytes: int = 512,
        newest_tool_view_bytes: int = 4_000,
    ):
        self.tool_preview_bytes = tool_preview_bytes
        self.pin_preview_bytes = pin_preview_bytes
        self.newest_tool_view_bytes = newest_tool_view_bytes

    @staticmethod
    def _tool_ids(message: Dict[str, Any]) -> List[str]:
        if message.get("role") != "assistant":
            return []
        return [call.get("id") for call in message.get("tool_calls", []) if call.get("id")]

    def _paired_units(self, transcript: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Group assistant tool calls with all matching results; discard orphans."""
        units: List[List[Dict[str, Any]]] = []
        index = 0
        while index < len(transcript):
            message = transcript[index]
            call_ids = self._tool_ids(message)
            if call_ids:
                unit = [message]
                found = set()
                cursor = index + 1
                while cursor < len(transcript) and transcript[cursor].get("role") == "tool":
                    result = transcript[cursor]
                    if result.get("tool_call_id") in call_ids:
                        unit.append(result)
                        found.add(result.get("tool_call_id"))
                    cursor += 1
                if found == set(call_ids):
                    units.append(unit)
                index = cursor
                continue
            if message.get("role") != "tool":
                units.append([message])
            index += 1
        return units

    def _spill_tool_message(
        self, runtime: LocalRuntime, message: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(content, str):
            return message, None
        raw = content.encode("utf-8")
        if len(raw) <= self.tool_preview_bytes:
            return message, None
        event_id = runtime.journal.new_event_id()
        artifact = runtime.artifacts.put(
            raw,
            "text/plain; charset=utf-8",
            event_id,
            labels=["spilled-observation", str(message.get("tool_call_id", "unknown"))],
        )
        runtime.journal.append(
            "observation_spill",
            {"artifact": artifact.to_dict(), "tool_call_id": message.get("tool_call_id")},
            event_id=event_id,
        )
        preview = raw[:self.tool_preview_bytes].decode("utf-8", errors="replace")
        rendered = dict(message)
        rendered["content"] = (
            f"{preview}\n[truncated: {len(raw) - self.tool_preview_bytes} bytes omitted; "
            f"exact observation: {artifact.artifact_id}]"
        )
        return rendered, {
            "artifact_id": artifact.artifact_id,
            "range": [0, self.tool_preview_bytes],
            "rendering": "truthful-preview",
            "source_byte_length": len(raw),
        }

    def _render_tool_message(
        self, runtime: LocalRuntime, message: Dict[str, Any], newest: bool
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        output = message.get("_reticle_output")
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(output, dict) or not isinstance(content, str):
            # Messages without a retrievable output handle keep the artifact spill behavior.
            return self._spill_tool_message(runtime, message)
        budget = self.newest_tool_view_bytes if newest else self.tool_preview_bytes
        text, rendering = render_output_view(content, output["handle"], budget, tail_heavy=output.get("tool") == "run")
        if rendering["rendering"] == "full":
            return message, None
        rendered = dict(message)
        rendered["content"] = text
        return rendered, {**rendering, "view_budget_bytes": budget, "newest_exchange": newest}

    def _record(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        selected: List[Dict[str, Any]],
        pin_overflow: List[Dict[str, Any]],
        diagnostics: List[str],
        omitted_items: Optional[List[Dict[str, Any]]] = None,
    ) -> ContextBuildResult:
        message_order = [
            str(message.get("_context_id", index)) for index, message in enumerate(messages)
        ]
        public_messages = [
            {key: value for key, value in message.items() if not key.startswith("_")}
            for message in messages
        ]
        request = {"messages": public_messages, "tools": tools}
        raw = _encoded(request)
        event_id = runtime.journal.new_event_id()
        request_artifact = runtime.artifacts.put(
            raw, "application/json", event_id, labels=["materialized-context-request"]
        )
        manifest = ContextManifest(
            policy_version=self.policy_version,
            task_id=task.task_id,
            max_context_bytes=max_context_bytes,
            materialized_request_artifact_id=request_artifact.artifact_id,
            materialized_request_hash=request_artifact.content_hash,
            selected_items=selected,
            message_order=message_order,
            selected_tool_schemas=tools,
            token_estimate=_estimate_tokens(len(raw)),
            request_bytes=len(raw),
            omitted_items=list(omitted_items or []),
            pin_overflow=pin_overflow,
            diagnostics=diagnostics,
        )
        runtime.journal.append(
            "context_manifest",
            {"manifest": manifest.to_dict()},
            event_id=event_id,
        )
        return ContextBuildResult(public_messages, tools, manifest, len(raw) > max_context_bytes)

    def build(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        transcript: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        diagnostics: Optional[List[str]] = None,
    ) -> ContextBuildResult:
        if max_context_bytes <= 0:
            raise ValueError("Context budget must be positive")
        notes = list(diagnostics or [])
        authority = json.dumps(task.authority, sort_keys=True)
        budgets = json.dumps(task.budgets, sort_keys=True)
        criteria = json.dumps(task.criteria, sort_keys=True)
        diagnostic_text = ""
        if notes:
            diagnostic_text = " Context diagnostics: " + " | ".join(notes)
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Reticle runtime contract. Preserve tool-call/result pairing. "
                    "Partial tool results name the read_output call for the rest. "
                    f"Authority: {authority}. Budgets: {budgets}. Criteria: {criteria}."
                    f"{diagnostic_text}"
                ),
                "_context_id": "contract",
            },
            {"role": "user", "content": task.description, "_context_id": "original-task"},
        ]
        selected: List[Dict[str, Any]] = [
            {"kind": "contract", "rendering": "full"},
            {"kind": "task", "task_id": task.task_id, "rendering": "full"},
        ]
        pin_overflow: List[Dict[str, Any]] = []

        base_size = len(_encoded({"messages": messages, "tools": tools}))
        remaining = max(0, max_context_bytes - base_size)
        pins = sorted(
            runtime.scratch.pins().items(),
            key=lambda item: (-int(item[1]["priority"]), item[0]),
        )
        for ref, pin in pins:
            read = runtime.scratch.read(pin["artifact_id"])
            raw = read.content
            full_text = raw.decode("utf-8", errors="replace")
            message = {
                "role": "system",
                "content": f"Pinned scratch {ref} ({read.artifact.artifact_id}):\n{full_text}",
                "_context_id": f"pin:{ref}",
            }
            cost = len(_encoded(message))
            if cost <= remaining:
                messages.append(message)
                remaining -= cost
                selected.append({
                    "kind": "pin",
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "reference_version": pin["reference_version"],
                    "range": [0, len(raw)],
                    "rendering": "full",
                })
                continue
            preview_length = min(len(raw), self.pin_preview_bytes, max(0, remaining // 2))
            overflow = {
                "ref": ref,
                "artifact_id": read.artifact.artifact_id,
                "requested_bytes": len(raw),
                "delivered_bytes": preview_length,
                "reason": "pin_exceeds_remaining_context_budget",
            }
            pin_overflow.append(overflow)
            if preview_length:
                preview = raw[:preview_length].decode("utf-8", errors="replace")
                compact = {
                    "role": "system",
                    "content": (
                        f"PIN OVERFLOW for {ref}: {preview}\n"
                        f"[{len(raw) - preview_length} bytes omitted; exact: {read.artifact.artifact_id}]"
                    ),
                    "_context_id": f"pin-overflow:{ref}",
                }
                messages.append(compact)
                remaining = max(0, remaining - len(_encoded(compact)))
                selected.append({
                    "kind": "pin",
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "reference_version": pin["reference_version"],
                    "range": [0, preview_length],
                    "rendering": "overflow-preview",
                })
        if pin_overflow:
            notes.append("One or more pins overflowed; baseline compact previews were used.")

        units = self._paired_units(transcript)
        newest_exchange = max((i for i, unit in enumerate(units) if self._tool_ids(unit[0])), default=None)
        rendered_units: List[tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]] = []
        for unit_index, unit in enumerate(units):
            rendered: List[Dict[str, Any]] = []
            unit_selected: List[Dict[str, Any]] = []
            for message_index, original in enumerate(unit):
                value, view = self._render_tool_message(runtime, original, unit_index == newest_exchange)
                value = dict(value)
                transcript_artifact_id = value.pop("_reticle_artifact_id", None)
                value["_context_id"] = f"transcript:{unit_index}:{message_index}"
                rendered.append(value)
                item = {
                    "kind": "transcript",
                    "role": value.get("role"),
                    "artifact_id": transcript_artifact_id,
                    "rendering": "full",
                }
                if view:
                    item.update(view)
                unit_selected.append(item)
            public = [{k: v for k, v in message.items() if not k.startswith("_")} for message in rendered]
            rendered_units.append((rendered, unit_selected, len(_encoded(public))))

        recent: List[tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
        omitted: List[Dict[str, Any]] = []
        for unit_index in reversed(range(len(rendered_units))):
            rendered, unit_selected, cost = rendered_units[unit_index]
            if cost > remaining:
                # Recorded only so manifests and comparisons show the drop; rendering is unchanged.
                omitted.append({"kind": "transcript_unit", "unit_index": unit_index, "reason": "context_budget"})
                continue
            recent.append((rendered, unit_selected))
            remaining -= cost
        for rendered, unit_selected in reversed(recent):
            messages.extend(rendered)
            selected.extend(unit_selected)

        return self._record(
            runtime, task, messages, tools, max_context_bytes, selected, pin_overflow, notes,
            omitted_items=sorted(omitted, key=lambda item: item["unit_index"]),
        )


class PressureRecentContextPolicy(BaselineContextPolicy):
    """Keep recent observations whole until the materialized request is under pressure.

    The latest complete assistant/tool exchange and every message after it are required.
    Older units are admitted newest-first as a contiguous run, then pins. If the latest
    result is itself too large, it is rendered with an exact output handle; if even that
    protocol-valid view cannot fit, ``over_budget`` remains true so the controller can
    checkpoint without calling the provider.
    """

    policy_version = "pressure-recent-v1"

    @staticmethod
    def _public(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {key: value for key, value in message.items() if not key.startswith("_")}
            for message in messages
        ]

    def _request_size(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> int:
        return len(_encoded({"messages": self._public(messages), "tools": tools}))

    def _pressure_message(
        self,
        original: Dict[str, Any],
        *,
        view_budget: Optional[int] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        value = dict(original)
        transcript_artifact_id = value.pop("_reticle_artifact_id", None)
        output = value.pop("_reticle_output", None)
        item: Dict[str, Any] = {
            "kind": "transcript",
            "role": value.get("role"),
            "artifact_id": transcript_artifact_id,
            "rendering": "full",
        }
        content = value.get("content")
        if value.get("role") != "tool" or not isinstance(content, str):
            return value, item

        if isinstance(output, dict) and output.get("handle"):
            handle = str(output["handle"])
            status = str(output.get("status", "unknown"))
            prefix = f"[tool result status={status}; output={handle}]\n"
            item.update({
                "output_handle": handle,
                "status": status,
                "source_bytes": len(content.encode("utf-8")),
            })
            if view_budget is not None:
                rendered, rendering = render_output_view(
                    content,
                    handle,
                    view_budget,
                    tail_heavy=output.get("tool") == "run",
                )
                value["content"] = prefix + rendered
                if rendering["rendering"] != "full":
                    item.update(rendering)
                    item["view_budget_bytes"] = view_budget
                    item["newest_exchange"] = True
            else:
                value["content"] = prefix + content
            return value, item

        # Controller-produced results always have an output handle. Retain the exact
        # transcript artifact reference for imported or historical messages that do not.
        item["retrieval_artifact_id"] = transcript_artifact_id
        return value, item

    def _render_unit(
        self,
        unit: List[Dict[str, Any]],
        unit_index: int,
        *,
        view_budget: Optional[int] = None,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        rendered: List[Dict[str, Any]] = []
        selected: List[Dict[str, Any]] = []
        for message_index, original in enumerate(unit):
            value, item = self._pressure_message(original, view_budget=view_budget)
            value["_context_id"] = f"transcript:{unit_index}:{message_index}"
            rendered.append(value)
            selected.append(item)
        return rendered, selected

    def _required_tail(
        self,
        base: List[Dict[str, Any]],
        units: List[List[Dict[str, Any]]],
        start: int,
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
    ) -> List[tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]]:
        """Render ``units[start:]``, reducing only the leading exchange's results to fit.

        Units after the latest exchange (a text-only reply, the no-tool-call prompt, a user
        correction) stay whole: dropping them would re-send the previous turn unchanged.
        """
        trailing = [
            (index, *self._render_unit(units[index], index))
            for index in range(start + 1, len(units))
        ]

        def assemble(view_budget: Optional[int]):
            rendered, selected = self._render_unit(units[start], start, view_budget=view_budget)
            return [(start, rendered, selected), *trailing]

        def fits(tail) -> bool:
            tail_messages = [message for _, rendered, _ in tail for message in rendered]
            return self._request_size([*base, *tail_messages], tools) <= max_context_bytes

        full = assemble(None)
        if fits(full):
            return full

        # View sizes below the retrieval-note reserve are not useful and can be larger
        # than their nominal budget. Find the largest useful common result view that fits.
        upper = max(
            [
                len(str(message.get("content", "")).encode("utf-8"))
                for message in units[start]
                if message.get("role") == "tool"
            ]
            or [0]
        )
        low = VIEW_NOTE_RESERVE_BYTES
        best = None
        while low <= upper:
            middle = (low + upper) // 2
            candidate = assemble(middle)
            if fits(candidate):
                best = candidate
                low = middle + 1
            else:
                upper = middle - 1
        if best is not None:
            return best

        # Return the smallest meaningful representation. The caller deliberately records
        # it as over budget rather than dropping the latest outcome.
        return assemble(VIEW_NOTE_RESERVE_BYTES)

    def _opening(
        self, task: TaskEnvelope, resource_status: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """The contract and original task. pressure-recent-v1 ignores resource_status."""
        authority = json.dumps(task.authority, sort_keys=True)
        budgets = json.dumps(task.budgets, sort_keys=True)
        criteria = json.dumps(task.criteria, sort_keys=True)
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Reticle runtime contract. Preserve tool-call/result pairing. "
                    "Partial results name an exact read_output/search_output retrieval. "
                    "Use search_history to discover omitted actions or observations, history "
                    "to page the session, and read_artifact for an authorized artifact ID. "
                    "Earlier exchanges may be omitted under context pressure. "
                    f"Authority: {authority}. Budgets: {budgets}. Criteria: {criteria}."
                ),
                "_context_id": "contract",
            },
            {"role": "user", "content": task.description, "_context_id": "original-task"},
        ]
        selected: List[Dict[str, Any]] = [
            {"kind": "contract", "rendering": "full"},
            {"kind": "task", "task_id": task.task_id, "rendering": "full"},
        ]
        return messages, selected

    def build(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        transcript: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        diagnostics: Optional[List[str]] = None,
        resource_status: Optional[Dict[str, Any]] = None,
    ) -> ContextBuildResult:
        if max_context_bytes <= 0:
            raise ValueError("Context budget must be positive")
        notes = list(diagnostics or [])
        messages, selected = self._opening(task, resource_status)
        omitted: List[Dict[str, Any]] = []
        pin_overflow: List[Dict[str, Any]] = []
        units = self._paired_units(transcript)
        required_start = max(
            (index for index, unit in enumerate(units) if self._tool_ids(unit[0])),
            default=None,
        )
        if required_start is None and units:
            # No tool exchange yet: protect from the model's latest reply onward.
            required_start = max(
                (index for index, unit in enumerate(units) if unit[0].get("role") == "assistant"),
                default=len(units) - 1,
            )
        required = (
            self._required_tail(messages, units, required_start, tools, max_context_bytes)
            if required_start is not None
            else []
        )
        required_messages = [message for _, rendered, _ in required for message in rendered]

        # Older history is a contiguous run back from the required tail: the first unit that
        # does not fit ends selection, so a newer unit is never dropped to admit an older one.
        chosen: List[tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]] = []
        chosen_messages: List[Dict[str, Any]] = []
        for unit_index in reversed(range(required_start or 0)):
            rendered, unit_selected = self._render_unit(units[unit_index], unit_index)
            if self._request_size(
                [*messages, *rendered, *chosen_messages, *required_messages], tools
            ) > max_context_bytes:
                omitted.extend(
                    {"kind": "transcript_unit", "unit_index": index, "reason": "context_pressure"}
                    for index in range(unit_index + 1)
                )
                break
            chosen.insert(0, (unit_index, rendered, unit_selected))
            chosen_messages = [*rendered, *chosen_messages]

        omission_message: List[Dict[str, Any]] = []
        if omitted:
            marker = {
                "role": "system",
                "content": (
                    "Context pressure omitted earlier transcript exchanges. Exact prior tool "
                    "results remain persisted; use search_history without an output ID, then "
                    "read_output/search_output or read_artifact using the returned reference."
                ),
                "_context_id": "history-omission",
            }
            def with_marker() -> List[Dict[str, Any]]:
                return [
                    *messages,
                    marker,
                    *[message for _, rendered, _ in chosen for message in rendered],
                    *required_messages,
                ]

            # Removing the oldest chosen unit keeps the retained history contiguous.
            while chosen and self._request_size(with_marker(), tools) > max_context_bytes:
                removed_index, _, _ = chosen.pop(0)
                omitted.append({
                    "kind": "transcript_unit",
                    "unit_index": removed_index,
                    "reason": "context_pressure_for_omission_marker",
                })
            if self._request_size(with_marker(), tools) <= max_context_bytes:
                omission_message = [marker]
                selected.append({"kind": "history_omission", "rendering": "full"})

        transcript_messages = [
            *[message for _, rendered, _ in chosen for message in rendered],
            *required_messages,
        ]
        transcript_selected = [item for _, _, items in [*chosen, *required] for item in items]

        # Pins are optional and cannot displace the authoritative contract or transcript.
        pin_messages: List[Dict[str, Any]] = []
        pin_selected: List[Dict[str, Any]] = []
        for ref, pin in sorted(
            runtime.scratch.pins().items(),
            key=lambda item: (-int(item[1]["priority"]), item[0]),
        ):
            read = runtime.scratch.read(pin["artifact_id"])
            message = {
                "role": "system",
                "content": (
                    f"Pinned scratch {ref} ({read.artifact.artifact_id}):\n"
                    f"{read.content.decode('utf-8', errors='replace')}"
                ),
                "_context_id": f"pin:{ref}",
            }
            candidate = [
                *messages,
                *pin_messages,
                message,
                *omission_message,
                *transcript_messages,
            ]
            if self._request_size(candidate, tools) <= max_context_bytes:
                pin_messages.append(message)
                pin_selected.append({
                    "kind": "pin",
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "reference_version": pin["reference_version"],
                    "range": [0, len(read.content)],
                    "rendering": "full",
                })
            else:
                pin_overflow.append({
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "requested_bytes": len(read.content),
                    "delivered_bytes": 0,
                    "reason": "pin_exceeds_remaining_context_budget",
                })

        final_messages = [
            *messages,
            *pin_messages,
            *omission_message,
            *transcript_messages,
        ]
        selected.extend(pin_selected)
        selected.extend(transcript_selected)
        if omitted:
            notes.append(
                f"{len(omitted)} earlier transcript unit(s) omitted under context pressure; "
                "tool results remain available by their output handles."
            )
        return self._record(
            runtime,
            task,
            final_messages,
            tools,
            max_context_bytes,
            selected,
            pin_overflow,
            notes,
            omitted_items=sorted(
                {item["unit_index"]: item for item in omitted}.values(),
                key=lambda item: item["unit_index"],
            ),
        )


RESOURCE_STATUS_PREFIX = "Remaining task resources before this response (the run stops when one is exhausted): "
_RESOURCE_LABELS = (
    ("model_responses", "model responses, including this one", "{:.0f}"),
    ("model_attempts", "HTTP attempts, retries included", "{:.0f}"),
    ("tool_actions", "tool actions", "{:.0f}"),
    ("active_seconds", "active seconds", "{:.0f}"),
    ("cost_usd", "cost USD", "{:.4f}"),
)


def render_resource_status(status: Dict[str, Any], labeled_limits: bool = False) -> Optional[str]:
    """pressure-recent-v2 renders "X of Y". pressure-recent-v3 (labeled_limits) renders "X remaining (limit Y)"
    and states how many attempts had no reported cost."""
    parts = []
    for key, label, number in _RESOURCE_LABELS:
        item = status.get(key)
        if item:
            remaining, limit = number.format(max(0.0, item["remaining"])), number.format(item["limit"])
            if not labeled_limits:
                parts.append(f"{label}: {remaining} of {limit}")
                continue
            text = f"{label}: {remaining} remaining (limit {limit})"
            unknown = status.get("cost_unknown_billing_attempts") if key == "cost_usd" else None
            if unknown:
                text += (f", after charging {unknown} attempt(s) with no reported cost at their reservation "
                         "(actual billing unknown)")
            parts.append(text)
    if not parts:
        return None
    reservation = status.get("attempt_cost_reservation_usd")
    if reservation:
        parts.append(f"each model attempt first reserves ${reservation:.4f}")
    return RESOURCE_STATUS_PREFIX + "; ".join(parts) + "."


class PressureRecentContextPolicyV2(PressureRecentContextPolicy):
    """pressure-recent-v1 plus the controller's remaining-resource status in every request.

    The status comes from the durable task ledger and the invocation limit at build time, and is
    placed after the original task. Everything else is identical to pressure-recent-v1.
    """

    policy_version = "pressure-recent-v2"
    renders_resource_status = True

    def _opening(
        self, task: TaskEnvelope, resource_status: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        messages, selected = super()._opening(task)
        text = render_resource_status(resource_status or {})
        if text:
            messages.append({"role": "system", "content": text, "_context_id": "resource-status"})
            selected.append({"kind": "resource_status", "rendering": "full"})
        return messages, selected


class PressureRecentContextPolicyV3(PressureRecentContextPolicyV2):
    """pressure-recent-v2 with original limits labeled separately and unknown billing stated."""

    policy_version = "pressure-recent-v3"

    def _opening(
        self, task: TaskEnvelope, resource_status: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        messages, selected = PressureRecentContextPolicy._opening(self, task)
        text = render_resource_status(resource_status or {}, labeled_limits=True)
        if text:
            messages.append({"role": "system", "content": text, "_context_id": "resource-status"})
            selected.append({"kind": "resource_status", "rendering": "full"})
        return messages, selected


class PressureRecentContextPolicyV4(PressureRecentContextPolicyV3):
    """pressure-recent-v3 laid out for provider prefix caching (E1 cache layout 008).

    Two differences from v3 and nothing else:

    1. The resource status (v3 wording) is the final message of the request instead of following
       the task. Everything before it can then stay byte-identical from one request to the next.
    2. Older units are omitted in pages. When the request would exceed the budget, the oldest units
       are omitted until it is at most half the budget, and that boundary stays where it is until the
       budget is exceeded again. v3 re-fits the boundary on every request, so under pressure the first
       transcript message after the opening changes almost every turn.

    The page boundary needs no stored state: it is a function of the transcript, the opening, the
    status size and the budget. The page rule is replayed over the requests the transcript implies
    (one before each assistant message, and this one), with every unit counted whole, so a rebuilt,
    compared or resumed session pages exactly as the live one did. Selection otherwise follows v3:
    the latest exchange and every message after it are required and reduced only if they cannot fit
    whole; retained history runs contiguously back from them (units the page plan kept are still
    fitted to the actual request, as v3 fits them); the omission marker is included when it fits;
    and pins fit after the transcript. Every size check counts the status, as in v3.
    """

    policy_version = "pressure-recent-v4"
    # The same text as pressure-recent-v1's marker; it is constant, so it never breaks the prefix.
    OMISSION_MARKER = (
        "Context pressure omitted earlier transcript exchanges. Exact prior tool "
        "results remain persisted; use search_history without an output ID, then "
        "read_output/search_output or read_artifact using the returned reference."
    )

    @staticmethod
    def _required_start(units: List[List[Dict[str, Any]]]) -> Optional[int]:
        """The first required unit, as v1-v3 choose it: the latest tool exchange, else the latest reply."""
        start = max(
            (index for index, unit in enumerate(units) if BaselineContextPolicy._tool_ids(unit[0])),
            default=None,
        )
        if start is None and units:
            start = max(
                (index for index, unit in enumerate(units) if unit[0].get("role") == "assistant"),
                default=len(units) - 1,
            )
        return start

    def _page_start(
        self,
        units: List[List[Dict[str, Any]]],
        sized: List[Dict[str, Any]],
        marker: Dict[str, Any],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
    ) -> int:
        """The first unit of the current page: units before it are omitted by page."""
        base = self._request_size(sized, tools)  # contract, task, status: never empty
        marker_bytes = len(_encoded(self._public([marker])[0])) + 1
        cumulative = [0]
        for index, unit in enumerate(units):
            rendered = self._public(self._render_unit(unit, index)[0])
            cumulative.append(cumulative[-1] + sum(len(_encoded(message)) + 1 for message in rendered))

        def size(start: int, end: int) -> int:
            return base + (marker_bytes if start else 0) + cumulative[end] - cumulative[start]

        # One request before each assistant message (the transcript as the model saw it), then this one.
        ends = sorted({index for index, unit in enumerate(units) if index and unit[0].get("role") == "assistant"}
                      | {len(units)})
        start = 0
        for end in ends:
            required_start = self._required_start(units[:end])
            if required_start is None or size(start, end) <= max_context_bytes:
                continue
            while start < required_start and size(start, end) > max_context_bytes // 2:
                start += 1
        return start

    def build(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        transcript: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        diagnostics: Optional[List[str]] = None,
        resource_status: Optional[Dict[str, Any]] = None,
    ) -> ContextBuildResult:
        if max_context_bytes <= 0:
            raise ValueError("Context budget must be positive")
        notes = list(diagnostics or [])
        messages, selected = PressureRecentContextPolicy._opening(self, task)
        status_text = render_resource_status(resource_status or {}, labeled_limits=True)
        status_message = (
            [{"role": "system", "content": status_text, "_context_id": "resource-status"}] if status_text else []
        )
        # A request's size does not depend on message order, so fits use the opening plus the status.
        sized = [*messages, *status_message]
        marker = {"role": "system", "content": self.OMISSION_MARKER, "_context_id": "history-omission"}
        omitted: List[Dict[str, Any]] = []
        pin_overflow: List[Dict[str, Any]] = []
        units = self._paired_units(transcript)
        required_start = self._required_start(units)
        required = (
            self._required_tail(sized, units, required_start, tools, max_context_bytes)
            if required_start is not None
            else []
        )
        required_messages = [message for _, rendered, _ in required for message in rendered]

        page_start = min(self._page_start(units, sized, marker, tools, max_context_bytes), required_start or 0)
        omitted.extend(
            {"kind": "transcript_unit", "unit_index": index, "reason": "context_pressure_page"}
            for index in range(page_start)
        )
        chosen: List[tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]] = []
        chosen_messages: List[Dict[str, Any]] = []
        for unit_index in reversed(range(page_start, required_start or 0)):
            rendered, unit_selected = self._render_unit(units[unit_index], unit_index)
            if self._request_size(
                [*sized, *rendered, *chosen_messages, *required_messages], tools
            ) > max_context_bytes:
                omitted.extend(
                    {"kind": "transcript_unit", "unit_index": index, "reason": "context_pressure"}
                    for index in range(page_start, unit_index + 1)
                )
                break
            chosen.insert(0, (unit_index, rendered, unit_selected))
            chosen_messages = [*rendered, *chosen_messages]

        omission_message: List[Dict[str, Any]] = []
        if omitted:
            def with_marker() -> List[Dict[str, Any]]:
                return [
                    *sized,
                    marker,
                    *[message for _, rendered, _ in chosen for message in rendered],
                    *required_messages,
                ]

            while chosen and self._request_size(with_marker(), tools) > max_context_bytes:
                removed_index, _, _ = chosen.pop(0)
                omitted.append({
                    "kind": "transcript_unit",
                    "unit_index": removed_index,
                    "reason": "context_pressure_for_omission_marker",
                })
            if self._request_size(with_marker(), tools) <= max_context_bytes:
                omission_message = [marker]
                selected.append({"kind": "history_omission", "rendering": "full"})

        transcript_messages = [
            *[message for _, rendered, _ in chosen for message in rendered],
            *required_messages,
        ]
        transcript_selected = [item for _, _, items in [*chosen, *required] for item in items]

        pin_messages: List[Dict[str, Any]] = []
        pin_selected: List[Dict[str, Any]] = []
        for ref, pin in sorted(
            runtime.scratch.pins().items(),
            key=lambda item: (-int(item[1]["priority"]), item[0]),
        ):
            read = runtime.scratch.read(pin["artifact_id"])
            message = {
                "role": "system",
                "content": (
                    f"Pinned scratch {ref} ({read.artifact.artifact_id}):\n"
                    f"{read.content.decode('utf-8', errors='replace')}"
                ),
                "_context_id": f"pin:{ref}",
            }
            candidate = [*sized, *pin_messages, message, *omission_message, *transcript_messages]
            if self._request_size(candidate, tools) <= max_context_bytes:
                pin_messages.append(message)
                pin_selected.append({
                    "kind": "pin",
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "reference_version": pin["reference_version"],
                    "range": [0, len(read.content)],
                    "rendering": "full",
                })
            else:
                pin_overflow.append({
                    "ref": ref,
                    "artifact_id": read.artifact.artifact_id,
                    "requested_bytes": len(read.content),
                    "delivered_bytes": 0,
                    "reason": "pin_exceeds_remaining_context_budget",
                })

        final_messages = [*messages, *pin_messages, *omission_message, *transcript_messages, *status_message]
        selected.extend(pin_selected)
        selected.extend(transcript_selected)
        if status_message:
            selected.append({"kind": "resource_status", "rendering": "full"})
        if omitted:
            notes.append(
                f"{len(omitted)} earlier transcript unit(s) omitted under context pressure; "
                "tool results remain available by their output handles."
            )
        return self._record(
            runtime,
            task,
            final_messages,
            tools,
            max_context_bytes,
            selected,
            pin_overflow,
            notes,
            omitted_items=sorted(
                {item["unit_index"]: item for item in omitted}.values(),
                key=lambda item: item["unit_index"],
            ),
        )


class ContextBuilder:
    """Run a selected policy with a visible bounded-baseline fallback."""

    def __init__(self, policy: ContextPolicy, baseline: Optional[BaselineContextPolicy] = None):
        self.policy = policy
        self.baseline = baseline or BaselineContextPolicy()

    def build(self, *args: Any, **kwargs: Any) -> ContextBuildResult:
        try:
            return self.policy.build(*args, **kwargs)
        except Exception as exc:
            diagnostic = f"Policy {self.policy.policy_version} failed: {type(exc).__name__}: {exc}"
            kwargs["diagnostics"] = [diagnostic]
            kwargs.pop("resource_status", None)  # the legacy fallback does not render resource status
            return self.baseline.build(*args, **kwargs)
