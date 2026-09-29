"""Hypothesis commitment tools (card 021): the structured half of the commitment nudge.

Two tools, offered from the first request whenever ``--nudge commit`` is on (reticle.runtime.nudges.CommitmentNudge
asks for them at the nudge fraction):
  commit_hypothesis   the leading hypothesis (file, function, line, mechanism) and a prediction: one specific
                      observation the model will make next and exactly what it will show if the hypothesis holds;
  record_observation  what that observation showed, whether it matched, and on a mismatch the surprise and the
                      revised hypothesis.
Neither tool acts on the workspace. Each call is journaled as a ``hypothesis_commit`` or ``hypothesis_observation``
event with the fields, the response and workspace revision it came at, and (for an observation) the tool calls made
since the commitment it answers. These records are the card's grader-free instrument: does a prediction that failed,
or was never checked, predict rejection? Nothing in a run reads them back; scoring against the mutation (file,
function, line) is offline (experiments/session_harness/score_commitments.py).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from reticle.tools.primitives import ToolOutcome


COMMITMENT_TOOLS_VERSION = "commitment-tools-v1"
COMMIT_TOOL, OBSERVE_TOOL = "commit_hypothesis", "record_observation"

_COMMIT_PARAMETERS = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Workspace-relative path of the file you believe holds the fault."},
        "function": {"type": "string", "description": "The function or method (Class.method) you believe is wrong."},
        "line": {"type": "integer", "description": "The line number you believe is wrong."},
        "mechanism": {"type": "string",
                      "description": "What is wrong there and how it produces the reported behavior."},
        "observation": {"type": "string",
                        "description": "The one command or read you will make next to test this hypothesis."},
        "prediction": {"type": "string",
                       "description": "Exactly what that observation will show if the hypothesis is right."},
    },
    "required": ["file", "function", "line", "mechanism", "observation", "prediction"],
}
_OBSERVE_PARAMETERS = {
    "type": "object",
    "properties": {
        "observed": {"type": "string", "description": "What the observation actually showed."},
        "matched": {"type": "boolean", "description": "Whether it showed what you predicted."},
        "surprise": {"type": "string",
                     "description": "Required when matched is false: what differed from the prediction and what "
                                    "that tells you."},
        "revised_hypothesis": {"type": "string",
                               "description": "Your leading hypothesis now, if it changed (file, function, line, "
                                              "mechanism)."},
    },
    "required": ["observed", "matched"],
}
COMMITMENT_SCHEMAS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": COMMIT_TOOL,
        "description": ("Record your leading hypothesis about the fault and a concrete prediction you will test "
                        "next. It changes nothing in the workspace; make the observation you named with the other "
                        "tools, then call record_observation."),
        "parameters": _COMMIT_PARAMETERS}},
    {"type": "function", "function": {
        "name": OBSERVE_TOOL,
        "description": ("Record what the observation you predicted in commit_hypothesis showed and whether it "
                        "matched; on a mismatch, what surprised you and your revised hypothesis. It changes nothing "
                        "in the workspace."),
        "parameters": _OBSERVE_PARAMETERS}},
]
_TYPES = {"string": str, "integer": int, "boolean": bool}


def commitment_schemas() -> List[Dict[str, Any]]:
    return json.loads(json.dumps(COMMITMENT_SCHEMAS))


def _problems(arguments: Dict[str, Any], parameters: Dict[str, Any]) -> List[str]:
    properties = parameters["properties"]
    problems = [f"unknown argument {key!r}" for key in sorted(arguments) if key not in properties]
    problems += [f"missing argument {key!r}" for key in parameters["required"] if key not in arguments]
    for key, value in arguments.items():
        expected = (properties.get(key) or {}).get("type")
        kind = _TYPES.get(expected)
        if kind is None:
            continue
        wrong = not isinstance(value, kind) or (kind is int and isinstance(value, bool))
        if wrong or (kind is str and not value.strip()):
            problems.append(f"{key!r} must be a non-empty string" if kind is str else f"{key!r} must be {expected}")
    return problems


class CommitmentLog:
    """The run's commitments and observations, as journaled; record() is the per-run summary."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.commits: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.calls_seen = 0  # every tool call dispatched in this suite, in order
        self._commit_call_index = None

    def _nudged(self) -> bool:
        """Whether the commitment nudge's harness message is already in the journal."""
        return any(event.kind == "harness_message" and event.payload.get("name") == "commit"
                   for event in self.runtime.journal.read_all())

    def commit(self, arguments: Dict[str, Any], tool_names_so_far: List[str]) -> str:
        entry = {"n": len(self.commits) + 1, **{key: arguments[key] for key in _COMMIT_PARAMETERS["properties"]},
                 "tool_calls_before": len(tool_names_so_far) - 1, "after_nudge": self._nudged(),
                 "workspace_revision": self.runtime.workspace.revision()}
        self.commits.append(entry)
        self._commit_call_index = len(tool_names_so_far) - 1
        self.runtime.journal.append("hypothesis_commit", {"version": COMMITMENT_TOOLS_VERSION, **entry})
        return (f"Hypothesis {entry['n']} recorded. Make the observation you named, then call record_observation "
                "with what it showed.")

    def observe(self, arguments: Dict[str, Any], tool_names_so_far: List[str]) -> str:
        since = [] if self._commit_call_index is None else tool_names_so_far[self._commit_call_index + 1:-1]
        entry = {"n": len(self.observations) + 1, "commit": self.commits[-1]["n"] if self.commits else None,
                 "observed": arguments["observed"], "matched": arguments["matched"],
                 "surprise": arguments.get("surprise"), "revised_hypothesis": arguments.get("revised_hypothesis"),
                 "tool_calls_since_commit": since, "workspace_revision": self.runtime.workspace.revision()}
        self.observations.append(entry)
        self.runtime.journal.append("hypothesis_observation", {"version": COMMITMENT_TOOLS_VERSION, **entry})
        if entry["commit"] is None:
            return "Observation recorded (no hypothesis was committed before it)."
        return f"Observation recorded for hypothesis {entry['commit']}."

    def record(self) -> Dict[str, Any]:
        matched = [o["matched"] for o in self.observations]
        return {"version": COMMITMENT_TOOLS_VERSION, "commits": len(self.commits),
                "commits_after_nudge": sum(1 for c in self.commits if c["after_nudge"]),
                "observations": len(self.observations), "matched": matched.count(True),
                "mismatched": matched.count(False),
                "first_commit": ({key: self.commits[0][key] for key in ("file", "function", "line")}
                                 if self.commits else None),
                "last_commit": ({key: self.commits[-1][key] for key in ("file", "function", "line")}
                                if self.commits else None)}


