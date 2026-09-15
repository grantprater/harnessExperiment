"""Unit tests for the Stateless Blank-Slate Epistemic Harness.

Verifies:
1. Falsification ledger recording and monotonic pruning.
2. Grounding pointer registration and address resolution.
3. Dynamic tool synthesis (AST validation, schema generation, execution).
4. Blank-slate state board packet rendering.
5. End-to-end goal progression across stateless blank-slate turns.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any, Dict, List

from stateless_harness import (
    BlankSlateHarness,
    DynamicToolRegistry,
    EpistemicNoteBoard,
    FalsificationLedger,
    GroundingLedger,
    StatelessEnvironment,
)


class MockBlankSlateClient:
    """Simulates an LLM agent taking sequential, informed actions using the note board."""

    def __init__(self, steps_script: List[Dict[str, Any]]):
        self.steps_script = steps_script
        self.call_count = 0
        self.observed_prompts: List[str] = []
        self.observed_system_prompts: List[str] = []

    def chat_completion(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.call_count += 1
        # Store user prompt (the state packet)
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        self.observed_prompts.append(user_msg)
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        self.observed_system_prompts.append(system_msg)

        if self.call_count <= len(self.steps_script):
            return self.steps_script[self.call_count - 1]
        return {"content": "No more actions.", "tool_calls": []}


class StatelessHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

        # Create sample file with calculation error
        self.calc_file = self.base_path / "calc.py"
        self.calc_file.write_text(
            "def calculate_discount(price: float, discount_percent: float) -> float:\n"
            "    # Buggy discount calculation\n"
            "    return price - discount_percent\n",
            encoding="utf-8"
        )

        # Create verification test
        self.test_file = self.base_path / "test_calc.py"
        self.test_file.write_text(
            "import sys\n"
            "from calc import calculate_discount\n"
            "assert calculate_discount(100.0, 20.0) == 80.0, 'Failed 20% discount'\n"
            "assert calculate_discount(50.0, 10.0) == 45.0, 'Failed 10% discount'\n"
            "print('ALL PASSED')\n",
            encoding="utf-8"
        )

        self.env = StatelessEnvironment(self.base_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_falsification_ledger(self):
        ledger = FalsificationLedger()
        rec = ledger.record(
            hypothesis="Replace lines with raw integer subtraction",
            action_taken="replace_lines(calc.py, 3, 3, 'return price - 20')",
            rejection_evidence="AssertionError: Failed 10% discount on 50.0",
            step=1
        )
        self.assertEqual(rec.id, "f_01")
        view = ledger.render_view()
        self.assertIn("f_01", view)
        self.assertIn("AssertionError", view)

    def test_grounding_ledger(self):
        ledger = GroundingLedger()
        ptr = ledger.record_pointer(
            target="calc.py",
            locator="L1-L3",
            description="Discount logic"
        )
        self.assertEqual(ptr.id, "ptr_01")
        view = ledger.render_view()
        self.assertIn("calc.py", view)
        self.assertIn("L1-L3", view)
        self.assertFalse(ptr.verified)
        self.assertIn("unvalidated", view)

    def test_dynamic_tool_synthesis_valid(self):
        registry = DynamicToolRegistry()
        code = (
            "def check_discount_formula(price, pct):\n"
            "    return price * (1.0 - pct / 100.0)\n"
        )
        ok, msg = registry.register_tool(
            name="check_discount_formula",
            code=code,
            description="Calculates true percentage discount value.",
            parameters={
                "type": "object",
                "properties": {
                    "price": {"type": "number"},
                    "pct": {"type": "number"}
                },
                "required": ["price", "pct"]
            }
        )
        self.assertTrue(ok, msg)
        self.assertIn("check_discount_formula", registry.tools)

        # Test execution
        res = registry.execute_tool("check_discount_formula", {"price": 100.0, "pct": 20.0})
        self.assertEqual(float(res), 80.0)

        # Test schema generation
        schemas = registry.get_schemas()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["function"]["name"], "check_discount_formula")

    def test_dynamic_tool_synthesis_rejects_syntax_error(self):
        registry = DynamicToolRegistry()
        bad_code = "def broken(\n  return price -"
        ok, msg = registry.register_tool("broken", bad_code, "broken tool")
        self.assertFalse(ok)
        self.assertIn("SyntaxError", msg)

    def test_dynamic_tool_uses_module_namespace_for_helpers_and_imports(self):
        registry = DynamicToolRegistry()
        code = (
            "import math\n"
            "OFFSET = 1\n"
            "def helper(value):\n"
            "    return math.floor(value) + OFFSET\n"
            "def composed(value):\n"
            "    return helper(value) * 2\n"
        )
        ok, msg = registry.register_tool("composed", code, "Uses sibling definitions")
        self.assertTrue(ok, msg)
        self.assertEqual(registry.execute_tool("composed", {"value": 2.8}), "6")

    def test_dispatch_returns_outline_and_command_streams(self):
        harness = BlankSlateHarness(env=self.env)
        board = EpistemicNoteBoard(goal="inspect", invariants=[])

        outline, _ = harness._dispatch_tool(
            "outline", {"file_path": "calc.py"}, board, 1, "unused"
        )
        self.assertIn("calculate_discount", outline)

        command = f'"{sys.executable}" -c "import sys; print(\'visible-out\'); print(\'visible-err\', file=sys.stderr)"'
        result, _ = harness._dispatch_tool(
            "run_command", {"cmd": command}, board, 1, "unused"
        )
        self.assertIn("visible-out", result)
        self.assertIn("visible-err", result)
        self.assertIn("Stdout:", result)
        self.assertIn("Stderr:", result)

        self.env.run_command = lambda cmd: {
            "exit_code": 0,
            "passed": True,
            "stdout": "x" * 9_000,
            "stderr": "",
        }
        truncated, _ = harness._dispatch_tool(
            "run_command", {"cmd": "large-output"}, board, 1, "unused"
        )
        self.assertIn("[truncated: 1000 characters omitted]", truncated)

    def test_edit_marks_pointer_to_prior_revision_stale(self):
        harness = BlankSlateHarness(env=self.env)
        board = EpistemicNoteBoard(goal="edit", invariants=[])
        harness._dispatch_tool(
            "record_grounding_pointer",
            {"target": "calc.py", "locator": "L3", "description": "return"},
            board,
            1,
            "unused",
        )
        pointer = board.grounding.pointers[0]
        self.assertFalse(pointer.stale)

        harness._dispatch_tool(
            "replace_lines",
            {
                "file_path": "calc.py",
                "start_line": 3,
                "end_line": 3,
                "new_content": "    return 0",
            },
            board,
            1,
            "unused",
        )
        self.assertTrue(pointer.stale)
        self.assertFalse(pointer.verified)
        self.assertIn("stale", board.grounding.render_view())

    def test_final_verification_overrides_earlier_pass_in_same_batch(self):
        verify_cmd = f'"{sys.executable}" test_calc.py'
        client = MockBlankSlateClient([
            {
                "content": "Pass first, then mutate.",
                "tool_calls": [
                    {"function": {"name": "replace_lines", "arguments": json.dumps({
                        "file_path": "calc.py", "start_line": 3, "end_line": 3,
                        "new_content": "    return price * (1.0 - discount_percent / 100.0)",
                    })}},
                    {"function": {"name": "run_command", "arguments": json.dumps({"cmd": verify_cmd})}},
                    {"function": {"name": "replace_lines", "arguments": json.dumps({
                        "file_path": "calc.py", "start_line": 3, "end_line": 3,
                        "new_content": "    return 0",
                    })}},
                ],
            }
        ])
        result = BlankSlateHarness(self.env, client=client, max_steps=1).run(
            goal="Keep tests passing", verify_cmd=verify_cmd
        )
        self.assertFalse(result["solved"])
        self.assertFalse(result["final_verification"]["passed"])

    def test_failed_verification_can_be_retried_after_repair(self):
        verify_cmd = f'"{sys.executable}" test_calc.py'
        client = MockBlankSlateClient([
            {
                "content": "Observe failure.",
                "tool_calls": [
                    {"function": {"name": "run_command", "arguments": json.dumps({"cmd": verify_cmd})}},
                ],
            },
            {
                "content": "Repair and retry under changed state.",
                "tool_calls": [
                    {"function": {"name": "replace_lines", "arguments": json.dumps({
                        "file_path": "calc.py", "start_line": 3, "end_line": 3,
                        "new_content": "    return price * (1.0 - discount_percent / 100.0)",
                    })}},
                    {"function": {"name": "run_command", "arguments": json.dumps({"cmd": verify_cmd})}},
                ],
            },
        ])
        result = BlankSlateHarness(self.env, client=client, max_steps=2).run(
            goal="Repair", verify_cmd=verify_cmd
        )
        attempts = [item for item in result["execution_history"] if item["tool"] == "run_command"]
        self.assertEqual(len(attempts), 2)
        self.assertTrue(result["solved"])
        self.assertNotIn("NEVER repeat", client.observed_system_prompts[0])

    def test_epistemic_note_board_stateless_rendering(self):
        board = EpistemicNoteBoard(
            goal="Fix discount formula in calc.py",
            invariants=["test_calc.py exits with code 0"]
        )
        board.falsifications.record(
            hypothesis="Hardcoded discount",
            action_taken="replace_lines",
            rejection_evidence="Failed on variable price",
            step=1
        )
        board.grounding.record_pointer(
            target="calc.py",
            locator="L3",
            description="Return statement for discount"
        )
        packet = board.render_packet()

        self.assertIn("GOAL & INVARIANTS", packet)
        self.assertIn("FALSIFICATION LEDGER", packet)
        self.assertIn("Hardcoded discount", packet)
        self.assertIn("GROUNDING POINTERS", packet)
        self.assertIn("calc.py", packet)

    def test_stateless_harness_goal_progression(self):
        """Tests sequential goal progression where each turn is a blank slate."""

        steps = [
            # Turn 1: Model inspects file using saccade and establishes grounding pointer
            {
                "content": "Inspecting calc.py to pinpoint discount formula.",
                "tool_calls": [
                    {
                        "function": {
                            "name": "saccade",
                            "arguments": json.dumps({"file_path": "calc.py", "start_line": 1, "end_line": 3})
                        }
                    },
                    {
                        "function": {
                            "name": "record_grounding_pointer",
                            "arguments": json.dumps({
                                "target": "calc.py",
                                "locator": "L3",
                                "description": "Defective return line subtracting raw percent"
                            })
                        }
                    }
                ]
            },
            # Turn 2: Model synthesizes a custom verification tool and registers it
            {
                "content": "Synthesizing a deterministic discount oracle tool to verify formulas.",
                "tool_calls": [
                    {
                        "function": {
                            "name": "synthesize_tool",
                            "arguments": json.dumps({
                                "name": "oracle_calc",
                                "code": "def oracle_calc(p, d):\n    return p * (1.0 - d / 100.0)\n",
                                "description": "Verifies percentage discount arithmetic.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "p": {"type": "number"},
                                        "d": {"type": "number"}
                                    },
                                    "required": ["p", "d"]
                                }
                            })
                        }
                    }
                ]
            },
            # Turn 3: Model calls synthesized tool, applies fix to pointed line, verifies
            {
                "content": "Applying verified discount formula to pointed line.",
                "tool_calls": [
                    {
                        "function": {
                            "name": "oracle_calc",
                            "arguments": json.dumps({"p": 50.0, "d": 10.0})
                        }
                    },
                    {
                        "function": {
                            "name": "replace_lines",
                            "arguments": json.dumps({
                                "file_path": "calc.py",
                                "start_line": 3,
                                "end_line": 3,
                                "new_content": "    return price * (1.0 - discount_percent / 100.0)"
                            })
                        }
                    },
                    {
                        "function": {
                            "name": "run_command",
                            "arguments": json.dumps({"cmd": f'"{sys.executable}" test_calc.py'})
                        }
                    }
                ]
            }
        ]

        client = MockBlankSlateClient(steps)
        harness = BlankSlateHarness(env=self.env, client=client, max_steps=5)

        verify_cmd = f'"{sys.executable}" test_calc.py'
        result = harness.run(
            goal="Fix calculate_discount in calc.py so all tests pass",
            verify_cmd=verify_cmd
        )

        self.assertTrue(result["solved"], "Harness failed to solve task")
        self.assertEqual(result["total_steps"], 3)
        self.assertEqual(result["grounding_pointers_count"], 1)
        self.assertEqual(result["synthesized_tools_count"], 1)

        # Verify that prompt in turn 3 contained the grounding pointer and synthesized tool from prior turns!
        turn3_prompt = client.observed_prompts[2]
        self.assertIn("ptr_01", turn3_prompt)
        self.assertIn("calc.py", turn3_prompt)
        self.assertIn("oracle_calc", turn3_prompt)


if __name__ == "__main__":
    unittest.main()
