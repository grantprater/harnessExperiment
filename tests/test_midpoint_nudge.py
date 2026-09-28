"""Midpoint nudge (S6 agent-loop treatment, --nudge midpoint): one harness message when half the response budget
is spent without a source edit, journaled and named in the context manifest (stub client; no model, no API)."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from reticle.context import PressureRecentContextPolicyV3
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.runtime.nudges import MidpointNudge
from reticle.runtime.source_edits import SourceEditTracker
from reticle.tools import ToolSuite

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402

NUDGE = ("Half of the response budget is spent and no source file has been edited. State the single most likely "
         "cause and edit it now; verify after.")
CORE = "def sign(x):\n    if x <= 0:\n        return -1\n    return 1\n"


def read(index):
    return {"id": f"r{index}", "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": "pkg/core.py", "start_line": 1, "end_line": index})}}


def edit(index):
    return {"id": f"e{index}", "type": "function", "function": {"name": "replace_text", "arguments": json.dumps(
        {"path": "pkg/core.py", "old_text": "x <= 0", "new_text": "x < 0"})}}


class Script:
    """Response i (1-based) is make(i): a tool call, or None for a reply without one."""

    def __init__(self, make):
        self.make, self.requests = make, []

    def complete(self, messages, tools):
        self.requests.append(messages)
        call = self.make(len(self.requests))
        message = {"role": "assistant", "content": None if call else "thinking", "tool_calls": [call] if call else []}
        return ModelResponse(message)


class NudgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_script(self, make, name="run", nudge=True, fraction=0.5, limit=10):
        workspace = self.root / name / "workspace"
        (workspace / "pkg").mkdir(parents=True)
        (workspace / "pkg" / "core.py").write_text(CORE, encoding="utf-8")
        runtime = LocalRuntime(self.root / name / "session", workspace)
        state = MidpointNudge(SourceEditTracker(runtime.workspace), fraction) if nudge else None
        client = Script(make)
        task = TaskEnvelope("nudge-task", "Fix sign.", budgets={"model_responses": limit})
        result = AgentController(runtime, task, ToolSuite(runtime, interpreter=sys.executable), client,
                                 AgentLimits(limit, 200_000), policy=PressureRecentContextPolicyV3(),
                                 interventions=[state] if state else ()).run()
        return runtime, client, result, state

    @staticmethod
    def events(runtime, kind):
        return [event.payload for event in runtime.journal.read_all() if event.kind == kind]

    @staticmethod
    def carries(request, text):
        return any(message.get("content") == text for message in request)


class NudgeTests(NudgeTestCase):
    def test_fires_exactly_once_after_half_the_responses(self):
        runtime, client, result, state = self.run_script(read)
        self.assertEqual((result.stop_reason, result.model_calls), ("model_call_limit", 10))
        first = [index for index, request in enumerate(client.requests) if self.carries(request, NUDGE)]
        self.assertEqual(first[0], 5)  # the 6th request, after 5 of 10 responses
        self.assertEqual(client.requests[5][-1], {"role": "system", "content": NUDGE})
        self.assertEqual(client.requests[5][-2]["role"], "tool")  # after the latest tool results
        [event] = self.events(runtime, "harness_message")
        self.assertEqual((event["name"], event["version"], event["content"], event["after_response"],
                          event["response_limit"]), ("midpoint", "midpoint-nudge-v1", NUDGE, 5, 10))
        transcript = [m for m in self.events(runtime, "transcript_message") if m["role"] == "system"]
        self.assertEqual([m["artifact_id"] for m in transcript], [event["transcript_artifact_id"]])
        self.assertEqual(state.record()["after_response"], 5)
        manifests = [e["manifest"] for e in self.events(runtime, "context_manifest")]
        marked = [[item for item in manifest["selected_items"] if "harness_message" in item] for manifest in manifests]
        self.assertEqual([len(items) for items in marked[:5]], [0] * 5)
        self.assertEqual(marked[5], [{"kind": "transcript", "role": "system", "rendering": "full",
                                       "artifact_id": event["transcript_artifact_id"],
                                       "harness_message": {"name": "midpoint", "version": "midpoint-nudge-v1"}}])
        # A later nudge object on the same session (a resumed invocation) does not repeat it.
        again = MidpointNudge(SourceEditTracker(runtime.workspace))
        self.assertIsNone(again.message_after_response(runtime, 7, 10))

    def test_does_not_fire_if_an_edit_already_happened(self):
        runtime, client, _, state = self.run_script(lambda i: edit(i) if i == 3 else read(i))
        self.assertEqual(self.events(runtime, "harness_message"), [])
        self.assertFalse(any(self.carries(request, NUDGE) for request in client.requests))
        self.assertEqual(state.record()["fired"], False)
        self.assertEqual(state.record()["edit_seen_after_response"], 3)

    def test_does_not_fire_without_the_treatment_and_leaves_requests_unchanged(self):
        runtime, plain, _, _ = self.run_script(read, name="plain", nudge=False)
        self.assertEqual(self.events(runtime, "harness_message"), [])
        self.assertFalse(any(self.carries(request, NUDGE) for request in plain.requests))
        # A nudge that never fires (an edit came first) leaves every request byte-identical to the untreated run.
        make = lambda i: edit(i) if i == 2 else read(i)  # noqa: E731
        _, untreated, _, _ = self.run_script(make, name="untreated", nudge=False)
        _, treated, _, _ = self.run_script(make, name="treated", nudge=True)
        self.assertEqual(json.dumps(untreated.requests), json.dumps(treated.requests))

    def test_fraction_is_a_parameter_and_a_reply_without_tool_calls_still_gets_it(self):
        runtime, client, _, _ = self.run_script(lambda i: None if i == 3 else read(i), fraction=0.25, limit=12)
        [event] = self.events(runtime, "harness_message")
        self.assertEqual(event["after_response"], 3)
        self.assertTrue(event["content"].startswith("25% of the response budget is spent"))
        self.assertEqual(client.requests[3][-1]["content"], event["content"])
        self.assertEqual(client.requests[3][-2]["role"], "user")  # the no-tool-call prompt comes first

    def test_an_edit_made_by_a_run_command_prevents_it(self):
        script = "from pathlib import Path; p = Path('pkg/core.py'); p.write_text(p.read_text().replace('<=', '<'))"
        run = {"id": "x", "type": "function", "function": {"name": "run", "arguments": json.dumps(
            {"command": f"python -c \"{script}\""})}}
        runtime, _, _, state = self.run_script(lambda i: run if i == 1 else read(i))
        self.assertEqual(self.events(runtime, "harness_message"), [])
        self.assertEqual(state.record()["edit_seen_after_response"], 1)


class RunnerWiringTests(unittest.TestCase):
    def test_flags_enter_the_hash_only_when_on(self):
        execution, guards = {"backend": "trusted-local"}, {"stop_on_repeats": False}
        off = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards)
        record = run_pilot.treatments_from_args(["--nudge", "midpoint"])
        self.assertEqual(record["nudge"]["text"], NUDGE)
        self.assertEqual((record["nudge"]["fraction"], record["nudge"]["version"]), (0.5, "midpoint-nudge-v1"))
        half = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), record)
        other = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (),
                                        run_pilot.treatments_from_args(["--nudge", "midpoint", "--nudge-fraction", "0.4"]))
        self.assertEqual(len({off, half, other}), 3)
        for bad in (["--nudge-fraction", "0.5"], ["--nudge", "midpoint", "--nudge-fraction", "1.5"]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                run_pilot.treatments_from_args(bad)

    def test_interventions_only_when_on(self):
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            runtime = LocalRuntime(Path(name) / "session", workspace)
            state = {}
            self.assertEqual(run_pilot.build_interventions(runtime, {}, state), [])
            self.assertEqual(state, {})
            treatments = run_pilot.treatments_from_args(["--nudge", "midpoint", "--nudge-fraction", "0.3"])
            [nudge] = run_pilot.build_interventions(runtime, treatments, state)
            self.assertIs(state["nudge"], nudge)
            self.assertEqual(nudge.fraction, 0.3)


if __name__ == "__main__":
    unittest.main()
