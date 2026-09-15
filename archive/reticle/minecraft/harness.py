"""Embodied Cognitive Harness for Minecraft (Reticle).

Orchestrates:
1. Coarse-to-Fine Perception: Macro overview (inventory + nearby block census) -> Fovea inspection.
2. Active Working Memory & Zero-Surprise Evaporation:
   - Uses WorkingMemoryManager to track EpistemicCommitments.
   - When an intervention matches predicted deltas, raw sensory dumps evaporate into 1-line belief updates.
   - Surprises/residuals remain in context for causal diagnosis.
3. Epistemic Belief Updates:
   - Synchronizes with EvidenceLedger and WorldLineLedger.
4. Episodic Tracing & Procedural Consolidation:
   - Trajectories logged to ./traces/ to feed the SkillEvolutionEngine.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from context_manager import WorkingMemoryManager, EpistemicCommitment
from reticle.core.evidence_ledger import EvidenceLedger
from reticle.core.world_line_ledger import WorldLineLedger
from reticle.adapters.minecraft_adapter import MinecraftAdapter, SimulatedMinecraftEnvironment
from reticle.minecraft.epistemic_probe import MinecraftEpistemicProbe, EpistemicHypothesis
from harness import LLMClient, EpisodicTrace


MINECRAFT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "macro_sense",
            "description": "Macro Sensor: View coarse bot state, health, equipped item, inventory summary, and census of nearby block types.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fovea_probe",
            "description": "Foveated Probe: Zoom in to inspect exact voxel properties (hardness, material, required tool) at specific coordinates (x, y, z).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "z": {"type": "integer", "description": "Z coordinate"}
                },
                "required": ["x", "y", "z"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_intervention",
            "description": "Active Intervention do(Action): Execute a physical action. In accordance with Predictive Coding, you MUST supply your predicted_delta before actuation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["dig", "craft", "equip"], "description": "Action type"},
                    "params": {"type": "object", "description": "Action arguments e.g. {'x': 1, 'y': 64, 'z': 0} or {'recipe_name': 'oak_planks'}"},
                    "predicted_inventory_delta": {"type": "object", "description": "Expected inventory deltas, e.g. {'cobblestone': 1}"},
                    "predicted_durability_delta": {"type": "integer", "description": "Expected tool durability delta (e.g. -1)", "default": 0},
                    "rationale": {"type": "string", "description": "Hypothesis rationale based on semiotics or prior belief."}
                },
                "required": ["action", "params", "predicted_inventory_delta", "rationale"]
            }
        }
    }
]


class MinecraftCognitiveHarness:
    """Embodied cognitive harness running perception, working memory, and belief updates."""

    def __init__(
        self,
        adapter: Optional[MinecraftAdapter] = None,
        llm_client: Optional[LLMClient] = None,
        trace_dir: str | Path = "traces"
    ):
        self.adapter = adapter or MinecraftAdapter(mode="simulated")
        self.client = llm_client or LLMClient()
        self.trace_dir = Path(trace_dir)
        self.working_memory = WorkingMemoryManager(max_working_tokens=16000)
        self.evidence_ledger = EvidenceLedger()
        self.world_ledger = WorldLineLedger()
        self.probe_runner = MinecraftEpistemicProbe(
            adapter=self.adapter,
            evidence_ledger=self.evidence_ledger,
            world_ledger=self.world_ledger
        )

    def generate_macro_perception(self) -> str:
        """Coarse sensor representation of the player state and surrounding world."""
        if self.adapter.mode == "simulated":
            sim = self.adapter.sim
            inv_str = ", ".join(f"{k}: {v}" for k, v in sim.inventory.items()) or "Empty"
            equipped = sim.equipped_tool or "Bare Hand"
            health = sim.health

            # Coarse block census within radius 4
            block_counts: Dict[str, int] = {}
            for (bx, by, bz), b in sim.voxels.items():
                if b.name != "air":
                    block_counts[b.name] = block_counts.get(b.name, 0) + 1
            census_str = ", ".join(f"{k}: {v}" for k, v in block_counts.items()) or "None"

            return (
                f"=== MACRO SENSOR VIEW ===\n"
                f"Position: {sim.player_pos} | Health: {health}/20.0 | Equipped: {equipped}\n"
                f"Inventory: [{inv_str}]\n"
                f"Nearby Voxels Census: [{census_str}]"
            )
        else:
            status = self.adapter.client.get_status()
            state = status.get("state", {})
            return f"=== MACRO SENSOR VIEW (Live Mineflayer) ===\nState: {json.dumps(state, indent=2)}"

    def run_cycle(
        self,
        task: str,
        max_steps: int = 8
    ) -> Dict[str, Any]:
        """Executes an embodied cognitive task with working memory and predictive evaporation."""
        self.working_memory.messages.clear()
        self.working_memory.commitments.clear()

        system_prompt = (
            "You are an embodied cognitive agent in Minecraft following the Reticle Harness philosophy:\n"
            "1. Coarse-to-fine perception: Orient via macro_sense, then use fovea_probe for exact coordinates.\n"
            "2. Predictive coding: Formulate explicit predicted_delta for every execute_intervention.\n"
            "3. Zero-surprise evaporation: Confirmed predictions evaporate to save working memory. Surprises are preserved.\n"
            "4. Epistemic belief: Learn physical invariants through active experimentation."
        )

        self.working_memory.add_system(system_prompt)
        macro_view = self.generate_macro_perception()
        self.working_memory.add_user(
            f"Goal: {task}\n\n"
            f"Initial Macro View:\n{macro_view}\n\n"
            "Formulate your hypotheses, inspect voxels, and conduct interventions to achieve the goal."
        )

        step = 0
        task_completed = False
        actions_log = []

        while step < max_steps and not task_completed:
            step += 1

            if self.client.mock_mode:
                # Deterministic simulation of an agent cycle in mock mode
                macro = self.generate_macro_perception()
                actions_log.append({"step": step, "type": "macro_sense", "output": macro[:100]})
                task_completed = True
                break

            messages = self.working_memory.get_messages_for_llm()
            response = self.client.chat_completion(messages, tools=MINECRAFT_TOOL_SCHEMAS)
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []

            self.working_memory.add_assistant(content, tool_calls=tool_calls)

            if not tool_calls:
                # Check if agent indicated completion
                if "goal completed" in content.lower() or "finished" in content.lower():
                    task_completed = True
                    break
                continue

            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                call_id = tc.get("id", f"call_{step}_{len(actions_log)}")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}

                if fn_name == "macro_sense":
                    out_str = self.generate_macro_perception()
                    self.working_memory.add_tool_result(
                        tool_call_id=call_id,
                        tool_name=fn_name,
                        raw_output=out_str,
                        can_evaporate=False
                    )
                    actions_log.append({"tool": fn_name, "args": args, "result": out_str[:120]})

                elif fn_name == "fovea_probe":
                    bx, by, bz = args.get("x", 0), args.get("y", 0), args.get("z", 0)
                    b_info = self.adapter.probe_block(bx, by, bz)
                    out_str = f"Voxel at ({bx}, {by}, {bz}): {json.dumps(b_info)}"
                    self.working_memory.add_tool_result(
                        tool_call_id=call_id,
                        tool_name=fn_name,
                        raw_output=out_str,
                        can_evaporate=True,
                        evaporation_summary=f"Inspected ({bx}, {by}, {bz}): {b_info.get('name')}"
                    )
                    actions_log.append({"tool": fn_name, "args": args, "result": out_str})

                elif fn_name == "execute_intervention":
                    action = args.get("action", "")
                    params = args.get("params", {})
                    pred_inv = args.get("predicted_inventory_delta", {})
                    pred_dur = args.get("predicted_durability_delta", 0)
                    rationale = args.get("rationale", "")

                    # 1. Record Epistemic Commitment in Working Memory
                    commit = self.working_memory.record_commitment(
                        intent=rationale,
                        expected_delta=f"Inv: {pred_inv}, Dur: {pred_dur}",
                        tool=f"do({action})",
                        args=params
                    )

                    # 2. Register and run hypothesis through probe runner
                    hyp_id = f"hyp_step_{step}_{len(actions_log)}"
                    hyp = EpistemicHypothesis(
                        hypothesis_id=hyp_id,
                        claim=rationale or f"Action {action} produces {pred_inv}",
                        affordance_source="agent_inference",
                        action_name=action,
                        action_params=params,
                        predicted_inventory_delta=pred_inv,
                        predicted_durability_delta=pred_dur
                    )
                    self.probe_runner.register_hypothesis(hyp)
                    exp_res = self.probe_runner.run_intervention(hyp_id)

                    commit.observed_result = exp_res.explanation
                    commit.surprise_detected = (exp_res.residual_error > 0.0)

                    # 3. Working Memory Evaporation: Zero-Surprise Silence
                    if exp_res.attribution == "RULE_CONFIRMED":
                        evap_summary = f"✓ [Evaporated Confirmation]: do({action}) confirmed rule: {rationale} (Residual=0.0)"
                        self.working_memory.add_tool_result(
                            tool_call_id=call_id,
                            tool_name=fn_name,
                            raw_output=exp_res.explanation,
                            can_evaporate=True,
                            evaporation_summary=evap_summary
                        )
                    else:
                        # Epistemic Surprise: Keep full residual in active context for diagnosis!
                        surprise_msg = (
                            f"⚠ [Epistemic Surprise - {exp_res.attribution}]: {exp_res.explanation}\n"
                            f"Predicted: {pred_inv} | Observed: {exp_res.observed_inventory_delta}\n"
                            f"Residual Error: {exp_res.residual_error}"
                        )
                        self.working_memory.add_tool_result(
                            tool_call_id=call_id,
                            tool_name=fn_name,
                            raw_output=surprise_msg,
                            can_evaporate=False
                        )

                    actions_log.append({
                        "tool": fn_name,
                        "action": action,
                        "attribution": exp_res.attribution,
                        "residual": exp_res.residual_error
                    })

        # Save Episodic Trace for procedural consolidation
        trace_id = f"mc_trace_{int(time.time())}"
        trace = EpisodicTrace(
            trace_id=trace_id,
            task=task,
            timestamp=time.time(),
            total_steps=step,
            actions=actions_log,
            success=task_completed,
            phase1_steps=step,
            phase2_executed=False,
            notes=f"Evidence atoms recorded: {len(self.evidence_ledger.atoms)}"
        )
        trace.save(self.trace_dir)

        return {
            "trace_id": trace_id,
            "success": task_completed,
            "steps": step,
            "working_memory_stats": self.working_memory.stats(),
            "evidence_atoms": len(self.evidence_ledger.atoms),
            "actions": actions_log
        }
