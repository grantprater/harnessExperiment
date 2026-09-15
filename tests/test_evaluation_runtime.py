"""P5 evidence and independent acceptance tests."""

from pathlib import Path
import tempfile
import unittest

import json
import os

from reticle.evaluation import (
    AcceptancePlan,
    AcceptanceRunner,
    CriterionContract,
    EvaluationBudget,
    EvaluationEvidence,
    InterpretationRecord,
    ScoreScale,
)
from reticle.runtime import LocalRuntime
from reticle.execution import ExecutionResult, IsolatedOCIBackend


class EvidenceDistinctionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.root / "session", self.workspace)
        self.evidence = EvaluationEvidence(self.runtime)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_observation_measurement_and_interpretation_remain_distinct(self):
        observation = self.evidence.observe(
            b"runner returned 8/10",
            source="fixed-evaluator",
            source_version="sha256:evaluator-v1",
            media_type="text/plain",
        )
        scale = ScoreScale("rubric points", 0, 10, higher_is_better=True, unit="points")
        measurement = self.evidence.measure(
            procedure="rubric-v1",
            procedure_version="1.0",
            scope="final artifact",
            outcome="pass",
            observation_ids=[observation.observation_id],
            value=8,
            scale=scale,
            coverage_id="rubric:all-sections:v1",
        )
        interpretation = self.evidence.interpret(
            claim="The final artifact likely satisfies the quality bar.",
            author="model",
            evidence_ids=[measurement.measurement_id],
        )

        self.assertEqual(
            [event.kind for event in self.runtime.journal.read_all()],
            ["evaluation_observation", "evaluation_measurement", "evaluation_interpretation"],
        )
        self.assertEqual(self.runtime.artifacts.read(observation.artifact_id), b"runner returned 8/10")
        self.assertEqual(measurement.scale.maximum, 10)
        self.assertNotEqual(observation.observation_id, measurement.measurement_id)
        self.assertEqual(interpretation.evidence_ids, [measurement.measurement_id])

    def test_numeric_claims_require_an_explicit_valid_scale(self):
        with self.assertRaisesRegex(ValueError, "both value and explicit scale"):
            self.evidence.measure(
                procedure="ambiguous-score",
                procedure_version="1",
                scope="draft",
                outcome="unknown",
                value=0.9,
            )
        with self.assertRaisesRegex(ValueError, "outside its declared scale"):
            self.evidence.measure(
                procedure="bounded-score",
                procedure_version="1",
                scope="draft",
                outcome="fail",
                value=90,
                scale=ScoreScale("fraction", 0, 1, True),
            )

    def test_interpretation_must_cite_evidence(self):
        with self.assertRaisesRegex(ValueError, "cite"):
            InterpretationRecord("interpret-1", "unsupported", "model", [])


class IndependentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "candidate-workspace"
        self.evaluator = self.root / "fixed-evaluator"
        self.workspace.mkdir()
        self.evaluator.mkdir()
        self.runtime = LocalRuntime(self.root / "session", self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_evaluator(self, body: str) -> None:
        (self.evaluator / "evaluate.py").write_text(body, encoding="utf-8")

    def _plan(self, expected=None) -> AcceptancePlan:
        return AcceptancePlan(
            task_id="answer-task",
            criteria=[CriterionContract(
                criterion_id="fixed-answer",
                wording="The answer must equal 42.",
                kind="executable",
                evaluator_version="fixed-answer-v1",
                expected_coverage_ids=list(expected or ["fixed::answer"]),
            )],
            evaluator_command=["{python}", "{bundle}/evaluate.py", "{candidate}"],
            evaluation_cost=2,
        )

    def test_candidate_authored_tests_cannot_replace_fixed_acceptance(self):
        (self.workspace / "answer.txt").write_text("7", encoding="utf-8")
        (self.workspace / "test_answer.py").write_text(
            "def test_candidate_claim():\n    assert True\n", encoding="utf-8"
        )
        self._write_evaluator(
            "import json, pathlib, sys\n"
            "value = (pathlib.Path(sys.argv[1]) / 'answer.txt').read_text().strip()\n"
            "print(json.dumps({'criteria': {'fixed-answer': {"
            "'outcome': 'pass' if value == '42' else 'fail', "
            "'evaluator_version': 'fixed-answer-v1', "
            "'coverage_ids': ['fixed::answer']}}}))\n"
        )
        budget = EvaluationBudget(total_units=5, reserved_final_units=2)
        self.assertTrue(budget.consume_work(3))
        self.assertFalse(budget.consume_work(1))

        rejected = AcceptanceRunner(self.runtime).evaluate(
            self._plan(), evaluator_root=self.evaluator, budget=budget
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.criterion_outcomes, {"fixed-answer": "fail"})
        self.assertEqual(budget.remaining_units, 0)

    def test_partial_coverage_is_unknown_not_a_pass(self):
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self._write_evaluator(
            "import json\n"
            "print(json.dumps({'criteria': {'fixed-answer': {"
            "'outcome': 'pass', 'evaluator_version': 'fixed-answer-v1', "
            "'coverage_ids': ['fixed::answer']}}}))\n"
        )
        decision = AcceptanceRunner(self.runtime).evaluate(
            self._plan(["fixed::answer", "fixed::edge-case"]),
            evaluator_root=self.evaluator,
        )
        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(decision.criterion_outcomes["fixed-answer"], "unknown")
        measurement = next(
            event for event in self.runtime.journal.read_all()
            if event.kind == "evaluation_measurement"
        )
        self.assertIn("fixed::edge-case", measurement.payload["infrastructure_error"])
        self.assertEqual(measurement.payload["coverage_ids"], ["fixed::answer"])

    def test_evaluator_failure_is_runtime_error_not_task_rejection(self):
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self._write_evaluator("raise RuntimeError('fixture unavailable')\n")
        decision = AcceptanceRunner(self.runtime).evaluate(
            self._plan(), evaluator_root=self.evaluator
        )
        self.assertEqual(decision.status, "runtime_error")
        self.assertEqual(decision.criterion_outcomes["fixed-answer"], "unknown")

    def test_human_only_task_produces_review_artifact(self):
        plan = AcceptancePlan(
            task_id="human-task",
            criteria=[
                CriterionContract("tone", "A reviewer approves the tone.", "human", "rubric-v2"),
                CriterionContract(
                    "novelty", "Novelty currently has no reliable oracle.",
                    "unmeasurable", "none-v1",
                ),
            ],
        )
        decision = AcceptanceRunner(self.runtime).evaluate(plan)
        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(decision.criterion_outcomes, {"tone": "not_run", "novelty": "unknown"})
        report = json.loads(self.runtime.artifacts.read(decision.report_artifact_id))
        self.assertEqual(report["criteria"][0]["wording"], "A reviewer approves the tone.")

    def test_evaluator_bundle_must_be_outside_candidate_authority(self):
        nested = self.workspace / "tests"
        nested.mkdir()
        with self.assertRaisesRegex(ValueError, "outside"):
            AcceptanceRunner(self.runtime).evaluate(self._plan(), evaluator_root=nested)

    def test_insufficient_final_cost_reports_budget_exhaustion(self):
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self._write_evaluator("raise AssertionError('must not execute')\n")
        decision = AcceptanceRunner(self.runtime).evaluate(
            self._plan(),
            evaluator_root=self.evaluator,
            budget=EvaluationBudget(total_units=1, reserved_final_units=1),
        )
        self.assertEqual(decision.status, "budget_exhausted")
        self.assertEqual(decision.criterion_outcomes["fixed-answer"], "not_run")

    def test_evaluator_version_mismatch_is_unknown(self):
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self._write_evaluator(
            "import json\n"
            "print(json.dumps({'criteria': {'fixed-answer': {"
            "'outcome': 'pass', 'evaluator_version': 'stale-v0', "
            "'coverage_ids': ['fixed::answer']}}}))\n"
        )
        decision = AcceptanceRunner(self.runtime).evaluate(
            self._plan(), evaluator_root=self.evaluator
        )
        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(decision.criterion_outcomes["fixed-answer"], "unknown")

    def test_graded_score_uses_declared_scale_and_threshold(self):
        self._write_evaluator(
            "import json\n"
            "print(json.dumps({'criteria': {'quality': {"
            "'outcome': 'unknown', 'evaluator_version': 'rubric-v3', "
            "'coverage_ids': ['rubric::all'], 'value': 7.5, "
            "'scale': {'name': 'rubric points', 'minimum': 0, 'maximum': 10, "
            "'higher_is_better': True, 'unit': 'points'}}}}))\n"
        )
        plan = AcceptancePlan(
            task_id="graded-task",
            criteria=[CriterionContract(
                "quality", "Score at least eight points.", "graded", "rubric-v3",
                minimum_score=8, expected_coverage_ids=["rubric::all"],
            )],
            evaluator_command=["{python}", "{bundle}/evaluate.py", "{candidate}"],
        )
        decision = AcceptanceRunner(self.runtime).evaluate(plan, evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.criterion_outcomes["quality"], "fail")

    def test_workspace_change_during_evaluation_invalidates_result(self):
        outer_workspace = self.workspace

        class MutatingBackend:
            name = "mutation-probe"
            host_isolation = False

            def run(self, request, cancellation_event=None):
                (outer_workspace / "late-change.txt").write_text("changed", encoding="utf-8")
                report = json.dumps({"criteria": {"fixed-answer": {
                    "outcome": "pass",
                    "evaluator_version": "fixed-answer-v1",
                    "coverage_ids": ["fixed::answer"],
                }}}).encode()
                return ExecutionResult("success", 0, report, b"", 1, self.name, False)

        self._write_evaluator("# custom backend does not launch this file\n")
        decision = AcceptanceRunner(self.runtime, MutatingBackend()).evaluate(
            self._plan(), evaluator_root=self.evaluator
        )
        self.assertEqual(decision.status, "runtime_error")
        self.assertEqual(decision.criterion_outcomes["fixed-answer"], "unknown")

    @unittest.skipUnless(
        os.environ.get("RETICLE_OCI_TEST_IMAGE"),
        "set RETICLE_OCI_TEST_IMAGE to run independent acceptance in isolated OCI",
    )
    def test_independent_acceptance_runs_in_isolated_oci(self):
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self._write_evaluator(
            "import json, pathlib, sys\n"
            "value = (pathlib.Path(sys.argv[1]) / 'answer.txt').read_text().strip()\n"
            "print(json.dumps({'criteria': {'fixed-answer': {"
            "'outcome': 'pass' if value == '42' else 'fail', "
            "'evaluator_version': 'fixed-answer-v1', "
            "'coverage_ids': ['fixed::answer']}}}))\n"
        )
        decision = AcceptanceRunner(
            self.runtime,
            IsolatedOCIBackend(os.environ["RETICLE_OCI_TEST_IMAGE"]),
        ).evaluate(self._plan(), evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "accepted")


class InstalledPackageImportTests(unittest.TestCase):
    def test_evidence_modules_import_without_root_checkout_modules(self):
        # A wheel ships only the package; root-level legacy modules must not be required.
        script = (
            "import importlib.abc, sys\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in {'stateless_harness', 'perception', 'harness'}:\n"
            "            raise ImportError('root checkout module: ' + name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "import reticle.cognitive, reticle.cognitive.falsification, reticle.evaluation\n"
            "print('ok')\n"
        )
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=root,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
