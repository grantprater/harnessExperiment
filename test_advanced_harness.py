"""Unit tests for runtime probe and context evaporation memory manager."""
import unittest
from pathlib import Path
import tempfile

from runtime_probe import run_with_probe, format_probe_summary
from context_manager import WorkingMemoryManager
from git_checkpoint import GitCheckpointManager
from swe_bench_loader import get_instance_summary


class AdvancedHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

        # Create a toy package
        pkg = self.base_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "calc.py").write_text(
            "def multiply(a, b):\n    return a * b\n\ndef divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('cannot divide by zero')\n    return a / b\n",
            encoding="utf-8"
        )
        self.test_file = self.base_path / "test_calc.py"
        self.test_file.write_text(
            "import unittest\nfrom mypkg.calc import multiply, divide\n\nclass TestCalc(unittest.TestCase):\n    def test_pass(self):\n        self.assertEqual(multiply(2, 3), 6)\n    def test_fail(self):\n        self.assertEqual(divide(10, 0), 5)\n\nif __name__ == '__main__':\n    unittest.main()\n",
            encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_runtime_probe_detects_failure_and_call_chain(self):
        probe = run_with_probe(self.test_file, target_prefix="mypkg", cwd=self.base_path)
        self.assertFalse(probe["passed"])
        self.assertIsNotNone(probe["failure_diagnostics"])

        summary = format_probe_summary(probe)
        self.assertIn("FAILED", summary)
        self.assertIn("Execution Footprint", summary)

    def test_context_evaporation_saves_tokens(self):
        wm = WorkingMemoryManager()
        wm.add_system("System instructions.")
        wm.add_user("Fix bug in calculation.")
        wm.add_assistant("Checking calc.py", tool_calls=[{"id": "c1", "function": {"name": "file", "arguments": "{}"}}])

        # Large tool result of 2,000 characters
        large_code = "\n".join(f"line_{i} = {i}" for i in range(100))
        wm.add_tool_result(
            tool_call_id="c1",
            tool_name="file",
            raw_output=large_code,
            can_evaporate=True,
            evaporation_summary="Verified calc.py: logic confirmed valid, no defects."
        )

        stats = wm.stats()
        self.assertGreater(stats["evaporated_tokens_saved"], 0)
        messages = wm.get_messages_for_llm()
        self.assertIn("Verified calc.py", messages[-1]["content"])
        self.assertNotIn("line_99", messages[-1]["content"])

    def test_dead_end_pruning(self):
        wm = WorkingMemoryManager()
        wm.add_system("System instructions.")
        wm.add_user("Search for symbol.")
        wm.add_assistant("Searching...")
        wm.add_tool_result(
            tool_call_id="c2",
            tool_name="search",
            raw_output="Searching prefix dispatchdesk/...\nMatches: 0; returned: 0. Narrow with PREFIX if needed." + " "*100
        )
        pruned = wm.prune_dead_ends()
        self.assertEqual(pruned, 1)
        self.assertIn("0 matches", wm.get_messages_for_llm()[-1]["content"])

    def test_swe_bench_instance_summary(self):
        sample = {
            "instance_id": "psf__requests-1234",
            "repo": "psf/requests",
            "base_commit": "abc1234",
            "problem_statement": "Bug in connection timeout\nDetailed issue description...",
            "FAIL_TO_PASS": ["test_timeout"],
            "PASS_TO_PASS": ["test_auth"],
            "test_patch": "+ def test_timeout(): pass",
            "patch": "+ # fix timeout"
        }
        summ = get_instance_summary(sample)
        self.assertEqual(summ["instance_id"], "psf__requests-1234")
        self.assertEqual(summ["problem_title"], "Bug in connection timeout")
        self.assertIn("test_timeout", summ["fail_to_pass_tests"])

    def test_git_checkpoint_manager_initialization(self):
        mgr = GitCheckpointManager(self.base_path)
        self.assertEqual(mgr.repo_dir, self.base_path)


if __name__ == "__main__":
    unittest.main()
