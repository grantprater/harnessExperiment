"""Opt-in model interface for durable evidence memory and advisory inference."""

import json
from pathlib import Path
import hashlib

from reticle.tools.primitives import ToolOutcome, _function


ENTITY = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["requirement", "hypothesis", "check", "change", "code_entity", "procedure"]},
        "text": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "cases": {"type": "array", "items": {"type": "string"}},
        "predictions": {"type": "object", "additionalProperties": {"type": "string"}},
        "observation": {"type": "string"},
        "path": {"type": "string"},
        "conditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "kind", "text", "evidence"],
}
RELATION = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "source": {"type": "string"}, "target": {"type": "string"},
        "relation": {"type": "string", "enum": ["supports", "contradicts", "tests", "depends_on", "addresses", "supersedes"]},
    }, "required": ["source", "relation", "target"],
}
REASONING_SCHEMAS = [
    _function("reasoning_state",
              "Recover durable hypotheses, checks, the authorized task description and runtime tool observations. Use "
              "evidence event IDs from observations or task requirements when adding assertions. Model scopes and "
              "semantic links are unverified claims. "
              "Code entities record a file fingerprint at assertion time. Procedures describe reusable steps with conditions. "
              "In symbolic mode, also returns advisory findings; missing evidence is unknown. Page with next_offset "
              "and as_of_sequence=high_water_sequence to keep the graph fixed. Staleness uses the current workspace.",
              {"offset": {"type": "integer"}, "limit": {"type": "integer"}, "focus": {"type": "string"},
               "as_of_sequence": {"type": "integer"}}, []),
    _function("reasoning_update",
              "Record at most 20 evidence-backed assertions/relations. Every entity requires a unique immutable ID "
              "and evidence listing authorized tool-output or task-description event IDs (from reasoning_state). "
              "Use supersedes to revise an assertion. Observations and task descriptions are runtime-owned. "
              "cases declare input classes for requirements/checks; "
              "check predictions map hypothesis IDs to expected outcomes; check observation references obs:<event_id> "
              "from a run tool. These declarations remain model assertions; they do not establish acceptance.",
              {"entities": {"type": "array", "items": ENTITY},
               "relations": {"type": "array", "items": RELATION}}, []),
    _function("assess_check", "Return the reasoning state focused on an existing check, with advisory findings in "
              "symbolic mode. This tool does not execute a command or certify the check's coverage.",
              {"id": {"type": "string"}}, ["id"]),
]


def tool_contract():
    return {"source_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "schemas": REASONING_SCHEMAS}


class ReasoningTools:
    def __init__(self, *args, reasoning, **kwargs):
        super().__init__(*args, **kwargs)
        self.reasoning = reasoning

    def schemas(self):
        return [*super().schemas(), *json.loads(json.dumps(REASONING_SCHEMAS))]

    def _dispatch(self, name, arguments, call_id):
        schema = next((item["function"] for item in REASONING_SCHEMAS if item["function"]["name"] == name), None)
        if schema is None:
            return super()._dispatch(name, arguments, call_id)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(parsed, dict):
                raise ValueError("arguments must be a JSON object")
            allowed = schema["parameters"]["properties"]
            if set(parsed) - set(allowed) or set(schema["parameters"]["required"]) - set(parsed):
                raise ValueError("unsupported or missing arguments; see the tool schema")
        except ValueError as exc:
            message = str(exc)
            return self._journaled(call_id, name, {}, lambda: ToolOutcome(message, "rejected"))

        def action():
            try:
                if name == "reasoning_update":
                    result = self.reasoning.update(**parsed)
                elif name == "assess_check":
                    result = self.reasoning.state(focus=parsed["id"])
                    if next(entity for entity in result["entities"] if entity["id"] == parsed["id"])["kind"] != "check":
                        raise ValueError("assess_check requires a check ID")
                else:
                    result = self.reasoning.state(**parsed)
                return ToolOutcome(json.dumps(result, sort_keys=True), "success")
            except (ValueError, TypeError, KeyError) as exc:
                return ToolOutcome(str(exc), "rejected")

        return self._journaled(call_id, name, parsed, action)
