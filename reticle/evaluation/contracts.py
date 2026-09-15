"""Typed evidence and acceptance contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from reticle._schema import SCHEMA_VERSION


MEASUREMENT_OUTCOMES = {"pass", "fail", "unknown", "not_run"}
CRITERION_KINDS = {"executable", "graded", "human", "unmeasurable"}
FINAL_STATUSES = {
    "accepted", "rejected", "needs_review", "budget_exhausted",
    "cancelled", "runtime_error",
}


@dataclass(frozen=True)
class ScoreScale:
    name: str
    minimum: float
    maximum: float
    higher_is_better: bool
    unit: Optional[str] = None

    def __post_init__(self) -> None:
        if self.maximum <= self.minimum:
            raise ValueError("score scale maximum must be greater than minimum")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    source: str
    source_version: str
    workspace_revision: str
    artifact_id: str
    event_id: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeasurementRecord:
    measurement_id: str
    procedure: str
    procedure_version: str
    scope: str
    workspace_revision: str
    outcome: str
    observation_ids: List[str] = field(default_factory=list)
    value: Optional[float] = None
    scale: Optional[ScoreScale] = None
    coverage_id: Optional[str] = None
    coverage_ids: List[str] = field(default_factory=list)
    infrastructure_error: Optional[str] = None
    event_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.outcome not in MEASUREMENT_OUTCOMES:
            raise ValueError(f"Unsupported measurement outcome: {self.outcome}")
        if (self.value is None) != (self.scale is None):
            raise ValueError("numeric measurements require both value and explicit scale")
        if self.value is not None and not self.scale.minimum <= self.value <= self.scale.maximum:
            raise ValueError("measurement value is outside its declared scale")
        if self.infrastructure_error and self.outcome not in {"unknown", "not_run"}:
            raise ValueError("infrastructure errors require an unknown or not_run outcome")

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        return value


@dataclass(frozen=True)
class InterpretationRecord:
    interpretation_id: str
    claim: str
    author: str
    evidence_ids: List[str]
    event_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ValueError("interpretations must cite at least one evidence record")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CriterionContract:
    criterion_id: str
    wording: str
    kind: str
    evaluator_version: str
    required: bool = True
    minimum_score: Optional[float] = None
    expected_coverage_ids: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in CRITERION_KINDS:
            raise ValueError(f"Unsupported criterion kind: {self.kind}")
        if self.kind != "graded" and self.minimum_score is not None:
            raise ValueError("minimum_score is only valid for graded criteria")
        if self.kind == "graded" and self.minimum_score is None:
            raise ValueError("graded criteria require minimum_score")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptancePlan:
    task_id: str
    criteria: List[CriterionContract]
    evaluator_command: List[str] = field(default_factory=list)
    evaluation_cost: int = 1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        identifiers = [criterion.criterion_id for criterion in self.criteria]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("criterion IDs must be unique")
        if self.evaluation_cost < 0:
            raise ValueError("evaluation_cost cannot be negative")
        needs_command = any(c.kind in {"executable", "graded"} for c in self.criteria)
        if needs_command and not self.evaluator_command:
            raise ValueError("executable or graded criteria require an evaluator command")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceDecision:
    task_id: str
    status: str
    final_workspace_revision: str
    criterion_outcomes: Dict[str, str]
    measurement_ids: List[str] = field(default_factory=list)
    report_artifact_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in FINAL_STATUSES:
            raise ValueError(f"Unsupported final status: {self.status}")
        invalid = set(self.criterion_outcomes.values()) - MEASUREMENT_OUTCOMES
        if invalid:
            raise ValueError(f"Unsupported criterion outcomes: {sorted(invalid)}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
