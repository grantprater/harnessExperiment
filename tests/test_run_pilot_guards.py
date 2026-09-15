"""Runner v4: durable per-attempt accounting and run stops (scripted models and a local HTTP stub; no API calls)."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402
from reticle.context import PressureRecentContextPolicy  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse  # noqa: E402

FINISH = {
    "id": "gen-finish", "provider": "Stub", "model": "stub/model",
    "choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "f1", "type": "function",
                        "function": {"name": "finish", "arguments": json.dumps({"summary": "done"})}}],
    }}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0009},
}
TEXT = {
    "id": "gen-text", "provider": "Stub", "model": "stub/model",
    "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "thinking"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0009},
}
UNAVAILABLE = (503, {"error": {"message": "overloaded"}})


def call(call_id, name, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class Script:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def complete(self, messages, tools):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class StubProvider:
    """Serves scripted (status, body) replies over HTTP; the last reply repeats."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                stub.requests += 1
                status, body = stub.replies.pop(0) if len(stub.replies) > 1 else stub.replies[0]
                payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "a.txt").write_text("alpha\n", encoding="utf-8")
        self.session = self.root / "session"
        self.runtime = LocalRuntime(self.session, self.workspace)
        self.tools = run_pilot.RepeatGuardTools(self.runtime, interpreter=sys.executable)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_agent(self, client, budgets, calls=6, runtime=None):
        runtime = runtime or self.runtime
        tools = self.tools if runtime is self.runtime else run_pilot.RepeatGuardTools(
            runtime, interpreter=sys.executable)
        task = TaskEnvelope("runner-task", "Runner test.", budgets=budgets)
        return AgentController(
            runtime, task, tools, client, AgentLimits(calls, 100_000), policy=PressureRecentContextPolicy(),
        ).run()


class RepeatStopTests(RunnerTestCase):
    def read(self, call_id):
        self.tools.dispatch("read_file", {"path": "a.txt"}, call_id)

    def test_repeat_flag_requires_three_identical_reads_without_a_workspace_change(self):
        self.read("r1")
        self.read("r2")
        self.tools.dispatch("write_file", {"path": "b.txt", "content": "new"}, "w1")
        self.read("r3")
        self.read("r4")
        self.assertIsNone(self.tools.diagnostic)
        self.read("r5")
        self.assertEqual(self.tools.diagnostic, "three identical read_file calls without a workspace change")

    def reads(self, count):
        return Script([
            ModelResponse({"role": "assistant", "content": None,
                           "tool_calls": [call(f"c{i}", "read_file", path="a.txt")]})
            for i in range(count)
        ])

    def test_repeat_stop_ends_the_run_before_the_next_model_call(self):
        inner = self.reads(5)
        result = self.run_agent(run_pilot.GuardedClient(inner, self.tools, stop_on_repeats=True),
                                {"model_responses": 6})
        self.assertEqual(inner.calls, 3)
        self.assertEqual(run_pilot.guard_stop_label(result.to_dict()), "diagnostic_termination")

    def test_repeats_do_not_stop_a_run_when_the_guard_is_off(self):
        inner = self.reads(4)
        result = self.run_agent(run_pilot.GuardedClient(inner, self.tools), {"model_responses": 6}, calls=4)
        self.assertEqual(inner.calls, 4)
        self.assertEqual(run_pilot.guard_stop_label(result.to_dict()), "model_call_limit")

    def test_pressure_arm_and_repeat_stop_are_part_of_the_protocol(self):
        self.assertIs(run_pilot.ARMS["pressure-recent-v1"], PressureRecentContextPolicy)
        execution = {"backend": "trusted-local"}
        self.assertNotEqual(
            run_pilot.protocol_hash("pressure-recent-v1", {}, execution, {"stop_on_repeats": False}),
            run_pilot.protocol_hash("pressure-recent-v1", {}, execution, {"stop_on_repeats": True}),
        )


