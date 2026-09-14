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

    def chat_completion(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.call_count += 1
        # Store user prompt (the state packet)
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        self.observed_prompts.append(user_msg)

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
                            "arguments": json.dumps({"cmd": f"{Path(sys.executable).name} test_calc.py"})
                        }
                    }
                ]
            }
        ]

        client = MockBlankSlateClient(steps)
        harness = BlankSlateHarness(env=self.env, client=client, max_steps=5)

        verify_cmd = f"{Path(sys.executable).name} test_calc.py"
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
