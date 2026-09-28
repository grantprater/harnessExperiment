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
import jev_labeller  # noqa: E402
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
        self.responses = 0
        self.runtime.journal.append("task_contract", {"task": {"task_id": task_id, "description": "Fix demo."}})

    def request(self, omitted=()):
        """A context manifest for the next request, omitting the transcript units of the given responses."""
        units = [number - 1 for number in range(1, self.responses + 1) if number not in omitted]
        self.runtime.journal.append("context_manifest", {"manifest": {
            "message_order": ["contract", "original-task"] + [f"transcript:{unit}:0" for unit in units],
            "omitted_items": [{"kind": "transcript_unit", "reason": "context_pressure", "unit_index": number - 1}
                              for number in sorted(omitted)]}})
        return self

    def respond(self, *calls, text=""):
        """calls: (tool, arguments, status, content, revision_before)"""
        tool_calls, results = [], []
        for tool, arguments, status, content, revision in calls:
            self.calls += 1
            call_id = f"call_{self.calls}"
            tool_calls.append({"id": call_id, "type": "function",
                               "function": {"name": tool, "arguments": json.dumps(arguments)}})
            results.append((call_id, tool, status, content, revision))
        self.responses += 1
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

    def end(self, stop_reason, acceptance, fail_to_pass="fail", pass_to_pass="pass", error=None, failing=None):
        """failing: {criterion: (expected, failing)} for an evaluator report and tool output in the artifact store."""
        self.runtime.journal.append("agent_run_result", {"result": {
            "task_id": self.task_id, "stop_reason": stop_reason, "error": error}})
        decision = {"status": acceptance, "criterion_outcomes": {"fail-to-pass": fail_to_pass,
                                                                 "pass-to-pass": pass_to_pass}}
        if failing is not None:
            output = {"criteria": {name: {"coverage_ids": [f"t{i}" for i in range(expected)],
                                          "failing": [f"t{i}" for i in range(bad)], "missing": []}
                                   for name, (expected, bad) in failing.items()}}
            tool = self.runtime.artifacts.put(b"evaluator log\n" + json.dumps(output).encode("utf-8"),
                                              "application/json", "evt_eval", labels=["evaluator-output"])
            report = self.runtime.artifacts.put(json.dumps({"tool_output_artifact_id": tool.artifact_id}).encode(),
                                                "application/json", "evt_report", labels=["acceptance-report"])
            decision["report_artifact_id"] = report.artifact_id
        self.runtime.journal.append("acceptance_decision", {"decision": decision})
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

    def test_a_call_whose_earlier_result_the_context_omitted_is_a_refetch_not_a_repeat(self):
        run = SyntheticRun(self.root, "refetch")
        run.request().respond(read("pkg/core.py"))
        run.request().respond(read("pkg/other.py"))
        run.request(omitted={1}).respond(read("pkg/core.py"))  # response 1's result was omitted: a refetch
        run.request(omitted={1}).respond(read("pkg/core.py"))  # response 3's identical result is in context: stuck
        # other.py's only earlier result (2) omitted: refetch; core.py's result from 4 still in context: a repeat
        run.request(omitted={1, 2, 3}).respond(read("pkg/other.py"), read("pkg/core.py"))
        rejected = ("run", {"command": "cd /testbed && python r.py"}, "rejected", "ERROR: shell operators", BASE)
        run.request(omitted={1, 2, 3}).respond(rejected)
        run.request(omitted={1, 2, 3, 6}).respond(rejected)  # the rejection itself was omitted: a refetch too
        record = self.analyse(run.end("model_call_limit", "rejected"))
        self.assertEqual(record["phases"], ["explore", "explore", "explore", "stuck", "explore", "reproduce",
                                            "reproduce"])
        self.assertEqual(record["stuck_responses"], [4])
        self.assertEqual(record["refetch_calls"], 3)
        self.assertEqual(record["causal_status"], "rejected_calls+repeated_call+refetch_after_omission")
        self.assertEqual([r.omitted for r in wm.load_run(self.root / "refetch").responses][2:4],
                         [frozenset({1}), frozenset({1})])
        self.assertEqual(wm._manifest_omissions({}), (1, frozenset()))  # the first request: response 1

    def test_without_manifests_every_earlier_result_counts_as_in_context(self):
        run = SyntheticRun(self.root, "no-manifest")
        run.respond(read("pkg/core.py"))
        run.respond(read("pkg/core.py"))
        record = self.analyse(run.end("model_call_limit", "rejected"))
        self.assertEqual((record["phases"], record["refetch_calls"]), (["explore", "stuck"], 0))

    def test_test_discovery_and_pip_are_look_only_commands(self):
        run = SyntheticRun(self.root, "discovery")
        run.respond(("run", {"command": "python -m pytest --collect-only -q"}, "error", "no tests collected", BASE))
        run.respond(("run", {"command": "pip download sqlparse --no-deps -d /tmp/x"}, "timeout", "Retrying", BASE))
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE))
        run.respond(("run", {"command": "cd /workspace && pytest --co -q"}, "error", "no tests collected", EDITED))
        run.respond(("finish", {"summary": "fixed"}, "success", "Finish recorded.", EDITED))
        record = self.analyse(run.end("finish_requested", "rejected"))
        self.assertEqual(record["phases"], ["explore", "explore", "edit", "explore", "finish"])
        self.assertFalse(record["verified_before_finish"])
        self.assertEqual(record["signature"],
                         "fail_to_pass_failed | no_verification_before_finish | edit_unverified")
        for command, look_only in (("python -m pytest -q", False), ("python -m pytest --cov=pkg", False),
                                   ("/usr/bin/python3.12 -m pytest tests --collect-only", True),
                                   ("python3 -m pip install -e .", True), ("pipx run x", False)):
            self.assertEqual(bool(wm.LOOK_ONLY_RUN.search(command)), look_only, command)

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
        self.assertEqual(wm.label_trajectory(wm.load_run(self.root / "good")).verify_responses, [2, 3])

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

    def test_evaluator_test_counts_come_from_the_report_artifacts(self):
        run = SyntheticRun(self.root, "partial")
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE))
        record = self.analyse(run.end("model_call_limit", "rejected", pass_to_pass="fail",
                                      failing={"fail-to-pass": (15, 2), "pass-to-pass": (476, 1)}))
        self.assertEqual(record["test_counts"], {"fail-to-pass": {"expected": 15, "failing": 2, "missing": 0},
                                                 "pass-to-pass": {"expected": 476, "failing": 1, "missing": 0}})
        self.assertEqual(wm.failing_tests(record["test_counts"]), "2/15, 1/476")
        self.assertEqual(record["verifier_cause"], "pass_to_pass_regression")  # the signature is unchanged
        bare = SyntheticRun(self.root, "no-report")
        bare.respond(read("pkg/core.py"))
        record = self.analyse(bare.end("model_call_limit", "rejected"))
        self.assertIsNone(record["test_counts"])
        self.assertEqual(wm.failing_tests(record["test_counts"]), "n/a")

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

    def test_evidence_bundles_pair_runs_and_point_at_a_module(self):
        def record(run, task, signature, stop, phases=("explore",), flags="none"):
            cause, _, mechanism = signature.split(" | ")
            return {"run": run, "task_id": task, "signature": signature, "verifier_cause": cause,
                    "causal_status": flags, "mechanism": mechanism, "stop_class": stop, "responses": len(phases),
                    "tool_calls": 1, "first_edit_response": None, "verified_before_finish": False,
                    "edit_in_gold_files": False, "edited_files": [], "rejected_calls": 0, "stuck_responses": [],
                    "refetch_calls": 0, "criterion_outcomes": {}, "phases": list(phases)}

        wrong = "fail_to_pass_failed | none | edit_verified"
        records = [
            record("a1", "t1", wrong, "finish", ("explore", "edit", "verify", "finish")),
            record("a2", "t1", "accepted | none | edit_verified", "finish"),
            record("b1", "t2", wrong, "finish"), record("b2", "t2", wrong, "finish"),
            record("c1", "t3", "budget | refetch_after_omission | explore_only", "budget",
                   flags="refetch_after_omission"),
        ]
        for item in records:
            item["signature"] = " | ".join((item["verifier_cause"], item["causal_status"], item["mechanism"]))
        bundles = wm.evidence_bundles(records, wm.cluster(records))
        self.assertEqual([b["signature"] for b in bundles], [wrong, "budget | refetch_after_omission | explore_only"])
        first = bundles[0]
        self.assertEqual((first["size"], first["distinct_tasks"], first["representative_runs"]), (3, 2, ["a1", "b1"]))
        self.assertEqual(first["contrastive_pairs"], [{
            "task_id": "t1", "rejected": "a1", "accepted": "a2",
            "accepted_signature": "accepted | none | edit_verified", "accepted_first_edit_response": None,
            "accepted_phases": "explore"}])
        self.assertEqual([(n["task_id"], n["runs"]) for n in first["negative_pairs"]], [("t2", ["b1", "b2"])])
        self.assertEqual([m["module"] for m in first["module"]["primary"]], ["task completion detection"])
        self.assertEqual(first["symptoms"]["members"][0]["phases"], "explore edit verify finish")
        self.assertNotRegex(json.dumps(bundles), r'"gold(_source)?_files":')
        self.assertEqual(first["prior_attempts"], [])
        second = bundles[1]["module"]
        self.assertEqual([m["module"] for m in second["primary"]], ["agent loop"])
        self.assertEqual([m["module"] for m in second["secondary"]], ["context management"])
        self.assertTrue(set(wm.MODULES) >= {m for _, (m, _) in wm.FLAG_MODULES.items()})

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

    def test_rules_labeller_writes_every_response_and_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = SyntheticRun(root, "good")
            run.respond(read("pkg/core.py"))
            run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                         "Replaced 1 occurrence(s)", BASE),
                        ("run", {"command": "python -m pytest tests -q"}, "success", "3 passed", EDITED))
            run.respond(("finish", {"summary": "fixed"}, "success", "Finish recorded.", EDITED))
            run_dir = run.end("finish_requested", "accepted", fail_to_pass="pass")
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps({"tasks": [{"task_id": "demo-1", "gold_source_files": ["pkg/core.py"]}]}),
                             encoding="utf-8")
            out = root / "rules.jsonl"
            label_phases.label_rules([run_dir], out, task_files=[tasks])
            rows = label_phases.read_labels(out)
        self.assertEqual([(r["kind"], r.get("response")) for r in rows],
                         [("response", 1), ("response", 2), ("response", 3), ("run", None)])
        self.assertEqual([r["rule_phase"] for r in rows[:3]], ["explore", "edit", "finish"])
        self.assertEqual([r["rule_edited_existing_source"] for r in rows[:3]], [False, True, False])
        self.assertEqual(rows[3]["rule"]["signature"], "accepted | none | edit_verified")
        self.assertEqual((rows[3]["rule"]["first_edit_response"], rows[3]["rule"]["edit_in_gold_files"]), (2, True))

    def test_development_tables_score_diagnose_against_an_adjudication(self):
        def rule(number, phase):
            return {"kind": "response", "run": "r", "response": number, "rule_phase": phase,
                    "rule_edited_existing_source": False, "rule_verified_after_edit": False}

        def jev(number, phase, diagnose):
            probabilities = {"explore": 1 - diagnose, "diagnose": diagnose}
            return {"kind": "response", "run": "r", "response": number, "rule_phase": "stale", "jev_phase": phase,
                    "jev_probabilities": probabilities, "jev_confidence": max(probabilities.values()),
                    "jev_edited_existing_source": 0.1, "jev_verified_after_edit": 0.1, "jev_cost": 0.0001,
                    "jev_model": "m", "jev": {"attempts": 1, "input_tokens": 10}}

        def verdict(number, phase, strength=None):
            return {"kind": "response", "run": "r", "response": number, "adjudicated_phase": phase,
                    "diagnose_strength": strength, "complete": True, "hypothesis_response": number}

        rules = [rule(1, "explore"), rule(2, "explore"), rule(3, "explore"), rule(4, "reproduce")]
        jevs = [jev(1, "diagnose", 0.6), jev(2, "explore", 0.35), jev(3, "explore", 0.1), jev(4, "diagnose", 0.5)]
        devset = [{"kind": "header"}, verdict(1, "diagnose", "clear"), verdict(2, "explore"),
                  verdict(3, "diagnose", "borderline"), verdict(4, "reproduce")]
        text = label_phases.jev_development_tables(rules, jevs, devset)
        self.assertIn("Jev = rules 2/4 (50.0%)", text)  # the rules file's phase is used, not Jev's stale copy
        self.assertIn("| explore | 3 | 2 | 2 | 2/3 | 0.80 |", text)
        self.assertIn("| r | 2 | explore | explore | 0.350 | explore |", text)
        self.assertIn("True diagnose: 1 clear, 2 clear or borderline.", text)
        self.assertIn("| clear only | Jev's choice is diagnose | 2 | 1 | 1/2 = 0.50 | 1/1 = 1.00 |", text)
        self.assertIn("| clear only | diagnose probability >= 0.3 | 3 | 1 | 1/3 = 0.33 | 1/1 = 1.00 |", text)
        self.assertIn("| clear or borderline | diagnose probability >= 0.3 | 3 | 1 | 1/3 = 0.33 | 1/2 = 0.50 |", text)
        self.assertIn("| r | 3 | borderline | explore | explore | 0.100 | #3 |", text)
        self.assertIn("Cost: 0.000400 USD for 4 responses", text)

    def test_reply_parsing_rejects_unknown_phases(self):
        self.assertEqual(label_phases.parse_reply('{"phase": "Stuck", "mechanism": "loops"}'),
                         {"phase": "stuck", "mechanism": "loops"})
        with self.assertRaises(ValueError):
            label_phases.parse_reply('{"phase": "planning"}')


