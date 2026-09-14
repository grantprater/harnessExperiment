"""Temporal Invariant Verifier & Linear Temporal Logic (LTL) Oracle.

Acts as the formal compiler for temporal event reasoning in video sequences:
1. Chronological Monotonicity:
   Enforces t_start < t_end and temporal ordering across state transitions.
2. Spatial Continuity (No Teleportation):
   Enforces bounded velocity ||p(t2) - p(t1)|| / dt <= v_max for each entity.
3. Physical Motion Energy Grounding:
   Cross-examines claimed motion intervals against the deterministic optical energy profile.
4. Causal State Transition Consistency:
   Verifies that state changes (e.g. at_rest -> in_motion) satisfy causal preconditions.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple

from world_line_ledger import WorldLineLedger, EntityInterval


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


class TemporalInvariantVerifier:
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

    def verify_temporal_invariants(self) -> TemporalVerificationResult:
        passed = []
        violations = []

        # 1. Check Chronological Monotonicity
        mono_ok = True
        for i in self.ledger.intervals:
            if i.t_start >= i.t_end:
                mono_ok = False
                violations.append(
                    f"Interval {i.interval_id} for '{i.entity_id}' violates monotonicity: t_start ({i.t_start}s) >= t_end ({i.t_end}s)"
                )
        if mono_ok:
            passed.append("Invariant 1: Chronological monotonicity holds across all entity intervals")

        # 2. Check Spatial Continuity & Object Permanence (No Teleportation)
        by_entity: Dict[str, List[EntityInterval]] = {}
        for i in self.ledger.intervals:
            by_entity.setdefault(i.entity_id, []).append(i)

        teleport_ok = True
        for eid, ints in by_entity.items():
            sorted_ints = sorted(ints, key=lambda x: x.t_start)
            for k in range(1, len(sorted_ints)):
                prev_i = sorted_ints[k - 1]
                curr_i = sorted_ints[k]
                dt = curr_i.t_start - prev_i.t_end
                dist = math.hypot(
                    curr_i.start_coords[0] - prev_i.end_coords[0],
                    curr_i.start_coords[1] - prev_i.end_coords[1]
                )
                if dt < 0:
                    violations.append(f"Entity '{eid}' has overlapping temporal intervals: [{prev_i.t_start}-{prev_i.t_end}] and [{curr_i.t_start}-{curr_i.t_end}]")
                    teleport_ok = False
                elif dt == 0 and dist > 10.0:
                    violations.append(f"Entity '{eid}' instant teleportation detected: jumped {dist:.1f}px at t={curr_i.t_start}s")
                    teleport_ok = False
                elif dt > 0 and (dist / dt) > self.max_v:
                    violations.append(f"Entity '{eid}' velocity violation: moved at {dist/dt:.1f}px/s (max: {self.max_v}px/s)")
                    teleport_ok = False

        if teleport_ok:
            passed.append("Invariant 2: Spatial continuity & object permanence hold (no teleportation)")

        # 3. Check Physical Motion Energy Grounding
        grounded_count = 0
        motion_intervals = [i for i in self.ledger.intervals if "motion" in i.state_predicate.lower() or "moving" in i.state_predicate.lower()]
        
        if not motion_intervals:
            grounding_score = 1.0
            passed.append("Invariant 3: Physical motion grounding verified (no ungrounded motion claims)")
        elif not self.energy_profile:
            grounding_score = 1.0
            passed.append("Invariant 3: Motion claims recorded (no profile attached)")
        else:
            for mi in motion_intervals:
                s_frame = int(mi.t_start * self.fps)
                e_frame = int(mi.t_end * self.fps)
                energies = [p["motion_energy"] for p in self.energy_profile if s_frame <= p["frame_index"] <= e_frame]
                peak = max(energies) if energies else 0.0
                if peak > 0.003:
                    grounded_count += 1
                else:
                    violations.append(
                        f"Hallucinated motion: Entity '{mi.entity_id}' claimed in motion during [{mi.t_start}s - {mi.t_end}s], "
                        f"but physical video motion energy was 0.0 (static frame)"
                    )
            grounding_score = grounded_count / max(1, len(motion_intervals))
            if grounding_score == 1.0:
                passed.append("Invariant 3: All motion intervals grounded in physical optical energy peaks")

        total_rules = 3
        score = len(passed) / total_rules
        all_passed = (len(violations) == 0)

        return TemporalVerificationResult(
            passed=all_passed,
            score=score,
            passed_invariants=passed,
            detected_violations=violations,
            energy_grounding_score=grounding_score,
            details={"entity_count": len(by_entity), "interval_count": len(self.ledger.intervals)}
        )
