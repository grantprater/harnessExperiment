"""Versioned boundary contracts for the Reticle runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from reticle._schema import SCHEMA_VERSION


TOOL_STATUSES = {"success", "error", "timeout", "cancelled", "rejected"}
FINAL_STATUSES = {
    "accepted",
    "rejected",
    "needs_review",
    "budget_exhausted",
    "cancelled",
    "runtime_error",
}
CRITERION_OUTCOMES = {"pass", "fail", "unknown", "not_run"}


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    description: str
    criteria: List[Dict[str, Any]] = field(default_factory=list)
    authority: Dict[str, Any] = field(default_factory=dict)
    budgets: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResultEnvelope:
    call_id: str
    status: str
    workspace_revision_before: str
    workspace_revision_after: str
    exit_code: Optional[int] = None
    stdout_ref: Optional[str] = None
    stderr_ref: Optional[str] = None
    output_refs: List[str] = field(default_factory=list)
    preview: str = ""
    preview_truncated: bool = False
    duration_ms: int = 0
    usage: Dict[str, Any] = field(default_factory=dict)
    error_kind: Optional[str] = None
    retry_hint: Optional[str] = None
    external_effect_status: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in TOOL_STATUSES:
            raise ValueError(f"Unsupported tool status: {self.status}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalResultEnvelope:
    task_id: str
    status: str
    workspace_revision: str
    artifact_id: Optional[str] = None
    criterion_outcomes: Dict[str, str] = field(default_factory=dict)
    evidence_event_ids: List[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in FINAL_STATUSES:
            raise ValueError(f"Unsupported final status: {self.status}")
        invalid = set(self.criterion_outcomes.values()) - CRITERION_OUTCOMES
        if invalid:
            raise ValueError(f"Unsupported criterion outcomes: {sorted(invalid)}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
