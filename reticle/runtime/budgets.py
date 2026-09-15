"""Journal-derived cumulative task resource reservations and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

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


class TaskBudgetLedger:
    """Use journal events as the authority; unknown outcomes retain their reservation."""

    CONFIG_KIND = "task_budget_configured"
    RESERVE_KIND = "task_resource_reserved"
    RECONCILE_KIND = "task_resource_reconciled"

    def __init__(self, runtime: LocalRuntime, task_id: str, limits: Dict[str, Any]):
        self.runtime = runtime
        self.task_id = task_id
        self.limits = self._normalize_limits(limits)
        self._ensure_configuration()

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

    def snapshot(self) -> BudgetSnapshot:
        consumed: Dict[str, float] = {}
        reservations: Dict[str, Dict[str, Any]] = {}
        reconciled: set[str] = set()
        for event in self._events():
            if event.kind == self.RESERVE_KIND:
                operation_id = str(event.payload["resource_operation_id"])
                reservations[operation_id] = dict(event.payload)
            elif event.kind == self.RECONCILE_KIND:
                operation_id = str(event.payload["resource_operation_id"])
                if operation_id in reconciled:
                    continue
                reconciled.add(operation_id)
                actual = event.payload.get("actual")
                resource = str(event.payload["resource"])
                # An ambiguous outcome is conservatively charged at its reservation until
                # a future adjustment mechanism can establish the provider's actual bill.
                charged = event.payload.get("reserved", 0.0) if actual is None else actual
                consumed[resource] = consumed.get(resource, 0.0) + float(charged)
        pending = {
            operation_id: reservation
            for operation_id, reservation in reservations.items()
            if operation_id not in reconciled
        }
        reserved: Dict[str, float] = {}
        for reservation in pending.values():
            resource = str(reservation["resource"])
            reserved[resource] = reserved.get(resource, 0.0) + float(reservation["amount"])
        remaining = {
            resource: limit - consumed.get(resource, 0.0) - reserved.get(resource, 0.0)
            for resource, limit in self.limits.items()
        }
        return BudgetSnapshot(self.task_id, dict(self.limits), consumed, reserved, remaining, pending)

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
