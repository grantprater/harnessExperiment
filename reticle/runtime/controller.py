"""Model-driven action loop: context policy -> model -> tools -> exact transcript.

The controller records what was sent, what came back, and provider-reported usage.
A finish request ends the loop; acceptance is decided separately by an evaluator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import hashlib
from time import monotonic
from typing import Any, Dict, List, Optional, Protocol, Sequence
from uuid import uuid4

from reticle.context.baseline import BaselineContextPolicy, ContextBuilder, ContextPolicy, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.budgets import ProviderAttemptRecorder, TaskBudgetExhausted, TaskBudgetLedger
from reticle.runtime.ownership import SessionWriterLock
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


class AttemptReportingModelClient(Protocol):
    """Opt-in client that journals every underlying provider attempt, including retries."""

    reports_provider_attempts: bool  # must be True

    def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        attempts: ProviderAttemptRecorder,
    ) -> ModelResponse: ...


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
    # finish_requested | model_call_limit | model_error | needs_reconciliation |
    # context_budget_exhausted | task_budget_exhausted | task_deadline_reached
    stop_reason: str
    model_calls: int  # model requests; provider_attempts counts retries within them
    tool_calls: int
    final_workspace_revision: str
    usage_reported: Dict[str, float]
    calls_missing_usage: Dict[str, int]
    finish_summary: Optional[str] = None
    error: Optional[str] = None
    task_resources: Dict[str, Any] = field(default_factory=dict)
    provider_attempts: int = 0

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
        interventions: Sequence[Any] = (),
        expose_usage: bool = False,
    ):
        self.runtime = runtime
        self.task = task
        self.tools = tools
        self.client = client
        self.limits = limits
        self.policy = policy or BaselineContextPolicy()
        # Agent-loop treatments (reticle.runtime.nudges); none by default, and then the loop is unchanged.
        self.interventions = tuple(interventions)
        self.expose_usage = expose_usage

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

    def _charge_active_time(self, budget: TaskBudgetLedger, outcome: str) -> None:
        now = monotonic()
        elapsed, self._active_mark = now - self._active_mark, now
        if elapsed > 0:
            budget.charge("active_seconds", elapsed, outcome=outcome)

    def _resource_status(self, budget: TaskBudgetLedger, model_calls: int) -> Dict[str, Any]:
        """Remaining resources before the next model response, as the ledger and invocation limit enforce them."""
        snapshot = budget.snapshot()
        status: Dict[str, Any] = {}
        invocation_left = self.limits.max_model_calls - model_calls
        task_left = snapshot.remaining.get("model_responses")
        if task_left is None or invocation_left < task_left:
            status["model_responses"] = {"remaining": invocation_left, "limit": self.limits.max_model_calls}
        else:
            status["model_responses"] = {"remaining": task_left, "limit": snapshot.limits["model_responses"]}
        for resource in ("model_attempts", "tool_actions", "active_seconds", "cost_usd"):
            if resource in snapshot.limits:
                status[resource] = {"remaining": snapshot.remaining[resource], "limit": snapshot.limits[resource]}
        reservation = self.task.budgets.get("model_attempt_cost_reservation")
        if "cost_usd" in snapshot.limits and isinstance(reservation, (int, float)) and not isinstance(reservation, bool):
            status["attempt_cost_reservation_usd"] = float(reservation)
        if "cost_usd" in snapshot.limits:
            status["cost_unknown_billing_attempts"] = budget.unknown_billing_count()
        if self.expose_usage:
            from reticle.runtime.telemetry import model_token_usage
            status['model_token_usage'] = model_token_usage(self.runtime, self.task.task_id)
        return status

    def _intervene(self, transcript: TranscriptStore, budget: TaskBudgetLedger, model_calls: int) -> None:
        """Append each intervention's harness message, if any, after the latest results; journal it."""
        if not self.interventions:
            return
        responses = self._resource_status(budget, model_calls)["model_responses"]
        used, limit = responses["limit"] - responses["remaining"], responses["limit"]
        for intervention in self.interventions:
            text = intervention.message_after_response(self.runtime, used, limit)
            if not text:
                continue
            marker = {"name": intervention.name, "version": intervention.version}
            artifact_id = transcript.append({"role": "system", "content": text, "_reticle_harness_message": marker})
            self.runtime.journal.append("harness_message", {
                "task_id": self.task.task_id, **marker, "content": text, "after_response": used,
                "response_limit": limit, "transcript_artifact_id": artifact_id,
            })

    def _record_budget_stop(self, exc: TaskBudgetExhausted, **extra: Any) -> None:
        self.runtime.journal.append("task_budget_exhausted", {
            "task_id": self.task.task_id,
            "resource": exc.resource,
            "requested": exc.requested,
            "remaining": exc.remaining,
            **extra,
        })

    def run(self) -> AgentRunResult:
        owner_id = f"controller-{uuid4().hex}"
        writer = SessionWriterLock(self.runtime.session_dir).acquire(owner_id)
        try:
            return self._run_owned()
        finally:
            writer.release()

    def _resume_recorded_actions(
        self, transcript: TranscriptStore, budget: TaskBudgetLedger
    ) -> tuple[int, bool, Optional[str], Optional[str]]:
        messages = transcript.load()
        completed = {
            message.get("tool_call_id") for message in messages if message.get("role") == "tool"
        }
        pending = [
            call
            for message in messages if message.get("role") == "assistant"
            for call in message.get("tool_calls", [])
            if call.get("id") not in completed
        ]
        not_started = {
            state.call_id: state.operation_id
            for state in self.runtime.recovery.pending_operations
            if state.classification == "known_not_started" and state.call_id
        }
        tool_calls = 0
        finished = False
        finish_summary: Optional[str] = None
        error: Optional[str] = None
        for call in pending:
            function = call.get("function") or {}
            call_id = str(call.get("id"))
            message: Dict[str, Any] = {"role": "tool", "tool_call_id": call_id}
            if finished:
                message["content"] = "Not executed: finish was requested earlier in this response."
                transcript.append(message)
                continue
            old_operation = not_started.get(call_id)
            if old_operation:
                self.runtime.abandon_not_started_action(
                    old_operation, "superseded by durable response continuation"
                )
            try:
                resource_operation = budget.reserve("tool_actions", 1)
            except TaskBudgetExhausted as exc:
                message["content"] = f"Not executed: {exc}"
                error = str(exc)
                finished = True
            else:
                tool_calls += 1
                self._charge_active_time(budget, "dispatch_boundary")
                outcome = self.tools.dispatch(
                    str(function.get("name") or ""), function.get("arguments", "{}"), call_id
                )
                budget.reconcile(resource_operation, 1, outcome=outcome.status)
                message["content"] = outcome.content
                if outcome.handle:
                    message["_reticle_output"] = {
                        "handle": outcome.handle,
                        "tool": function.get("name"),
                        "status": outcome.status,
                    }
                if outcome.finished:
                    finished = True
                    finish_summary = self._summary(str(function.get("arguments", "{}")))
            transcript.append(message)
        return tool_calls, finished, finish_summary, error

    def _run_owned(self) -> AgentRunResult:
        self.runtime.repair_model_response_publications()
        self.runtime.repair_completed_action_publications()
        extensions = getattr(self.tools, 'extensions', None)
        if extensions:
            extensions.begin_turn(self.task.task_id)
        style = getattr(self.tools, 'style', None)
        if style:
            style.begin_turn(self.task.task_id)
        transcript = TranscriptStore(self.runtime)
        builder = ContextBuilder(self.policy)
        self.runtime.persist_task_contract(self.task)
        budget = TaskBudgetLedger(self.runtime, self.task.task_id, self.task.budgets)
        self._active_mark = monotonic()
        reported = {name: 0.0 for name in USAGE_FIELDS}
        missing = {name: 0 for name in USAGE_FIELDS}
        model_calls = 0
        provider_attempts = 0
        tool_calls = 0
        stop_reason = "model_call_limit"
        finish_summary: Optional[str] = None
        error: Optional[str] = None
        ambiguous = [
            state for state in self.runtime.recovery.pending_operations
            if state.classification == "unknown_external_outcome" and not state.replay_safe
        ]
        recovery_blocked = bool(ambiguous)
        if recovery_blocked:
            stop_reason = "needs_reconciliation"
            error = "Unknown external outcome for: " + ", ".join(
                state.operation_id for state in ambiguous
            )
            self.runtime.journal.append("controller_needs_reconciliation", {
                "task_id": self.task.task_id,
                "operation_ids": [state.operation_id for state in ambiguous],
            })

        if not recovery_blocked:
            resumed_calls, resumed_finished, resumed_summary, resumed_error = self._resume_recorded_actions(
                transcript, budget
            )
            tool_calls += resumed_calls
            if resumed_error:
                stop_reason, error = "task_budget_exhausted", resumed_error
                recovery_blocked = True
            elif resumed_finished:
                stop_reason, finish_summary = "finish_requested", resumed_summary
                recovery_blocked = True

        while not recovery_blocked and model_calls < self.limits.max_model_calls:
            # Dispatch boundary: persist active time so a crash cannot renew it.
            self._charge_active_time(budget, "dispatch_boundary")
            active_remaining = budget.snapshot().remaining.get("active_seconds")
            if active_remaining is not None and active_remaining <= 0:
                stop_reason = "task_budget_exhausted"
                error = "Task active-time budget exhausted before model dispatch"
                self.runtime.journal.append("task_budget_exhausted", {
                    "task_id": self.task.task_id,
                    "resource": "active_seconds",
                    "remaining": active_remaining,
                })
                break
            if budget.deadline_passed():
                stop_reason = "task_deadline_reached"
                error = f"Task deadline {budget.deadline.isoformat()} passed before model dispatch"
                self.runtime.journal.append("task_deadline_reached", {
                    "task_id": self.task.task_id,
                    "deadline_utc": budget.deadline.isoformat(),
                })
                break
            build_options: Dict[str, Any] = {}
            if getattr(self.policy, "renders_resource_status", False):
                build_options["resource_status"] = self._resource_status(budget, model_calls)
            built = builder.build(
                self.runtime, self.task, transcript.load(), self.tools.schemas(), self.limits.max_context_bytes,
                **build_options,
            )
            materialized = self.runtime.artifacts.read(
                built.manifest.materialized_request_artifact_id
            )
            request_envelope = self.runtime.artifacts.get_envelope(
                built.manifest.materialized_request_artifact_id
            )
            expected = json.dumps(
                {"messages": built.messages, "tools": built.tools},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            if materialized != expected:
                raise RuntimeError("materialized context request does not match the provider request")
            if (
                request_envelope.content_hash != built.manifest.materialized_request_hash
                or len(materialized) != built.manifest.request_bytes
            ):
                raise RuntimeError("context manifest size or hash does not match its request artifact")
            if len(materialized) > self.limits.max_context_bytes or built.over_budget:
                stop_reason = "context_budget_exhausted"
                error = (
                    f"materialized request is {len(materialized)} bytes; "
                    f"limit is {self.limits.max_context_bytes} bytes"
                )
                self.runtime.journal.append(
                    "context_budget_exhausted",
                    {
                        "request_artifact_id": built.manifest.materialized_request_artifact_id,
                        "request_hash": built.manifest.materialized_request_hash,
                        "request_bytes": len(materialized),
                        "max_context_bytes": self.limits.max_context_bytes,
                        "policy_version": built.manifest.policy_version,
                    },
                )
                break
            cost_reservation: Optional[float] = None
            if "cost_usd" in budget.limits:
                reservation = self.task.budgets.get("model_attempt_cost_reservation")
                if isinstance(reservation, bool) or not isinstance(reservation, (int, float)) or reservation <= 0:
                    stop_reason = "task_budget_exhausted"
                    error = "A positive model_attempt_cost_reservation is required with cost_usd"
                    self.runtime.journal.append("task_budget_exhausted", {
                        "task_id": self.task.task_id,
                        "resource": "cost_usd",
                        "reason": "missing_conservative_reservation",
                    })
                    break
                cost_reservation = float(reservation)
            # An attempt-reporting client reserves each underlying provider attempt itself;
            # any other client is charged one attempt per request.
            attempt_aware = getattr(self.client, "reports_provider_attempts", False) is True
            attempt_operation: Optional[str] = None
            try:
                if attempt_aware:
                    budget.require_available("model_attempts", 1)
                    if cost_reservation is not None:
                        budget.require_available("cost_usd", cost_reservation)
                    request_id = f"model-request:{self.task.task_id}:{uuid4().hex}"
                else:
                    attempt_operation = budget.reserve("model_attempts", 1)
                    request_id = attempt_operation
            except TaskBudgetExhausted as exc:
                stop_reason, error = "task_budget_exhausted", str(exc)
                self._record_budget_stop(exc)
                break
            request_ref = {
                "task_id": self.task.task_id,
                "call_index": model_calls + 1,
                "attempt_id": request_id,
                "request_artifact_id": built.manifest.materialized_request_artifact_id,
                "request_hash": built.manifest.materialized_request_hash,
                "context_over_budget": built.over_budget,
                "runtime_version": os.environ.get('RETICLE_RUNTIME_VERSION', 'unversioned'),
                "extension_versions": getattr(self.tools, 'extensions', None).versions()
                    if getattr(self.tools, 'extensions', None) else {},
                "style_profile_id": getattr(self.tools, 'style', None).target_id
                    if getattr(self.tools, 'style', None) else None,
                "context_policy_version": built.manifest.policy_version,
                "request_bytes": built.manifest.request_bytes,
                "decision_state_event_id": next((item.get('state_event_id') for item in built.manifest.selected_items
                                                   if item.get('kind') == 'decision_state'), None),
                "token_target": self.task.budgets.get('token_target'),
                "usage_feedback_enabled": self.expose_usage,
                "tool_schema_hash": hashlib.sha256(json.dumps(
                    built.tools, sort_keys=True, separators=(',', ':'), ensure_ascii=False
                ).encode('utf-8')).hexdigest(),
            }
            try:
                response_operation = budget.reserve("model_responses", 1)
            except TaskBudgetExhausted as exc:
                if attempt_operation is not None:
                    budget.reconcile(attempt_operation, 0, outcome="not_dispatched_response_budget_exhausted")
                stop_reason, error = "task_budget_exhausted", str(exc)
                self._record_budget_stop(exc)
                break
            cost_operation: Optional[str] = None
            if attempt_operation is not None and cost_reservation is not None:
                try:
                    cost_operation = budget.reserve("cost_usd", cost_reservation)
                except TaskBudgetExhausted as exc:
                    budget.reconcile(attempt_operation, 0, outcome="not_dispatched_cost_exhausted")
                    budget.reconcile(response_operation, 0, outcome="not_dispatched_cost_exhausted")
                    stop_reason, error = "task_budget_exhausted", str(exc)
                    self._record_budget_stop(exc)
                    break
            self.runtime.journal.append("model_request_intent", {
                "task_id": self.task.task_id,
                "attempt_reporting": attempt_aware,
                **request_ref,
            }, operation_id=request_id)
            model_calls += 1
            recorder = (
                ProviderAttemptRecorder(budget, request_id, cost_reservation) if attempt_aware else None
            )
            try:
                if recorder is not None:
                    response = self.client.complete(built.messages, built.tools, attempts=recorder)
                else:
                    response = self.client.complete(built.messages, built.tools)
            except (ModelClientError, TaskBudgetExhausted) as exc:
                if recorder is not None:
                    recorder.close_unfinished(succeeded=False)
                    provider_attempts += recorder.count
                else:
                    provider_attempts += 1
                    budget.reconcile(str(attempt_operation), 1, outcome="provider_error")
                    if cost_operation is not None:
                        budget.reconcile(cost_operation, None, outcome="unknown_billing_after_provider_error")
                budget.reconcile(response_operation, 0, outcome="provider_error")
                self.runtime.journal.append("model_call_failed", {
                    **request_ref,
                    "error": str(exc),
                    "provider_attempts": recorder.count if recorder is not None else 1,
                })
                if isinstance(exc, TaskBudgetExhausted):
                    stop_reason, error = "task_budget_exhausted", str(exc)
                    self._record_budget_stop(exc, request_id=request_id)
                else:
                    stop_reason, error = "model_error", str(exc)
                break

            usage = response.usage if isinstance(response.usage, dict) else None
            actual_cost = usage.get("cost") if usage else None
            if isinstance(actual_cost, bool) or not isinstance(actual_cost, (int, float)):
                actual_cost = None
            if recorder is not None:
                recorder.close_unfinished(succeeded=True, final_cost=actual_cost)
                if recorder.count == 0:
                    # Contract violation: a response arrived without a recorded attempt.
                    budget.charge("model_attempts", 1, outcome="unrecorded_provider_attempt")
                provider_attempts += max(recorder.count, 1)
            else:
                provider_attempts += 1
                budget.reconcile(str(attempt_operation), 1, outcome="response")
                if cost_operation is not None:
                    budget.reconcile(cost_operation, actual_cost, outcome=(
                        "reported" if actual_cost is not None else "unknown_billing"
                    ))
            budget.reconcile(response_operation, 1, outcome="response_persisted")
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
            message["_reticle_attempt_id"] = attempt_operation
            transcript.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                transcript.append({"role": "user", "content": NO_TOOL_CALL_PROMPT})
                self._intervene(transcript, budget, model_calls)
                continue

            finished = False
            for call in calls:
                function = call["function"]
                message = {"role": "tool", "tool_call_id": call["id"]}
                if finished:
                    message["content"] = "Not executed: finish was requested earlier in this response."
                    self.runtime.journal.append(
                        "tool_call_skipped", {"call_id": call["id"], "name": function["name"], "reason": "after_finish"}
                    )
                else:
                    try:
                        tool_operation = budget.reserve("tool_actions", 1)
                    except TaskBudgetExhausted as exc:
                        message["content"] = f"Not executed: {exc}"
                        stop_reason, error = "task_budget_exhausted", str(exc)
                        finished = True
                        self.runtime.journal.append("task_budget_exhausted", {
                            "task_id": self.task.task_id,
                            "resource": exc.resource,
                            "requested": exc.requested,
                            "remaining": exc.remaining,
                            "call_id": call["id"],
                        })
                    else:
                        tool_calls += 1
                        self._charge_active_time(budget, "dispatch_boundary")
                        outcome = self.tools.dispatch(function["name"], function["arguments"], call["id"])
                        budget.reconcile(tool_operation, 1, outcome=outcome.status)
                        message["content"] = outcome.content
                        if outcome.handle:
                            # Private key: lets context policies show a bounded view that names this output.
                            message["_reticle_output"] = {
                                "handle": outcome.handle,
                                "tool": function["name"],
                                "status": outcome.status,
                            }
                        if outcome.finished:
                            finished = True
                            finish_summary = self._summary(function["arguments"])
                transcript.append(message)
            if finished:
                if stop_reason != "task_budget_exhausted":
                    stop_reason = "finish_requested"
                break
            self._intervene(transcript, budget, model_calls)

        self._charge_active_time(budget, "controller_invocation")
        task_snapshot = budget.snapshot()

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
            task_resources={
                "limits": task_snapshot.limits,
                "consumed": task_snapshot.consumed,
                "reserved": task_snapshot.reserved,
                "remaining": task_snapshot.remaining,
                "pending": task_snapshot.pending,
                "adjusted": task_snapshot.adjusted,
            },
            provider_attempts=provider_attempts,
        )
        self.runtime.journal.append("agent_run_result", {"result": result.to_dict()})
        return result
