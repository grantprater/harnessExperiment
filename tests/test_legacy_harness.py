"""Regression tests for the legacy phased harness completion contract."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from harness import CognitiveHarness, Environment


class ScriptedClient:
    mock_mode = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_completion(self, messages, tools):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def tool_call(name, arguments, call_id):
    return {
        "id": call_id,
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class LegacyHarnessCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "calc.py").write_text(
            "def value():\n    return 0\n", encoding="utf-8"
        )
        (self.root / "check.py").write_text(
            "from calc import value\nassert value() == 1\n", encoding="utf-8"
        )
        self.verify_cmd = f'"{sys.executable}" -B check.py'

    def tearDown(self):
        self.temp_dir.cleanup()

    def fixing_response(self):
        return {
            "content": "Fix value.",
            "tool_calls": [
                tool_call(
                    "replace_lines",
                    {
                        "file_path": "calc.py",
                        "start_line": 2,
                        "end_line": 2,
                        "new_content": "    return 1",
                    },
                    "fix",
                ),
                tool_call("run_command", {"cmd": self.verify_cmd}, "verify"),
            ],
        }

    def test_editorial_pass_is_disabled_by_default(self):
        client = ScriptedClient([self.fixing_response()])
        trace = CognitiveHarness(Environment(self.root), client=client).run(
            task="Fix value", verify_cmd=self.verify_cmd, target_file="calc.py"
        )

        self.assertTrue(trace.success)
        self.assertFalse(trace.phase2_executed)
        self.assertEqual(client.calls, 1)

    def test_failed_editorial_edit_is_restored_and_reported(self):
        breaking_editorial_response = {
            "content": "Change the implementation.",
            "tool_calls": [
                tool_call(
                    "replace_lines",
                    {
                        "file_path": "calc.py",
                        "start_line": 2,
                        "end_line": 2,
                        "new_content": "    return 2",
                    },
                    "break",
                )
            ],
        }
        client = ScriptedClient([self.fixing_response(), breaking_editorial_response])
        trace = CognitiveHarness(Environment(self.root), client=client).run(
            task="Fix value",
            verify_cmd=self.verify_cmd,
            target_file="calc.py",
            editorial_pass=True,
        )

        self.assertTrue(trace.success)
        self.assertTrue(trace.phase2_executed)
        self.assertFalse(trace.phase2_succeeded)
        self.assertTrue(trace.rollback_succeeded)
        self.assertIn("return 1", (self.root / "calc.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
