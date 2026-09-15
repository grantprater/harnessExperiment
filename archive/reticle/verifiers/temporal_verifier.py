"""Temporal Invariant Verifier and Linear Temporal Logic (LTL) Oracle."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from reticle.core.world_line_ledger import WorldLineLedger, EntityInterval
from reticle.core.verifier_base import BaseVerifier, VerificationResult


@dataclass
class TemporalVerificationResult:
    passed: bool
    score: float  # 0.0 - 1.0
    passed_invariants: List[str]
    detected_violations: List[str]
    energy_grounding_score: float
    details: Dict[str, Any]

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Temporal Logic (LTL) Verification: {status} (Score: {self.score*100:.1f}%) ===",
            f"- Passed Invariants ({len(self.passed_invariants)}): {self.passed_invariants}",
        ]
        if self.detected_violations:
            lines.append(f"- Violations Detected ({len(self.detected_violations)}): {self.detected_violations}")
        lines.append(f"- Physical Motion Grounding: {self.energy_grounding_score*100:.1f}%")
        return "\n".join(lines)


class TemporalInvariantVerifier(BaseVerifier):
    """Evaluates world-line ledgers and temporal claims against LTL invariants and physical profiles."""

    def __init__(
        self,
        ledger: WorldLineLedger,
        energy_profile: Optional[List[Dict[str, Any]]] = None,
        fps: float = 10.0,
        max_velocity_px_per_s: float = 500.0
    ):
        self.ledger = ledger
        self.energy_profile = energy_profile or []
        self.fps = fps
        self.max_v = max_velocity_px_per_s

    def _check_monotonicity(self) -> Tuple[bool, List[str]]:
        violations = []
        for i in self.ledger.intervals:
            if i.t_start >= i.t_end:
                violations.append(
                    f"Interval {i.interval_id} for '{i.entity_id}' violates monotonicity: t_start ({i.t_start}s) >= t_end ({i.t_end}s)"
                )
        return len(violations) == 0, violations

    def _check_spatial_continuity(self) -> Tuple[bool, List[str], int]:
        violations = []
        by_entity: Dict[str, List[EntityInterval]] = {}
        for i in self.ledger.intervals:
            by_entity.setdefault(i.entity_id, []).append(i)

        for eid, ints in by_entity.items():
            sorted_ints = sorted(ints, key=lambda x: x.t_start)
            for idx in range(1, len(sorted_ints)):
                prev_i = sorted_ints[idx - 1]
                curr_i = sorted_ints[idx]
                dt = max(0.001, curr_i.t_start - prev_i.t_end)
                dx = curr_i.start_coords[0] - prev_i.end_coords[0]
                dy = curr_i.start_coords[1] - prev_i.end_coords[1]
                dist = math.hypot(dx, dy)
                speed = dist / dt
                if speed > self.max_v:
                    violations.append(
                        f"Entity '{eid}' teleported between {prev_i.interval_id} and {curr_i.interval_id}: "
                        f"moved {dist:.2f}px in {dt:.2f}s (Speed {speed:.1f}px/s > max {self.max_v}px/s)"
                    )
        return len(violations) == 0, violations, len(by_entity)

    def _check_energy_grounding(self) -> Tuple[bool, float, List[str], int]:
        violations = []
        motion_grounded_count = 0
        motion_total_count = 0

        for i in self.ledger.intervals:
            if "in_motion" in i.state_predicate.lower():
                motion_total_count += 1
                s_frame = int(i.t_start * self.fps)
                e_frame = int(i.t_end * self.fps)
                sub_e = [
                    p["motion_energy"]
                    for p in self.energy_profile
                    if s_frame <= p["frame_index"] <= e_frame
                ]
                mean_e = sum(sub_e) / len(sub_e) if sub_e else 0.0
                if mean_e > 0.002 or not self.energy_profile:
                    motion_grounded_count += 1
                else:
                    violations.append(
                        f"Interval {i.interval_id} for '{i.entity_id}' claimed motion during {i.t_start}s-{i.t_end}s, "
                        f"but deterministic motion energy was zero ({mean_e:.4f})"
                    )

        energy_score = 1.0
        if motion_total_count > 0:
            energy_score = round(motion_grounded_count / motion_total_count, 4)
            return energy_score >= 0.8, energy_score, violations, motion_total_count
        return True, 1.0, violations, 0

    def verify_temporal_invariants(self) -> TemporalVerificationResult:
        passed = []
        all_violations = []

        mono_ok, mono_errs = self._check_monotonicity()
        if mono_ok:
            passed.append("Invariant 1: Chronological monotonicity holds across all entity intervals")
        all_violations.extend(mono_errs)

        cont_ok, cont_errs, entity_count = self._check_spatial_continuity()
        if cont_ok:
            passed.append("Invariant 2: Spatial continuity & object permanence hold (no teleportation)")
        all_violations.extend(cont_errs)

        energy_ok, energy_score, energy_errs, motion_count = self._check_energy_grounding()
        if energy_ok:
            passed.append("Invariant 3: All motion intervals grounded in physical optical energy peaks" if motion_count > 0 else "Invariant 3: Static consistency holds")
        all_violations.extend(energy_errs)

        all_passed = (len(all_violations) == 0)
        score = 1.0 if all_passed else max(0.0, 1.0 - (len(all_violations) * 0.25))

        return TemporalVerificationResult(
            passed=all_passed,
            score=round(score, 4),
            passed_invariants=passed,
            detected_violations=all_violations,
            energy_grounding_score=energy_score,
            details={"by_entity_count": entity_count, "motion_intervals": motion_count}
        )

    def verify(self, *args, **kwargs) -> VerificationResult:
        res = self.verify_temporal_invariants()
        return VerificationResult(
            passed=res.passed,
            score=res.score,
            passed_invariants=res.passed_invariants,
            detected_violations=res.detected_violations,
            details={"energy_grounding_score": res.energy_grounding_score}
        )
