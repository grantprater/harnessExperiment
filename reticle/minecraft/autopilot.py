"""Spinal Cord Behavioral Autopilot (System 1 Execution Engine).

Runs a tight 20Hz closed-loop motor execution routine without LLM invocation.
Features:
1. Hardwired Spinal Reflexes: Zero-latency reactive maneuvers on damage or critical events.
2. Invariant Precondition Guards: Continuous validation of tools, health, and resources.
3. Asynchronous Sensory Event Listening: Ingests streaming interrupts from the perceptual transducer.
4. Boundary Yielding: Returns control to the Executive Cortex only upon goal completion,
   threat detection, or epistemic surprise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from reticle.adapters.minecraft_adapter import MinecraftAdapter, SimulatedMinecraftEnvironment
from reticle.sensory.streaming_transducer import SensoryEvent, StreamingVideoTransducer


class AutopilotStatus(str, Enum):
    GOAL_COMPLETED = "GOAL_COMPLETED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    THREAT_INTERRUPT = "THREAT_INTERRUPT"
    EPISTEMIC_SURPRISE = "EPISTEMIC_SURPRISE"
    MAX_TICKS_EXCEEDED = "MAX_TICKS_EXCEEDED"


@dataclass
class AutopilotYieldReport:
    status: AutopilotStatus
    intent: str
    ticks_elapsed: int
    actions_executed: int
    inventory_delta: Dict[str, int]
    health_delta: Optional[float]
    durability_delta: Optional[int]
    interrupt_event: Optional[SensoryEvent] = None
    explanation: str = ""
    observations: List[Dict[str, Any]] = field(default_factory=list)
    inventory_observed: bool = True


class SpinalCordAutopilot:
    """System 1 motor controller executing high-frequency behavioral skills."""

    def __init__(
        self,
        adapter: MinecraftAdapter,
        transducer: Optional[StreamingVideoTransducer] = None
    ):
        self.adapter = adapter
        self.transducer = transducer
        self.reflexes_enabled: bool = True
        self.emergency_retreat_distance: int = 3

    def execute_skill_routine(
        self,
        intent: str,
        skill_fn: Callable[[MinecraftAdapter, Dict[str, Any]], Dict[str, Any]],
        skill_params: Dict[str, Any],
        max_ticks: int = 100,
        stop_on_threat: bool = True
    ) -> AutopilotYieldReport:
        """Release inputs at every boundary, including cancellation and exceptions.

        Skill callbacks must themselves be bounded; Python cannot preempt an
        arbitrary blocking callback here.
        """
        try:
            return self._execute_skill_routine(intent, skill_fn, skill_params, max_ticks, stop_on_threat)
        finally:
            result = self.adapter.release_all()
            if not result.get("success", False):
                raise RuntimeError(f"Input release not confirmed: {result}")

    def _execute_skill_routine(
        self, intent, skill_fn, skill_params, max_ticks, stop_on_threat
    ) -> AutopilotYieldReport:
        """Executes a behavioral skill loop at high frequency until a boundary is reached."""
        if not isinstance(max_ticks, int) or not 1 <= max_ticks <= 10000:
            raise ValueError("max_ticks must be between 1 and 10000")
        pre_state = self.adapter.get_state()
        pre_inv = pre_state.get("inventory")
        pre_health = pre_state.get("health")
        pre_dur = pre_state.get("durability")

        ticks = 0
        actions_count = 0
        interrupt_event = None
        status = AutopilotStatus.MAX_TICKS_EXCEEDED
        explanation = "Reached maximum allocated motor ticks."
        observations: List[Dict[str, Any]] = [{"tick": 0, "state": pre_state}]
        previous_health = pre_health

        while ticks < max_ticks:
            ticks += 1
            state = self.adapter.get_state()
            if state:
                observations.append({"tick": ticks, "state": state})
            if self.adapter.mode != "simulated" and state.get("connected") is not True:
                status = AutopilotStatus.PRECONDITION_FAILED
                explanation = "Live state unavailable; stopped without assuming safety."
                break
            health = state.get("health")
            if stop_on_threat and isinstance(health, (int, float)):
                if health <= 0 or (isinstance(previous_health, (int, float)) and health < previous_health):
                    status = AutopilotStatus.THREAT_INTERRUPT
                    explanation = "Observed health loss; inputs released and control yielded."
                    break
                previous_health = health

            # 1. Check Streaming Sensory Interrupts (Zero-Latency Reflex)
            if self.transducer and stop_on_threat:
                recent_events = self.transducer.poll_events(max_count=5)
                for evt in recent_events:
                    if evt.event_type == "TRANSIENT_SPIKE" and evt.channel in ("health_bar", "minimap_threat"):
                        # Execute hardwired spinal reflex
                        self._spinal_reflex_retreat()
                        status = AutopilotStatus.THREAT_INTERRUPT
                        interrupt_event = evt
                        explanation = f"Spinal reflex triggered by {evt.channel} transient (z={evt.metadata.get('z_score')}). " + ("Simulated retreat executed." if self.adapter.mode == "simulated" else "Inputs released; retreat path not verified.")
                        break

            if status == AutopilotStatus.THREAT_INTERRUPT:
                break

            # 2. Execute Motor Step of the Skill
            try:
                step_res = skill_fn(self.adapter, skill_params)
            except Exception as e:
                status = AutopilotStatus.PRECONDITION_FAILED
                explanation = f"Motor execution exception: {str(e)}"
                break

            actions_count += 1

            # 3. Check Step Outcome & Preconditions
            if step_res.get("stop", False):
                if step_res.get("goal_achieved", False):
                    status = AutopilotStatus.GOAL_COMPLETED
                    explanation = step_res.get("message", "Target goal reached successfully.")
                elif step_res.get("precondition_failed", False):
                    status = AutopilotStatus.PRECONDITION_FAILED
                    explanation = step_res.get("message", "Precondition violated during execution.")
                elif step_res.get("surprise", False):
                    status = AutopilotStatus.EPISTEMIC_SURPRISE
                    explanation = step_res.get("message", "Unexpected environmental state encountered.")
                break

        # Compute Total State Deltas
        post_state = self.adapter.get_state()
        observations.append({"tick": ticks, "phase": "post", "state": post_state})
        post_inv = post_state.get("inventory")
        post_health = post_state.get("health")
        post_dur = post_state.get("durability")
        inventory_observed = isinstance(pre_inv, dict) and isinstance(post_inv, dict)
        if stop_on_threat and isinstance(post_health, (int, float)) and isinstance(pre_health, (int, float)) and post_health < pre_health:
            status = AutopilotStatus.THREAT_INTERRUPT
            explanation = "Observed health loss during routine; control yielded."

        inv_delta = {}
        all_keys = set(pre_inv).union(post_inv) if inventory_observed else set()
        for k in all_keys:
            d = post_inv.get(k, 0) - pre_inv.get(k, 0)
            if d != 0:
                inv_delta[k] = d

        return AutopilotYieldReport(
            status=status,
            intent=intent,
            ticks_elapsed=ticks,
            actions_executed=actions_count,
            inventory_delta=inv_delta,
            health_delta=(round(post_health - pre_health, 2) if post_health is not None and pre_health is not None else None),
            durability_delta=(post_dur - pre_dur if post_dur is not None and pre_dur is not None else None),
            interrupt_event=interrupt_event,
            explanation=explanation,
            observations=observations,
            inventory_observed=inventory_observed
        )

    def _spinal_reflex_retreat(self):
        """Zero-latency instinctual retreat without calling the LLM."""
        if self.adapter.mode == "simulated" and self.adapter.sim:
            px, py, pz = self.adapter.sim.player_pos
            self.adapter.sim.player_pos = (px - self.emergency_retreat_distance, py, pz)
            self.adapter.sim.event_log.append({"event": "spinal_reflex_retreat", "distance": self.emergency_retreat_distance})

    def _get_inventory_snapshot(self) -> Dict[str, int]:
        if self.adapter.mode == "simulated" and self.adapter.sim:
            return dict(self.adapter.sim.inventory)
        state = self.adapter.get_state()
        inventory = state.get("inventory") if isinstance(state, dict) else None
        return dict(inventory) if isinstance(inventory, dict) else {}

    def _inventory_is_observed(self) -> bool:
        if self.adapter.mode == "simulated":
            return True
        state = self.adapter.get_state()
        return isinstance(state, dict) and isinstance(state.get("inventory"), dict)

    def _get_health(self) -> Optional[float]:
        if self.adapter.mode == "simulated" and self.adapter.sim:
            return self.adapter.sim.health
        state = self.adapter.get_state()
        value = state.get("health") if isinstance(state, dict) else None
        return float(value) if isinstance(value, (int, float)) else None

    def _get_durability(self) -> Optional[int]:
        if self.adapter.mode == "simulated" and self.adapter.sim:
            tool = self.adapter.sim.equipped_tool
            if tool:
                return self.adapter.sim.tool_durability.get(tool, 0)
        state = self.adapter.get_state()
        value = state.get("durability") if isinstance(state, dict) else None
        return int(value) if isinstance(value, (int, float)) else None
