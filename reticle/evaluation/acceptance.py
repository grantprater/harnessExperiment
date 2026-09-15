"""Independent evaluation of an immutable candidate snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional

from reticle.evaluation.contracts import (
    AcceptanceDecision,
    AcceptancePlan,
    CriterionContract,
    MeasurementRecord,
    ScoreScale,
)
from reticle.evaluation.evidence import EvaluationEvidence
from reticle.execution import ExecutionController, ExecutionRequest, TrustedLocalBackend
from reticle.runtime import LocalRuntime


@dataclass
class EvaluationBudget:
    total_units: int
    reserved_final_units: int
    consumed_units: int = 0

    def __post_init__(self) -> None:
        if min(self.total_units, self.reserved_final_units, self.consumed_units) < 0:
            raise ValueError("budget values cannot be negative")
        if self.reserved_final_units > self.total_units:
            raise ValueError("final reserve cannot exceed total budget")
        if self.consumed_units > self.total_units:
            raise ValueError("consumed budget cannot exceed total budget")

    @property
    def remaining_units(self) -> int:
        return self.total_units - self.consumed_units

    def consume_work(self, units: int) -> bool:
        if units < 0:
            raise ValueError("units cannot be negative")
        if self.remaining_units - units < self.reserved_final_units:
            return False
        self.consumed_units += units
        return True

    def consume_final(self, units: int) -> bool:
        if units < 0:
            raise ValueError("units cannot be negative")
        if units > self.remaining_units:
            return False
        self.consumed_units += units
        self.reserved_final_units = max(0, self.reserved_final_units - units)
        return True


class AcceptanceRunner:
    """Run a fixed evaluator outside candidate authority against a snapshot."""

    def __init__(self, runtime: LocalRuntime, backend=None):
        self.runtime = runtime
        self.backend = backend or TrustedLocalBackend()
        self.evidence = EvaluationEvidence(runtime)

    def evaluate(
        self,
        plan: AcceptancePlan,
        *,
        evaluator_root: Optional[str | Path] = None,
        budget: Optional[EvaluationBudget] = None,
        timeout_seconds: float = 60,
    ) -> AcceptanceDecision:
        final_revision = self.runtime.workspace.revision()
        automated = [c for c in plan.criteria if c.kind in {"executable", "graded"}]
        if not automated:
            outcomes = {
                c.criterion_id: "not_run" if c.kind == "human" else "unknown"
                for c in plan.criteria
            }
            measurements = [
                self.evidence.measure(
                    procedure=c.kind,
                    procedure_version=c.evaluator_version,
                    scope=c.wording,
                    outcome=outcomes[c.criterion_id],
                    workspace_revision=final_revision,
                )
                for c in plan.criteria
            ]
            return self._record_decision(plan, "needs_review", final_revision, outcomes, measurements)

        if evaluator_root is None:
            raise ValueError("evaluator_root is required for automated criteria")
        evaluator_root = Path(evaluator_root).resolve()
        if not evaluator_root.is_dir():
            raise ValueError(f"Evaluator root is not a directory: {evaluator_root}")
        try:
            evaluator_root.relative_to(self.runtime.workspace.root)
        except ValueError:
            pass
        else:
            raise ValueError("fixed evaluator inputs must be outside the candidate workspace")

        if budget is not None and not budget.consume_final(plan.evaluation_cost):
            outcomes = {c.criterion_id: "not_run" for c in plan.criteria}
            measurements = [
                self.evidence.measure(
                    procedure="reserved-final-evaluation",
                    procedure_version=c.evaluator_version,
                    scope=c.wording,
                    outcome="not_run",
                    infrastructure_error="insufficient reserved final-evaluation budget",
                    workspace_revision=final_revision,
                )
                for c in plan.criteria
            ]
            return self._record_decision(
                plan, "budget_exhausted", final_revision, outcomes, measurements
            )

        with tempfile.TemporaryDirectory(prefix="acceptance-", dir=self.runtime.session_dir) as name:
            evaluation_root = Path(name)
            bundle = evaluation_root / "evaluator"
            candidate = evaluation_root / "candidate"
            shutil.copytree(evaluator_root, bundle)
            self._copy_candidate(candidate)
            command = self._render_command(plan.evaluator_command, evaluation_root)
            record = ExecutionController(self.runtime, self.backend).execute(
                ExecutionRequest(
                    command=command,
                    working_directory=evaluation_root,
                    timeout_seconds=timeout_seconds,
                    output_limit_bytes=1_000_000,
                    mutates_workspace=False,
                )
            )
            measurements, outcomes, infrastructure_failure = self._measure_results(
                plan, final_revision, record.execution.status, record.execution.stdout,
                record.execution.stderr, record.execution.error_kind,
            )

        if self.runtime.workspace.revision() != final_revision:
            outcomes = {criterion.criterion_id: "unknown" for criterion in plan.criteria}
            measurements = [
                self.evidence.measure(
                    procedure="final-revision-check",
                    procedure_version=criterion.evaluator_version,
                    scope=criterion.wording,
                    outcome="unknown",
                    infrastructure_error="candidate workspace changed during final evaluation",
                    workspace_revision=final_revision,
                )
                for criterion in plan.criteria
            ]
            return self._record_decision(
                plan, "runtime_error", final_revision, outcomes, measurements,
                tool_output_artifact_id=record.tool_result.stdout_ref,
            )

        if infrastructure_failure:
            status = "runtime_error"
        elif any(
            outcomes[c.criterion_id] == "fail" for c in plan.criteria if c.required
        ):
            status = "rejected"
        elif any(
            outcomes[c.criterion_id] in {"unknown", "not_run"}
            for c in plan.criteria if c.required
        ):
            status = "needs_review"
        else:
            status = "accepted"
        return self._record_decision(
            plan, status, final_revision, outcomes, measurements,
            tool_output_artifact_id=record.tool_result.stdout_ref,
        )

    def _copy_candidate(self, destination: Path) -> None:
        destination.mkdir()
        for source in sorted(self.runtime.workspace.root.rglob("*")):
            if self.runtime.workspace._is_excluded(source):
                continue
            relative = source.relative_to(self.runtime.workspace.root)
            target = destination / relative
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    def _render_command(self, command: List[str], evaluation_root: Path) -> List[str]:
        isolated = bool(getattr(self.backend, "host_isolation", False))
        if isolated:
            values = {
                "{python}": "python",
                "{root}": "/workspace",
                "{bundle}": "/workspace/evaluator",
                "{candidate}": "/workspace/candidate",
            }
        else:
            values = {
                "{python}": sys.executable,
                "{root}": str(evaluation_root),
                "{bundle}": str(evaluation_root / "evaluator"),
                "{candidate}": str(evaluation_root / "candidate"),
            }
        rendered = []
        for part in command:
            for placeholder, value in values.items():
                part = part.replace(placeholder, value)
            rendered.append(part)
        return rendered

    def _measure_results(
        self,
        plan: AcceptancePlan,
        workspace_revision: str,
        execution_status: str,
        stdout: bytes,
        stderr: bytes,
        error_kind: Optional[str],
    ) -> tuple[List[MeasurementRecord], Dict[str, str], bool]:
        infrastructure_error = None
        report: Dict[str, Any] = {}
        if execution_status != "success":
            detail = stderr.decode("utf-8", errors="replace")[-500:].strip()
            infrastructure_error = f"evaluator {execution_status} ({error_kind or 'unknown'}): {detail}"
        else:
            try:
                report = json.loads(stdout.decode("utf-8"))
                if not isinstance(report.get("criteria"), dict):
                    raise ValueError("report must contain a criteria object")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                infrastructure_error = f"invalid evaluator report: {exc}"

        outcomes: Dict[str, str] = {}
        measurements: List[MeasurementRecord] = []
        for criterion in plan.criteria:
            if criterion.kind == "human":
                result: Dict[str, Any] = {}
                outcome = "not_run"
                issue = None
            elif criterion.kind == "unmeasurable":
                result = {}
                outcome = "unknown"
                issue = None
            elif infrastructure_error:
                result = {}
                outcome = "unknown"
                issue = infrastructure_error
            else:
                result = report["criteria"].get(criterion.criterion_id)
                issue = None
                if not isinstance(result, dict):
                    result = {}
                    outcome = "unknown"
                    issue = "evaluator omitted criterion result"
                else:
                    reported_version = result.get("evaluator_version")
                    observed = set(result.get("coverage_ids", []))
                    missing = sorted(set(criterion.expected_coverage_ids) - observed)
                    if reported_version != criterion.evaluator_version:
                        outcome = "unknown"
                        issue = (
                            f"evaluator version is {reported_version!r}, expected "
                            f"{criterion.evaluator_version!r}"
                        )
                    elif missing:
                        outcome = "unknown"
                        issue = f"incomplete coverage; missing {missing}"
                    else:
                        outcome = result.get("outcome", "unknown")
                        if outcome not in {"pass", "fail", "unknown", "not_run"}:
                            outcome = "unknown"
                            issue = "evaluator returned an invalid outcome"
            value = result.get("value")
            scale_value = result.get("scale")
            scale = ScoreScale(**scale_value) if value is not None and isinstance(scale_value, dict) else None
            if criterion.kind == "graded" and value is not None and scale is not None:
                outcome = "pass" if value >= criterion.minimum_score else "fail"
            coverage = sorted(set(result.get("coverage_ids", [])))
            coverage_id = None
            if coverage:
                coverage_id = "sha256:" + hashlib.sha256(
                    json.dumps(coverage, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
            measurement = self.evidence.measure(
                procedure=f"independent-{criterion.kind}",
                procedure_version=criterion.evaluator_version,
                scope=criterion.wording,
                outcome=outcome,
                value=value,
                scale=scale,
                coverage_id=coverage_id,
                coverage_ids=coverage,
                infrastructure_error=issue,
                workspace_revision=workspace_revision,
            )
            outcomes[criterion.criterion_id] = outcome
            measurements.append(measurement)
        return measurements, outcomes, infrastructure_error is not None

    def _record_decision(
        self,
        plan: AcceptancePlan,
        status: str,
        workspace_revision: str,
        outcomes: Dict[str, str],
        measurements: List[MeasurementRecord],
        tool_output_artifact_id: Optional[str] = None,
    ) -> AcceptanceDecision:
        event_id = self.runtime.journal.new_event_id()
        report = {
            "task_id": plan.task_id,
            "status": status,
            "final_workspace_revision": workspace_revision,
            "criteria": [criterion.to_dict() for criterion in plan.criteria],
            "criterion_outcomes": outcomes,
            "measurements": [measurement.to_dict() for measurement in measurements],
            "tool_output_artifact_id": tool_output_artifact_id,
        }
        artifact = self.runtime.artifacts.put(
            (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "application/json",
            event_id,
            labels=["acceptance-report", plan.task_id, status],
        )
        decision = AcceptanceDecision(
            task_id=plan.task_id,
            status=status,
            final_workspace_revision=workspace_revision,
            criterion_outcomes=dict(outcomes),
            measurement_ids=[measurement.measurement_id for measurement in measurements],
            report_artifact_id=artifact.artifact_id,
        )
        self.runtime.journal.append(
            "acceptance_decision",
            {"decision": decision.to_dict(), "plan": plan.to_dict()},
            event_id=event_id,
        )
        return decision
