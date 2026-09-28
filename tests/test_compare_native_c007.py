"""compare_native_c007: the paired card 018 vs card 007 comparison on synthetic records, with partial native data."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import compare_native_c007 as compare  # noqa: E402

# (run, task, rollout, accepted, responses, active seconds, first edit)
RETICLE = [
    ("c007-t-a-r1", "t-a", 1, True, 10, 100.0, 5), ("c007-t-a-r2", "t-a", 2, True, 12, 120.0, 6),
    ("c007-t-b-r1", "t-b", 1, False, 20, 400.0, None), ("c007-t-b-r2", "t-b", 2, True, 14, 200.0, 8),
    ("c007-t-c-r1", "t-c", 1, True, 8, 80.0, 3), ("c007-t-c-r2", "t-c", 2, True, 8, 90.0, 4),
]
# (run, task, accepted, responses, turns, wall seconds, first edit, audit clean); t-c has no native run yet
NATIVE = [
    ("c018-t-a-r1", "t-a", True, 7, 7, 60.0, 3, True), ("c018-t-a-r2", "t-a", True, 9, 10, 80.0, 4, True),
    ("c018-t-b-r1", "t-b", True, 12, 12, 150.0, 5, False),
]


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.runs, self.native = root / "runs", root / "native_runs"
        log_rows, labels = [], []
        for run, task, rollout, accepted, responses, seconds, first_edit in RETICLE:
            (self.runs / run).mkdir(parents=True)
            record = {"task_id": task, "stop": "finish_requested", "elapsed_s": seconds + 9,
                      "acceptance": {"status": "accepted" if accepted else "rejected"},
                      "agent": {"model_calls": responses, "task_resources": {"consumed": {"active_seconds": seconds}}}}
            (self.runs / run / "results.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            log_rows.append({"run": run, "task": task, "rollout": rollout})
            labels.append({"kind": "run", "run": run, "rule": {"first_edit_response": first_edit}})
            labels.append({"kind": "response", "run": run, "response": 1})
        log_rows.insert(0, {"run": "c007-t-a-r1", "task": "t-a", "rollout": 1, "crash_retry": 0})  # a retried run
        log_rows.append({"campaign": "E3-calibration-007", "status": "complete"})
        self.log = root / "c007-campaign.jsonl"
        self.log.write_text("".join(json.dumps(row) + "\n" for row in log_rows), encoding="utf-8")
        self.labels = root / "labels.jsonl"
        self.labels.write_text("".join(json.dumps(row) + "\n" for row in labels), encoding="utf-8")
        for run, task, accepted, responses, turns, seconds, first_edit, clean in NATIVE:
            (self.native / run).mkdir(parents=True)
            record = {"task_id": task, "stop": "end_turn",
                      "acceptance": {"status": "accepted" if accepted else "rejected"},
                      "responses": responses, "turns_used": turns, "wall_seconds": seconds, "audit_clean": clean,
                      "first_base_file_edit": {"response": first_edit}}
            (self.native / run / "result.json").write_text(json.dumps(record), encoding="utf-8")
        for ignored in ("c018-control-gold", "c018-t-c-r1.interrupted-20260928000000"):
            (self.native / ignored).mkdir()
            (self.native / ignored / "result.json").write_text(json.dumps(
                {"task_id": "t-c", "acceptance": {"status": "accepted"}}), encoding="utf-8")
        (self.native / "c018-t-c-r2").mkdir()  # a run in progress: no result.json yet

    def tearDown(self):
        self.temp_dir.cleanup()

    def report(self):
        reticle = compare.load_reticle(self.log, self.runs, self.labels)
        native = compare.load_native(self.native)
        return compare.compare(reticle, native, ["t-a", "t-b", "t-c"], {"responses": 1.8, "seconds": 55.0})

    def test_loaders_read_every_run_once_and_ignore_controls_and_partial_runs(self):
        reticle = compare.load_reticle(self.log, self.runs, self.labels)
        native = compare.load_native(self.native)
        self.assertEqual(len(reticle), 6)
        self.assertEqual(sorted(run["run"] for run in native), ["c018-t-a-r1", "c018-t-a-r2", "c018-t-b-r1"])
        first = next(run for run in reticle if run["run"] == "c007-t-a-r1")
        self.assertEqual((first["responses"], first["seconds"], first["first_edit"]), (10, 100.0, 5))

    def test_per_task_rows_and_paired_differences(self):
        report = self.report()
        self.assertEqual(report["tasks_with_native_runs"], 2)
        rows = {row["task"]: row for row in report["rows"]}
        self.assertEqual((rows["t-b"]["reticle"]["accepted"], rows["t-b"]["reticle"]["runs"]), (1, 2))
        self.assertEqual(rows["t-b"]["reticle"]["responses_to_accept"], 14)  # accepted runs only
        self.assertEqual(rows["t-b"]["reticle"]["first_edit"], 8)  # runs that made an edit
        self.assertEqual(rows["t-a"]["native"]["turns_to_accept"], 8.5)
        self.assertEqual(rows["t-c"]["native"]["runs"], 0)
        self.assertEqual(report["totals"],
                         {"reticle": {"runs": 4, "accepted": 3}, "native": {"runs": 3, "accepted": 3}})
        self.assertEqual(report["native_unclean_accepted"], 1)
        acceptance = report["acceptance"]
        self.assertEqual((acceptance["n"], acceptance["mean"]), (2, 0.25))
        self.assertAlmostEqual(acceptance["sd"], math.sqrt(0.125))
        self.assertEqual((acceptance["native_better"], acceptance["reticle_better"], acceptance["equal"]), (1, 0, 1))
        responses = report["responses_to_accept"]
        self.assertEqual((responses["n"], responses["mean"], responses["by_task"]),
                         (2, -2.5, {"t-a": -3.0, "t-b": -2.0}))
        self.assertAlmostEqual(responses["sd"], math.sqrt(0.5))
        self.assertEqual((report["seconds_to_accept"]["mean"], report["first_edit"]["mean"]), (-45.0, -2.5))

    def test_two_sigma_line_follows_the_number_of_runs_behind_each_mean(self):
        report = self.report()
        # t-a: 2 accepted runs per arm (1/2 + 1/2); t-b: 1 accepted run per arm (1/1 + 1/1); n = 2 tasks
        line = report["detectability"]["responses"]
        self.assertAlmostEqual(line["mean_2sigma"], 2 * 1.8 * math.sqrt(1 + 2) / 2)
        self.assertEqual(line["per_task_2sigma_two_runs_each"], 3.6)
        self.assertAlmostEqual(line["observed_2se"], 2 * math.sqrt(0.5) / math.sqrt(2))
        self.assertFalse(line["detectable"])
        self.assertAlmostEqual(report["detectability"]["seconds"]["mean_2sigma"], 55 * math.sqrt(3))
        self.assertAlmostEqual(report["within_task_sd"]["reticle"]["responses"], 1.0)  # t-a (10, 12), t-c (8, 8)
        text = compare.render(report)
        self.assertIn("| t-c | 2/2 | - |", text)
        self.assertIn("| responses to accept | 2 | -2.50 | 0.71 | 3.12 | 1.00 | no |", text)

    def test_no_native_runs_at_all(self):
        report = compare.compare(compare.load_reticle(self.log, self.runs, self.labels), [], ["t-a", "t-b", "t-c"])
        self.assertEqual((report["tasks_with_native_runs"], report["responses_to_accept"]["n"]), (0, 0))
        self.assertIsNone(report["detectability"]["responses"]["detectable"])
        self.assertIn("Tasks with native runs: 0 of 3", compare.render(report))


if __name__ == "__main__":
    unittest.main()
