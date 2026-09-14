"""Small, evidence-backed ledger for discovered controllable outcomes.

The ledger deliberately records observations rather than intentions.  A trial
with an unknown pre/post measurement is retained as ``unknown`` evidence, but
never changes success or failure rates.  The first observed change discovers a
capability; only later trials are used to estimate repeatability.
"""

from __future__ import annotations

import json
import os
import tempfile
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, Mapping, Optional, Union


DEFAULT_MIN_TRIALS = 3
DEFAULT_RELIABILITY = 2 / 3


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_outcome(delta: Mapping[str, Any]) -> Optional[str]:
    """Return a stable meaningful outcome identity for an observed delta.

    Inventory changes are grouped by item and direction, so collecting ten
    logs does not create ten capabilities.  Position/yaw changes are omitted
    by default because ordinary movement and looking are not useful coverage.
    """
    if not isinstance(delta, Mapping):
        return None
    inventory = delta.get("inventory") if isinstance(delta.get("inventory"), Mapping) else delta
    meaningful = []
    for item, amount in inventory.items():
        if item in {"position", "yaw", "pitch", "health", "food"}:
            continue
        if isinstance(amount, bool):
            continue
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if math.isfinite(amount) and amount:
            direction = "positive" if amount > 0 else "negative"
            if direction == "positive":
                meaningful.append(f"inventory:{item}:{direction}")
    if not meaningful:
        return None
    return "|".join(sorted(set(meaningful)))


