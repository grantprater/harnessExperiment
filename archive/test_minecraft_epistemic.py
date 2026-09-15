"""Unit tests for Minecraft Epistemic Probes, Causal Interventions, and Genetic Skills."""

from __future__ import annotations

import unittest

from reticle.adapters.minecraft_adapter import (
    SimulatedMinecraftEnvironment,
    MinecraftAdapter,
    CANONICAL_BLOCKS
)
from reticle.minecraft.epistemic_probe import (
    EpistemicHypothesis,
    MinecraftEpistemicProbe
)
from reticle.minecraft.genetic_skills import (
    SkillGenome,
    MAPElitesSkillArchive,
    SkillEvolutionEngine
)


class MinecraftEpistemicTests(unittest.TestCase):

    def setUp(self):
        self.adapter = MinecraftAdapter(mode="simulated")
        self.probe = MinecraftEpistemicProbe(adapter=self.adapter)

    def test_deterministic_mining_and_crafting_physics(self):
        sim = self.adapter.sim
        # Set up a tree and stone block
        sim.set_block(0, 64, 1, "oak_log")
        sim.set_block(0, 64, 2, "stone")

        # 1. Punch oak_log with bare hand -> drops oak_log
        res = sim.dig_block(0, 64, 1)
        self.assertTrue(res["success"])
        self.assertTrue(res["harvested"])
        self.assertEqual(sim.inventory.get("oak_log"), 1)

        # 2. Punch stone with bare hand -> no drop, requires pickaxe!
        res_stone_hand = sim.dig_block(0, 64, 2)
        self.assertTrue(res_stone_hand["success"])
        self.assertFalse(res_stone_hand["harvested"])
        self.assertEqual(sim.inventory.get("cobblestone", 0), 0)

        # 3. Crafting chain: 3 oak_logs -> 12 planks -> crafting table + sticks + wooden pickaxe
        sim.add_item("oak_log", 2)  # total 3 logs
        sim.craft_recipe("oak_planks", count=3)
        self.assertEqual(sim.inventory.get("oak_planks"), 12)

        sim.craft_recipe("crafting_table", count=1)
        self.assertEqual(sim.inventory.get("crafting_table"), 1)
        self.assertEqual(sim.inventory.get("oak_planks"), 8)

        sim.craft_recipe("stick", count=1)
        self.assertEqual(sim.inventory.get("stick"), 4)
        self.assertEqual(sim.inventory.get("oak_planks"), 6)

        # 4. Craft wooden pickaxe (requires table in inventory or world)
        craft_res = sim.craft_recipe("wooden_pickaxe", count=1)
        self.assertTrue(craft_res["success"])
        self.assertEqual(sim.inventory.get("wooden_pickaxe"), 1)
        self.assertEqual(sim.inventory.get("oak_planks"), 3)
        self.assertEqual(sim.inventory.get("stick"), 2)

        # 5. Equip wooden pickaxe and mine a second stone block -> drops cobblestone!
        sim.set_block(0, 64, 3, "stone")
        sim.equip("wooden_pickaxe")
        res_pickaxe = sim.dig_block(0, 64, 3)
        self.assertTrue(res_pickaxe["success"])
        self.assertTrue(res_pickaxe["harvested"])
        self.assertEqual(sim.inventory.get("cobblestone"), 1)
        self.assertEqual(sim.tool_durability.get("wooden_pickaxe"), 58)  # 59 - 1

    def test_epistemic_hypothesis_confirms_rule(self):
        sim = self.adapter.sim
        sim.set_block(1, 64, 1, "stone")
        sim.add_item("wooden_pickaxe", 1)
        sim.equip("wooden_pickaxe")

        hyp = EpistemicHypothesis(
            hypothesis_id="HYP_PICKAXE_STONE",
            claim="Wooden pickaxe yields cobblestone from stone",
            affordance_source="tooltip:wooden_pickaxe",
            action_name="dig",
            action_params={"x": 1, "y": 64, "z": 1},
            predicted_inventory_delta={"cobblestone": 1},
            predicted_voxel_state="air",
            predicted_durability_delta=-1
        )
        self.probe.register_hypothesis(hyp)

        result = self.probe.run_intervention("HYP_PICKAXE_STONE")
        self.assertEqual(result.attribution, "RULE_CONFIRMED")
        self.assertEqual(result.residual_error, 0.0)
        self.assertGreater(result.confidence_after, 0.5)
        self.assertEqual(hyp.status, "CONFIRMED")

    def test_epistemic_hypothesis_detects_precondition_failure(self):
        sim = self.adapter.sim
        sim.set_block(2, 64, 1, "stone")
        sim.equip(None)  # bare hand

        # Incorrect naive belief: punching stone yields cobblestone
        hyp = EpistemicHypothesis(
            hypothesis_id="HYP_HAND_STONE",
            claim="Bare hand yields cobblestone from stone",
            affordance_source="naive_prior",
            action_name="dig",
            action_params={"x": 2, "y": 64, "z": 1},
            predicted_inventory_delta={"cobblestone": 1},
            predicted_voxel_state="air"
        )
        self.probe.register_hypothesis(hyp)

        result = self.probe.run_intervention("HYP_HAND_STONE")
        self.assertEqual(result.attribution, "PRECONDITION_FAILURE")
        self.assertGreater(result.residual_error, 0.5)
        self.assertEqual(hyp.status, "REFINED")

    def test_epistemic_probe_disambiguates_perceptual_glitch(self):
        sim = self.adapter.sim
        sim.set_block(3, 64, 1, "stone")
        sim.add_item("wooden_pickaxe", 1)
        sim.equip("wooden_pickaxe")

        hyp = EpistemicHypothesis(
            hypothesis_id="HYP_GLITCH_TEST",
            claim="Mining stone with pickaxe removes block",
            affordance_source="tooltip",
            action_name="dig",
            action_params={"x": 3, "y": 64, "z": 1},
            predicted_inventory_delta={"cobblestone": 1},
            predicted_voxel_state="air",
            predicted_durability_delta=-1
        )
        self.probe.register_hypothesis(hyp)

        # Inject sensor noise (visual probe pretends block didn't update)
        result = self.probe.run_intervention("HYP_GLITCH_TEST", injected_sensor_noise=True)
        self.assertEqual(result.attribution, "PERCEPTUAL_GLITCH")

    def test_genetic_skill_evolution_and_map_elites(self):
        archive = MAPElitesSkillArchive(
            tiers=["wood", "stone", "iron"],
            domains=["gathering", "mining", "crafting"]
        )
        engine = SkillEvolutionEngine(archive=archive, mutation_rate=0.5, crossover_rate=0.5)

        def env_factory():
            env = SimulatedMinecraftEnvironment()
            # Surround player with oak logs
            for i in range(1, 4):
                env.set_block(i, 64, 0, "oak_log")
            return env

        # Define a parameterized wood gathering policy
        def gather_wood_policy(env: SimulatedMinecraftEnvironment, params: dict):
            reach = int(params.get("reach_distance", 2))
            harvested = 0
            for dx in range(1, reach + 1):
                block = env.get_block(dx, 64, 0)
                if block.name == "oak_log":
                    res = env.dig_block(dx, 64, 0)
                    if res["harvested"]:
                        harvested += 1
            return {"success": harvested > 0, "harvested": harvested}

        initial_population = [
            SkillGenome(
                skill_id=f"init_{i}",
                name="gather_wood",
                niche=("wood", "gathering"),
                parameters={"reach_distance": float(i + 1), "timeout_ticks": 50.0},
                policy_fn=gather_wood_policy
            )
            for i in range(4)
        ]

        # Evolve over 3 generations
        pop = initial_population
        for gen in range(3):
            pop = engine.run_evolution_step(
                population=pop,
                env_factory=env_factory,
                target_item="oak_log",
                target_pop_size=6
            )

        # Verify MAP-Elites has recorded a high-fitness champion for ("wood", "gathering")
        champion = archive.get_champion("wood", "gathering")
        self.assertIsNotNone(champion)
        self.assertGreater(champion.fitness, 50.0)
        self.assertGreater(archive.coverage_ratio(), 0.0)

    def test_minecraft_cognitive_harness_working_memory(self):
        from reticle.minecraft.harness import MinecraftCognitiveHarness
        from harness import LLMClient

        mock_client = LLMClient(api_key="mock_key")
        harness = MinecraftCognitiveHarness(
            adapter=self.adapter,
            llm_client=mock_client,
            trace_dir="traces"
        )
        self.adapter.sim.set_block(1, 64, 0, "oak_log")
        self.adapter.sim.add_item("wooden_pickaxe", 1)

        # 1. Check Macro Perception formatting
        macro_text = harness.generate_macro_perception()
        self.assertIn("MACRO SENSOR VIEW", macro_text)
        self.assertIn("oak_log", macro_text)
        self.assertIn("wooden_pickaxe", macro_text)

        # 2. Run an active cycle in mock mode
        result = harness.run_cycle("Gather oak logs", max_steps=3)
        self.assertTrue(result["success"])
        self.assertIn("trace_id", result)

        # 3. Verify Working Memory Evaporation logic directly
        # Commit prediction and test zero-surprise evaporation
        commit = harness.working_memory.record_commitment(
            intent="Mine oak log",
            expected_delta="Inv: {'oak_log': 1}",
            tool="do(dig)",
            args={"x": 1, "y": 64, "z": 0}
        )
        self.assertEqual(commit.step, 1)

        # Large payload that should evaporate if verified
        large_payload = "Voxel raw buffer " * 50
        harness.working_memory.add_tool_result(
            tool_call_id="call_test",
            tool_name="fovea_probe",
            raw_output=large_payload,
            can_evaporate=True,
            evaporation_summary="✓ [Evaporated]: Target is oak_log, verified."
        )

        stats = harness.working_memory.stats()
        self.assertGreater(stats["evaporated_tokens_saved"], 0)
        messages = harness.working_memory.get_messages_for_llm()
        self.assertIn("[Evaporated]", messages[-1]["content"])
        self.assertNotIn("Voxel raw buffer", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()