def jev_reply(phase="explore", edited=0.02, verified=0.01, confidence=0.9):
    probabilities = {name: (confidence if name == phase.lower() else (1 - confidence) / 7) for name in wm.PHASES}
    return {"model": "typesafe/jev-1.13", "answers": {
        "phase": {"type": "choice", "choice": phase, "probabilities": probabilities, "confidence": confidence},
        "edited_existing_source": {"type": "noul", "noul": edited},
        "verified_after_edit": {"type": "noul", "noul": verified}},
        "usage": {"input_tokens": 1200, "cost": 0.00002}}


class StubTransport:
    """Stands in for the HTTP call: records each request and answers from a queue (no network)."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, url, body, headers, timeout):
        self.requests.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class JevLabellerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_request_shape_is_one_choice_and_two_yes_no_questions(self):
        transport = StubTransport(jev_reply())
        jev_labeller.ask("STATE", transport=transport, key="test-key")
        request = transport.requests[0]
        self.assertEqual(request["url"], "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(request["headers"], {"Authorization": "Bearer test-key", "Content-Type": "application/json"})
        body = request["body"]
        self.assertEqual(set(body), {"model", "state", "questions"})
        self.assertEqual((body["model"], body["state"]), ("typesafe/jev-1.13", "STATE"))
        questions = body["questions"]
        self.assertEqual(set(questions), {"phase", "edited_existing_source", "verified_after_edit"})
        self.assertEqual(questions["phase"]["type"], "choice")
        self.assertEqual(set(questions["phase"]["criteria"]), set(wm.PHASES))
        self.assertTrue(all(isinstance(rubric, str) and rubric for rubric in questions["phase"]["criteria"].values()))
        for name in ("edited_existing_source", "verified_after_edit"):
            self.assertEqual(questions[name]["type"], "noul")
            self.assertEqual(set(questions[name]["criteria"]), {"true", "false"})
        json.dumps(body)  # serialisable as sent

    def test_reply_parsing_and_malformed_replies(self):
        parsed = jev_labeller.parse_answers(jev_reply("Verify", edited=0.1, verified=0.97, confidence=0.8))
        self.assertEqual(parsed["phase"], "verify")
        self.assertEqual((parsed["edited_existing_source"], parsed["verified_after_edit"]), (0.1, 0.97))
        self.assertEqual((parsed["confidence"], parsed["cost"], parsed["input_tokens"]), (0.8, 0.00002, 1200))
        self.assertEqual(parsed["model"], "typesafe/jev-1.13")
        self.assertAlmostEqual(parsed["probabilities"]["verify"], 0.8)
        bad_phase = jev_reply()
        bad_phase["answers"]["phase"]["choice"] = "planning"
        bad_noul = jev_reply()
        bad_noul["answers"]["verified_after_edit"] = {"type": "noul", "noul": 1.5}
        missing = jev_reply()
        del missing["answers"]["edited_existing_source"]
        for reply in (bad_phase, bad_noul, missing, {"error": {"message": "x"}}):
            with self.assertRaises(ValueError):
                jev_labeller.parse_answers(reply)

    def test_one_retry_then_failure(self):
        transport = StubTransport(RuntimeError("HTTP 502: bad gateway"), jev_reply("edit"))
        self.assertEqual(jev_labeller.ask("S", transport=transport, key="k", retry_wait=0)["attempts"], 2)
        with self.assertRaises(RuntimeError):
            jev_labeller.ask("S", transport=StubTransport(OSError("down")), key="k", retry_wait=0)

    def test_label_jev_writes_one_row_per_response_keyed_by_run_and_response(self):
        run = SyntheticRun(self.root, "good")
        run.respond(read("pkg/core.py"))
        run.respond(("replace_text", {"path": "pkg/core.py", "old_text": "a", "new_text": "b"}, "success",
                     "Replaced 1 occurrence(s)", BASE),
                    ("run", {"command": "python -m pytest tests -q"}, "success", "3 passed", EDITED))
        run.respond(("finish", {"summary": "fixed"}, "success", "Finish recorded.", EDITED))
        run_dir = run.end("finish_requested", "accepted", fail_to_pass="pass")
        transport = StubTransport(jev_reply("explore"), jev_reply("edit", edited=0.95, verified=0.9),
                                  jev_reply("finish"))
        out = self.root / "labels_jev.jsonl"
        label_phases.label_jev([run_dir], out, transport=transport, key="secret-key")
        rows = label_phases.read_labels(out)
        self.assertEqual([(r["run"], r["response"]) for r in rows], [("good", 1), ("good", 2), ("good", 3)])
        self.assertEqual(set(rows[1]), {
            "kind", "run", "task_id", "response", "rule_phase", "rule_edited_existing_source",
            "rule_verified_after_edit", "jev_phase", "jev_probabilities", "jev_confidence",
            "jev_edited_existing_source", "jev_verified_after_edit", "jev_cost", "jev_model", "jev"})
        self.assertEqual([r["rule_phase"] for r in rows], ["explore", "edit", "finish"])
        self.assertEqual([r["jev_phase"] for r in rows], ["explore", "edit", "finish"])
        self.assertEqual([r["rule_edited_existing_source"] for r in rows], [False, True, False])
        self.assertEqual([r["rule_verified_after_edit"] for r in rows], [False, True, False])
        self.assertEqual((rows[1]["jev_edited_existing_source"], rows[1]["jev_verified_after_edit"]), (0.95, 0.9))
        self.assertEqual((rows[1]["jev_cost"], rows[1]["jev_model"]), (0.00002, "typesafe/jev-1.13"))
        self.assertEqual(rows[1]["jev"]["questions_sha256"], jev_labeller.QUESTIONS_SHA256)
        trajectory = wm.load_run(run_dir)
        state = label_phases.render_request(trajectory, trajectory.responses[1])
        self.assertEqual(transport.requests[1]["body"]["state"], state)  # the Claude labeller's user message
        self.assertNotIn("secret-key", out.read_text(encoding="utf-8"))
        label_phases.label_jev([run_dir], out, transport=transport, key="secret-key")  # resumes: nothing to do
        self.assertEqual(len(transport.requests), 3)

    def test_jev_agreement_tables(self):
        def jev_row(number, phase, confidence, edited=0.0, verified=0.0, rule_edited=False):
            return {"kind": "response", "run": "r", "response": number, "rule_phase": "explore",
                    "rule_edited_existing_source": rule_edited, "rule_verified_after_edit": False,
                    "jev_phase": phase, "jev_probabilities": {phase: confidence, "explore": 1 - confidence}
                    if phase != "explore" else {"explore": confidence, "diagnose": 1 - confidence},
                    "jev_confidence": confidence, "jev_edited_existing_source": edited,
                    "jev_verified_after_edit": verified, "jev_cost": 0.00002, "jev_model": "typesafe/jev-1.13",
                    "jev": {"at": f"2026-09-27T12:00:0{number}.000+00:00", "latency_s": 0.2, "attempts": 1,
                            "input_tokens": 100, "request_sha256": str(number), "questions_sha256": "q"}}

        records = [{"kind": "response", "run": "r", "response": i, "rule_phase": "explore", "claude_phase": claude,
                    "gold_phase": "explore"} for i, claude in ((1, "explore"), (2, "diagnose"), (3, "explore"))]
        records.append({"kind": "run", "run": "r", "rule": {"first_edit_response": None,
                                                           "verified_before_finish": False},
                        "human": {"first_edit_response": None, "verified_before_finish": False}})
        first = [jev_row(1, "explore", 1.0), jev_row(2, "diagnose", 0.6), jev_row(3, "explore", 0.8, edited=0.7)]
        second = [jev_row(1, "explore", 1.0), jev_row(2, "explore", 0.55), jev_row(3, "explore", 0.8, edited=0.7)]
        text = label_phases.jev_agreement_tables(records, first, second)
        self.assertIn("Jev = gold 2/3 (66.7%)", text)
        self.assertIn("| explore | 3 | 3 | 2 | 2 | 2/3 | 0.21 | 0.80 | 0.80 | 1.00 |", text)
        self.assertIn("| diagnose | 0 | 0 | 1 | 1 | 0/0 | - | 0.00 | 0.00 | 1.00 |", text)
        self.assertAlmostEqual(label_phases.wilson_lower(40, 40), 40 / (40 + 1.96 ** 2))
        self.assertIn("| r | 2 | explore | explore | diagnose | diagnose | 0.6 | diagnose 0.60, explore 0.40 |", text)
        self.assertIn("| (0.5, 0.7] | 1 | 0.600 | 0 | 0.00 |", text)
        self.assertIn("| (0.99, 1.0] | 1 | 1.000 | 1 | 1.00 |", text)
        self.assertIn("| edited_existing_source | 0 | 0 | - | 3 | 1 | 0.700 |", text)
        self.assertIn("| r | None / None / 3 | False / False / False | 3 | - |", text)
        self.assertIn("identical phase 2/3 (66.7%)", text)
        self.assertIn("| first | 3 (3) | 0.000060 | 300 | 0.6 | 2.2 | typesafe/jev-1.13 |", text)


if __name__ == "__main__":
    unittest.main()
