"""S3 interface revision: observable remaining resources, file_glob naming, recoverable errors, friction metrics."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from reticle.context import ContextBuilder, PressureRecentContextPolicy, PressureRecentContextPolicyV2
from reticle.context.baseline import RESOURCE_STATUS_PREFIX
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.tools import ToolSuite
from reticle.tools.primitives import TOOL_SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import interface_friction  # noqa: E402


def call(call_id, name, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def reply(*tool_calls, cost=None):
    return ModelResponse({"role": "assistant", "content": None, "tool_calls": list(tool_calls)},
                         {"cost": cost} if cost is not None else None)


class Recorder:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def complete(self, messages, tools):
        self.requests.append(messages)
        return self.responses.pop(0)


def status_line(messages):
    return next((m["content"] for m in messages
                 if isinstance(m.get("content"), str) and m["content"].startswith(RESOURCE_STATUS_PREFIX)), None)


class InterfaceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "a.txt").write_text("a.b\naxb\n", encoding="utf-8")
        self.runtime = LocalRuntime(root / "session", self.workspace)
        self.tools = ToolSuite(self.runtime, interpreter=sys.executable)

    def tearDown(self):
        self.temp_dir.cleanup()


class ResourceStatusTests(InterfaceTestCase):
    def test_v2_reports_ledger_remaining_before_each_response(self):
        model = Recorder([
            reply(call("r1", "read_file", path="a.txt"), cost=0.002),
            reply(call("r2", "read_file", path="a.txt", start_line=1, end_line=1), cost=0.002),
            reply(call("f", "finish", summary="done"), cost=0.002),
        ])
        task = TaskEnvelope("status-task", "Status test.", budgets={
            "model_responses": 5, "tool_actions": 7, "cost_usd": 0.05, "model_attempt_cost_reservation": 0.001})
        result = AgentController(self.runtime, task, self.tools, model, AgentLimits(5, 100_000),
                                 policy=PressureRecentContextPolicyV2()).run()
        self.assertEqual(result.stop_reason, "finish_requested")
        lines = [status_line(request) for request in model.requests]
        self.assertIn("model responses, including this one: 5 of 5", lines[0])
        self.assertIn("tool actions: 7 of 7", lines[0])
        self.assertIn("cost USD: 0.0500 of 0.0500", lines[0])
        self.assertIn("each model attempt first reserves $0.0010", lines[0])
        self.assertIn("model responses, including this one: 4 of 5", lines[1])
        self.assertIn("tool actions: 6 of 7", lines[1])
        self.assertIn("cost USD: 0.0480 of 0.0500", lines[1])
        self.assertIn("model responses, including this one: 3 of 5", lines[2])
        self.assertIn("tool actions: 5 of 7", lines[2])

    def test_invocation_limit_below_the_task_budget_is_what_is_reported(self):
        model = Recorder([reply(call("f", "finish", summary="done"))])
        task = TaskEnvelope("status-task", "Status test.", budgets={"model_responses": 10})
        AgentController(self.runtime, task, self.tools, model, AgentLimits(2, 100_000),
                        policy=PressureRecentContextPolicyV2()).run()
        self.assertIn("model responses, including this one: 2 of 2", status_line(model.requests[0]))

    def test_v1_ignores_resource_status_and_is_unchanged(self):
        task = TaskEnvelope("status-task", "Status test.")
        status = {"model_responses": {"remaining": 1, "limit": 1}}
        plain = PressureRecentContextPolicy().build(self.runtime, task, [], TOOL_SCHEMAS, 100_000)
        given = PressureRecentContextPolicy().build(self.runtime, task, [], TOOL_SCHEMAS, 100_000, resource_status=status)
        self.assertEqual(plain.messages, given.messages)
        self.assertIsNone(status_line(given.messages))
        self.assertEqual(given.manifest.policy_version, "pressure-recent-v1")

    def test_v2_places_the_status_after_the_task_and_records_it(self):
        task = TaskEnvelope("status-task", "Status test.")
        built = PressureRecentContextPolicyV2().build(
            self.runtime, task, [], TOOL_SCHEMAS, 100_000, resource_status={"tool_actions": {"remaining": 3, "limit": 4}})
        self.assertEqual(built.messages[1]["content"], "Status test.")
        self.assertTrue(built.messages[2]["content"].startswith(RESOURCE_STATUS_PREFIX))
        self.assertEqual(built.manifest.policy_version, "pressure-recent-v2")
        self.assertIn({"kind": "resource_status", "rendering": "full"}, built.manifest.selected_items)

    def test_builder_fallback_does_not_pass_resource_status_to_the_legacy_policy(self):
        class Broken(PressureRecentContextPolicyV2):
            def build(self, *args, **kwargs):
                raise RuntimeError("boom")

        built = ContextBuilder(Broken()).build(
            self.runtime, TaskEnvelope("t", "d"), [], TOOL_SCHEMAS, 100_000,
            resource_status={"tool_actions": {"remaining": 1, "limit": 1}})
        self.assertEqual(built.manifest.policy_version, "bounded-recent-v2")


class SearchInterfaceTests(InterfaceTestCase):
    def dispatch(self, name, **arguments):
        return self.tools.dispatch(name, arguments, f"c-{name}-{len(arguments)}")

    def test_schema_uses_file_glob(self):
        properties = {s["function"]["name"]: s["function"]["parameters"]["properties"] for s in TOOL_SCHEMAS}
        self.assertIn("file_glob", properties["search_text"])
        self.assertNotIn("pattern", properties["search_text"])
        self.assertNotIn("search", properties)  # legacy names are dispatch-only in toolset v3

    def test_missing_query_error_explains_and_gives_an_example(self):
        outcome = self.dispatch("search", pattern="a|b")
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("missing required argument 'query': search finds literal text inside files", outcome.content)
        self.assertIn("'pattern' only selects which files are searched", outcome.content)
        self.assertIn("search accepts: query (required), path, file_glob.", outcome.content)
        self.assertIn('Example: {"query": "def get_real_name", "file_glob": "*.py"}', outcome.content)

    def test_other_rejections_include_accepted_arguments_and_an_example(self):
        outcome = self.dispatch("read_file")
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("missing required argument 'path'.", outcome.content)
        self.assertIn("read_file accepts: path (required), start_line, end_line.", outcome.content)
        self.assertIn("Example:", outcome.content)

    def test_legacy_search_keeps_v2_behavior_with_explicit_notes(self):
        legacy = self.dispatch("search", query="a.b", pattern="*.txt")
        self.assertTrue(legacy.content.startswith("Note: 'search' is the legacy name of 'search_text'."))
        self.assertIn("Note: 'pattern' is now named 'file_glob'", legacy.content)
        self.assertIn("1 match(es)", legacy.content)
        self.assertIn("0 match(es)", self.dispatch("search", query="a.b", file_glob="*.py").content)
        listing = self.dispatch("list_files", pattern="*.txt")
        self.assertIn("1 file(s):", listing.content)

    def test_legacy_matching_stays_literal_and_empty_results_say_so(self):
        self.assertIn("1 match(es)", self.dispatch("search", query="a.b").content)
        empty = self.dispatch("search", query="^a")
        self.assertIn("(no matches; query is matched as literal text, not a regex)", empty.content)

    def test_legacy_unknown_arguments_are_reported_not_silently_ignored(self):
        outcome = self.dispatch("list_files", path=".", regex="x")
        self.assertEqual(outcome.status, "success")
        self.assertIn("Note: ignored unknown argument(s) regex; list_files accepts: path, file_glob.", outcome.content)


class FrictionMetricTests(unittest.TestCase):
    def test_summary_counts_rejections_recovery_lookups_and_first_actions(self):
        actions = [
            {"response": 1, "tool": "list_files", "status": "success", "content": "3 file(s):", "path": ".", "seconds": 1.0},
            {"response": 2, "tool": "search", "status": "rejected", "content": "ERROR: missing", "path": None, "seconds": 2.0},
            {"response": 3, "tool": "search", "status": "success", "content": "0 match(es) for 'x':", "path": None, "seconds": 3.0},
            {"response": 4, "tool": "read_file", "status": "error", "content": "ERROR: ValueError", "path": "gone.py", "seconds": 4.0},
            {"response": 5, "tool": "write_file", "status": "success", "content": "Created", "path": "repro.py", "seconds": 5.0},
            {"response": 6, "tool": "run", "status": "success", "content": "$ python repro.py", "path": None, "seconds": 6.5},
            {"response": 7, "tool": "replace_text", "status": "success", "content": "Replaced", "path": "pkg/mod.py", "seconds": 8.0},
            {"response": 8, "tool": "outline", "status": "rejected", "content": "ERROR: missing", "path": None, "seconds": 9.0},
        ]
        summary = interface_friction.summarize_actions(actions, base_files={"pkg/mod.py"})
        self.assertEqual((summary["tool_calls"], summary["rejected"], summary["rejected_rate"]), (8, 2, 0.25))
        self.assertEqual(summary["recovery_turns"], [1, None])
        self.assertEqual(summary["failed_lookups"], 2)
        self.assertEqual(summary["first_command"], {"response": 6, "seconds": 6.5})
        self.assertEqual(summary["first_base_file_edit"], {"response": 7, "seconds": 8.0})
        self.assertEqual(summary["first_any_edit"], {"response": 5, "seconds": 5.0})


if __name__ == "__main__":
    unittest.main()
