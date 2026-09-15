"""Unit tests for Raw Motor Primitives, Skill Synthesis, Counterfactuals, and HUD Grounding."""

from __future__ import annotations

import unittest
from pathlib import Path
import numpy as np

from reticle.adapters.minecraft_adapter import (
    SimulatedMinecraftEnvironment,
    MinecraftAdapter
)
from reticle.adapters.raw_motor_controller import (
    RawMotorController,
    RawMotorState
)
from reticle.minecraft.skill_synthesizer import (
    SkillSynthesizer,
    SynthesisResult
)
from reticle.minecraft.counterfactual_env import (
    PermutedMinecraftEnvironment,
    CounterfactualEmpiricalEvaluator
)
from reticle.minecraft.epistemic_probe import MinecraftEpistemicProbe
from reticle.minecraft.hud_perception import (
    HUDPerceptionTransducer,
    PerceivedHUDState
)
from harness import LLMClient


class RawMotorAndEmergenceTests(unittest.TestCase):

    def test_raw_motor_controller_physics_and_raycast(self):
        env = SimulatedMinecraftEnvironment()
        # Place an oak log right in front of the player
        # Player is at (0.0, 64.0, 0.0), facing yaw=0 (positive Z direction)
        env.set_block(0, 65, 2, "oak_log")

        controller = RawMotorController(env=env)
        controller.set_look(yaw=0.0, pitch=0.0)

        # 1. Raycast should intersect the oak_log
        target_pos, target_block, dist = controller.raycast_crosshair()
        self.assertIsNotNone(target_pos)
        self.assertEqual(target_pos, (0, 65, 2))
        self.assertEqual(target_block.name, "oak_log")

        # 2. Hold left click to mine over time (takes 60 ticks / 3.0s with bare hand)
        controller.mouse_down("left")
        # Tick 30 times: block should NOT be broken yet
        res_partial = controller.tick(30)
        self.assertEqual(len(res_partial["broken_blocks"]), 0)
        self.assertEqual(env.get_block(0, 65, 2).name, "oak_log")

        # Tick remaining 30 times: block breaks on tick 60!
        res_full = controller.tick(30)
        self.assertEqual(len(res_full["broken_blocks"]), 1)
        self.assertEqual(env.get_block(0, 65, 2).name, "air")
        self.assertEqual(env.inventory.get("oak_log"), 1)

        controller.mouse_up("left")

    def test_skill_synthesizer_self_repair_loop(self):
        skills_dir = Path("test_skills_dir")
        skills_dir.mkdir(parents=True, exist_ok=True)

        synthesizer = SkillSynthesizer(
            llm_client=LLMClient(api_key="mock_key"),
            skills_dir=skills_dir
        )

        def env_factory():
            env = SimulatedMinecraftEnvironment()
            env.set_block(0, 65, 2, "dirt")
            controller = RawMotorController(env=env)
            controller.set_look(yaw=0.0, pitch=0.0)
            return env, controller

        def verifier(env, controller, result):
            return result.get("success", False) and env.inventory.get("dirt", 0) >= 1

        # Synthesize skill
        res = synthesizer.synthesize_skill(
            skill_name="break_front_block",
            goal_description="Aim at block, hold left click until broken, release click",
            env_factory=env_factory,
            verification_fn=verifier
        )

        self.assertTrue(res.success)
        self.assertEqual(res.skill_name, "break_front_block")
        self.assertIsNotNone(res.saved_path)
        self.assertTrue(Path(res.saved_path).exists())

        # Cleanup
        import shutil
        shutil.rmtree(skills_dir)

    def test_counterfactual_empirical_falsification(self):
        # Create a counterfactual world where stone drops feathers instead of cobblestone!
        rules_override = {
            "stone": {
                "drops_item": "feathers",
                "required_tool_type": "pickaxe",
                "min_tool_tier": 1
            }
        }
        env = PermutedMinecraftEnvironment(rules_override=rules_override)
        adapter = MinecraftAdapter(mode="simulated")
        adapter.sim = env
        probe = MinecraftEpistemicProbe(adapter=adapter)

        eval_res = CounterfactualEmpiricalEvaluator.run_falsification_benchmark(
            env=env,
            probe=probe,
            test_block="stone",
            coords=(1, 64, 0)
        )

        # 1. The agent's vanilla prior MUST be falsified
        self.assertTrue(eval_res["vanilla_prior_falsified"])
        # 2. It must discover the empirical truth: stone drops feathers!
        self.assertEqual(eval_res["actual_drop_discovered"], "feathers")
        # 3. It generates an empirical induced hypothesis for this alien world
        self.assertIsNotNone(eval_res["induced_empirical_hypothesis"])
        self.assertEqual(eval_res["induced_empirical_hypothesis"].predicted_inventory_delta, {"feathers": 1})

    def test_perceptual_hud_grounding_from_pixels(self):
        transducer = HUDPerceptionTransducer(
            health_roi=(10, 10, 190, 30),
            hotbar_roi=(10, 50, 200, 80)
        )

        # Create a synthetic 100x250 screen frame
        frame = np.ones((100, 250, 3), dtype=np.uint8) * 30  # Dark background

        # Draw 10 red hearts (each full heart has 40 red pixels, total 400 pixels)
        # In BGR: Red is [0, 0, 255]
        frame[12:28, 20:45] = [0, 0, 255]  # Red heart pixels

        # Draw occupied items in hotbar slot 0 and 1 with color variations
        frame[55:75, 15:30] = np.random.randint(50, 255, (20, 15, 3), dtype=np.uint8)
        frame[55:75, 35:50] = np.random.randint(50, 255, (20, 15, 3), dtype=np.uint8)

        hud_state = transducer.perceive_hud(frame)

        # Verify state is extracted directly from pixels
        self.assertGreater(hud_state.health_units, 0)
        self.assertIn(0, hud_state.occupied_hotbar_slots)
        self.assertIn(1, hud_state.occupied_hotbar_slots)
        self.assertEqual(hud_state.total_active_slots, 2)

    def test_emergent_causal_hud_discovery_without_hardcoding(self):
        from reticle.sensory.causal_probe import CausalSpatialCorrelationProbe

        probe = CausalSpatialCorrelationProbe(delta_threshold=20.0, min_area=50)

        # Baseline 720p frame
        pre_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 50

        # Draw an arbitrary health bar at an unknown random position (e.g. x=310..490, y=640..660)
        pre_frame[640:660, 310:490] = [0, 0, 255]  # Red hearts

        # Post-damage frame: player falls, 3 hearts vanish (turn dark gray/black)
        post_frame = pre_frame.copy()
        post_frame[640:660, 430:490] = [20, 20, 20]  # Damaged hearts vanish

        # The probe discovers the bounding box of the damage indicator EMERGENTLY!
        discovered = probe.discover_roi_from_event(
            channel_name="health_indicator",
            pre_frame_bgr=pre_frame,
            post_frame_bgr=post_frame
        )

        self.assertIsNotNone(discovered)
        self.assertEqual(discovered.channel_name, "health_indicator")
        x1, y1, x2, y2 = discovered.bbox
        # Verify the discovered bounding box matches the actual vanishing hearts: x in [310..490], y in [640..660]
        self.assertTrue(300 <= x1 <= 440)
        self.assertTrue(450 <= x2 <= 500)
        self.assertTrue(635 <= y1 <= 645)
        self.assertTrue(655 <= y2 <= 665)
        self.assertGreater(discovered.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()

