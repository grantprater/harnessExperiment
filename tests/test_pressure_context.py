"""S1a/E1 regressions for pressure-based recent context and controller validation."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

from reticle.context import BaselineContextPolicy, PressureRecentContextPolicy, TranscriptStore
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import NO_TOOL_CALL_PROMPT, AgentController, AgentLimits
from reticle.tools import ToolSuite


class NeverCalledModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        raise AssertionError("provider must not be called with an over-budget request")


class PressureRecentContextTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.root / "session", self.workspace)
        self.task = TaskEnvelope("pressure", "Keep the newest tool outcome visible.")
        self.transcript = TranscriptStore(self.runtime)
        self.policy = PressureRecentContextPolicy()

    def tearDown(self):
        self.temp_dir.cleanup()

    def exchange(self, index: int, content: str, *, status: str = "success") -> None:
        call_id = f"call-{index}"
        self.transcript.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{index}.txt"})},
            }],
        })
        self.transcript.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
            "_reticle_output": {"handle": f"out_{index}", "tool": "read_file", "status": status},
        })

    def build(self, budget: int):
        return self.policy.build(
            self.runtime,
            self.task,
            self.transcript.load(),
            [],
            budget,
        )

    @staticmethod
    def tool_contents(result):
        return [message["content"] for message in result.messages if message.get("role") == "tool"]

    def test_ample_budget_retains_all_recent_observations_in_full(self):
        older = "OLDER-BEGIN\n" + ("a" * 3_000) + "\nOLDER-END"
        newest = "NEWEST-BEGIN\n" + ("b" * 3_000) + "\nNEWEST-END"
        self.exchange(1, older)
        self.exchange(2, newest)

        result = self.build(20_000)

        self.assertFalse(result.over_budget)
        self.assertEqual(result.manifest.policy_version, "pressure-recent-v1")
        self.assertEqual(result.manifest.omitted_items, [])
        shown = "\n".join(self.tool_contents(result))
        self.assertIn(older, shown)
        self.assertIn(newest, shown)
        self.assertEqual(result.manifest.request_bytes, len(
            self.runtime.artifacts.read(result.manifest.materialized_request_artifact_id)
        ))

    def test_pressure_omits_older_exchange_but_never_substitutes_it_for_latest(self):
        self.exchange(1, "OLDER-ONLY\n" + ("a" * 3_000))
        self.exchange(2, "LATEST-REQUIRED\n" + ("b" * 3_000), status="error")

        result = self.build(4_300)

        self.assertFalse(result.over_budget)
        shown = "\n".join(self.tool_contents(result))
        self.assertNotIn("OLDER-ONLY", shown)
        self.assertIn("LATEST-REQUIRED", shown)
        self.assertIn("status=error; output=out_2", shown)
        self.assertTrue(any(
            "omitted earlier transcript exchanges" in (message.get("content") or "")
            for message in result.messages
        ))
        self.assertEqual([item["unit_index"] for item in result.manifest.omitted_items], [0])

    def test_oversized_latest_exchange_gets_a_retrievable_view(self):
        self.exchange(1, "LATEST-BEGIN\n" + ("line of evidence\n" * 2_000) + "LATEST-END")

        result = self.build(3_000)

        self.assertFalse(result.over_budget)
        self.assertLessEqual(result.manifest.request_bytes, 3_000)
        shown = self.tool_contents(result)[0]
        self.assertIn("status=success; output=out_1", shown)
        self.assertIn('read_output(id="out_1"', shown)
        tool_item = next(item for item in result.manifest.selected_items if item.get("role") == "tool")
        self.assertNotEqual(tool_item["rendering"], "full")

    def test_no_tool_call_prompt_after_latest_exchange_survives_pressure(self):
        # Dropping the reply and prompt would re-send the previous turn and invite a loop.
        self.exchange(1, "line\n" * 4_000)
        self.transcript.append({"role": "assistant", "content": "I believe the task is complete."})
        self.transcript.append({"role": "user", "content": NO_TOOL_CALL_PROMPT})

        result = self.build(5_000)

        self.assertFalse(result.over_budget)
        self.assertEqual(result.messages[-1]["content"], NO_TOOL_CALL_PROMPT)
        self.assertEqual(result.messages[-2]["content"], "I believe the task is complete.")
        self.assertIn('read_output(id="out_1"', self.tool_contents(result)[0])
        self.assertEqual(result.manifest.omitted_items, [])

    def test_later_user_correction_survives_pressure(self):
        self.exchange(1, "line\n" * 4_000)
        self.transcript.append({"role": "user", "content": "CORRECTION: target the v2 API, not v1."})

        result = self.build(5_000)

        self.assertFalse(result.over_budget)
        self.assertEqual(result.messages[-1]["content"], "CORRECTION: target the v2 API, not v1.")

    def test_omission_keeps_a_contiguous_recent_history(self):
        self.exchange(1, "OLD-SMALL")
        self.transcript.append({"role": "assistant", "content": "PLAN " + ("p" * 3_000)})
        self.exchange(2, "LATEST")

        result = self.build(2_500)

        self.assertFalse(result.over_budget)
        shown = "\n".join(str(message.get("content")) for message in result.messages)
        self.assertIn("LATEST", shown)
        self.assertNotIn("PLAN", shown)
        self.assertNotIn("OLD-SMALL", shown)
        self.assertEqual([item["unit_index"] for item in result.manifest.omitted_items], [0, 1])

    def test_multi_tool_latest_exchange_keeps_every_result_paired(self):
        calls = []
        for index in (1, 2):
            calls.append({
                "id": f"multi-{index}",
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{index}.txt"})},
            })
        self.transcript.append({"role": "assistant", "content": None, "tool_calls": calls})
        for index in (1, 2):
            self.transcript.append({
                "role": "tool",
                "tool_call_id": f"multi-{index}",
                "content": (f"RESULT-{index}\n" + ("evidence\n" * 500)),
                "_reticle_output": {
                    "handle": f"out_{index}",
                    "tool": "read_file",
                    "status": "success",
                },
            })

        result = self.build(2_500)

        self.assertFalse(result.over_budget)
        calls_shown = next(message for message in result.messages if message.get("tool_calls"))
        results_shown = [message for message in result.messages if message.get("role") == "tool"]
        self.assertEqual(len(calls_shown["tool_calls"]), 2)
        self.assertEqual([message["tool_call_id"] for message in results_shown], ["multi-1", "multi-2"])
        self.assertTrue(all("read_output" in message["content"] for message in results_shown))

    def test_utf8_long_line_uses_valid_exact_byte_retrieval_view(self):
        self.exchange(1, "é" * 10_000)

        result = self.build(2_500)

        self.assertFalse(result.over_budget)
        shown = self.tool_contents(result)[0]
        self.assertIn('read_output(id="out_1", start_byte=', shown)
        artifact = self.runtime.artifacts.read(result.manifest.materialized_request_artifact_id)
        self.assertEqual(json.loads(artifact.decode("utf-8"))["messages"], result.messages)

    def test_huge_latest_arguments_stop_instead_of_dropping_the_exchange(self):
        self.transcript.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "huge-args",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "x.txt", "content": "x" * 10_000}),
                },
            }],
        })
        self.transcript.append({
            "role": "tool",
            "tool_call_id": "huge-args",
            "content": "success",
            "_reticle_output": {"handle": "out_1", "tool": "write_file", "status": "success"},
        })

        result = self.build(2_000)

        self.assertTrue(result.over_budget)
        self.assertTrue(any(message.get("tool_call_id") == "huge-args" for message in result.messages))

    def test_pin_cannot_displace_the_latest_exchange(self):
        note = self.runtime.scratch.write("large-pin", "P" * 10_000)
        self.runtime.scratch.pin("large-pin", priority=100)
        self.exchange(1, "LATEST-MUST-STAY\n" + ("z" * 1_000))

        result = self.build(2_000)

        self.assertFalse(result.over_budget)
        self.assertIn("LATEST-MUST-STAY", "\n".join(self.tool_contents(result)))
        self.assertEqual(result.manifest.pin_overflow[0]["artifact_id"], note.artifact.artifact_id)
        self.assertEqual(result.manifest.pin_overflow[0]["delivered_bytes"], 0)

    def test_named_legacy_policy_keeps_its_preview_semantics(self):
        self.exchange(1, "old\n" + ("x" * 2_000))
        self.exchange(2, "new\n" + ("y" * 6_000))

        result = BaselineContextPolicy().build(
            self.runtime, self.task, self.transcript.load(), [], 20_000
        )

        self.assertEqual(result.manifest.policy_version, "bounded-recent-v2")
        contents = self.tool_contents(result)
        self.assertLessEqual(len(contents[0].encode("utf-8")), 512)
        self.assertLessEqual(len(contents[1].encode("utf-8")), 4_000)

    def test_controller_stops_before_provider_when_minimum_request_cannot_fit(self):
        model = NeverCalledModel()
        tools = ToolSuite(self.runtime, interpreter=sys.executable)
        result = AgentController(
            self.runtime,
            self.task,
            tools,
            model,
            AgentLimits(max_model_calls=2, max_context_bytes=100),
            policy=self.policy,
        ).run()

        self.assertEqual(result.stop_reason, "context_budget_exhausted")
        self.assertEqual(result.model_calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertIn("context_budget_exhausted", {event.kind for event in self.runtime.journal.read_all()})


if __name__ == "__main__":
    unittest.main()
