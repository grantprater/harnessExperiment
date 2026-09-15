"""End-to-end checks of the falsification evaluation loop with a scripted fake model (no API calls)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "run_falsification_eval", ROOT / "experiments" / "falsification_eval" / "run_falsification_eval.py")
runner_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner_module
spec.loader.exec_module(runner_module)

TASK = {
    "slug": "adder",
    "snake_name": "adder",
    "instructions": "Implement add(a, b).",
    "stub": "def add(a, b):\n    pass\n",
    "test_code": (
        "import unittest\n"
        "from adder import add\n\n"
        "class AdderTest(unittest.TestCase):\n"
        "    def test_small(self):\n"
        "        self.assertEqual(add(1, 2), 3)\n\n"
        "    def test_negative(self):\n"
        "        self.assertEqual(add(-1, -2), -3)\n"
    ),
}

CONSTANT = "APPROACH: return a constant\n```python\ndef add(a, b):\n    return 3\n```"
CONSTANT_REFORMATTED = "APPROACH: return a constant again\n```python\ndef add( a, b ):\n    # same idea\n    return (3)\n```"
CORRECT = "APPROACH: sum the arguments\n```python\ndef add(a, b):\n    return a + b\n```"


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, api_key, model, messages, timeout=120):
        self.seen.append([dict(m) for m in messages])
        return self.replies[len(self.seen) - 1], 100, 10, 1


class FalsificationEvalLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)
        self.original_chat = runner_module.chat

    def tearDown(self):
        runner_module.chat = self.original_chat
        self.tmp.cleanup()

    def run_arm(self, arm, replies, max_calls=10, max_turns=4):
        fake = FakeChat(replies)
        runner_module.chat = fake
        runner = runner_module.Runner("key", "fake-model", self.run_dir, max_calls)
        return runner.run_task_arm(TASK, arm, max_turns), fake

    def test_ledger_arm_flags_repeat_and_shows_dead_end(self):
        rec, fake = self.run_arm("ledger", [CONSTANT, CONSTANT_REFORMATTED, CORRECT])
        self.assertTrue(rec["passed"])
        self.assertEqual(rec["turns_used"], 3)
        self.assertIsNone(rec["turns"][0]["repeat_of_turn"])
        self.assertEqual(rec["turns"][1]["repeat_of_turn"], 1)
        self.assertTrue(rec["turns"][1]["same_signature_as_previous"])
        self.assertEqual([t["approach_found"] for t in rec["turns"]], [True, True, True])

        turn3_prompt = fake.seen[2][-1]["content"]
        self.assertIn("## Dead ends so far", turn3_prompt)
        self.assertIn("f_01", turn3_prompt)
        self.assertIn("return a constant", turn3_prompt)
        self.assertIn("identical (ignoring comments and formatting)", turn3_prompt)
        self.assertEqual(len(rec["ledger"]), 1)
        self.assertEqual(rec["ledger"][0]["resolved_turn"], 3)
        self.assertEqual(rec["ledger"][0]["attempts"], 2)
        self.assertEqual(len((self.run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_last_failure_arm_is_blank_slate_without_ledger(self):
        rec, fake = self.run_arm("last_failure", [CONSTANT, CORRECT])
        self.assertTrue(rec["passed"])
        self.assertEqual(len(fake.seen[1]), 2)
        retry = fake.seen[1][-1]["content"]
        self.assertIn("## Latest test result", retry)
        self.assertIn("return 3", retry)
        self.assertNotIn("Dead ends", retry)

    def test_transcript_arm_grows_the_conversation(self):
        rec, fake = self.run_arm("transcript", [CONSTANT, CONSTANT, CORRECT])
        self.assertTrue(rec["passed"])
        self.assertEqual([len(m) for m in fake.seen], [2, 4, 6])
        self.assertEqual(fake.seen[2][2]["role"], "assistant")

    def test_failing_arm_uses_all_turns(self):
        rec, _ = self.run_arm("ledger", [CONSTANT] * 3, max_turns=3)
        self.assertFalse(rec["passed"])
        self.assertEqual(rec["turns_used"], 3)
        self.assertEqual(rec["turns"][-1]["failing"], 1)

    def test_call_cap_stops_the_loop(self):
        with self.assertRaises(runner_module.BudgetExceeded):
            self.run_arm("ledger", [CONSTANT] * 4, max_calls=2)

    def test_exact_mcnemar(self):
        self.assertEqual(runner_module.exact_mcnemar(0, 0), 1.0)
        self.assertAlmostEqual(runner_module.exact_mcnemar(6, 0), 0.03125)
        self.assertAlmostEqual(runner_module.exact_mcnemar(3, 1), 0.625)


if __name__ == "__main__":
    unittest.main()
