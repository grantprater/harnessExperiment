"""native_control: transcript summary, audit flags, and the base-commit diff (no CLI call)."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import native_control  # noqa: E402


def assistant(message_id, *blocks):
    return {"type": "assistant", "message": {"id": message_id, "content": list(blocks)}}


def use(use_id, name, **inputs):
    return {"type": "tool_use", "id": use_id, "name": name, "input": inputs}


def result(use_id, is_error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": use_id, "is_error": is_error}]}}


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "pkg").mkdir(parents=True)
        (self.workspace / "pkg" / "mod.py").write_bytes(b"x = 1\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_summary_counts_responses_first_actions_and_audit_flags(self):
        stream = [
            {"type": "system", "subtype": "init", "tools": ["Bash", "Read"], "model": "m", "apiKeySource": "none"},
            assistant("m1", {"type": "thinking", "thinking": ""}),
            assistant("m1", use("u1", "Read", file_path=str(self.workspace / "pkg" / "mod.py"))),
            result("u1"),
            assistant("m2", use("u2", "Bash", command="python -m pytest tests -q"),
                      use("u3", "Bash", command="curl https://example.com/fix.patch")),
            result("u2"), result("u3"),
            assistant("m3", use("u4", "Edit", file_path="pkg/mod.py", old_string="1", new_string="2"),
                      use("u5", "Read", file_path="C:/elsewhere/secret.py")),
            result("u4"), result("u5", is_error=True),
            {"type": "result", "subtype": "success", "num_turns": 4, "is_error": False},
        ]
        events = [{"t": float(i), "event": e} for i, e in enumerate(stream)]
        summary = native_control.summarize_stream(events, self.workspace, {"pkg/mod.py"})
        self.assertEqual(summary["responses"], 3)
        self.assertEqual(summary["tool_calls"], 5)
        self.assertEqual(summary["first_command"]["response"], 2)
        self.assertEqual(summary["first_base_file_edit"]["response"], 3)
        self.assertEqual(summary["edited_files"], ["pkg/mod.py"])
        self.assertEqual(summary["test_commands"], 1)
        self.assertEqual(summary["tool_errors"], 1)
        self.assertEqual(len(summary["audit"]["network_commands"]), 1)
        self.assertEqual([o.get("file_path") for o in summary["audit"]["paths_outside_workspace"]],
                         ["C:/elsewhere/secret.py"])
        self.assertEqual(summary["result"]["num_turns"], 4)

    def test_diff_is_taken_against_a_pristine_copy_without_touching_the_workspace(self):
        pristine = self.root / "pristine"
        (pristine / "pkg").mkdir(parents=True)
        (pristine / "pkg" / "mod.py").write_bytes(b"x = 1\n")
        (self.workspace / "pkg" / "mod.py").write_bytes(b"x = 2\n")
        (self.workspace / "pkg" / "__pycache__").mkdir()
        (self.workspace / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"\0")
        (self.workspace / "check.py").write_text("print(1)\n", encoding="utf-8")
        diff = native_control.workspace_diff(pristine, self.workspace)
        self.assertIn("pkg/mod.py", diff["stat"])
        self.assertIn("check.py", diff["stat"])
        self.assertNotIn("pycache", diff["stat"])
        self.assertIn("-x = 1\n+x = 2", diff["patch"])
        self.assertFalse((self.workspace / ".git").exists())


if __name__ == "__main__":
    unittest.main()
