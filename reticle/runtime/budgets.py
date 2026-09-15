"""Journal-derived cumulative task resource reservations and reconciliation.

Pause and deadline semantics: a task is paused whenever no controller owns its session
(between invocations, or after a crash). ``active_seconds`` accrues only while a controller
runs and is charged at each dispatch boundary, so a crash loses at most the time since the
last boundary. ``deadline_utc`` is an absolute wall-clock limit that keeps running while
paused. Pausing never releases a pending reservation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reticle.runtime.session import LocalRuntime


class TaskBudgetExhausted(RuntimeError):
    def __init__(self, resource: str, requested: float, remaining: Optional[float]):
        self.resource = resource
        self.requested = requested
        self.remaining = remaining
        detail = "unlimited" if remaining is None else f"{remaining:g} remaining"
        super().__init__(f"Task budget exhausted for {resource}: requested {requested:g}; {detail}")


@dataclass(frozen=True)
class BudgetSnapshot:
    task_id: str
    limits: Dict[str, float]
    consumed: Dict[str, float]
    reserved: Dict[str, float]
    remaining: Dict[str, float]
    pending: Dict[str, Dict[str, Any]]
    adjusted: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def parse_deadline(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("deadline_utc must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"deadline_utc is not ISO 8601: {value}") from None
    if parsed.tzinfo is None:
        raise ValueError("deadline_utc must include a UTC offset")
    return parsed.astimezone(timezone.utc)


class TaskBudgetLedger:
    """Use journal events as the authority; unknown outcomes retain their reservation."""

    CONFIG_KIND = "task_budget_configured"
    RESERVE_KIND = "task_resource_reserved"
    RECONCILE_KIND = "task_resource_reconciled"
    ADJUST_KIND = "task_resource_adjusted"

    def __init__(self, runtime: LocalRuntime, task_id: str, limits: Dict[str, Any]):
        self.runtime = runtime
        self.task_id = task_id
        self.limits = self._normalize_limits(limits)
        self.deadline = parse_deadline(limits.get("deadline_utc"))
        self._ensure_configuration()

    def deadline_passed(self, now: Optional[datetime] = None) -> bool:
        if self.deadline is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.deadline

    @staticmethod
    def _normalize_limits(limits: Dict[str, Any]) -> Dict[str, float]:
        normalized: Dict[str, float] = {}
        aliases = {"model_calls": "model_attempts", "tool_calls": "tool_actions"}
        for raw_name, raw_value in limits.items():
            name = aliases.get(raw_name, raw_name)
            if name not in {"model_attempts", "model_responses", "tool_actions", "active_seconds", "cost_usd"}:
                continue
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"Task budget {raw_name} must be numeric")
            value = float(raw_value)
            if value < 0:
                raise ValueError(f"Task budget {raw_name} cannot be negative")
            if name in normalized and normalized[name] != value:
                raise ValueError(f"Conflicting task budget values for {name}")
            normalized[name] = value
        return normalized

    def _events(self):
        return [
            event for event in self.runtime.journal.read_all()
            if event.payload.get("task_id") == self.task_id
        ]

    def _ensure_configuration(self) -> None:
        configured = [event for event in self._events() if event.kind == self.CONFIG_KIND]
        if configured:
            original = {key: float(value) for key, value in configured[0].payload.get("limits", {}).items()}
            if original != self.limits:
                raise ValueError(
                    f"Task {self.task_id} budget contract changed: {original} != {self.limits}"
                )
            return
        self.runtime.journal.append(self.CONFIG_KIND, {"task_id": self.task_id, "limits": self.limits})

    def _charges(self):
        reservations: Dict[str, Dict[str, Any]] = {}
        charges: Dict[str, tuple[str, float]] = {}
        adjusted: Dict[str, Dict[str, Any]] = {}
        for event in self._events():
            operation_id = event.payload.get("resource_operation_id")
            if event.kind == self.RESERVE_KIND:
                reservations[str(operation_id)] = dict(event.payload)
            elif event.kind == self.RECONCILE_KIND:
                if str(operation_id) in charges:
                    continue
                actual = event.payload.get("actual")
                # An ambiguous outcome is conservatively charged at its reservation until a
                # supervisor adjustment records the provider's actual bill.
                charged = event.payload.get("reserved", 0.0) if actual is None else actual
                charges[str(operation_id)] = (str(event.payload["resource"]), float(charged))
            elif event.kind == self.ADJUST_KIND and str(operation_id) in charges:
                resource = charges[str(operation_id)][0]
                charges[str(operation_id)] = (resource, float(event.payload["actual"]))
                adjusted[str(operation_id)] = dict(event.payload)
        return reservations, charges, adjusted

    def snapshot(self) -> BudgetSnapshot:
        reservations, charges, adjusted = self._charges()
        consumed: Dict[str, float] = {}
        for resource, charged in charges.values():
            consumed[resource] = consumed.get(resource, 0.0) + charged
        pending = {
            operation_id: reservation
            for operation_id, reservation in reservations.items()
            if operation_id not in charges
        }
        reserved: Dict[str, float] = {}
        for reservation in pending.values():
            resource = str(reservation["resource"])
            reserved[resource] = reserved.get(resource, 0.0) + float(reservation["amount"])
        remaining = {
            resource: limit - consumed.get(resource, 0.0) - reserved.get(resource, 0.0)
            for resource, limit in self.limits.items()
        }
        return BudgetSnapshot(
            self.task_id, dict(self.limits), consumed, reserved, remaining, pending, adjusted
        )

    def require_available(self, resource: str, amount: float) -> None:
        remaining = self.snapshot().remaining.get(resource)
        if remaining is not None and amount > remaining:
            raise TaskBudgetExhausted(resource, amount, remaining)

    def unknown_billing_count(self, resource: str = "cost_usd") -> int:
        """Reconciled reservations with no reported amount and no later supervisor adjustment."""
        _, _, adjusted = self._charges()
        return sum(
            1 for event in self._events()
            if event.kind == self.RECONCILE_KIND and event.payload.get("resource") == resource
            and event.payload.get("actual") is None and float(event.payload.get("reserved") or 0) > 0
            and str(event.payload.get("resource_operation_id")) not in adjusted
        )

    def next_operation_id(self, resource: str) -> str:
        prefix = f"resource:{self.task_id}:{resource}:"
        used = {
            str(event.payload.get("resource_operation_id"))
            for event in self._events() if event.kind == self.RESERVE_KIND
        }
        ordinal = 1
        while f"{prefix}{ordinal}" in used:
            ordinal += 1
        return f"{prefix}{ordinal}"

    def reserve(self, resource: str, amount: float, operation_id: Optional[str] = None) -> str:
        if amount <= 0:
            raise ValueError("Reservation amount must be positive")
        operation_id = operation_id or self.next_operation_id(resource)
        snapshot = self.snapshot()
        if operation_id in snapshot.pending or any(
            event.payload.get("resource_operation_id") == operation_id for event in self._events()
        ):
            raise ValueError(f"Resource operation ID was already used: {operation_id}")
        remaining = snapshot.remaining.get(resource)
        if remaining is not None and amount > remaining:
            raise TaskBudgetExhausted(resource, amount, remaining)
        self.runtime.journal.append(self.RESERVE_KIND, {
            "task_id": self.task_id,
            "resource_operation_id": operation_id,
            "resource": resource,
            "amount": float(amount),
        })
        return operation_id

    def reconcile(
        self,
        operation_id: str,
        actual: Optional[float],
        *,
        outcome: str,
    ) -> None:
        snapshot = self.snapshot()
        reservation = snapshot.pending.get(operation_id)
        if reservation is None:
            raise ValueError(f"No pending resource reservation: {operation_id}")
        if actual is not None and actual < 0:
            raise ValueError("Actual resource use cannot be negative")
        self.runtime.journal.append(self.RECONCILE_KIND, {
            "task_id": self.task_id,
            "resource_operation_id": operation_id,
            "resource": reservation["resource"],
            "reserved": reservation["amount"],
            "actual": actual,
            "outcome": outcome,
        })

    def charge(self, resource: str, actual: float, *, outcome: str) -> str:
        """Record measured use after completion, including an unavoidable overrun."""
        if actual < 0:
            raise ValueError("Actual resource use cannot be negative")
        operation_id = self.next_operation_id(resource)
        self.runtime.journal.append(self.RESERVE_KIND, {
            "task_id": self.task_id,
            "resource_operation_id": operation_id,
            "resource": resource,
            "amount": 0.0,
            "posthoc": True,
        })
        self.reconcile(operation_id, actual, outcome=outcome)
        return operation_id

    def adjust(self, operation_id: str, actual: float, *, source: str, reason: str) -> None:
        """Supervisor-only: replace a reconciled charge once the actual use is established.

        The controller never calls this and it is not exposed to model tools. Every adjustment
        is journaled with the charge it replaces; the latest adjustment wins.
        """
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or actual < 0:
            raise ValueError("Adjusted resource use must be a non-negative number")
        if not source or not reason:
            raise ValueError("An adjustment requires a source and a reason")
        reservations, charges, _ = self._charges()
        if operation_id not in charges:
            state = "pending" if operation_id in reservations else "unknown"
            raise ValueError(f"Only reconciled operations can be adjusted; {operation_id} is {state}")
        resource, previous = charges[operation_id]
        self.runtime.journal.append(self.ADJUST_KIND, {
            "task_id": self.task_id,
            "resource_operation_id": operation_id,
            "resource": resource,
            "previous_charge": previous,
            "actual": float(actual),
            "source": source,
            "reason": reason,
        })


class ProviderAttemptRecorder:
    """Journals each underlying provider attempt of one model request.

    A client that sets ``reports_provider_attempts = True`` receives this recorder and must
    call ``begin`` before every network attempt (including retries) and must stop retrying
    when it raises ``TaskBudgetExhausted``. It should call ``finish`` for failed attempts; the
    controller finishes the successful attempt with the response's reported cost and charges
    any other unfinished attempt conservatively.
    """

    STARTED_KIND = "provider_attempt_started"
    FINISHED_KIND = "provider_attempt_finished"

    def __init__(self, ledger: TaskBudgetLedger, request_id: str, cost_reservation: Optional[float] = None):
        self.ledger = ledger
        self.request_id = request_id
        self.cost_reservation = cost_reservation
        self.attempt_ids: List[str] = []
        self._open: Dict[str, Dict[str, Optional[str]]] = {}

    @property
    def count(self) -> int:
        return len(self.attempt_ids)

    def begin(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        attempt_operation = self.ledger.reserve("model_attempts", 1)
        cost_operation: Optional[str] = None
        if self.cost_reservation is not None:
            try:
                cost_operation = self.ledger.reserve("cost_usd", self.cost_reservation)
            except TaskBudgetExhausted:
                self.ledger.reconcile(attempt_operation, 0, outcome="not_dispatched_cost_exhausted")
                raise
        attempt_id = f"{self.request_id}:attempt:{self.count + 1}"
        self.ledger.runtime.journal.append(self.STARTED_KIND, {
            "task_id": self.ledger.task_id,
            "request_id": self.request_id,
            "provider_attempt_id": attempt_id,
            "attempt_operation_id": attempt_operation,
            "cost_operation_id": cost_operation,
            "metadata": metadata or {},
        })
        self.attempt_ids.append(attempt_id)
        self._open[attempt_id] = {"attempt": attempt_operation, "cost": cost_operation}
        return attempt_id

    def finish(
        self,
        attempt_id: str,
        *,
        outcome: str,
        cost: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        operations = self._open.pop(attempt_id, None)
        if operations is None:
            raise ValueError(f"Provider attempt is not open: {attempt_id}")
        if isinstance(cost, bool) or (cost is not None and not isinstance(cost, (int, float))):
            cost = None
        self.ledger.reconcile(str(operations["attempt"]), 1, outcome=outcome)
        if operations["cost"] is not None:
            self.ledger.reconcile(operations["cost"], cost, outcome=(
                "reported" if cost is not None else "unknown_billing"
            ))
        self.ledger.runtime.journal.append(self.FINISHED_KIND, {
            "task_id": self.ledger.task_id,
            "request_id": self.request_id,
            "provider_attempt_id": attempt_id,
            "outcome": outcome,
            "cost": cost,
            "metadata": metadata or {},
        })

    def close_unfinished(self, *, succeeded: bool, final_cost: Optional[float] = None) -> None:
        latest = self.attempt_ids[-1] if self.attempt_ids else None
        for attempt_id in list(self._open):
            if succeeded and attempt_id == latest:
                self.finish(attempt_id, outcome="response", cost=final_cost)
            else:
                self.finish(attempt_id, outcome="unknown_not_finished_by_client")
