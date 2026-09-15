"""Durable recording for observations, measurements, and interpretations."""

from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

from reticle.evaluation.contracts import (
    InterpretationRecord,
    MeasurementRecord,
    ObservationRecord,
    ScoreScale,
)
from reticle.runtime import LocalRuntime


class EvaluationEvidence:
    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime

    def observe(
        self,
        content: bytes,
        *,
        source: str,
        source_version: str,
        media_type: str = "application/octet-stream",
    ) -> ObservationRecord:
        event_id = self.runtime.journal.new_event_id()
        artifact = self.runtime.artifacts.put(
            content,
            media_type,
            event_id,
            labels=["evaluation-observation", source, source_version],
        )
        record = ObservationRecord(
            observation_id=f"obs_{uuid4().hex}",
            source=source,
            source_version=source_version,
            workspace_revision=self.runtime.workspace.revision(),
            artifact_id=artifact.artifact_id,
            event_id=event_id,
        )
        self.runtime.journal.append("evaluation_observation", record.to_dict(), event_id=event_id)
        return record

    def measure(
        self,
        *,
        procedure: str,
        procedure_version: str,
        scope: str,
        outcome: str,
        observation_ids: Optional[List[str]] = None,
        value: Optional[float] = None,
        scale: Optional[ScoreScale] = None,
        coverage_id: Optional[str] = None,
        coverage_ids: Optional[List[str]] = None,
        infrastructure_error: Optional[str] = None,
        workspace_revision: Optional[str] = None,
    ) -> MeasurementRecord:
        event_id = self.runtime.journal.new_event_id()
        record = MeasurementRecord(
            measurement_id=f"measure_{uuid4().hex}",
            procedure=procedure,
            procedure_version=procedure_version,
            scope=scope,
            workspace_revision=workspace_revision or self.runtime.workspace.revision(),
            outcome=outcome,
            observation_ids=list(observation_ids or []),
            value=value,
            scale=scale,
            coverage_id=coverage_id,
            coverage_ids=list(coverage_ids or []),
            infrastructure_error=infrastructure_error,
            event_id=event_id,
        )
        self.runtime.journal.append("evaluation_measurement", record.to_dict(), event_id=event_id)
        return record

    def interpret(self, *, claim: str, author: str, evidence_ids: List[str]) -> InterpretationRecord:
        event_id = self.runtime.journal.new_event_id()
        record = InterpretationRecord(
            interpretation_id=f"interpret_{uuid4().hex}",
            claim=claim,
            author=author,
            evidence_ids=list(evidence_ids),
            event_id=event_id,
        )
        self.runtime.journal.append("evaluation_interpretation", record.to_dict(), event_id=event_id)
        return record
