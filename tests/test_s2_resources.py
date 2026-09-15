"""S2a focused tests for durable resources and single-writer ownership."""

from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest

from reticle.context import TranscriptStore
from reticle.runtime import (
    LocalRuntime,
    SessionOwnedError,
    SessionWriterLock,
    TaskBudgetExhausted,
    TaskBudgetLedger,
)
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.tools import ToolSuite
from reticle.execution import ExecutionController


class FinishModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return ModelResponse({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"finish-{self.calls}",
                "type": "function",
                "function": {"name": "finish", "arguments": json.dumps({"summary": "done"})},
            }],
        })


class S2ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.session = self.root / "session"
        self.runtime = LocalRuntime(self.session, self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_second_writer_is_rejected_and_replacement_takes_ownership(self):
        first = SessionWriterLock(self.session).acquire("controller-one")
        try:
            with self.assertRaises(SessionOwnedError):
                SessionWriterLock(self.session).acquire("controller-two")
        finally:
            first.release()

        replacement = SessionWriterLock(self.session).acquire("controller-two")
        replacement.release()
        self.assertFalse((self.session / "writer-owner.json").exists())

    def test_consumption_survives_runtime_replacement(self):
        ledger = TaskBudgetLedger(self.runtime, "task-1", {"model_calls": 2})
        first = ledger.reserve("model_attempts", 1)
        ledger.reconcile(first, 1, outcome="response")

        resumed = TaskBudgetLedger(LocalRuntime(self.session), "task-1", {"model_calls": 2})
        self.assertEqual(resumed.snapshot().consumed["model_attempts"], 1)
        second = resumed.reserve("model_attempts", 1)
        resumed.reconcile(second, 1, outcome="response")
        with self.assertRaises(TaskBudgetExhausted):
            resumed.reserve("model_attempts", 1)

    def test_unknown_outcome_holds_conservative_reservation(self):
        ledger = TaskBudgetLedger(self.runtime, "task-1", {"cost_usd": 0.10})
        operation_id = ledger.reserve("cost_usd", 0.06)

        resumed = TaskBudgetLedger(LocalRuntime(self.session), "task-1", {"cost_usd": 0.10})
        snapshot = resumed.snapshot()
        self.assertEqual(snapshot.reserved["cost_usd"], 0.06)
        self.assertIn(operation_id, snapshot.pending)
        with self.assertRaises(TaskBudgetExhausted):
            resumed.reserve("cost_usd", 0.05)

        resumed.reconcile(operation_id, None, outcome="unknown_external_outcome")
        # Unknown billing is recorded but remains conservatively charged at the reservation.
        # The reconciled event carries no actual, so expose it as consumed reservation.
        final = resumed.snapshot()
        self.assertNotIn(operation_id, final.pending)
        self.assertEqual(final.consumed["cost_usd"], 0.06)
        with self.assertRaises(TaskBudgetExhausted):
            resumed.reserve("cost_usd", 0.05)

    def test_budget_contract_cannot_change_on_resume(self):
        TaskBudgetLedger(self.runtime, "task-1", {"model_calls": 2})
        with self.assertRaisesRegex(ValueError, "budget contract changed"):
            TaskBudgetLedger(LocalRuntime(self.session), "task-1", {"model_calls": 3})

    def test_task_contract_persists_and_cannot_silently_change(self):
        task = TaskEnvelope("durable-task", "Original instruction", budgets={"model_calls": 2})
        self.runtime.persist_task_contract(task)
        resumed = LocalRuntime(self.session)
        resumed.persist_task_contract(task)
        with self.assertRaisesRegex(ValueError, "Task contract changed"):
            resumed.persist_task_contract(TaskEnvelope(
                "durable-task", "Different instruction", budgets={"model_calls": 2}
            ))

    def test_dispatched_model_request_without_response_requires_reconciliation(self):
        self.runtime.journal.append(
            "model_request_intent",
            {"task_id": "task-1", "attempt_id": "attempt-unknown"},
            operation_id="attempt-unknown",
        )

        resumed = LocalRuntime(self.session)
        state = next(
            item for item in resumed.recovery.pending_operations
            if item.operation_id == "attempt-unknown"
        )
        self.assertEqual(state.classification, "unknown_external_outcome")
        self.assertFalse(state.replay_safe)

        model = FinishModel()
        result = AgentController(
            resumed,
            TaskEnvelope("task-1", "Do not retry ambiguous request", budgets={"model_calls": 2}),
            ToolSuite(resumed, interpreter=sys.executable),
            model,
            AgentLimits(1, 100_000),
        ).run()
        self.assertEqual(result.stop_reason, "needs_reconciliation")
        self.assertEqual(model.calls, 0)

    def test_exhausted_task_resume_makes_no_provider_call(self):
        task = TaskEnvelope("task-controller", "Finish once.", budgets={"model_calls": 1})
        first_model = FinishModel()
        first = AgentController(
            self.runtime,
            task,
            ToolSuite(self.runtime, interpreter=sys.executable),
            first_model,
            AgentLimits(1, 100_000),
        ).run()
        self.assertEqual(first.stop_reason, "finish_requested")
        self.assertEqual(first_model.calls, 1)

        resumed = LocalRuntime(self.session)
        second_model = FinishModel()
        second = AgentController(
            resumed,
            task,
            ToolSuite(resumed, interpreter=sys.executable),
            second_model,
            AgentLimits(1, 100_000),
        ).run()
        self.assertEqual(second.stop_reason, "task_budget_exhausted")
        self.assertEqual(second.model_calls, 0)
        self.assertEqual(second_model.calls, 0)

    def test_hard_cost_cap_requires_conservative_pre_dispatch_reservation(self):
        task = TaskEnvelope("task-cost", "Do not dispatch.", budgets={"cost_usd": 0.01})
        model = FinishModel()

        result = AgentController(
            self.runtime,
            task,
            ToolSuite(self.runtime, interpreter=sys.executable),
            model,
            AgentLimits(1, 100_000),
        ).run()

        self.assertEqual(result.stop_reason, "task_budget_exhausted")
        self.assertEqual(result.model_calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertIn("model_attempt_cost_reservation", result.error)

    def test_crash_states_distinguish_not_started_from_ambiguous_effect(self):
        self.runtime.begin_action("not-started", "write_file", {"call_id": "c1"})
        self.runtime.begin_action("ambiguous", "write_file", {"call_id": "c2"})
        self.runtime.mark_action_dispatched("ambiguous", "workspace_mutation")

        resumed = LocalRuntime(self.session)
        states = {state.operation_id: state for state in resumed.recovery.pending_operations}
        self.assertEqual(states["not-started"].classification, "known_not_started")
        self.assertTrue(states["not-started"].replay_safe)
        self.assertEqual(states["ambiguous"].classification, "unknown_external_outcome")
        self.assertFalse(states["ambiguous"].replay_safe)

    def test_persisted_mutation_outcome_is_republished_without_reexecution(self):
        TranscriptStore(self.runtime).append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "write-call", "type": "function",
                "function": {"name": "write_file", "arguments": "{}"},
            }],
        })
        before = self.runtime.workspace.revision()
        self.runtime.begin_action("completed", "write_file", {"call_id": "write-call"})
        self.runtime.mark_action_dispatched("completed", "workspace_mutation")
        (self.workspace / "done.txt").write_text("written once", encoding="utf-8")
        after = self.runtime.workspace.revision()
        self.runtime.record_tool_result(
            "completed", "write-call", "success", before, after,
            stdout=b"Created done.txt (12 bytes).",
        )

        resumed = LocalRuntime(self.session)
        state = next(item for item in resumed.recovery.pending_operations if item.operation_id == "completed")
        self.assertEqual(state.classification, "known_complete_unpublished")
        self.assertEqual(resumed.repair_completed_action_publications(), ["completed"])
        self.assertEqual((self.workspace / "done.txt").read_text(encoding="utf-8"), "written once")
        transcript = TranscriptStore(resumed).load()
        self.assertEqual(transcript[-1]["tool_call_id"], "write-call")
        self.assertIn("Created done.txt", transcript[-1]["content"])
        self.assertFalse(any(
            item.operation_id == "completed" for item in resumed.recovery.pending_operations
        ))

    def test_native_file_edit_uses_execution_mutation_boundary(self):
        started = threading.Event()
        finished = threading.Event()
        tools = ToolSuite(self.runtime, interpreter=sys.executable)

        def write_file():
            started.set()
            tools.dispatch("write_file", {"path": "blocked.txt", "content": "done"}, "blocked")
            finished.set()

        with ExecutionController.workspace_boundary(self.runtime, True):
            thread = threading.Thread(target=write_file)
            thread.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(finished.wait(0.1))
        thread.join(2)
        self.assertTrue(finished.is_set())
        self.assertEqual((self.workspace / "blocked.txt").read_text(encoding="utf-8"), "done")

    def test_persisted_model_response_resumes_without_regeneration(self):
        task = TaskEnvelope("resume-response", "Finish from recorded response", budgets={"model_calls": 2})
        self.runtime.persist_task_contract(task)
        ledger = TaskBudgetLedger(self.runtime, task.task_id, task.budgets)
        attempt = ledger.reserve("model_attempts", 1)
        response_use = ledger.reserve("model_responses", 1)
        self.runtime.journal.append(
            "model_request_intent", {"task_id": task.task_id, "attempt_id": attempt}, operation_id=attempt
        )
        response = {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "recorded-finish", "type": "function",
                "function": {"name": "finish", "arguments": json.dumps({"summary": "recorded"})},
            }],
        }
        event_id = self.runtime.journal.new_event_id()
        artifact = self.runtime.artifacts.put(
            json.dumps(response).encode(), "application/json", event_id, labels=["model-response"]
        )
        self.runtime.journal.append("model_call", {
            "task_id": task.task_id,
            "attempt_id": attempt,
            "call_index": 1,
            "response_artifact_id": artifact.artifact_id,
        }, event_id=event_id)
        ledger.reconcile(attempt, 1, outcome="response")
        ledger.reconcile(response_use, 1, outcome="response_persisted")

        resumed = LocalRuntime(self.session)
        model = FinishModel()
        result = AgentController(
            resumed,
            task,
            ToolSuite(resumed, interpreter=sys.executable),
            model,
            AgentLimits(1, 100_000),
        ).run()

        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual(result.finish_summary, "recorded")
        self.assertEqual(model.calls, 0)
        transcript = TranscriptStore(resumed).load()
        self.assertEqual(transcript[-2]["tool_calls"][0]["id"], "recorded-finish")
        self.assertEqual(transcript[-1]["tool_call_id"], "recorded-finish")


if __name__ == "__main__":
    unittest.main()
