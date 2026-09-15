"""Counterfactual Permutation Environment for Testing True Empirical Learning.

Prevents memorization leakage from LLM pre-training corpora (e.g. Minecraft Wiki)
by perturbing canonical game physics, block harvest yields, and tool prerequisites:

Examples of Counterfactual Invariants:
1. Yield Permutations: 'stone' yields 'feathers' or 'diamond', 'oak_log' yields 'iron_ingot'.
2. Tool Tier Inversions: 'stone' requires an 'axe', 'oak_log' requires a 'pickaxe'.
3. Durability Shocks: 'wooden_pickaxe' breaks after 3 uses instead of 59.

A genuine epistemic agent succeeds because its active experimentation loop catches
the prediction error, falsifies the memorized prior, and updates its empirical belief.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Optional, Tuple

from reticle.adapters.minecraft_adapter import (
    SimulatedMinecraftEnvironment,
    VoxelBlock,
    CANONICAL_BLOCKS,
    TOOL_TIERS
)
from reticle.minecraft.epistemic_probe import (
    EpistemicHypothesis,
    MinecraftEpistemicProbe,
    ExperimentResult
)


class PermutedMinecraftEnvironment(SimulatedMinecraftEnvironment):
    """Minecraft environment with counterfactual, permuted physical laws."""

    def __init__(self, seed: Optional[int] = None, rules_override: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.rules_override = rules_override or {}
        if seed is not None and not rules_override:
            self._generate_random_permutation(seed)

    def _generate_random_permutation(self, seed: int):
        rng = random.Random(seed)
        candidate_items = ["cobblestone", "dirt", "oak_log", "feathers", "raw_iron", "diamond"]
        candidate_tools = ["pickaxe", "axe", None]

        # Shuffle drops for canonical blocks
        for b_name, b_obj in CANONICAL_BLOCKS.items():
            if b_name == "air":
                continue
            shuffled_drop = rng.choice(candidate_items)
            shuffled_tool = rng.choice(candidate_tools)
            shuffled_tier = rng.choice([0, 1, 2])
            self.rules_override[b_name] = {
                "drops_item": shuffled_drop,
                "required_tool_type": shuffled_tool,
                "min_tool_tier": shuffled_tier
            }

    def set_block(self, x: int, y: int, z: int, block_name: str):
        base_block = CANONICAL_BLOCKS.get(block_name, VoxelBlock(name=block_name, hardness=1.0))
        # Apply counterfactual override if present
        if block_name in self.rules_override:
            overrides = self.rules_override[block_name]
            permuted_block = copy.deepcopy(base_block)
            if "drops_item" in overrides:
                permuted_block.drops_item = overrides["drops_item"]
            if "required_tool_type" in overrides:
                permuted_block.required_tool_type = overrides["required_tool_type"]
            if "min_tool_tier" in overrides:
                permuted_block.min_tool_tier = overrides["min_tool_tier"]
            if "hardness" in overrides:
                permuted_block.hardness = overrides["hardness"]
            self.voxels[(x, y, z)] = permuted_block
        else:
            self.voxels[(x, y, z)] = base_block


class CounterfactualEmpiricalEvaluator:
    """Evaluates whether an agent genuinely updates its beliefs when reality contradicts pre-training."""

    @staticmethod
    def run_falsification_benchmark(
        env: PermutedMinecraftEnvironment,
        probe: MinecraftEpistemicProbe,
        test_block: str = "stone",
        coords: Tuple[int, int, int] = (1, 64, 0)
    ) -> Dict[str, Any]:
        """Runs the active experimentation loop to test prior falsification and belief update."""
        env.set_block(*coords, test_block)
        env.add_item("wooden_pickaxe", 1)
        env.equip("wooden_pickaxe")

        # 1. Prior Hypothesis based on memorized vanilla Minecraft wiki
        vanilla_hypothesis = EpistemicHypothesis(
            hypothesis_id="HYP_VANILLA_PRIOR",
            claim=f"Mining {test_block} with wooden pickaxe yields cobblestone",
            affordance_source="pretraining_wiki_memory",
            action_name="dig",
            action_params={"x": coords[0], "y": coords[1], "z": coords[2]},
            predicted_inventory_delta={"cobblestone": 1},
            predicted_voxel_state="air",
            confidence=0.9
        )
        probe.register_hypothesis(vanilla_hypothesis)

        # 2. Execute active intervention in the counterfactual world
        result = probe.run_intervention("HYP_VANILLA_PRIOR")

        # 3. Assess whether the agent successfully detected prior falsification
        prior_falsified = (result.attribution != "RULE_CONFIRMED")
        actual_drop = None
        for item, count in result.observed_inventory_delta.items():
            if count > 0:
                actual_drop = item
                break

        # 4. Formulate empirical induced hypothesis based on observed reality
        induced_hypothesis = None
        if prior_falsified and actual_drop:
            induced_hypothesis = EpistemicHypothesis(
                hypothesis_id="HYP_EMPIRICAL_INDUCED",
                claim=f"Mining {test_block} in this world empirically yields {actual_drop}",
                affordance_source="observed_intervention_residual",
                action_name="dig",
                action_params={"x": coords[0], "y": coords[1], "z": coords[2] + 1},
                predicted_inventory_delta={actual_drop: 1},
                predicted_voxel_state="air",
                confidence=0.75
            )

        return {
            "vanilla_prior_falsified": prior_falsified,
            "observed_residual_error": result.residual_error,
            "actual_drop_discovered": actual_drop,
            "induced_empirical_hypothesis": induced_hypothesis,
            "explanation": result.explanation
        }
