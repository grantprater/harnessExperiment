"""Bounded check oracle (S6 tool-use treatment, --oracle hidden-tests:K): check() returns only fail_to_pass counts,
is capped, and never leaves the hidden tests in the workspace or in model-visible history (synthetic repository;
trusted-local backend; no model, no API)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from reticle.context import PressureRecentContextPolicyV3
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.tools import ToolSuite
from reticle.tools.check_oracle import CheckOracleTools, HiddenTestOracle, check_schema
from reticle.tools.primitives import TOOL_SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_pilot  # noqa: E402
from task_python import PYTEST_PYTHON  # noqa: E402

GIT = ["git", "-c", "core.autocrlf=false", "-c", "user.name=oracle-test", "-c", "user.email=oracle@localhost"]
HEALTHY = b"def sign(x):\n    if x < 0:\n        return -1\n    return 1\n"
TESTS = (b"from pkg.mod import sign\n\n\ndef test_zero_is_positive_marker():\n    assert sign(0) == 1\n\n\n"
         b"def test_negative():\n    assert sign(-2) == -1\n")
MUTATION_PATCH = (
    "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,4 +1,4 @@\n def sign(x):\n-    if x < 0:\n+    if x <= 0:\n"
    "         return -1\n     return 1\n"
)
HIDDEN_NAME = "test_zero_is_positive_marker"


class OracleSuite(CheckOracleTools, ToolSuite):
    pass


def git(cwd, *args):
    return subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, check=True).stdout.decode().strip()


@unittest.skipUnless(PYTEST_PYTHON, "the evaluator needs an interpreter with pytest")
class OracleTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        repo = self.root / "repo"
        for path, content in {"pkg/__init__.py": b"", "pkg/mod.py": HEALTHY, "tests/test_mod.py": TESTS}.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_bytes(content)
        git(repo, "init", "-q", ".")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "healthy")
        commit = git(repo, "rev-parse", "HEAD")
        self.task = {
            "task_id": "synthetic-mut-001", "repo": "synthetic", "repo_url": "https://example.invalid/synthetic",
            "base_commit": commit, "fix_commit": commit, "statement": "synthetic has a regression.",
            "evaluator_test_files": ["tests/test_mod.py"], "fail_to_pass": [f"tests.test_mod::{HIDDEN_NAME}"],
            "pass_to_pass": ["tests.test_mod::test_negative"], "gold_source_files": ["pkg/mod.py"],
            "hidden_tests": True, "hidden_paths": ["tests"], "mutation_patch": MUTATION_PATCH,
            "mutation_kind": "compare_flip", "mutation_file": "pkg/mod.py",
        }
        run_root = self.root / "runs" / "run"
        self.workspace, self.bundle = run_root / "workspace", run_root / "evaluator"
        run_pilot.materialize_workspace(self.task, repo, self.workspace)
        run_pilot.build_evaluator(self.task, repo, self.bundle, 120, PYTEST_PYTHON)
        self.runtime = LocalRuntime(run_root / "session", self.workspace)
        self.oracle = HiddenTestOracle(self.runtime, None, self.bundle, max_calls=3, timeout_seconds=240)
        self.tools = OracleSuite(self.runtime, interpreter=sys.executable, oracle=self.oracle)
        self.counter = 0

    def tearDown(self):
        self.temp_dir.cleanup()

    def dispatch(self, name, **arguments):
        self.counter += 1
        return self.tools.dispatch(name, json.dumps(arguments), f"call-{self.counter}")

    def fix(self):
        self.assertEqual(self.dispatch("replace_text", path="pkg/mod.py", old_text="x <= 0", new_text="x < 0").status,
                         "success")

    def assert_no_hidden_tests_anywhere_visible(self):
        self.assertFalse((self.workspace / "tests").exists())
        self.assertEqual([p for p in self.workspace.rglob("*") if p.name.startswith("test")], [])
        self.assertEqual(list(Path(self.runtime.session_dir).glob("oracle-*")), [])  # scratch copies removed
        for event in self.runtime.journal.read_all():
            self.assertNotIn(HIDDEN_NAME, json.dumps(event.payload))
        for reference in self.runtime.artifacts.list_references():
            self.assertNotIn(HIDDEN_NAME.encode(), self.runtime.artifacts.read(reference.artifact_id))
        search = self.dispatch("search_history", query="test_zero")
        self.assertIn('"records": []', search.content)


class OracleTests(OracleTestCase):
    def test_counts_are_right_before_and_after_the_fix(self):
        before = self.runtime.workspace.revision()
        first = self.dispatch("check")
        self.assertEqual((first.status, first.content), ("success", '{"failing": 1, "passing": 0, "calls_left": 2}'))
        self.assertEqual(self.runtime.workspace.revision(), before)
        self.fix()
        second = self.dispatch("check")
        self.assertEqual(second.content, '{"failing": 0, "passing": 1, "calls_left": 1}')
        events = [e.payload for e in self.runtime.journal.read_all() if e.kind == "oracle_check"]
        self.assertEqual([(e["call"], e["failing"], e["passing"], e["calls_left"], e["scratch_removed"])
                          for e in events], [(1, 1, 0, 2, True), (2, 0, 1, 1, True)])
        self.assert_no_hidden_tests_anywhere_visible()

    def test_cap_is_enforced_and_refusals_are_recorded(self):
        for left in (2, 1, 0):
            self.assertIn(f'"calls_left": {left}', self.dispatch("check").content)
        refused = self.dispatch("check")
        self.assertEqual(refused.status, "rejected")
        self.assertEqual(refused.content,
                         "ERROR: check refused: all 3 check calls of this run are used (3 of 3); nothing was run.")
        self.assertEqual(self.oracle.record()["calls"], 3)
        self.assertEqual(self.oracle.record()["refused"], 1)
        events = [e.payload for e in self.runtime.journal.read_all() if e.kind == "oracle_check"]
        self.assertEqual([e["refused"] for e in events], [False, False, False, True])
        self.assert_no_hidden_tests_anywhere_visible()

    def test_arguments_are_rejected_without_spending_a_call(self):
        wrong = self.dispatch("check", test=HIDDEN_NAME)
        self.assertEqual(wrong.status, "rejected")
        self.assertEqual(self.oracle.calls, 0)

    def test_through_the_controller_the_model_sees_only_counts(self):
        calls = iter([("check", {}), ("replace_text", {"path": "pkg/mod.py", "old_text": "x <= 0", "new_text": "x < 0"}),
                      ("check", {}), ("finish", {"summary": "fixed"})])

        class Client:
            requests, tools = [], []

            def complete(self, messages, tools):
                self.requests.append(messages)
                self.tools.append([tool["function"]["name"] for tool in tools])
                name, arguments = next(calls)
                return ModelResponse({"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"c{len(self.requests)}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)}}]})

        client = Client()
        task = TaskEnvelope("oracle-task", "Fix sign.", budgets={"model_responses": 6})
        result = AgentController(self.runtime, task, self.tools, client, AgentLimits(6, 100_000),
                                 policy=PressureRecentContextPolicyV3()).run()
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual(client.tools[0][-1], "check")
        self.assertIn('{"failing": 1, "passing": 0, "calls_left": 2}', client.requests[1][-1]["content"])
        self.assertIn('{"failing": 0, "passing": 1, "calls_left": 1}', client.requests[3][-1]["content"])
        self.assertNotIn(HIDDEN_NAME, json.dumps(client.requests))
        self.assert_no_hidden_tests_anywhere_visible()


class OracleSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.workspace = self.root / "workspace"
        (self.workspace / "pkg").mkdir(parents=True)
        (self.workspace / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def bundle(self, where, script):
        where.mkdir(parents=True)
        (where / "task.json").write_text(json.dumps({"fail_to_pass": ["tests.test_x::test_secret_name"]}),
                                         encoding="utf-8")
        (where / "evaluate_task.py").write_text(script, encoding="utf-8")
        return where

    def test_a_bundle_inside_the_workspace_is_refused(self):
        inside = self.bundle(self.workspace / "evaluator", "print('{}')\n")
        with self.assertRaisesRegex(ValueError, "outside the workspace"):
            HiddenTestOracle(self.runtime, None, inside)

    def test_a_failed_evaluator_reports_no_output(self):
        leaky = self.bundle(self.root / "evaluator", "import sys\nprint('tests.test_x::test_secret_name FAILED')\n"
                                                     "sys.exit(3)\n")
        tools = OracleSuite(self.runtime, interpreter=sys.executable,
                            oracle=HiddenTestOracle(self.runtime, None, leaky, max_calls=2))
        outcome = tools.dispatch("check", "{}", "c1")
        self.assertEqual((outcome.status, outcome.content),
                         ("error", '{"error": "the check did not complete", "calls_left": 1}'))
        for event in self.runtime.journal.read_all():
            self.assertNotIn("test_secret_name", json.dumps(event.payload))

    def test_tool_absent_when_the_option_is_off(self):
        plain = ToolSuite(self.runtime, interpreter=sys.executable)
        self.assertNotIn("check", [schema["function"]["name"] for schema in plain.schemas()])
        outcome = plain.dispatch("check", "{}", "c1")
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("unknown tool 'check'", outcome.content)
        self.assertEqual(run_pilot.model_tool_schemas({}), TOOL_SCHEMAS)


class RunnerWiringTests(unittest.TestCase):
    def test_flag_enters_the_hash_and_the_offered_tools_only_when_on(self):
        execution, guards = {"backend": "trusted-local"}, {"stop_on_repeats": False}
        off = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards)
        three = run_pilot.treatments_from_args(["--oracle", "hidden-tests:3"])
        self.assertEqual(three, run_pilot.treatments_from_args(["--oracle", "hidden-tests"]))
        self.assertEqual((three["oracle"]["name"], three["oracle"]["version"], three["oracle"]["max_calls"]),
                         ("hidden-tests", "hidden-test-oracle-v1", 3))
        self.assertEqual(run_pilot.model_tool_schemas(three), [*TOOL_SCHEMAS, check_schema(3)])
        five = run_pilot.treatments_from_args(["--oracle", "hidden-tests:5"])
        hashes = {off, run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), three),
                  run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), five)}
        self.assertEqual(len(hashes), 3)
        for bad in ("hidden-tests:0", "visible-tests", "hidden-tests:x"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                run_pilot.treatments_from_args(["--oracle", bad])

    def test_build_tools_offers_check_only_when_on(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            (root / "workspace").mkdir()
            bundle = root / "evaluator"
            bundle.mkdir()
            (bundle / "task.json").write_text(json.dumps({"fail_to_pass": ["a::b"]}), encoding="utf-8")
            runtime = LocalRuntime(root / "session", root / "workspace")
            plain, _ = run_pilot.build_tools(runtime, {}, ToolSuite, interpreter=sys.executable)
            self.assertEqual(plain.schemas(), TOOL_SCHEMAS)
            treatments = run_pilot.treatments_from_args(["--oracle", "hidden-tests:2"])
            tools, state = run_pilot.build_tools(runtime, treatments, ToolSuite, interpreter=sys.executable,
                                                 evaluator_root=bundle, oracle_timeout_seconds=60)
            self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(treatments))
            self.assertEqual((state["oracle"].max_calls, state["oracle"].timeout_seconds), (2, 60.0))


if __name__ == "__main__":
    unittest.main()
