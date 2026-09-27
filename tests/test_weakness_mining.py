"""weakness_mining: failure signatures and rule phases from a synthetic session journal (no recorded runs)."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

from reticle.context import TranscriptStore  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
import label_phases  # noqa: E402
import weakness_mining as wm  # noqa: E402

GOLD = {"pkg/core.py"}
BASE, EDITED = "sha256:base", "sha256:edited"


class SyntheticRun:
    """Writes a run directory whose journal has the same event shapes the runner records."""

    def __init__(self, root: Path, name: str, task_id: str = "demo-1"):
        self.run_dir = root / name
        workspace = self.run_dir / "sessions" / f"{task_id}__model" / "workspace"
        workspace.mkdir(parents=True)
        self.runtime = LocalRuntime(self.run_dir / "sessions" / f"{task_id}__model" / "session", workspace)
        self.transcript = TranscriptStore(self.runtime)
        self.task_id = task_id
        self.calls = 0
        self.runtime.journal.append("task_contract", {"task": {"task_id": task_id, "description": "Fix demo."}})

    def respond(self, *calls, text=""):
        """calls: (tool, arguments, status, content, revision_before)"""
        tool_calls, results = [], []
        for tool, arguments, status, content, revision in calls:
            self.calls += 1
            call_id = f"call_{self.calls}"
            tool_calls.append({"id": call_id, "type": "function",
                               "function": {"name": tool, "arguments": json.dumps(arguments)}})
            results.append((call_id, tool, status, content, revision))
        self.transcript.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
        for call_id, tool, status, content, revision in results:
            self.runtime.journal.append("action_outcome", {"result": {
                "call_id": call_id, "status": status, "workspace_revision_before": revision,
                "workspace_revision_after": revision}}, operation_id=f"op_{call_id}")
            self.transcript.append({"role": "tool", "tool_call_id": call_id, "content": content,
                                    "_reticle_output": {"handle": f"out_{call_id}", "tool": tool, "status": status}})
        return self

    def attempt(self, outcome):
        self.runtime.journal.append("provider_attempt_finished", {"outcome": outcome})
        return self

    def end(self, stop_reason, acceptance, fail_to_pass="fail", pass_to_pass="pass", error=None):
        self.runtime.journal.append("agent_run_result", {"result": {
            "task_id": self.task_id, "stop_reason": stop_reason, "error": error}})
        self.runtime.journal.append("acceptance_decision", {"decision": {
            "status": acceptance, "criterion_outcomes": {"fail-to-pass": fail_to_pass, "pass-to-pass": pass_to_pass}}})
        return self.run_dir


def read(path, revision=BASE):
    return ("read_file", {"path": path}, "success", f"{path} (lines 1-10 of 10)", revision)


class WeaknessMiningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def analyse(self, run_dir):
        return wm.analyse(wm.load_run(run_dir), GOLD)

    def test_budget_run_that_only_explored_with_rejected_calls(self):
        run = SyntheticRun(self.root, "explorer")
        run.respond(("list_files", {"path": "."}, "success", "3 file(s)", BASE))
        run.respond(("search", {"pattern": "x"}, "rejected", "ERROR: missing required argument 'query'", BASE))
        run.respond(("search", {"query": "x"}, "success", "1 match(es)", BASE))
        record = self.analyse(run.end("model_call_limit", "rejected"))
        self.assertEqual(record["phases"], ["explore", "explore", "explore"])
        self.assertEqual(record["signature"], "budget | rejected_calls | explore_only")
        self.assertEqual(record["rejected_calls"], 1)
        self.assertIsNone(record["first_edit_response"])
        self.assertFalse(record["edit_in_gold_files"])

    def test_identical_rejected_call_is_stuck_and_a_read_after_an_edit_is_not(self):
        run = SyntheticRun(self.root, "looper")
        run.respond(("write_file", {"path": "repro.py", "content": "print(1)"}, "success",
                     "Created repro.py (8 bytes, 1 lines).", BASE))
        rejected = ("run", {"command": "cd /testbed && python repro.py"}, "rejected",
                    "ERROR: shell operators are not supported", BASE)
        run.respond(rejected)
        run.respond(rejected)
        run.respond(read("pkg/core.py"))
        run.respond(read("pkg/core.py"))  # identical, no workspace change: stuck
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE))
        run.respond(read("pkg/core.py", EDITED))  # identical arguments, but the workspace changed
        record = self.analyse(run.end("model_call_limit", "rejected"))
        self.assertEqual(record["phases"], ["reproduce", "reproduce", "stuck", "explore", "stuck", "edit", "explore"])
        self.assertEqual(record["stuck_responses"], [3, 5])
        self.assertEqual(record["verifier_cause"], "fail_to_pass_failed")
        self.assertEqual(record["causal_status"], "rejected_calls+repeated_call")
        self.assertEqual(record["mechanism"], "edit_unverified")
        self.assertEqual(record["first_edit_response"], 6)

    def test_edit_outside_gold_and_finish_without_verification(self):
        run = SyntheticRun(self.root, "wrong-file")
        run.respond(read("pkg/other.py"))
        run.respond(("write_file", {"path": "pkg/other.py", "content": "x = 1\n"}, "success",
                     "Overwrote pkg/other.py (6 bytes, 1 lines).", BASE))
        run.respond(("finish", {"summary": "done"}, "success", "Finish recorded.", EDITED))
        record = self.analyse(run.end("finish_requested", "rejected"))
        self.assertEqual(record["phases"], ["explore", "edit", "finish"])
        self.assertEqual(record["signature"],
                         "fail_to_pass_failed | edit_outside_gold+no_verification_before_finish | edit_unverified")
        self.assertEqual(record["edited_files"], ["pkg/other.py"])
        self.assertFalse(record["edit_in_gold_files"])

    def test_accepted_run_edits_gold_then_verifies_then_finishes(self):
        run = SyntheticRun(self.root, "good")
        run.respond(read("pkg/core.py"), ("search_text", {"query": "def f"}, "success", "1 match(es)", BASE))
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE),
                    ("run", {"command": "python -m pytest tests -q"}, "success", "3 passed", EDITED))
        run.respond(("run", {"command": "cd /workspace && python -c \"import pkg\""}, "success", "ok", EDITED))
        run.respond(("finish", {"summary": "fixed"}, "success", "Finish recorded.", EDITED))
        record = self.analyse(run.end("finish_requested", "accepted", fail_to_pass="pass"))
        self.assertEqual(record["phases"], ["explore", "edit", "verify", "finish"])
        self.assertEqual(record["signature"], "accepted | none | edit_verified")
        self.assertTrue(record["verified_before_finish"])
        self.assertTrue(record["edit_in_gold_files"])
        self.assertEqual(record["results_check"], None)  # no results.jsonl in this run directory

    def test_stop_classes_map_to_verifier_causes(self):
        cases = [
            ("repeat", "model_error", "diagnostic_termination: three identical read_file calls", [], "no_edit"),
            ("provider", "model_error", "failed after 3 attempts: HTTP 429: busy", ["response", "http_429"],
             "provider_error"),
            ("adapter", "model_error", "failed after 3 attempts: CLI error (error_max_turns)", ["cli_error"],
             "adapter_error"),
            ("slow", "model_error", "failed after 3 attempts: CLI timed out after 300 s", ["timeout"], "timeout"),
        ]
        for name, stop, error, outcomes, cause in cases:
            run = SyntheticRun(self.root, name)
            run.respond(read("pkg/core.py"))
            for outcome in outcomes:
                run.attempt(outcome)
            record = self.analyse(run.end(stop, "rejected", error=error))
            self.assertEqual(record["verifier_cause"], cause, name)
        self.assertIn("repeat_stop", self.analyse(self.root / "repeat")["causal_status"])
        regression = SyntheticRun(self.root, "regression")
        regression.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                            "Replaced 1 occurrence(s)", BASE))
        record = self.analyse(regression.end("model_call_limit", "rejected", pass_to_pass="fail"))
        self.assertEqual(record["verifier_cause"], "pass_to_pass_regression")

    def test_signature_reads_the_journal_only_and_leaves_it_untouched(self):
        run = SyntheticRun(self.root, "journal-only")
        run.respond(read("pkg/core.py"))
        run_dir = run.end("model_call_limit", "rejected")
        journal = next(run_dir.glob("sessions/*/session/events.jsonl"))
        before = (journal.read_bytes(), journal.stat().st_mtime_ns)
        self.assertFalse((run_dir / "calls.jsonl").exists())
        self.assertEqual(self.analyse(run_dir)["signature"], "budget | none | explore_only")
        self.assertEqual((journal.read_bytes(), journal.stat().st_mtime_ns), before)
        (run_dir / "results.jsonl").write_text(json.dumps({
            "task_id": "demo-1", "agent": {"stop_reason": "model_call_limit"},
            "acceptance": {"status": "rejected"}}) + "\n", encoding="utf-8")
        self.assertEqual(self.analyse(run_dir)["results_check"], "agrees")

    def test_unknown_gold_files_are_flagged_not_guessed(self):
        run = SyntheticRun(self.root, "no-gold")
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE))
        record = wm.analyse(wm.load_run(run.end("model_call_limit", "rejected")), None)
        self.assertIn("gold_unknown", record["causal_status"])
        self.assertIsNone(record["edit_in_gold_files"])

    def test_clusters_group_exact_signatures_and_rank_minable_first(self):
        records = [
            {"run": "a", "task_id": "t1", "signature": "budget | none | explore_only", "verifier_cause": "budget",
             "causal_status": "none", "mechanism": "explore_only"},
            {"run": "b", "task_id": "t2", "signature": "budget | none | explore_only", "verifier_cause": "budget",
             "causal_status": "none", "mechanism": "explore_only"},
            {"run": "c", "task_id": "t1", "signature": "provider_error | none | explore_only",
             "verifier_cause": "provider_error", "causal_status": "none", "mechanism": "explore_only"},
            {"run": "d", "task_id": "t1", "signature": "no_edit | repeat_stop | explore_only",
             "verifier_cause": "no_edit", "causal_status": "repeat_stop", "mechanism": "explore_only"},
        ]
        clusters = wm.cluster(records)
        self.assertEqual([c["members"] for c in clusters], [["a", "b"], ["d"], ["c"]])
        self.assertEqual((clusters[0]["runs"], clusters[0]["tasks"]), (2, 2))
        self.assertFalse(clusters[-1]["minable"])

    def test_native_stream_is_read_with_the_same_rules(self):
        run_dir = self.root / "native"
        run_dir.mkdir()
        workspace = "C:\\tmp\\ws"
        events = [
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": "u1", "name": "Grep", "input": {"pattern": "def f", "path": workspace}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "content": "x"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [
                {"type": "tool_use", "id": "u2", "name": "Edit", "input": {"file_path": workspace + "\\pkg\\core.py"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u2", "content": "ok"}]}},
            {"type": "assistant", "message": {"id": "m3", "content": [
                {"type": "tool_use", "id": "u3", "name": "Bash", "input": {"command": "cd x && python -m pytest -q"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u3", "content": "1 passed"}]}},
            {"type": "assistant", "message": {"id": "m4", "content": [{"type": "text", "text": "Fixed."}]}},
        ]
        (run_dir / "stream.jsonl").write_text("".join(json.dumps({"t": i, "event": e}) + "\n"
                                                      for i, e in enumerate(events)), encoding="utf-8")
        (run_dir / "result.json").write_text(json.dumps({
            "task_id": "demo-1", "timed_out": False, "init": {"cwd": workspace},
            "result": {"subtype": "success"},
            "acceptance": {"status": "accepted", "criterion_outcomes": {"fail-to-pass": "pass", "pass-to-pass": "pass"}},
        }), encoding="utf-8")
        record = self.analyse(run_dir)
        self.assertEqual(record["source"], "claude-code-stream")
        self.assertEqual(record["phases"], ["explore", "edit", "verify", "finish"])
        self.assertEqual(record["signature"], "accepted | none | edit_verified")
        self.assertEqual(record["edited_files"], ["pkg/core.py"])


class LabelAgreementTests(unittest.TestCase):
    def test_agreement_counts_and_kappa(self):
        rows = [{"kind": "response", "run": "r", "response": i, "rule_phase": rule, "claude_phase": claude,
                 "claude_mechanism": "m", "gold_phase": rule}
                for i, (rule, claude) in enumerate([("explore", "explore"), ("explore", "diagnose"),
                                                    ("edit", "edit"), ("verify", "verify")], 1)]
        text = label_phases.agreement_tables(rows)
        self.assertIn("rule = Claude on 3 (75.0%)", text)
        self.assertIn("| explore | 2 | 1 | 1 | 0.67 |", text)
        self.assertIn("| r | 2 | explore | diagnose | explore |", text)
        self.assertAlmostEqual(label_phases.kappa(["a", "a", "b"], ["a", "a", "b"]), 1.0)

    def test_reply_parsing_rejects_unknown_phases(self):
        self.assertEqual(label_phases.parse_reply('{"phase": "Stuck", "mechanism": "loops"}'),
                         {"phase": "stuck", "mechanism": "loops"})
        with self.assertRaises(ValueError):
            label_phases.parse_reply('{"phase": "planning"}')


if __name__ == "__main__":
    unittest.main()
