import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from reticle.cognitive.autotelic_drive import AutotelicDriveEngine, AffordanceGatedMemoryIndex
from reticle.minecraft.autopilot import SpinalCordAutopilot, AutopilotStatus
from reticle.minecraft.executive_cortex import ExecutiveCortex


class GroundingBoundaryTests(unittest.TestCase):
    def engine(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return AutotelicDriveEngine(AffordanceGatedMemoryIndex(Path(directory.name) / 'beliefs.jsonl'))

    def test_low_health_dominates_even_in_bright_shelter(self):
        state = self.engine().arbitrate_drives(np.full((20, 20, 3), 255, dtype=np.uint8),
                                             {'oak_log': 1}, 0, health_hearts=2, sheltered=True)
        self.assertEqual(state.dominant_drive, 'HOMEOSTASIS')

    def test_unknown_health_is_not_a_measured_ratio(self):
        state = self.engine().evaluate_homeostasis(np.full((20, 20, 3), 255, dtype=np.uint8))
        self.assertIsNone(state.health_ratio)

    def test_single_unlock_still_activates_empowerment(self):
        state = self.engine().arbitrate_drives(np.full((20, 20, 3), 255, dtype=np.uint8),
                                             {'crafting_table': 1}, 0, health_hearts=20)
        self.assertEqual(state.dominant_drive, 'EMPOWERMENT')

    def adapter(self, states):
        adapter = Mock(mode='mineflayer')
        adapter.get_state.side_effect = states
        adapter.release_all.return_value = {'success': True}
        return adapter

    def test_unknown_pre_inventory_cannot_verify_a_gain(self):
        missing = {'connected': True, 'health': 20, 'source': 'test'}
        present = {**missing, 'inventory': {'oak_log': 1}}
        adapter = self.adapter([missing, present, present])
        cortex = ExecutiveCortex(adapter=adapter)
        report = cortex.dispatch_intent('mine', lambda *_: {'stop': True, 'goal_achieved': True}, {}, {'oak_log': 1})
        self.assertFalse(report.inventory_observed)
        self.assertEqual(report.inventory_delta, {})
        self.assertEqual(cortex.evidence_ledger.atoms, [])
        adapter.release_all.assert_called_once()

    def test_damage_interrupts_before_next_motor_step(self):
        healthy = {'connected': True, 'health': 20, 'inventory': {}}
        damaged = {**healthy, 'health': 18}
        adapter = self.adapter([healthy, damaged, damaged])
        skill = Mock()
        report = SpinalCordAutopilot(adapter).execute_skill_routine('move', skill, {})
        self.assertEqual(report.status, AutopilotStatus.THREAT_INTERRUPT)
        skill.assert_not_called()
        adapter.release_all.assert_called_once()

    def test_cancellation_releases_inputs(self):
        state = {'connected': True, 'health': 20, 'inventory': {}}
        adapter = self.adapter([state, state])
        with self.assertRaises(KeyboardInterrupt):
            SpinalCordAutopilot(adapter).execute_skill_routine('move', Mock(side_effect=KeyboardInterrupt), {})
        adapter.release_all.assert_called_once()

    def test_tick_budget_boundary_releases_inputs(self):
        state = {'connected': True, 'health': 20, 'inventory': {}}
        adapter = self.adapter([state, state, state])
        report = SpinalCordAutopilot(adapter).execute_skill_routine('move', lambda *_: {}, {}, max_ticks=1)
        self.assertEqual(report.status, AutopilotStatus.MAX_TICKS_EXCEEDED)
        adapter.release_all.assert_called_once()
