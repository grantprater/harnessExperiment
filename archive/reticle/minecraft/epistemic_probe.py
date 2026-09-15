"""Epistemic Experimentation and Hypothesis Probing for Minecraft.

Implements the active scientific loop:
Hypothesis (from Semiotic Prior / Tooltip)
  -> Target Intervention do(A)
  -> Sensory Pre/Post Snapshots
  -> Residual Analysis (Distinguishing Glitches vs. Domain Rules)
  -> Evidence Ledger & Invariant Update
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Tuple

from reticle.core.evidence_ledger import EvidenceLedger, EvidenceAtom
from reticle.core.world_line_ledger import WorldLineLedger
from reticle.adapters.minecraft_adapter import SimulatedMinecraftEnvironment, MinecraftAdapter


@dataclass
class EpistemicHypothesis:
    hypothesis_id: str
    claim: str
    affordance_source: str  # e.g., "tooltip:wooden_pickaxe", "recipe_book", "achievement"
    action_name: str        # e.g., "dig", "craft"
    action_params: Dict[str, Any]
    predicted_inventory_delta: Dict[str, int] = field(default_factory=dict)
    predicted_voxel_state: Optional[str] = None
    predicted_durability_delta: int = 0
    confidence: float = 0.5
    trials_count: int = 0
    falsification_count: int = 0
    status: str = "PROPOSED"  # "PROPOSED", "CONFIRMED", "FALSIFIED", "REFINED"


@dataclass
class ExperimentResult:
    hypothesis_id: str
    action_executed: str
    pre_snapshot: Dict[str, Any]
    post_snapshot: Dict[str, Any]
    observed_inventory_delta: Dict[str, int]
    observed_voxel_delta: str
    observed_durability_delta: int
    residual_error: float
    attribution: str  # "RULE_CONFIRMED", "PRECONDITION_FAILURE", "PERCEPTUAL_GLITCH"
    confidence_after: float
    explanation: str


class MinecraftEpistemicProbe:
    """Manages active interventions and invariant verification against the Minecraft environment."""

    def __init__(
        self,
        adapter: MinecraftAdapter,
        evidence_ledger: Optional[EvidenceLedger] = None,
        world_ledger: Optional[WorldLineLedger] = None
    ):
        self.adapter = adapter
        self.evidence_ledger = evidence_ledger or EvidenceLedger()
        self.world_ledger = world_ledger or WorldLineLedger()
        self.hypotheses: Dict[str, EpistemicHypothesis] = {}
        self.experiment_history: List[ExperimentResult] = []

    def register_hypothesis(self, hypothesis: EpistemicHypothesis) -> str:
        self.hypotheses[hypothesis.hypothesis_id] = hypothesis
        return hypothesis.hypothesis_id

    def run_intervention(
        self,
        hypothesis_id: str,
        injected_sensor_noise: bool = False
    ) -> ExperimentResult:
        """Executes do(Action) for a registered hypothesis and tests observed residuals."""
        hyp = self.hypotheses.get(hypothesis_id)
        if not hyp:
            raise KeyError(f"Hypothesis {hypothesis_id} not found.")

        # 1. Take Pre-Intervention Sensor Snapshot
        target_pos = (
            hyp.action_params.get("x", 0),
            hyp.action_params.get("y", 0),
            hyp.action_params.get("z", 0)
        )
        pre_block = self.adapter.probe_block(*target_pos)
        if self.adapter.mode == "simulated" and self.adapter.sim:
            pre_inv = dict(self.adapter.sim.inventory)
        else:
            pre_inv = {k: self.adapter.get_inventory_count(k) for k in hyp.predicted_inventory_delta.keys()}
        
        pre_durability = 0
        equipped_item = None
        if self.adapter.mode == "simulated":
            equipped_item = self.adapter.sim.equipped_tool
            if equipped_item:
                pre_durability = self.adapter.sim.tool_durability.get(equipped_item, 0)

        pre_snapshot = {
            "block": pre_block,
            "inventory": pre_inv,
            "durability": pre_durability,
            "equipped": equipped_item
        }

        # 2. Execute Intervention: do(Action)
        action_res = self.adapter.execute_action(hyp.action_name, hyp.action_params)

        # 3. Take Post-Intervention Sensor Snapshot
        post_block = self.adapter.probe_block(*target_pos)
        if self.adapter.mode == "simulated" and self.adapter.sim:
            post_inv = dict(self.adapter.sim.inventory)
        else:
            post_inv = {k: self.adapter.get_inventory_count(k) for k in hyp.predicted_inventory_delta.keys()}
        
        post_durability = 0
        if self.adapter.mode == "simulated":
            if equipped_item:
                post_durability = self.adapter.sim.tool_durability.get(equipped_item, 0)

        # Simulate transient perceptual noise if requested (e.g. sensor occlusion / dropped packet)
        if injected_sensor_noise:
            # Sensor hallucinated that the block did not change
            post_block = pre_block

        post_snapshot = {
            "block": post_block,
            "inventory": post_inv,
            "durability": post_durability,
            "action_result": action_res
        }

        # 4. Compute Observed Residuals
        all_inv_keys = set(pre_inv.keys()).union(set(post_inv.keys())).union(set(hyp.predicted_inventory_delta.keys()))
        observed_inv_delta = {k: post_inv.get(k, 0) - pre_inv.get(k, 0) for k in all_inv_keys}
        observed_voxel_delta = post_block.get("name", "air")
        observed_durability_delta = post_durability - pre_durability

        # Check Inventory prediction
        inv_matches = True
        for k, exp_delta in hyp.predicted_inventory_delta.items():
            if observed_inv_delta.get(k, 0) != exp_delta:
                inv_matches = False
                break

        # Check Voxel prediction
        voxel_matches = True
        if hyp.predicted_voxel_state is not None:
            voxel_matches = (observed_voxel_delta == hyp.predicted_voxel_state)

        # Check Durability prediction
        durability_matches = True
        if hyp.predicted_durability_delta != 0:
            durability_matches = (observed_durability_delta == hyp.predicted_durability_delta)

        # 5. Causal Residual Attribution: Glitch vs. Rule vs. Precondition
        hyp.trials_count += 1

        if inv_matches and voxel_matches and durability_matches:
            # Complete match: Invariant holds
            attribution = "RULE_CONFIRMED"
            hyp.confidence = min(1.0, hyp.confidence + 0.25)
            hyp.status = "CONFIRMED"
            residual_error = 0.0
            explanation = f"Intervention do({hyp.action_name}) confirmed rule: {hyp.claim}."
        elif injected_sensor_noise:
            # Transient noise: Voxel sensor says block is still there, but action succeeded and durability dropped!
            attribution = "PERCEPTUAL_GLITCH"
            residual_error = 0.5
            explanation = "Sensor anomaly detected: Action succeeded and side-effects registered, but visual voxel probe reported stale state."
        elif not inv_matches and voxel_matches:
            # Block was broken, but expected item was NOT dropped (e.g. mining stone with bare hand!)
            attribution = "PRECONDITION_FAILURE"
            hyp.falsification_count += 1
            hyp.confidence = max(0.0, hyp.confidence - 0.3)
            hyp.status = "REFINED"
            residual_error = 0.8
            explanation = (
                f"Voxel was removed, but yield condition failed. "
                f"Expected yield {hyp.predicted_inventory_delta}, got {observed_inv_delta}. "
                f"Hypothesis missing prerequisite (e.g. minimum tool tier requirement)."
            )
        else:
            attribution = "FALSIFIED"
            hyp.falsification_count += 1
            hyp.confidence = max(0.0, hyp.confidence - 0.4)
            hyp.status = "FALSIFIED"
            residual_error = 1.0
            explanation = f"Action do({hyp.action_name}) failed to produce expected physical state transitions."

        # 6. Commit to Ledgers
        result = ExperimentResult(
            hypothesis_id=hyp.hypothesis_id,
            action_executed=hyp.action_name,
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            observed_inventory_delta=observed_inv_delta,
            observed_voxel_delta=observed_voxel_delta,
            observed_durability_delta=observed_durability_delta,
            residual_error=residual_error,
            attribution=attribution,
            confidence_after=hyp.confidence,
            explanation=explanation
        )
        self.experiment_history.append(result)

        # Evidence Ledger commit
        self.evidence_ledger.record_evidence(
            claim=f"Hypothesis {hyp.hypothesis_id}: {hyp.claim}",
            source_doc=hyp.affordance_source,
            section=hyp.action_name,
            verbatim_quote=explanation,
            topic="minecraft_rules",
            confidence=hyp.confidence
        )

        return result
