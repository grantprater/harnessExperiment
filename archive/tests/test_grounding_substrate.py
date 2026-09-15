import unittest
from unittest.mock import patch

import numpy as np

from reticle.adapters.minecraft_adapter import MinecraftAdapter
from reticle.adapters.raw_motor_controller import RawMotorController
from reticle.cognitive.autotelic_drive import AutotelicDriveEngine
import run_autotelic_cortex


class GroundingSubstrateTests(unittest.TestCase):
    def test_raw_controller_releases_all_inputs(self):
        adapter = MinecraftAdapter(mode="simulated")
        controller = RawMotorController(adapter.sim)
        controller.key_down("w")
        controller.mouse_down("left")
        controller.release_all()
        self.assertFalse(controller.state.keys_held)
        self.assertFalse(controller.state.mouse_buttons_held)

    def test_simulated_state_is_structured_and_source_attributed(self):
        adapter = MinecraftAdapter(mode="simulated")
        adapter.sim.add_item("acacia_log", 1)
        state = adapter.get_state()
        self.assertEqual(state["source"], "simulated_environment")
        self.assertEqual(state["inventory"]["acacia_log"], 1)

    def test_shelter_reduces_nightfall_urgency_and_variants_unlock(self):
        engine = AutotelicDriveEngine()
        dark = np.zeros((100, 100, 3), dtype=np.uint8)
        exposed = engine.evaluate_homeostasis(dark, health_hearts=20, sheltered=False)
        safe = engine.evaluate_homeostasis(dark, health_hearts=20, sheltered=True)
        self.assertLess(safe.urgency_score, exposed.urgency_score)
        empowerment = engine.evaluate_empowerment({"acacia_log": 1})
        self.assertIn("craft_planks", empowerment.unlockable_verbs)

    def test_runner_bounds_cycles_and_reuses_engine(self):
        engines = []
        def fake_once(engine, llm, cycle_index, log_path, prior_feedback=None, capability_ledger=None):
            engines.append(engine)
            return {"cycle": cycle_index}
        with patch.object(run_autotelic_cortex, "_run_autotelic_cycle_once", side_effect=fake_once):
            result = run_autotelic_cortex.run_autotelic_cycle(0)
        self.assertEqual(len(result), 1)
        with patch.object(run_autotelic_cortex, "_run_autotelic_cycle_once", side_effect=fake_once):
            result = run_autotelic_cortex.run_autotelic_cycle(3)
        self.assertEqual([r["cycle"] for r in result], [0, 1, 2])
        self.assertIs(engines[-1], engines[-2])


if __name__ == "__main__":
    unittest.main()
