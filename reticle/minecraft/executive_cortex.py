"""Executive Cortex Orchestrator (System 2 + System 1 Integration).

Bridges:
1. Online Streaming Perception (StreamingVideoTransducer)
2. Spinal Cord Motor Autopilot (SpinalCordAutopilot)
3. Working Memory Manager & Zero-Surprise Evaporation (WorkingMemoryManager)
4. Formal Invariant & Evidence Ledgers (EvidenceLedger, WorldLineLedger)
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from context_manager import WorkingMemoryManager
from reticle.core.evidence_ledger import EvidenceLedger
from reticle.core.world_line_ledger import WorldLineLedger
from reticle.adapters.minecraft_adapter import MinecraftAdapter
from reticle.sensory.streaming_transducer import StreamingVideoTransducer
from reticle.minecraft.autopilot import SpinalCordAutopilot, AutopilotStatus, AutopilotYieldReport


class ExecutiveCortex:
    """System 2 Executive Controller dispatching intents to the System 1 Spinal Autopilot."""

    def __init__(
        self,
        adapter: Optional[MinecraftAdapter] = None,
        transducer: Optional[StreamingVideoTransducer] = None,
        max_working_tokens: int = 16000
    ):
        self.adapter = adapter or MinecraftAdapter(mode="simulated")
        self.transducer = transducer or StreamingVideoTransducer()
        self.autopilot = SpinalCordAutopilot(adapter=self.adapter, transducer=self.transducer)
        self.working_memory = WorkingMemoryManager(max_working_tokens=max_working_tokens)
        self.evidence_ledger = EvidenceLedger()
        self.world_ledger = WorldLineLedger()
        self.completed_skills_history: List[AutopilotYieldReport] = []

    def dispatch_intent(
        self,
        intent: str,
        skill_fn: Callable[[MinecraftAdapter, Dict[str, Any]], Dict[str, Any]],
        skill_params: Dict[str, Any],
        expected_inventory_delta: Dict[str, int],
        rationale: str = "",
        max_ticks: int = 100
    ) -> AutopilotYieldReport:
        """Dispatches an intent to the high-frequency autopilot and handles the boundary yield."""
        # 1. System 2 commits epistemic prediction to Working Memory
        commit = self.working_memory.record_commitment(
            intent=intent,
            expected_delta=f"Inventory: {expected_inventory_delta}",
            tool="spinal_cord_autopilot",
            args={"skill_params": skill_params, "rationale": rationale}
        )

        # 2. System 1 executes autonomous motor routine at 20Hz (No LLM in the loop!)
        t0 = time.time()
        yield_report = self.autopilot.execute_skill_routine(
            intent=intent,
            skill_fn=skill_fn,
            skill_params=skill_params,
            max_ticks=max_ticks
        )
        duration_s = round(time.time() - t0, 3)

        commit.observed_result = yield_report.explanation
        self.completed_skills_history.append(yield_report)

        # 3. System 2 processes the boundary yield with Working Memory Evaporation
        call_id = f"exec_{len(self.completed_skills_history)}"

        if yield_report.status == AutopilotStatus.GOAL_COMPLETED:
            # Check if observed inventory matches prediction
            prediction_matched = yield_report.inventory_observed and bool(expected_inventory_delta)
            for item, count in expected_inventory_delta.items():
                if yield_report.inventory_delta.get(item, 0) != count:
                    prediction_matched = False
                    break

            if prediction_matched:
                # Zero-Surprise Evaporation: Compress multi-tick execution into a 1-line confirmation
                summary = (
                    f"✓ [Evaporated Routine]: Intent '{intent}' achieved by autopilot in "
                    f"{yield_report.ticks_elapsed} ticks ({duration_s}s). "
                    f"Yield: {yield_report.inventory_delta}. Inventory prediction matched."
                )
                full_trace = (
                    f"Spinal Autopilot Motor Trajectory Log:\n"
                    f"Intent: {intent} | Ticks: {yield_report.ticks_elapsed} | Status: {yield_report.status.value}\n"
                    f"Actions executed: {yield_report.actions_executed} | Health delta: {yield_report.health_delta}\n"
                    f"Inventory deltas: {yield_report.inventory_delta} | Durability delta: {yield_report.durability_delta}\n"
                    f"Explanation: {yield_report.explanation}\n"
                    f"Observed telemetry samples: {len(yield_report.observations)}; "
                    f"source={yield_report.observations[-1]['state'].get('source', 'unknown') if yield_report.observations else 'unknown'}"
                )
                self.working_memory.add_tool_result(
                    tool_call_id=call_id,
                    tool_name="spinal_cord_autopilot",
                    raw_output=full_trace,
                    can_evaporate=True,
                    evaporation_summary=summary
                )
                self.evidence_ledger.record_evidence(
                    claim=f"This execution of '{intent}' observed inventory delta {yield_report.inventory_delta}; repeatability untested",
                    source_doc="spinal_autopilot",
                    section=intent,
                    verbatim_quote=summary,
                    topic="execution_observation",
                    confidence=1.0
                )
            else:
                # Partial yield / surprise
                surprise_msg = (
                    f"⚠ [Epistemic Mismatch]: Autopilot signaled completion, but yield fell short. "
                    f"Expected: {expected_inventory_delta}, Observed: {yield_report.inventory_delta}."
                )
                self.working_memory.add_tool_result(
                    tool_call_id=call_id,
                    tool_name="spinal_cord_autopilot",
                    raw_output=surprise_msg,
                    can_evaporate=False
                )

        elif yield_report.status == AutopilotStatus.THREAT_INTERRUPT:
            # Threat interrupt: keep raw sensory details for the Cortex to re-orient
            interrupt_info = yield_report.interrupt_event
            threat_msg = (
                f"🚨 [THREAT INTERRUPT]: Autopilot halted execution due to sensory trigger. "
                f"{yield_report.explanation} | Channel: {interrupt_info.channel if interrupt_info else 'unknown'}, "
                f"Health delta: {yield_report.health_delta}."
            )
            self.working_memory.add_tool_result(
                tool_call_id=call_id,
                tool_name="spinal_cord_autopilot",
                raw_output=threat_msg,
                can_evaporate=False
            )

        else:
            # Precondition failure or max ticks
            boundary_msg = (
                f"⚠ [Autopilot Boundary - {yield_report.status.value}]: {yield_report.explanation} "
                f"(Actions: {yield_report.actions_executed}, Ticks: {yield_report.ticks_elapsed})."
            )
            self.working_memory.add_tool_result(
                tool_call_id=call_id,
                tool_name="spinal_cord_autopilot",
                raw_output=boundary_msg,
                can_evaporate=False
            )

        return yield_report
