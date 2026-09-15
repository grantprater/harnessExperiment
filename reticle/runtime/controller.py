"""Model-driven action loop: context policy -> model -> tools -> exact transcript.

The controller records what was sent, what came back, and provider-reported usage.
A finish request ends the loop; acceptance is decided separately by an evaluator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Optional, Protocol

from reticle.context.baseline import BaselineContextPolicy, ContextBuilder, ContextPolicy, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime
from reticle.tools.primitives import ToolSuite


NO_TOOL_CALL_PROMPT = (
    "No tool call was received. Continue by calling a tool, or call finish when the task is complete."
)
USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "cost")


@dataclass(frozen=True)
class ModelResponse:
    message: Dict[str, Any]
    usage: Optional[Dict[str, Any]] = None  # exactly as reported by the provider; None if absent
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelClientError(RuntimeError):
    """A provider call failed after the client's own retry policy."""


class ModelClient(Protocol):
    def complete(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ModelResponse: ...


@dataclass(frozen=True)
class AgentLimits:
    max_model_calls: int
    max_context_bytes: int

    def __post_init__(self) -> None:
        if self.max_model_calls <= 0 or self.max_context_bytes <= 0:
            raise ValueError("agent limits must be positive")


@dataclass(frozen=True)
class AgentRunResult:
    task_id: str
    stop_reason: str  # finish_requested | model_call_limit | model_error
    model_calls: int
    tool_calls: int
    final_workspace_revision: str
    usage_reported: Dict[str, float]
    calls_missing_usage: Dict[str, int]
    finish_summary: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentController:
    def __init__(
        self,
        runtime: LocalRuntime,
        task: TaskEnvelope,
        tools: ToolSuite,
        client: ModelClient,
        limits: AgentLimits,
        policy: Optional[ContextPolicy] = None,
    ):
        self.runtime = runtime
        self.task = task
        self.tools = tools
        self.client = client
        self.limits = limits
        self.policy = policy or BaselineContextPolicy()

    @staticmethod
    def _normalize(message: Dict[str, Any], call_index: int) -> Dict[str, Any]:
        content = message.get("content")
        if isinstance(content, list):  # some providers return content parts
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
            # Some reasoning models require their reasoning to be returned with tool results.
            normalized["reasoning_details"] = message["reasoning_details"]
        return normalized

    @staticmethod
    def _summary(arguments: str) -> Optional[str]:
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            return None
        summary = value.get("summary") if isinstance(value, dict) else None
        return str(summary)[:2_000] if summary is not None else None

    def run(self) -> AgentRunResult:
        transcript = TranscriptStore(self.runtime)
        builder = ContextBuilder(self.policy)
        reported = {name: 0.0 for name in USAGE_FIELDS}
        missing = {name: 0 for name in USAGE_FIELDS}
        model_calls = 0
        tool_calls = 0
        stop_reason = "model_call_limit"
        finish_summary: Optional[str] = None
        error: Optional[str] = None

        while model_calls < self.limits.max_model_calls:
            built = builder.build(
                self.runtime, self.task, transcript.load(), self.tools.schemas(), self.limits.max_context_bytes
            )
            model_calls += 1
            request_ref = {
                "call_index": model_calls,
                "request_artifact_id": built.manifest.materialized_request_artifact_id,
                "request_hash": built.manifest.materialized_request_hash,
                "context_over_budget": built.over_budget,
            }
            try:
                response = self.client.complete(built.messages, built.tools)
            except ModelClientError as exc:
                self.runtime.journal.append("model_call_failed", {**request_ref, "error": str(exc)})
                stop_reason, error = "model_error", str(exc)
                break

            usage = response.usage if isinstance(response.usage, dict) else None
            for name in USAGE_FIELDS:
                value = usage.get(name) if usage else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    reported[name] += value
                else:
                    missing[name] += 1
            event_id = self.runtime.journal.new_event_id()
            response_artifact = self.runtime.artifacts.put(
                json.dumps(response.message, sort_keys=True, ensure_ascii=False).encode("utf-8"),
                "application/json",
                event_id,
                labels=["model-response"],
            )
            self.runtime.journal.append(
                "model_call",
                {
                    **request_ref,
                    "response_artifact_id": response_artifact.artifact_id,
                    "usage": usage,
                    "metadata": response.metadata,
                },
                event_id=event_id,
            )

            message = self._normalize(response.message, model_calls)
            transcript.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                transcript.append({"role": "user", "content": NO_TOOL_CALL_PROMPT})
                continue

            finished = False
            for call in calls:
                function = call["function"]
                if finished:
                    content = "Not executed: finish was requested earlier in this response."
                    self.runtime.journal.append(
                        "tool_call_skipped", {"call_id": call["id"], "name": function["name"], "reason": "after_finish"}
                    )
                else:
                    tool_calls += 1
                    outcome = self.tools.dispatch(function["name"], function["arguments"], call["id"])
                    content = outcome.content
                    if outcome.finished:
                        finished = True
                        finish_summary = self._summary(function["arguments"])
                transcript.append({"role": "tool", "tool_call_id": call["id"], "content": content})
            if finished:
                stop_reason = "finish_requested"
                break

        result = AgentRunResult(
            task_id=self.task.task_id,
            stop_reason=stop_reason,
            model_calls=model_calls,
            tool_calls=tool_calls,
            final_workspace_revision=self.runtime.workspace.revision(),
            usage_reported=reported,
            calls_missing_usage=missing,
            finish_summary=finish_summary,
            error=error,
        )
        self.runtime.journal.append("agent_run_result", {"result": result.to_dict()})
        return result
