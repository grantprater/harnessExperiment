"""P3 acceptance tests for scratch, observations, and bounded context."""

from pathlib import Path
import json
import tempfile
import unittest

from reticle.context import BaselineContextPolicy, ContextBuilder, TranscriptStore
from reticle.runtime import LocalRuntime, ObservationService
from reticle.runtime.contracts import TaskEnvelope


class P3RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.session = self.root / "session"
        self.workspace.mkdir()
        (self.workspace / "sample.py").write_text(
            "# heading\n\nclass Example:\n    def alpha(self):\n        return 'needle'\n",
            encoding="utf-8",
        )
        self.runtime = LocalRuntime(self.session, self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_arbitrary_scratch_discovery_pins_and_forget_preserve_history(self):
        first = self.runtime.scratch.write(
            "work/unfinished", b"plan\x00step two", expected_version=0, labels=["plan"]
        )
        self.assertEqual(first.reference.version, 1)
        self.assertEqual(self.runtime.scratch.read("work/unfinished").content, b"plan\x00step two")
        self.assertEqual(self.runtime.scratch.read("work/unfinished", 5, 9).content, b"step")
        self.assertEqual(
            [item.name for item in self.runtime.scratch.list("work/", labels=["plan"])],
            ["work/unfinished"],
        )
        hit = self.runtime.scratch.search("step", scope="work/")[0]
        self.assertEqual(hit.byte_offset, 5)

        self.runtime.scratch.pin("work/unfinished", priority=7)
        self.assertEqual(self.runtime.scratch.pins()["work/unfinished"]["priority"], 7)
        self.assertTrue(self.runtime.scratch.unpin("work/unfinished"))
        self.assertFalse(self.runtime.scratch.unpin("work/unfinished"))
        self.runtime.scratch.pin("work/unfinished", priority=7)
        forgotten = self.runtime.scratch.forget("work/unfinished", expected_version=1)
        self.assertFalse(self.runtime.scratch.pins())
        with self.assertRaises(KeyError):
            self.runtime.scratch.read("work/unfinished")
        self.assertEqual(
            self.runtime.artifacts.read(forgotten.artifact_id), b"plan\x00step two"
        )

    def test_shared_observation_modes_and_truthful_large_preview(self):
        service = ObservationService(self.runtime)
        full = service.observe("sample.py", "full")
        region = service.observe("sample.py", "region", start_line=3, end_line=4)
        outline = service.observe("sample.py", "outline")
        search = service.observe("sample.py", "search", query="needle")
        self.assertTrue(full.exact)
        self.assertEqual(self.runtime.artifacts.read(full.view_artifact.artifact_id), full.content)
        self.assertIn(b"class Example", region.content)
        self.assertIn(b"function alpha", outline.content)
        self.assertIn(b"L5", search.content)

        (self.workspace / "large.txt").write_bytes(b"x" * 2_500)
        large = service.observe("large.txt")
        preview = large.preview(100)
        self.assertIn("2400 bytes omitted", preview)
        self.assertIn(large.view_artifact.artifact_id, preview)
        self.assertEqual(self.runtime.artifacts.read(large.view_artifact.artifact_id), b"x" * 2_500)

    def test_restart_small_context_recovers_plan_exact_output_and_tool_pair(self):
        task = TaskEnvelope(
            task_id="multi-step",
            description="Original task: finish the multi-step repair",
            authority={"filesystem": "workspace"},
            budgets={"context_bytes": 1_900},
        )
        plan = self.runtime.scratch.write("plan/current", "unfinished: inspect then repair")
        self.runtime.scratch.pin("plan/current", priority=10)
        transcript = TranscriptStore(self.runtime)
        transcript.append({"role": "user", "content": "inspect it"})
        transcript.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }],
        })
        exact_output = "BEGIN-EVIDENCE\n" + ("evidence-line\n" * 200) + "END-EVIDENCE"
        transcript.append({"role": "tool", "tool_call_id": "call-1", "content": exact_output})
        transcript.append({"role": "assistant", "content": "I will resume after restart."})

        resumed = LocalRuntime(self.session)
        loaded = TranscriptStore(resumed).load()
        result = BaselineContextPolicy(tool_preview_bytes=120).build(
            resumed,
            task,
            loaded,
            tools=[{"type": "function", "function": {"name": "read"}}],
            max_context_bytes=1_900,
        )
        self.assertFalse(result.over_budget)
        self.assertTrue(any(message.get("content") == task.description for message in result.messages))
        self.assertTrue(any("unfinished: inspect then repair" in message.get("content", "") for message in result.messages))
        assistant_calls = [message for message in result.messages if message.get("tool_calls")]
        tool_results = [message for message in result.messages if message.get("role") == "tool"]
        self.assertTrue(assistant_calls)
        self.assertTrue(tool_results)
        self.assertEqual(tool_results[0]["tool_call_id"], assistant_calls[0]["tool_calls"][0]["id"])
        self.assertIn("exact observation: art_", tool_results[0]["content"])
        spill = next(
            item for item in result.manifest.selected_items
            if item.get("rendering") == "truthful-preview"
        )
        self.assertEqual(
            resumed.artifacts.read(spill["artifact_id"]).decode("utf-8"), exact_output
        )

        request = json.loads(
            resumed.artifacts.read(result.manifest.materialized_request_artifact_id)
        )
        self.assertEqual(request, {"messages": result.messages, "tools": result.tools})
        transcript_items = [
            item for item in result.manifest.selected_items if item["kind"] == "transcript"
        ]
        self.assertTrue(all(item["artifact_id"].startswith("art_") for item in transcript_items))
        self.assertEqual(
            resumed.artifacts.get_envelope(result.manifest.materialized_request_artifact_id).content_hash,
            result.manifest.materialized_request_hash,
        )
        self.assertEqual(resumed.artifacts.read(plan.artifact.artifact_id).decode(), "unfinished: inspect then repair")

    def test_pin_overflow_is_explicit_under_forced_small_context(self):
        task = TaskEnvelope(task_id="tiny", description="Do not lose this original task")
        note = self.runtime.scratch.write("huge-pin", "P" * 4_000)
        self.runtime.scratch.pin("huge-pin", priority=100)
        result = BaselineContextPolicy(pin_preview_bytes=80).build(
            self.runtime, task, [], [], max_context_bytes=500
        )
        self.assertFalse(result.over_budget)
        self.assertTrue(result.manifest.pin_overflow)
        overflow = result.manifest.pin_overflow[0]
        self.assertEqual(overflow["artifact_id"], note.artifact.artifact_id)
        self.assertLess(overflow["delivered_bytes"], overflow["requested_bytes"])
        self.assertTrue(any("PIN OVERFLOW" in message["content"] for message in result.messages))
        self.assertTrue(any(message.get("content") == task.description for message in result.messages))
        self.assertEqual(self.runtime.artifacts.read(note.artifact.artifact_id), b"P" * 4_000)

    def test_failed_policy_uses_visible_baseline_fallback(self):
        class BrokenPolicy:
            policy_version = "broken-v1"

            def build(self, *args, **kwargs):
                raise RuntimeError("selection exploded")

        result = ContextBuilder(BrokenPolicy()).build(
            self.runtime,
            TaskEnvelope(task_id="fallback", description="survive policy failure"),
            [],
            [],
            800,
        )
        self.assertEqual(result.manifest.policy_version, "bounded-recent-v2")
        self.assertIn("selection exploded", result.manifest.diagnostics[0])
        self.assertIn("selection exploded", result.messages[0]["content"])
        self.assertTrue(any(message.get("content") == "survive policy failure" for message in result.messages))


if __name__ == "__main__":
    unittest.main()