def _outcomes(delta: Mapping[str, Any], expected: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Individual positive item outcomes, optionally restricted by prediction."""
    source = delta.get("inventory") if isinstance(delta.get("inventory"), Mapping) else delta
    expected_source = expected.get("inventory") if isinstance(expected, Mapping) and isinstance(expected.get("inventory"), Mapping) else expected
    if expected_source:
        source = {k: v for k, v in source.items() if k in expected_source}
    return [f"inventory:{k}:positive" for k, v in source.items()
            if k not in {"position", "yaw", "pitch", "health", "food"}
            and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and v > 0]


def compact_conditions(pre_state: Optional[Mapping[str, Any]], explicit: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Keep observed, compact context; fields are descriptors, not guarantees."""
    result: Dict[str, Any] = {}
    if isinstance(pre_state, Mapping):
        for key in ("source", "connected", "health", "food", "yaw", "sheltered"):
            if key in pre_state and pre_state[key] is not None:
                result[key] = _jsonable(pre_state[key])
        inv = pre_state.get("inventory")
        if isinstance(inv, Mapping):
            result["inventory_items"] = sorted(str(k) for k, v in inv.items() if v)
            result["inventory_counts"] = dict(inv)
    if explicit:
        result["supplied_descriptors"] = _jsonable(explicit)
    return result


@dataclass
class CapabilityRecord:
    capability_id: str
    routine: str
    outcome: str
    conditions: Dict[str, Any] = field(default_factory=dict)
    condition_variants: list[Dict[str, Any]] = field(default_factory=list)
    condition_stats: Dict[str, Any] = field(default_factory=dict)
    discovery_count: int = 0
    successes: int = 0
    failures: int = 0
    unknown: int = 0
    durations_s: list[float] = field(default_factory=list)
    trials: int = 0

    @property
    def known_trials(self) -> int:
        return self.successes + self.failures

    @property
    def reliability(self) -> Optional[float]:
        return self.successes / self.known_trials if self.known_trials else None

    @property
    def median_cost_s(self) -> Optional[float]:
        return float(median(self.durations_s)) if self.durations_s else None

    def is_reliable(self, min_trials: int = DEFAULT_MIN_TRIALS, threshold: float = DEFAULT_RELIABILITY) -> bool:
        return self.known_trials >= min_trials and (self.reliability or 0) >= threshold

    def summary(self, min_trials: int = DEFAULT_MIN_TRIALS, threshold: float = DEFAULT_RELIABILITY) -> Dict[str, Any]:
        return {"routine": self.routine, "outcome": self.outcome, "conditions": self.conditions,
                "condition_variants": self.condition_variants[-3:],
                "condition_count": len(self.condition_stats),
                "scope": "pooled observed conditions; generalization untested",
                "successes": self.successes, "failures": self.failures, "unknown": self.unknown,
                "discovery_count": self.discovery_count, "known_trials": self.known_trials,
                "reliability": self.reliability, "median_cost_s": self.median_cost_s,
                "cost_scope": "known repeat trials including failures",
                "reliable": self.is_reliable(min_trials, threshold)}

    def record_outcome(self, status: str, cond: Dict[str, Any], duration_s: Optional[float]) -> Dict[str, Any]:
        """Update counts, condition variants, and duration metrics for this trial outcome."""
        self.trials += 1
        attr = {"discovery": "discovery_count", "success": "successes",
                "failure": "failures", "unknown": "unknown"}[status]
        setattr(self, attr, getattr(self, attr) + 1)
        if cond != self.conditions and cond not in self.condition_variants:
            self.condition_variants.append(cond)
        context_key = json.dumps(cond, sort_keys=True, allow_nan=False)
        stats = self.condition_stats.setdefault(context_key, {
            "conditions": cond, "discovery": 0, "success": 0,
            "failure": 0, "unknown": 0, "durations_s": []})
        stats[status] += 1
        if status in ("success", "failure") and duration_s is not None:
            self.durations_s.append(duration_s)
            stats["durations_s"].append(duration_s)
        return {"capability_id": self.capability_id, "outcome": self.outcome, "status": status}


class CapabilityLedger:
    def __init__(self, path: Optional[Union[str, Path]] = None, min_trials: int = DEFAULT_MIN_TRIALS,
                 reliability_threshold: float = DEFAULT_RELIABILITY):
        self.path = Path(path) if path else None
        self.min_trials = max(1, int(min_trials))
        self.reliability_threshold = float(reliability_threshold)
        if not 0 < self.reliability_threshold <= 1:
            raise ValueError("reliability_threshold must be in (0, 1]")
        self.records: Dict[str, CapabilityRecord] = {}
        self.unknown_trials = 0
        self.trial_log = []
        if self.path and self.path.exists():
            self._load()

    @staticmethod
    def routine_name(action: Any) -> str:
        if isinstance(action, str):
            return action
        if not isinstance(action, Mapping):
            return "unknown"
        typ = str(action.get("type", "unknown"))
        params = action.get("params") if isinstance(action.get("params"), Mapping) else {}
        identity = params.get("skill_id") or params.get("skill")
        version = params.get("skill_version") or params.get("version")
        suffix = f":{identity}" if identity else ""
        suffix += f"@{version}" if version else ""
        if typ == "craft":
            return f"craft:{params.get('recipe', 'unknown')}{suffix}"
        return typ + suffix

    def record_trial(self, routine: Any, outcome_delta: Optional[Mapping[str, Any]], *,
                     duration_s: Optional[float] = None, conditions: Optional[Mapping[str, Any]] = None,
                     pre_state: Optional[Mapping[str, Any]] = None,
                     post_state_known: Optional[bool] = None,
                     expected_delta: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Record one observed trial and return its classification.

        ``outcome_delta=None`` is unknown.  An observed delta discovers a new
        outcome and is excluded from repeatability denominators.  Once known,
        a later empty delta is a failure for that routine/outcome.
        """
        if duration_s is not None:
            if isinstance(duration_s, bool):
                raise ValueError("duration_s must be finite and nonnegative")
            duration_s = float(duration_s)
            if not math.isfinite(duration_s) or duration_s < 0:
                raise ValueError("duration_s must be finite and nonnegative")
        routine_key = self.routine_name(routine)
        cond = compact_conditions(pre_state, conditions)
        source = outcome_delta
        if isinstance(source, Mapping) and "inventory" in source:
            source = source["inventory"]
        known = isinstance(source, Mapping) and post_state_known is not False
        if isinstance(pre_state, Mapping) and pre_state.get("connected") is False:
            known = False
        if known:
            source = {k: v for k, v in source.items()
                      if k not in {"position", "yaw", "pitch", "health", "food"}}
            known = all(isinstance(k, str) and bool(k) and isinstance(v, (int, float))
                        and not isinstance(v, bool) and math.isfinite(v) and int(v) == v
                        for k, v in source.items())
        # Expected deltas are evidence, never a filter that hides incidental changes.
        outcomes = set(_outcomes(source)) if known else set()
        existing = [r for r in self.records.values() if r.routine == routine_key]
        updates = []
        event = {"trial_id": len(self.trial_log) + 1, "routine": routine_key,
                 "action": _jsonable(routine), "conditions": cond,
                 "observed_inventory_delta": dict(source) if known else None,
                 "expected_delta": _jsonable(expected_delta), "duration_s": duration_s,
                 "observations_known": known}
        # Validate persistability before changing any counters.
        json.dumps(event, allow_nan=False)
        if not known:
            self.unknown_trials += 1

        for rec in existing:
            status_val = "unknown" if not known else "success" if rec.outcome in outcomes else "failure"
            updates.append(rec.record_outcome(status_val, cond, duration_s))

        for outcome in sorted(outcomes - {r.outcome for r in existing}):
            key = json.dumps([routine_key, outcome], separators=(",", ":"))
            rec = CapabilityRecord(key, routine_key, outcome, cond)
            self.records[key] = rec
            updates.append(rec.record_outcome("discovery", cond, duration_s))
        statuses = {u["status"] for u in updates}
        status = ("unknown" if not known else "discovery" if "discovery" in statuses
                  else "success" if "success" in statuses else "failure" if updates else "unattributed")
        event.update(status=status, updates=updates)
        self.trial_log.append(event)
        self._save()
        result = {"status": status, "routine": routine_key, "trial_id": event["trial_id"],
                  "outcome": next(iter(outcomes)) if len(outcomes) == 1 else None,
                  "updates": updates}
        if len(updates) == 1:
            result["record"] = self.records[updates[0]["capability_id"]].summary(self.min_trials, self.reliability_threshold)
        return result

    def coverage(self) -> int:
        return len({r.outcome for r in self.records.values()
                     if r.is_reliable(self.min_trials, self.reliability_threshold)})

    def summaries(self) -> list[Dict[str, Any]]:
        return [r.summary(self.min_trials, self.reliability_threshold) for r in self.records.values()]

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("records"), list):
                raise ValueError("unsupported ledger schema")
            self.unknown_trials = int(payload.get("unknown_trials", 0))
            self.trial_log = payload.get("trial_log", [])
            for raw in payload.get("records", []):
                rec = CapabilityRecord(**raw)
                self.records[rec.capability_id] = rec
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid capability ledger: {self.path}") from exc

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "unknown_trials": self.unknown_trials,
                   "trial_log": self.trial_log,
                   "records": [asdict(r) for r in self.records.values()]}
        fd, name = tempfile.mkstemp(prefix=self.path.name, dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, allow_nan=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
