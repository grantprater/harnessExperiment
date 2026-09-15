"""Reticle-style board policy: bounded recent exchanges plus a journal-derived board."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

from reticle.context import TranscriptStore
from reticle.context.board import ReticleBoardPolicy
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.tools import ToolSuite


class BoardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        self.runtime = LocalRuntime(root / "session", self.workspace)
        self.tools = ToolSuite(self.runtime, interpreter=sys.executable)
        self.transcript = TranscriptStore(self.runtime)
        self.task = TaskEnvelope("calc-add", "Original task: make calc.add return the sum.")

    def tearDown(self):
        self.temp_dir.cleanup()

    def exchange(self, call_id, name, arguments):
        self.transcript.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]})
        outcome = self.tools.dispatch(name, arguments, call_id)
        self.transcript.append({"role": "tool", "tool_call_id": call_id, "content": outcome.content})
        return outcome

    def test_board_reports_failures_edits_and_notes_with_bounded_history(self):
        failed = self.exchange("c1", "run", {"command": 'python -c "import calc; assert calc.add(2, 3) == 5"'})
        self.assertEqual(failed.status, "error")
        self.exchange("c2", "replace_text", {"path": "calc.py", "old_text": "nope", "new_text": "x"})
        self.exchange("c3", "replace_text", {"path": "calc.py", "old_text": "a - b", "new_text": "a + b"})
        self.exchange("c4", "note", {"name": "plan", "content": "rerun the check"})

        policy = ReticleBoardPolicy(recent_units=1)
        built = policy.build(self.runtime, self.task, self.transcript.load(), self.tools.schemas(), 60_000)

        roles = [m["role"] for m in built.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "user"])
        self.assertEqual(built.messages[1]["content"], self.task.description)
        self.assertEqual(built.messages[2]["tool_calls"][0]["id"], "c4")
        board = built.messages[-1]["content"]
        self.assertIn("Earlier exchanges not shown here: 3", board)
        self.assertIn("Files modified so far: calc.py", board)
        self.assertIn("Saved notes: plan", board)
        self.assertIn("Unsuccessful actions (2 total", board)
        self.assertIn("run {\"command\":", board)
        self.assertIn("exit code 1; workspace changed since", board)
        self.assertIn("replace_text", board)
        self.assertIn("old_text was not found", board)
        self.assertNotIn("Do not", board)
        self.assertEqual(built.manifest.policy_version, "reticle-board-v2")

    def test_board_without_history_still_carries_task(self):
        built = ReticleBoardPolicy().build(self.runtime, self.task, [], self.tools.schemas(), 60_000)
        self.assertEqual([m["role"] for m in built.messages], ["system", "user", "user"])
        self.assertIn("Unsuccessful actions: none.", built.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
