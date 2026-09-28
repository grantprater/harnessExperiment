"""Finish guard (S6 task-completion-detection treatment, --completion finish-guard): the first finish after a
source edit is rejected once unless a run since the edit shows a test or check executing (no model, no API)."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from reticle.context import PressureRecentContextPolicyV3
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.runtime.source_edits import SourceEditTracker, import_names, is_source_path
from reticle.tools import ToolSuite
from reticle.tools.finish_guard import FinishGuard, FinishGuardTools, tests_executed
from reticle.tools.primitives import TOOL_SCHEMAS, TOOLSET_VERSION

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_pilot  # noqa: E402
from task_python import PYTEST_PYTHON  # noqa: E402

CORE = "def sign(x):\n    if x <= 0:\n        return -1\n    return 1\n"
TEST_FILE = "from pkg.core import sign\n\n\ndef test_zero():\n    assert sign(0) == 1\n"
UNITTEST_FILE = ("import unittest\nfrom pkg.core import sign\n\n\nclass T(unittest.TestCase):\n"
                 "    def test_zero(self):\n        self.assertEqual(sign(0), 1)\n")


class GuardedSuite(FinishGuardTools, ToolSuite):
    pass


def call(call_id, name, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class Script:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def complete(self, messages, tools):
        self.requests.append(messages)
        return ModelResponse({"role": "assistant", "content": None, "tool_calls": [self.responses.pop(0)]})


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        for relative, content in {"pkg/__init__.py": "", "pkg/core.py": CORE, "setup.cfg": "[metadata]\n"}.items():
            (self.workspace / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.workspace / relative).write_text(content, encoding="utf-8")
        self.runtime = LocalRuntime(root / "session", self.workspace)
        self.guard = FinishGuard(self.runtime, SourceEditTracker(self.runtime.workspace))
        self.tools = GuardedSuite(self.runtime, interpreter=PYTEST_PYTHON or sys.executable, finish_guard=self.guard,
                                  environment={"PYTHONPATH": str(self.workspace)})
        self.counter = 0

    def tearDown(self):
        self.temp_dir.cleanup()

    def dispatch(self, name, **arguments):
        self.counter += 1
        return self.tools.dispatch(name, json.dumps(arguments), f"call-{self.counter}")

    def edit(self):
        outcome = self.dispatch("replace_text", path="pkg/core.py", old_text="x <= 0", new_text="x < 0")
        self.assertEqual(outcome.status, "success")

    def guard_events(self):
        return [e.payload for e in self.runtime.journal.read_all() if e.kind == "finish_guard"]


class GuardBehaviourTests(GuardTestCase):
    def test_fires_on_edit_then_finish_and_names_what_would_count(self):
        self.edit()
        rejected = self.dispatch("finish", summary="fixed")
        self.assertEqual(rejected.status, "rejected")
        self.assertFalse(rejected.finished)
        self.assertIn("you changed pkg/core.py, and no run has executed since that change", rejected.content)
        self.assertIn("pytest tests/test_fix.py -q", rejected.content)
        self.assertIn("python repro.py", rejected.content)
        self.assertIn("the next finish call will be accepted regardless", rejected.content)
        [event] = self.guard_events()
        self.assertEqual((event["event"], event["guard_triggered"], event["guard_reason"], event["forced_finish"]),
                         ("rejected", True, "no_run_after_edit", False))
        self.assertEqual(event["edited_files"], ["pkg/core.py"])

    def test_second_finish_is_accepted_and_recorded_as_forced(self):
        self.edit()
        self.dispatch("finish", summary="fixed")
        accepted = self.dispatch("finish", summary="fixed")
        self.assertTrue(accepted.finished)
        self.assertEqual(accepted.status, "success")
        self.assertEqual(self.guard_events()[-1]["event"], "accepted")
        self.assertEqual(self.guard.record()["guard_triggered"], True)
        self.assertEqual(self.guard.record()["forced_finish"], True)
        self.assertEqual(self.guard.record()["guard_reason"], "no_run_after_edit")

    @unittest.skipUnless(PYTEST_PYTHON, "needs an interpreter with pytest")
    def test_does_not_fire_when_a_real_check_ran_after_the_edit(self):
        self.edit()
        self.dispatch("write_file", path="tests/test_fix.py", content=TEST_FILE)  # a new file: not a source edit
        run = self.dispatch("run", command="pytest tests/test_fix.py -q -p no:cacheprovider")
        self.assertIn("1 passed", run.content)
        finish = self.dispatch("finish", summary="fixed and tested")
        self.assertTrue(finish.finished)
        self.assertEqual(self.guard.record(), {"guard_triggered": False, "guard_reason": None, "forced_finish": False,
                                               "edited_files": ["pkg/core.py"], "version": "finish-guard-v1"})

    def test_a_unittest_run_counts_and_a_unittest_run_of_nothing_does_not(self):
        self.edit()
        self.dispatch("write_file", path="checks/test_fix.py", content=TEST_FILE)  # pytest style: unittest finds 0
        empty = self.dispatch("run", command="python -m unittest discover -s checks")
        self.assertIn("Ran 0 tests", empty.content)
        missing = self.dispatch("run", command="python -m unittest checks.test_hidden")
        self.assertIn("_FailedTest", missing.content)
        self.assertTrue(self.guard.unverified())
        self.dispatch("write_file", path="checks/test_fix.py", content=UNITTEST_FILE)
        ran = self.dispatch("run", command="python -m unittest discover -s checks")
        self.assertIn("Ran 1 test", ran.content)
        self.assertTrue(self.dispatch("finish", summary="fixed").finished)
        self.assertFalse(self.guard.triggered)

    def test_a_reproduction_script_that_imports_the_library_counts(self):
        self.edit()
        self.dispatch("write_file", path="repro.py", content="from pkg.core import sign\nprint(sign(0))\n")
        self.dispatch("run", command="python repro.py")
        self.assertTrue(self.dispatch("finish", summary="fixed").finished)
        self.assertFalse(self.guard.triggered)

    def test_does_not_fire_without_an_edit(self):
        self.dispatch("read_file", path="pkg/core.py")
        self.dispatch("write_file", path="notes.py", content="print('scratch')\n")  # new file, not pre-existing
        finish = self.dispatch("finish", summary="nothing to change")
        self.assertTrue(finish.finished)
        self.assertEqual(self.guard.record()["guard_triggered"], False)
        self.assertEqual(self.guard.record()["edited_files"], [])

    @unittest.skipUnless(PYTEST_PYTHON, "needs an interpreter with pytest")
    def test_no_tests_ran_does_not_satisfy_it(self):
        self.edit()
        missing = self.dispatch("run", command="pytest tests/test_hidden.py -q -p no:cacheprovider")
        self.assertIn("no tests ran", missing.content)
        rejected = self.dispatch("finish", summary="fixed")
        self.assertEqual(rejected.status, "rejected")
        self.assertIn("none of the 1 run(s) since that change showed a test or check executing "
                      "(last: `pytest tests/test_hidden.py -q -p no:cacheprovider`)", rejected.content)
        self.assertEqual(self.guard_events()[0]["guard_reason"], "no_check_in_runs_after_edit")

    def test_a_command_that_only_prints_does_not_count(self):
        self.edit()
        self.dispatch("run", command="python -c \"print('3 passed')\"")
        self.assertEqual(self.dispatch("finish", summary="fixed").status, "rejected")

    def test_a_check_before_the_latest_edit_does_not_count(self):
        self.edit()
        self.dispatch("write_file", path="repro.py", content="from pkg.core import sign\nprint(sign(0))\n")
        self.dispatch("run", command="python repro.py")
        self.dispatch("replace_text", path="pkg/core.py", old_text="return 1", new_text="return +1")
        self.assertEqual(self.dispatch("finish", summary="fixed").status, "rejected")

    def test_an_edit_made_by_a_run_command_counts_as_an_edit(self):
        script = "from pathlib import Path; p = Path('pkg/core.py'); p.write_text(p.read_text().replace('<=', '<'))"
        self.dispatch("run", command=f"python -c \"{script}\"")
        self.assertEqual(self.guard.record()["edited_files"], ["pkg/core.py"])
        self.assertEqual(self.dispatch("finish", summary="fixed").status, "rejected")

    def test_controller_run_rejects_then_accepts_finish(self):
        client = Script(call("e", "replace_text", path="pkg/core.py", old_text="x <= 0", new_text="x < 0"),
                        call("f1", "finish", summary="fixed"), call("f2", "finish", summary="fixed"))
        task = TaskEnvelope("guard-task", "Fix sign.", budgets={"model_responses": 5})
        result = AgentController(self.runtime, task, self.tools, client, AgentLimits(5, 100_000),
                                 policy=PressureRecentContextPolicyV3()).run()
        self.assertEqual((result.stop_reason, result.model_calls), ("finish_requested", 3))
        self.assertIn("Finish not accepted yet", json.dumps(client.requests[2]))
        self.assertEqual([e["event"] for e in self.guard_events()], ["rejected", "accepted"])
        self.assertTrue(self.guard.record()["forced_finish"])


class CheckDetectionTests(unittest.TestCase):
    def test_test_runner_summaries(self):
        cases = {
            "3 passed in 0.12s": 3,
            "=== 1 failed, 2 passed, 1 warning in 0.30s ===": 3,
            "no tests ran in 0.01s": 0,
            "collected 0 items\n\n=== no tests ran in 0.00s ===": 0,
            "ERROR collecting tests/test_x.py\nInterrupted: 1 error during collection\n1 error in 0.10s": 0,
            "1 passed, 1 error in 0.20s": 2,
            "Ran 2 tests in 0.001s\n\nOK": 2,
            "Ran 0 tests in 0.000s\n\nNO TESTS RAN": 0,
            "print says 3 passed": 0,
        }
        for output, expected in cases.items():
            with self.subTest(output=output):
                self.assertEqual(tests_executed(output), expected)

    def test_source_rule(self):
        self.assertTrue(is_source_path("sqlparse/filters/reindent.py"))
        for path in ("tests/test_x.py", "pkg/tests/helpers.py", "test_repro.py", "pkg/core_test.py", "conftest.py",
                     "pkg/__pycache__/core.py", "README.md"):
            self.assertFalse(is_source_path(path), path)
        self.assertEqual(import_names(["sqlparse/sql.py", "src/pkg/mod.py", "six.py"]), ["pkg", "six", "sqlparse"])


class IncumbentUnchangedTests(unittest.TestCase):
    """Golden checks: toolset v3 and the incumbent protocol are what card 007 ran."""

    def test_toolset_v3_schemas_are_unchanged(self):
        self.assertEqual(TOOLSET_VERSION, "reticle-tools-v3")
        digest = hashlib.sha256(json.dumps(TOOL_SCHEMAS, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(digest[:16], "7d919d61e9a8196d")
        self.assertNotIn("check", [schema["function"]["name"] for schema in TOOL_SCHEMAS])

    def test_plain_toolsuite_finishes_immediately_after_an_edit(self):
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            (workspace / "pkg").mkdir(parents=True)
            (workspace / "pkg" / "core.py").write_text(CORE, encoding="utf-8")
            tools = ToolSuite(LocalRuntime(Path(name) / "session", workspace), interpreter=sys.executable)
            tools.dispatch("replace_text", {"path": "pkg/core.py", "old_text": "<=", "new_text": "<"}, "c1")
            self.assertTrue(tools.dispatch("finish", {"summary": "done"}, "c2").finished)
            self.assertEqual(tools.schemas(), TOOL_SCHEMAS)

    def test_no_treatment_recomputes_card_007_recorded_hash(self):
        config_path = ROOT / "experiments" / "p6_pilot" / "runs" / "c007-sqlparse-mut-001-r1" / "config.json"
        if b"\r\n" not in (run_pilot.HERE / "evaluate_task.py").read_bytes():
            self.skipTest("card 007 was recorded on a CRLF checkout; the runner hashes evaluate_task.py as checked out")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        arguments = (config["arm"], config["provider_routing"], config["execution"], config["guards"],
                     config["task_contracts"])
        self.assertEqual(run_pilot.protocol_hash(*arguments), config["protocol_hash"])
        self.assertEqual(run_pilot.protocol_hash(*arguments, {}), config["protocol_hash"])
        self.assertEqual(run_pilot.treatments_from_args([]), {})
        self.assertEqual(run_pilot.model_tool_schemas({}), config["tools"])


class RunnerWiringTests(unittest.TestCase):
    def test_flag_enters_the_hash_and_only_when_on(self):
        execution, guards = {"backend": "trusted-local"}, {"stop_on_repeats": False}
        off = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards)
        treatments = run_pilot.treatments_from_args(["--completion", "finish-guard"])
        self.assertEqual(treatments["completion"]["name"], "finish-guard")
        self.assertEqual(treatments["completion"]["version"], "finish-guard-v1")
        on = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), treatments)
        self.assertNotEqual(on, off)
        changed = json.loads(json.dumps(treatments))
        changed["completion"]["rejection"] += " "
        self.assertNotEqual(run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), changed), on)

    def test_build_tools_composes_the_guard_only_when_on(self):
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            runtime = LocalRuntime(Path(name) / "session", workspace)
            plain, state = run_pilot.build_tools(runtime, {}, run_pilot.ToolSuite, interpreter=sys.executable)
            self.assertIs(type(plain), run_pilot.ToolSuite)
            self.assertEqual(state, {})
            treatments = run_pilot.treatments_from_args(["--completion", "finish-guard"])
            guarded, state = run_pilot.build_tools(runtime, treatments, run_pilot.RepeatGuardTools,
                                                   interpreter=sys.executable)
            self.assertIsInstance(guarded, FinishGuardTools)
            self.assertIsInstance(guarded, run_pilot.RepeatGuardTools)
            self.assertEqual(set(state), {"completion"})
            self.assertEqual(guarded.schemas(), TOOL_SCHEMAS)


if __name__ == "__main__":
    unittest.main()