class ProviderAccountingTests(RunnerTestCase):
    def setUp(self):
        super().setUp()
        self.calls_path = self.root / "calls.jsonl"
        self.stub = None
        no_proxy = mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        no_proxy.start()
        self.addCleanup(no_proxy.stop)

    def tearDown(self):
        if self.stub is not None:
            self.stub.close()
        super().tearDown()

    def provider(self, replies, campaign_cap=100):
        self.stub = StubProvider(replies)
        inner = run_pilot.OpenRouterClient(
            "test-key", "stub/model", self.calls_path, "run-1", run_pilot.CallBudget(campaign_cap, 0), 64, {},
            timeout=10, base_url=self.stub.url, backoff_seconds=0,
        )
        return run_pilot.GuardedClient(inner, self.tools)

    def outcomes(self, runtime):
        return [event.payload["outcome"] for event in runtime.journal.read_all()
                if event.kind == "provider_attempt_finished"]

    def test_every_retry_is_reserved_reconciled_and_logged(self):
        result = self.run_agent(self.provider([UNAVAILABLE, UNAVAILABLE, (200, FINISH)]),
                                {"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.provider_attempts, self.stub.requests), (1, 3, 3))
        self.assertEqual(self.outcomes(self.runtime), ["http_503", "http_503", "response"])
        self.assertEqual(result.task_resources["consumed"]["model_attempts"], 3)
        self.assertEqual(result.task_resources["consumed"]["model_responses"], 1)
        started = [event.payload["provider_attempt_id"] for event in self.runtime.journal.read_all()
                   if event.kind == "provider_attempt_started"]
        self.assertEqual([row["provider_attempt_id"] for row in run_pilot.read_jsonl(self.calls_path)], started)

    def test_retry_exhaustion_stops_and_resume_makes_no_provider_call(self):
        budgets = {"model_responses": 5, "model_attempts": 2}
        client = self.provider([UNAVAILABLE])
        result = self.run_agent(client, budgets)
        self.assertEqual(result.stop_reason, "task_budget_exhausted")
        self.assertEqual(self.stub.requests, 2)

        resumed = LocalRuntime(self.session)
        self.assertEqual(resumed.recovery.pending_operations, [])
        again = self.run_agent(client, budgets, runtime=resumed)
        self.assertEqual(again.stop_reason, "task_budget_exhausted")
        self.assertEqual(again.model_calls, 0)
        self.assertEqual(self.stub.requests, 2)

    def test_a_request_gets_at_most_two_retries(self):
        result = self.run_agent(self.provider([UNAVAILABLE]), {"model_responses": 5})
        self.assertEqual(result.stop_reason, "model_error")
        self.assertIn("failed after 3 attempts", result.error)
        self.assertEqual(self.stub.requests, 3)

    def test_non_retryable_status_is_charged_once_and_stops(self):
        result = self.run_agent(self.provider([(400, {"error": {"message": "bad request"}})]),
                                {"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "model_error")
        self.assertEqual(self.stub.requests, 1)
        self.assertEqual(result.task_resources["consumed"]["model_attempts"], 1)
        self.assertEqual(self.outcomes(self.runtime), ["http_400"])

    def test_campaign_cap_stops_without_a_phantom_attempt(self):
        result = self.run_agent(self.provider([UNAVAILABLE], campaign_cap=1),
                                {"model_responses": 5, "model_attempts": 5})
        self.assertEqual(run_pilot.guard_stop_label(result.to_dict()), "attempt_cap_reached")
        self.assertEqual(self.stub.requests, 1)
        self.assertEqual(result.task_resources["consumed"]["model_attempts"], 1)
        self.assertEqual(result.task_resources["pending"], {})
        self.assertEqual(LocalRuntime(self.session).recovery.pending_operations, [])

    def test_cost_budget_reserves_a_worst_case_before_each_attempt(self):
        budgets = {"model_responses": 10, "cost_usd": 0.0025, "model_attempt_cost_reservation": 0.001}
        result = self.run_agent(self.provider([(200, TEXT)]), budgets, calls=10)
        self.assertEqual(result.stop_reason, "task_budget_exhausted")
        self.assertEqual(self.stub.requests, 2)
        self.assertAlmostEqual(result.task_resources["consumed"]["cost_usd"], 0.0018)


class ChunkedRunTests(ProviderAccountingTests):
    def run_chunked(self, client, budgets, max_resumes, calls=6):
        waits = []
        task = TaskEnvelope("runner-task", "Runner test.", budgets=budgets)
        invocations = run_pilot.run_invocations(
            self.runtime, task, self.tools, client, AgentLimits(calls, 100_000), PressureRecentContextPolicy,
            max_resumes=max_resumes, wait_seconds=42.0, sleep=waits.append,
        )
        return invocations, waits

    def test_provider_stop_resumes_the_same_session_and_finishes(self):
        client = self.provider([UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, (200, FINISH)])
        invocations, waits = self.run_chunked(client, {"model_responses": 5, "model_attempts": 6}, max_resumes=2)
        self.assertEqual([i["stop_reason"] for i in invocations], ["model_error", "finish_requested"])
        self.assertEqual(waits, [42.0])
        self.assertEqual(self.stub.requests, 4)
        # Budgets are durable: the second invocation's ledger includes the first invocation's attempts.
        self.assertEqual(invocations[-1]["task_resources"]["consumed"]["model_attempts"], 4)
        resumes = [e for e in self.runtime.journal.read_all() if e.kind == "runner_resume_scheduled"]
        self.assertEqual(len(resumes), 1)
        self.assertEqual(LocalRuntime(self.session).recovery.pending_operations, [])

    def test_resumes_are_bounded(self):
        invocations, waits = self.run_chunked(self.provider([UNAVAILABLE]), {"model_responses": 5}, max_resumes=2)
        self.assertEqual(len(invocations), 3)
        self.assertEqual(len(waits), 2)
        self.assertEqual(self.stub.requests, 9)

    def test_attempt_budget_still_caps_a_chunked_run(self):
        invocations, _ = self.run_chunked(
            self.provider([UNAVAILABLE]), {"model_responses": 5, "model_attempts": 4}, max_resumes=5)
        self.assertEqual([i["stop_reason"] for i in invocations], ["model_error", "task_budget_exhausted"])
        self.assertEqual(self.stub.requests, 4)

    def test_non_retryable_errors_and_disabled_resumes_do_not_resume(self):
        invocations, waits = self.run_chunked(
            self.provider([(400, {"error": {"message": "bad request"}})]), {"model_responses": 5}, max_resumes=3)
        self.assertEqual(len(invocations), 1)
        self.assertEqual(waits, [])

    def test_no_resume_when_disabled(self):
        client = self.provider([UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, (200, FINISH)])
        invocations, waits = self.run_chunked(client, {"model_responses": 5}, max_resumes=0)
        self.assertEqual([i["stop_reason"] for i in invocations], ["model_error"])
        self.assertEqual((waits, self.stub.requests), ([], 3))


if __name__ == "__main__":
    unittest.main()
