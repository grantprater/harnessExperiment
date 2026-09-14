import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import run_autotelic_cortex as runner
from reticle.cognitive.autotelic_drive import AutotelicDriveEngine, AffordanceGatedMemoryIndex


class RunnerOutcomeTests(unittest.TestCase):
    def run_once(self, decision, states, actions=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        engine = AutotelicDriveEngine(AffordanceGatedMemoryIndex(base / 'beliefs.jsonl'))
        llm = Mock()
        llm.chat_completion.return_value = {'content': json.dumps(decision)}
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(runner, 'get_frame', return_value=np.full((480, 640, 3), 200, dtype=np.uint8)))
            stack.enter_context(patch.object(runner.cv2, 'imwrite'))
            stack.enter_context(patch.object(runner, 'get_structured_state', side_effect=states))
            send = stack.enter_context(patch.object(runner, 'send_action', side_effect=actions))
            if actions is None:
                send.return_value = {'success': True}
            self.last_send = send
            return runner._run_autotelic_cycle_once(engine, llm, 0, str(base / 'cycles.jsonl'))

    def state(self, health=20):
        return {'connected': True, 'source': 'test', 'health': health,
                'inventory': {}, 'yaw': 0, 'position': {'x': 0, 'y': 64, 'z': 0}}

    def test_craft_ack_with_empty_prediction_is_not_verified(self):
        decision = {'motor_action': {'type': 'craft', 'params': {'recipe': 'stick', 'predicted_inventory_delta': {}}}}
        result = self.run_once(decision, [self.state(), self.state()])
        self.assertFalse(result['action_result']['verified'])

    def test_key_down_timeout_still_releases(self):
        decision = {'motor_action': {'type': 'move', 'params': {}}}
        with self.assertRaises(TimeoutError):
            self.run_once(decision, [self.state()], [{'success': True}, TimeoutError(), {'success': True}])
        self.assertEqual(self.last_send.call_args.args, ('release_all',))

    def test_damage_stops_movement_and_releases(self):
        decision = {'motor_action': {'type': 'move', 'params': {'walk_duration_s': 1}}}
        result = self.run_once(decision, [self.state(), self.state(18), self.state(18)])
        self.assertTrue(result['action_result']['interrupted'])
        self.assertFalse(result['action_result']['verified'])
        self.assertEqual(self.last_send.call_args.args, ('release_all',))