class CommitmentTools:
    """ToolSuite mixin: offers commit_hypothesis and record_observation (appended to the toolset's schemas)."""

    def __init__(self, *args, commitment: CommitmentLog, **kwargs):
        super().__init__(*args, **kwargs)
        self.commitment = commitment
        self._commitment_tool_names: List[str] = []
        self._handlers[COMMIT_TOOL] = self._commit
        self._handlers[OBSERVE_TOOL] = self._observe

    def schemas(self) -> List[Dict[str, Any]]:
        return [*super().schemas(), *commitment_schemas()]

    def dispatch(self, name, arguments, call_id):
        self._commitment_tool_names.append(str(name))
        return super().dispatch(name, arguments, call_id)

    def _dispatch(self, name, arguments, call_id):
        if name not in (COMMIT_TOOL, OBSERVE_TOOL):
            return super()._dispatch(name, arguments, call_id)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (
                {} if isinstance(arguments, str) else arguments)
        except json.JSONDecodeError as exc:
            message = f"ERROR: arguments are not valid JSON ({exc.msg} at position {exc.pos}); nothing was recorded."
            return self._journaled(call_id, name, {"raw_arguments": arguments}, lambda: ToolOutcome(message, "rejected"))
        if not isinstance(parsed, dict):
            return self._journaled(call_id, name, {"raw_arguments": parsed}, lambda: ToolOutcome(
                "ERROR: arguments must be a JSON object; nothing was recorded.", "rejected"))
        parameters = _COMMIT_PARAMETERS if name == COMMIT_TOOL else _OBSERVE_PARAMETERS
        problems = _problems(parsed, parameters)
        if name == OBSERVE_TOOL and parsed.get("matched") is False and not str(parsed.get("surprise") or "").strip():
            problems.append("'surprise' is required when matched is false")
        if problems:
            message = f"ERROR: {'; '.join(problems)}; nothing was recorded."
            return self._journaled(call_id, name, parsed, lambda: ToolOutcome(message, "rejected"))
        return self._journaled(call_id, name, parsed, lambda: self._handlers[name](parsed))

    def _commit(self, arguments: Dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(self.commitment.commit(arguments, list(self._commitment_tool_names)), "success")

    def _observe(self, arguments: Dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(self.commitment.observe(arguments, list(self._commitment_tool_names)), "success")
