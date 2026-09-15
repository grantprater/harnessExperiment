"""Bounded tool-output views with exact, discoverable retrieval (read_output / search_output)."""

from pathlib import Path
import json
import re
import sys
import tempfile
import unittest

from reticle.context import BaselineContextPolicy, TranscriptStore
from reticle.context.baseline import render_output_view
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.tools import ToolSuite

NOTE = re.compile(r'read_output\(id="(out_\d+)", start_line=(\d+), end_line=(\d+)\)')


def tool_messages(messages):
    return [m for m in messages if m.get("role") == "tool"]


class OutputPagingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "big.py").write_text("".join(f"line_{i} = {i}\n" for i in range(1, 1262)), encoding="utf-8")
        self.runtime = LocalRuntime(root / "session", self.workspace)
        self.tools = ToolSuite(self.runtime, interpreter=sys.executable)
        self.transcript = TranscriptStore(self.runtime)
        self.task = TaskEnvelope("paging", "Original task: inspect big.py.")
        self.policy = BaselineContextPolicy()

    def tearDown(self):
        self.temp_dir.cleanup()

    def exchange(self, call_id, name, arguments):
        self.transcript.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]})
        outcome = self.tools.dispatch(name, arguments, call_id)
        self.transcript.append({"role": "tool", "tool_call_id": call_id, "content": outcome.content,
                                "_reticle_output": {"handle": outcome.handle, "tool": name}})
        return outcome

    def build(self):
        return self.policy.build(self.runtime, self.task, self.transcript.load(), self.tools.schemas(), 200_000)

    def test_newest_large_read_is_bounded_and_names_the_exact_next_page(self):
        outcome = self.exchange("c1", "read_file", {"path": "big.py"})
        full_lines = outcome.content.splitlines()
        shown = tool_messages(self.build().messages)[-1]["content"]

        self.assertLessEqual(len(shown.encode("utf-8")), 4_000)
        self.assertNotIn("_reticle_output", json.dumps(self.build().messages))
        self.assertIn(f"[output {outcome.handle}: showing lines 1-", shown)
        self.assertIn(f"of {len(full_lines)}", shown)
        handle, start, end = NOTE.search(shown).groups()
        page = self.tools.dispatch("read_output", {"id": handle, "start_line": int(start), "end_line": int(end)}, "p1")
        self.assertEqual(page.content.splitlines()[1:], full_lines[int(start) - 1:int(end)])
        # The page continues exactly where the view stopped.
        last_shown = shown.split("\n[output")[0].splitlines()[-1]
        self.assertEqual(full_lines.index(last_shown) + 2, int(start))

    def test_older_results_shrink_but_stay_recoverable(self):
        first = self.exchange("c1", "read_file", {"path": "big.py", "start_line": 1, "end_line": 300})
        self.exchange("c2", "read_file", {"path": "big.py", "start_line": 301, "end_line": 600})
        older, newest = [m["content"] for m in tool_messages(self.build().messages)]
        self.assertLessEqual(len(older.encode("utf-8")), 512)
        self.assertGreater(len(newest.encode("utf-8")), 2_000)
        self.assertIn(f'read_output(id="{first.handle}"', older)
        found = self.tools.dispatch("search_output", {"id": first.handle, "query": "line_250 ="}, "s1")
        self.assertIn("line_250 = 250", found.content)

    def test_command_output_keeps_the_end(self):
        script = "for i in range(2000): print('progress', i)\nprint('SUMMARY: 3 failed, 12 passed')"
        (self.workspace / "noisy.py").write_text(script, encoding="utf-8")
        outcome = self.exchange("c1", "run", {"command": "python noisy.py"})
        shown = tool_messages(self.build().messages)[-1]["content"]
        self.assertIn("SUMMARY: 3 failed, 12 passed", shown)
        self.assertIn("$ python noisy.py", shown)
        self.assertRegex(shown, r"\[\.\.\. lines \d+-\d+ omitted \.\.\.\]")
        handle, start, end = NOTE.search(shown).groups()
        self.assertEqual(handle, outcome.handle)
        page = self.tools.dispatch("read_output", {"id": handle, "start_line": int(start), "end_line": int(end)}, "p1")
        self.assertIn("progress", page.content)

    def test_long_single_line_uses_byte_ranges(self):
        text = "x" * 10_000
        view, rendering = render_output_view(text, "out_9", 4_000, tail_heavy=False)
        self.assertEqual(rendering["rendering"], "byte-prefix")
        match = re.search(r'read_output\(id="out_9", start_byte=(\d+), end_byte=(\d+)\)', view)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), rendering["shown_bytes"][1])

    def test_unknown_output_id_is_rejected(self):
        missing = self.tools.dispatch("read_output", {"id": "out_999"}, "m1")
        self.assertEqual(missing.status, "rejected")
        self.assertIn("unknown output id 'out_999'", missing.content)

    def test_controller_paging_round_trip_with_a_scripted_model(self):
        class PagingModel:
            def __init__(self):
                self.requests = []

            def complete(self, messages, tools):
                self.requests.append(messages)
                step = len(self.requests)
                if step == 1:
                    call = ("read_file", {"path": "big.py"})
                elif step == 2:
                    handle, start, end = NOTE.search(tool_messages(messages)[-1]["content"]).groups()
                    call = ("read_output", {"id": handle, "start_line": int(start), "end_line": int(end)})
                else:
                    call = ("finish", {"summary": "paged"})
                return ModelResponse({"role": "assistant", "content": None, "tool_calls": [
                    {"id": f"c{step}", "type": "function", "function": {"name": call[0], "arguments": json.dumps(call[1])}}]})

        model = PagingModel()
        result = AgentController(self.runtime, self.task, self.tools, model, AgentLimits(5, 200_000)).run()
        self.assertEqual(result.stop_reason, "finish_requested")
        third = tool_messages(model.requests[2])[-1]["content"]
        self.assertRegex(third, r"^out_1 lines \d+-\d+ of 1262:\n")
        self.assertIn("line_", third)


if __name__ == "__main__":
    unittest.main()
