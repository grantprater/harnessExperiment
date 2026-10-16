"""Reticle-style board policy: recent exchanges plus a runtime-generated state board.

Instead of the whole recent transcript, each request carries the original task, the last
few protocol-safe tool exchanges, and a board derived from the journal: failed actions
(with whether the workspace changed since), files modified so far, and saved notes.
Failures are conditional evidence, not prohibitions. Every omitted exchange stays
retrievable from the transcript store and journal.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from reticle.context.baseline import BaselineContextPolicy, ContextBuildResult
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime


EDIT_ACTIONS = {"write_file", "replace_text", "apply_patch"}


class _BoardRenderer(BaselineContextPolicy):
    policy_version = "reticle-board-v2"


class ReticleBoardPolicy:
    policy_version = _BoardRenderer.policy_version

    def __init__(self, recent_units: int = 2, failure_limit: int = 12, preview_chars: int = 300):
        if recent_units < 1:
            raise ValueError("recent_units must be at least 1")
        self.recent_units = recent_units
        self.failure_limit = failure_limit
        self.preview_chars = preview_chars
        self.renderer = _BoardRenderer()

    @staticmethod
    def _describe(intent: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        action = intent.get("action", "unknown")
        arguments = intent.get("arguments") or {}
        if action == "execute":
            return "run", {"command": " ".join(arguments.get("command") or [])}
        return action, arguments.get("arguments") or {}

    def _board(self, runtime: LocalRuntime, omitted_units: int) -> str:
        events = runtime.journal.read_all()
        intents = {e.operation_id: e.payload for e in events if e.kind == "action_intent" and e.operation_id}
        current_revision = runtime.workspace.revision()
        failures: List[str] = []
        modified: List[str] = []
        model_calls = sum(1 for e in events if e.kind == "model_call")
        for event in events:
            if event.kind != "action_outcome" or event.operation_id not in intents:
                continue
            result = event.payload["result"]
            name, arguments = self._describe(intents[event.operation_id])
            if result["status"] == "success":
                path = arguments.get("path")
                if name in EDIT_ACTIONS and isinstance(path, str) and path not in modified:
                    modified.append(path)
                continue
            if name == "run" and result["status"] == "error" and result.get("error_kind") == "process_exit":
                label = f"exit code {result.get('exit_code')}"
            else:
                label = result["status"]
            changed = "workspace changed since" if result["workspace_revision_after"] != current_revision else "workspace unchanged since"
            preview = " ".join(result.get("preview", "").split())[: self.preview_chars]
            summary = json.dumps(arguments, ensure_ascii=False, sort_keys=True)[:160]
            failures.append(f"- {name} {summary}: {label}; {changed}. Output: {preview}")

        notes = [record.name for record in runtime.scratch.list("notes/")]
        lines = [
            "RUNTIME BOARD (generated from the journal; conditional evidence, not rules)",
            f"Model calls so far: {model_calls}. Earlier exchanges not shown here: {omitted_units}.",
            "Files modified so far: " + (", ".join(modified) if modified else "none"),
            "Saved notes: " + (", ".join(name.split("/", 1)[1] for name in notes) if notes else "none")
            + " (read_note retrieves one; pinned notes appear above).",
        ]
        if failures:
            shown = failures[-self.failure_limit:]
            lines.append(
                f"Unsuccessful actions ({len(failures)} total, most recent {len(shown)} shown). "
                "Retrying is reasonable when the workspace or approach has changed:"
            )
            lines.extend(shown)
        else:
            lines.append("Unsuccessful actions: none.")
        return "\n".join(lines)

    def build(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        transcript: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_context_bytes: int,
        diagnostics: Optional[List[str]] = None,
    ) -> ContextBuildResult:
        units = self.renderer._paired_units(transcript)
        recent_units = units[-self.recent_units:]
        recent = [message for unit in recent_units for message in unit]
        board = {"role": "user", "content": self._board(runtime, len(units) - len(recent_units))}
        return self.renderer.build(runtime, task, [*recent, board], tools, max_context_bytes, diagnostics)
