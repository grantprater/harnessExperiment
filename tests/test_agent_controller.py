"""P6 shared-runner tests: tools, the action loop, and independent acceptance (scripted model)."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

from reticle.context import TranscriptStore
from reticle.evaluation import AcceptancePlan, AcceptanceRunner, CriterionContract
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError, ModelResponse
from reticle.tools import ToolSuite


def call(call_id, name, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def reply(*tool_calls, content=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = list(tool_calls)
    return ModelResponse(message, usage)


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append({"messages": messages, "tools": tools})
        if not self.responses:
            raise ModelClientError("script exhausted")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


EVALUATOR = (
    "import json, pathlib, subprocess, sys\n"
    "candidate = pathlib.Path(sys.argv[1])\n"
    "proc = subprocess.run([sys.executable, '-c', 'import calc; assert calc.add(2, 3) == 5'], cwd=candidate)\n"
    "print(json.dumps({'criteria': {'hidden-add': {'outcome': 'pass' if proc.returncode == 0 else 'fail', "
    "'evaluator_version': 'hidden-add-v1', 'coverage_ids': ['hidden::add']}}}))\n"
)


def tool_contents(request):
    return [m["content"] for m in request["messages"] if m.get("role") == "tool"]


class AgentControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.evaluator = self.root / "evaluator"
        self.workspace.mkdir()
        self.evaluator.mkdir()
        (self.workspace / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (self.evaluator / "evaluate.py").write_text(EVALUATOR, encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", self.workspace)
        self.task = TaskEnvelope(
            task_id="calc-add",
            description="calc.add(2, 3) returns -1 instead of 5. Fix it.",
            criteria=[{"id": "hidden-add", "kind": "executable", "visibility": "hidden"}],
            budgets={"model_calls": 6},
        )
        self.plan = AcceptancePlan(
            task_id="calc-add",
            criteria=[CriterionContract(
                "hidden-add", "calc.add returns the sum", "executable", "hidden-add-v1",
                expected_coverage_ids=["hidden::add"],
            )],
            evaluator_command=["{python}", "{bundle}/evaluate.py", "{candidate}"],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def controller(self, model, max_calls=6, tools=None):
        return AgentController(
            self.runtime, self.task, tools or ToolSuite(self.runtime, interpreter=sys.executable), model,
            AgentLimits(max_model_calls=max_calls, max_context_bytes=60_000),
        )

    def test_scripted_repair_reaches_independent_acceptance(self):
        model = ScriptedModel([
            reply(call("c1", "read_file", path="calc.py"), call("c2", "search", query="return a"),
                  usage={"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001}),
            reply(call("c3", "replace_text", path="calc.py", old_text="return a - b", new_text="return a + b")),
            reply(call("c4", "run", command='python -c "import calc; print(calc.add(2, 3))"')),
            reply(call("c5", "finish", summary="add now sums")),
        ])
        result = self.controller(model).run()

        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.tool_calls), (4, 5))
        self.assertEqual(result.finish_summary, "add now sums")
        second = "\n".join(tool_contents(model.requests[1]))
        self.assertIn("    1| def add(a, b):", second)
        self.assertIn("calc.py:2: return a - b", second)
        fourth = "\n".join(tool_contents(model.requests[3]))
        self.assertIn("exit code: 0", fourth)
        self.assertIn("5", fourth.split("--- stdout ---", 1)[1])
        self.assertEqual(model.requests[0]["messages"][1]["content"], self.task.description)
        self.assertEqual(result.usage_reported["prompt_tokens"], 100)
        self.assertEqual(result.calls_missing_usage, {"prompt_tokens": 3, "completion_tokens": 3, "cost": 3})
        self.assertEqual(len(TranscriptStore(self.runtime).load()), 9)
        kinds = {event.kind for event in self.runtime.journal.read_all()}
        self.assertTrue({"model_call", "context_manifest", "agent_run_result"} <= kinds)

        decision = AcceptanceRunner(self.runtime).evaluate(self.plan, evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "accepted")

    def test_bad_calls_and_text_replies_become_visible_results(self):
        model = ScriptedModel([
            reply(content="I think it is fixed."),
            reply(
                {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{bad"}},
                call("c2", "delete_everything"),
                call("c3", "replace_text", path="calc.py", old_text="not present", new_text="x"),
            ),
            reply(call("c4", "read_file", path="../outside.txt")),
        ])
        result = self.controller(model, max_calls=3).run()

        self.assertEqual(result.stop_reason, "model_call_limit")
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(model.requests[1]["messages"][-1]["role"], "user")
        self.assertIn("No tool call was received", model.requests[1]["messages"][-1]["content"])
        third = "\n".join(tool_contents(model.requests[2]))
        self.assertIn("not valid JSON", third)
        self.assertIn("unknown tool 'delete_everything'", third)
        self.assertIn("old_text was not found", third)
        escape = next(
            event.payload["result"]["preview"] for event in self.runtime.journal.read_all()
            if event.kind == "action_outcome" and event.payload["result"]["call_id"] == "c4"
        )
        self.assertIn("escapes workspace", escape)
        self.assertEqual((self.workspace / "calc.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")
        self.assertEqual(result.calls_missing_usage["cost"], 3)

        decision = AcceptanceRunner(self.runtime).evaluate(self.plan, evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "rejected")

    def test_ambiguous_edit_shell_operators_and_large_output_are_truthful(self):
        tools = ToolSuite(self.runtime, interpreter=sys.executable, preview_bytes=1_000)
        tools.dispatch("write_file", {"path": "pkg/dup.py", "content": "x = 1\nx = 1\n"}, "w1")
        ambiguous = tools.dispatch("replace_text", {"path": "pkg/dup.py", "old_text": "x = 1", "new_text": "x = 2"}, "r1")
        self.assertEqual(ambiguous.status, "error")
        self.assertIn("occurs 2 times", ambiguous.content)
        self.assertEqual((self.workspace / "pkg" / "dup.py").read_text(encoding="utf-8"), "x = 1\nx = 1\n")
        every = tools.dispatch(
            "replace_text", {"path": "pkg/dup.py", "old_text": "x = 1", "new_text": "x = 2", "replace_all": True}, "r2"
        )
        self.assertEqual(every.status, "success")
        self.assertEqual((self.workspace / "pkg" / "dup.py").read_text(encoding="utf-8"), "x = 2\nx = 2\n")

        piped = tools.dispatch("run", {"command": "python -c 1 | more"}, "p1")
        self.assertEqual(piped.status, "rejected")
        self.assertIn("shell operators are not supported", piped.content)

        large = tools.dispatch("run", {"command": "python -c \"print('y' * 30000)\""}, "big")
        self.assertEqual(large.status, "success")
        self.assertIn("bytes omitted; exact: art_", large.content)
        outcome = next(
            event.payload["result"] for event in self.runtime.journal.read_all()
            if event.kind == "action_outcome" and event.payload["result"]["call_id"] == "big"
        )
        self.assertTrue(self.runtime.artifacts.read(outcome["stdout_ref"]).startswith(b"y" * 30_000))

        noted = tools.dispatch("note", {"name": "plan", "content": "check subtraction", "pin": True}, "n1")
        self.assertIn("pinned", noted.content)
        self.assertEqual(tools.dispatch("read_note", {"name": "plan"}, "n2").content, "check subtraction")

    def test_model_error_and_calls_after_finish_are_recorded(self):
        failing = ScriptedModel([ModelClientError("HTTP 503 after 4 attempts")])
        result = self.controller(failing).run()
        self.assertEqual(result.stop_reason, "model_error")
        self.assertIn("503", result.error)
        self.assertIn("model_call_failed", {event.kind for event in self.runtime.journal.read_all()})

    def test_tool_calls_after_finish_are_not_executed(self):
        model = ScriptedModel([
            reply(call("f1", "finish", summary="done"), call("w1", "write_file", path="late.py", content="x = 1\n")),
        ])
        result = self.controller(model).run()
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual(result.tool_calls, 1)
        self.assertFalse((self.workspace / "late.py").exists())
        transcript = TranscriptStore(self.runtime).load()
        self.assertEqual(transcript[-1]["content"], "Not executed: finish was requested earlier in this response.")


if __name__ == "__main__":
    unittest.main()
