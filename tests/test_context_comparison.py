"""S1c checkpoint-based context comparison diagnostics."""

from pathlib import Path
import json
import tempfile
import unittest

from reticle.context import (
    BaselineContextPolicy,
    PressureRecentContextPolicy,
    TranscriptStore,
    compare_context_at_checkpoint,
)
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope


class ContextComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        self.runtime = LocalRuntime(self.root / "session", workspace)
        self.transcript = TranscriptStore(self.runtime)
        self.task = TaskEnvelope("compare", "Compare the frozen transcript.")

    def tearDown(self):
        self.temp_dir.cleanup()

    def exchange(self, index: int, marker: str, size: int):
        call_id = f"c{index}"
        self.transcript.append({
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{index}.txt"})},
            }],
        })
        self.transcript.append({
            "role": "tool", "tool_call_id": call_id,
            "content": marker + ("x" * size),
            "_reticle_output": {"handle": f"out_{index}", "tool": "read_file", "status": "success"},
        })

    def test_replays_two_policies_at_frozen_checkpoint(self):
        self.exchange(1, "OLD-CHECKPOINT-EVIDENCE", 3_000)
        self.exchange(2, "LATEST-CHECKPOINT-EVIDENCE", 3_000)
        checkpoint = self.runtime.checkpoint()
        self.transcript.append({"role": "user", "content": "AFTER-CHECKPOINT-MUST-NOT-APPEAR"})

        comparison = compare_context_at_checkpoint(
            self.runtime,
            self.task,
            {
                "legacy": BaselineContextPolicy(),
                "pressure": PressureRecentContextPolicy(),
            },
            [],
            4_300,
        )

        self.assertEqual(comparison.checkpoint_sequence, checkpoint["last_event_sequence"])
        self.assertEqual(comparison.transcript_messages, 4)
        self.assertEqual(len(comparison.policies), 2)
        by_name = {item.name: item for item in comparison.policies}
        self.assertEqual(by_name["legacy"].policy_version, "bounded-recent-v2")
        pressure = by_name["pressure"]
        self.assertEqual(pressure.policy_version, "pressure-recent-v1")
        self.assertTrue(pressure.omitted_items)
        self.assertEqual(pressure.retrieval_entry_points[0]["output_handle"], "out_1")
        self.assertIn("read_output", pressure.retrieval_entry_points[0]["read"])

        for policy in comparison.policies:
            request = self.runtime.artifacts.read(policy.request_artifact_id)
            self.assertEqual(len(request), policy.request_bytes)
            self.assertNotIn(b"AFTER-CHECKPOINT-MUST-NOT-APPEAR", request)
        recorded = json.loads(self.runtime.artifacts.read(comparison.comparison_artifact_id))
        self.assertEqual(recorded["checkpoint_sequence"], checkpoint["last_event_sequence"])
        self.assertEqual(recorded["scratch_state"], "current_at_replay_time")

    def test_legacy_omissions_match_its_request(self):
        for index in range(3):
            self.exchange(index, f"UNIT-{index}", 3_000)
        self.runtime.checkpoint()

        comparison = compare_context_at_checkpoint(
            self.runtime, self.task, {"legacy": BaselineContextPolicy()}, [], 1_200
        )

        legacy = comparison.policies[0]
        request = json.loads(self.runtime.artifacts.read(legacy.request_artifact_id))
        shown = {message.get("tool_call_id") for message in request["messages"] if message.get("role") == "tool"}
        dropped = {index for index in range(3) if f"c{index}" not in shown}
        self.assertTrue(dropped)
        self.assertEqual({item["unit_index"] for item in legacy.omitted_items}, dropped)
        self.assertEqual(
            {entry["output_handle"] for entry in legacy.retrieval_entry_points},
            {f"out_{index}" for index in dropped},
        )

    def test_requires_a_real_checkpoint_by_default(self):
        with self.assertRaisesRegex(ValueError, "checkpoint is required"):
            compare_context_at_checkpoint(
                self.runtime, self.task, {"pressure": PressureRecentContextPolicy()}, [], 2_000
            )


if __name__ == "__main__":
    unittest.main()
