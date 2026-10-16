"""Card 022's post-hoc scorer (Brier/log, pairing, cluster bootstrap, verdict, calibration, vacuity), its regression
against the pastcast ledgers (metac-bot probe: 0.0832 and 0.0870), and the one-shot comparator's pinned prompt.
Offline: fixtures only."""

import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "forecast"
sys.path.insert(0, str(ROOT / "experiments" / "forecast_tasks"))

import oneshot_forecast  # noqa: E402
import score_forecasts as score  # noqa: E402


def record(task_id, probability, committed=True, treatments=None):
    entry = {"task_id": task_id, "acceptance": {"status": "accepted" if committed else "rejected",
                                                "forecast": {"committed": committed, "probability": probability}}}
    if treatments is not None:
        entry["treatments"] = treatments
    return entry


class RuleTests(unittest.TestCase):
    def test_brier_and_log(self):
        self.assertAlmostEqual(score.brier(0.3, True), 0.49)
        self.assertAlmostEqual(score.brier(0.3, False), 0.09)
        self.assertAlmostEqual(score.log_loss(0.8, True), -math.log(0.8))
        self.assertAlmostEqual(score.log_loss(0.0, True), -math.log(0.01))  # clipped
        self.assertAlmostEqual(score.log_loss(1.0, False), -math.log(0.01))

    def test_pastcast_ledgers_reproduce(self):
        results = json.loads((FIXTURES / "pastcast" / "results.json").read_text(encoding="utf-8"))
        expected = {"ledger_claude.jsonl": 0.0832, "ledger_free.jsonl": 0.0870}
        for name, brier in expected.items():
            rows = [json.loads(line) for line in (FIXTURES / "pastcast" / name).read_text(encoding="utf-8").splitlines()]
            summary = score.score_ledger(rows, results)
            self.assertEqual(summary["n"], 6)
            self.assertAlmostEqual(summary["brier"], brier, places=4)
        # by hand for the Claude (fable) ledger: medians .35 .25 .42 .32 .16 .90 against no no no no no yes
        self.assertAlmostEqual((0.35**2 + 0.25**2 + 0.42**2 + 0.32**2 + 0.16**2 + 0.1**2) / 6, 0.083233, places=6)

    def test_missing_or_uncommitted_forecasts_score_as_one_half(self):
        forecasts = score.arm_forecasts([record("a", 0.9), record("b", 0.8, committed=False), record("a", 0.1)])
        scores = score.question_scores(["a", "b", "c"], forecasts, {"a": True, "b": True, "c": False})
        self.assertEqual((scores["a"]["p"], scores["a"]["committed"]), (0.9, True))  # first run per task
        self.assertEqual((scores["b"]["p"], scores["b"]["committed"]), (0.5, False))
        self.assertEqual((scores["c"]["p"], scores["c"]["committed"]), (0.5, False))
        self.assertAlmostEqual(scores["c"]["brier"], 0.25)

    def test_resolutions_must_match_the_pinned_hash(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "resolutions.json"
            path.write_bytes(b'{"resolutions": {"a": {"outcome": true}}}\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(score.load_resolutions(path, digest), {"a": True})
            with self.assertRaisesRegex(SystemExit, "not the pinned"):
                score.load_resolutions(path, "0" * 64)

    def test_percentile_interpolates(self):
        self.assertEqual(score.percentile([0.0, 1.0, 2.0, 3.0, 4.0], 0.5), 2.0)
        self.assertAlmostEqual(score.percentile([0.0, 10.0], 0.95), 9.5)

    def test_verdict_table(self):
        self.assertEqual(score.verdict(-0.001, -0.02, 0.0, 0.01), "transfers, with gain")
        self.assertEqual(score.verdict(0.005, -0.01, -0.05, 0.01), "transfers, no harm")
        self.assertEqual(score.verdict(0.005, -0.01, -0.06, 0.01), "inconclusive")  # commitment fell > 5 points
        self.assertEqual(score.verdict(0.03, 0.001, 0.0, 0.01), "harms")
        self.assertEqual(score.verdict(0.03, -0.001, 0.0, 0.01), "inconclusive")
        self.assertEqual(score.verdict(0.008, 0.001, 0.0, 0.01), "transfers, no harm")  # first row that matches

    def test_cluster_bootstrap_is_seeded_and_resamples_whole_series(self):
        diffs, clusters = [0.1, 0.1, -0.2, 0.0], ["s1", "s1", "s2", "s3"]
        first = score.cluster_bootstrap(diffs, clusters, resamples=500)
        self.assertEqual(first, score.cluster_bootstrap(diffs, clusters, resamples=500))
        # every draw is a mean over whole clusters: with s1 = (0.2, 2), s2 = (-0.2, 1), s3 = (0.0, 1) the possible
        # means are a finite set
        possible = set()
        sums = {"s1": (0.2, 2), "s2": (-0.2, 1), "s3": (0.0, 1)}
        import itertools
        for draw in itertools.product(sums, repeat=3):
            possible.add(round(sum(sums[k][0] for k in draw) / sum(sums[k][1] for k in draw), 12))
        self.assertTrue({round(m, 12) for m in first} <= possible)
        self.assertEqual(score.cluster_bootstrap([0.02] * 6, list("aabbcc"), resamples=200), [0.02] * 200)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.ids = [f"q{i}" for i in range(12)]
        self.tasks = {t: {"series": f"s{i % 6}", "forecast_date": f"2026-08-{3 + 7 * (i % 4):02d}"}
                      for i, t in enumerate(self.ids)}
        self.outcomes = {t: i % 3 == 0 for i, t in enumerate(self.ids)}

    def scores(self, probability):
        forecasts = score.arm_forecasts([record(t, probability(t)) for t in self.ids])
        return score.question_scores(self.ids, forecasts, self.outcomes)

    def test_a_uniformly_better_treatment_transfers_with_gain(self):
        baseline = self.scores(lambda t: 0.5)
        treatment = self.scores(lambda t: 0.8 if self.outcomes[t] else 0.2)
        result = score.paired_comparison(self.ids, self.tasks, baseline, treatment, resamples=300)
        self.assertAlmostEqual(result["brier"]["D"], 0.04 - 0.25)
        self.assertEqual(result["brier"]["verdict"], "transfers, with gain")
        self.assertEqual(result["log"]["verdict"], "transfers, with gain")
        self.assertEqual(result["series"], 6)

    def test_identical_arms_are_no_harm_and_a_silent_treatment_is_not_exercised(self):
        baseline = self.scores(lambda t: 0.4)
        result = score.paired_comparison(self.ids, self.tasks, baseline, baseline, resamples=100)
        self.assertEqual(result["brier"]["D"], 0.0)
        self.assertEqual(result["brier"]["verdict"], "transfers, no harm")
        records = [record(t, 0.4, treatments={"nudge": {"fired": False}}) for t in self.ids]
        records[0]["treatments"]["nudge"]["fired"] = True  # 1 of 12 < 20%
        silent = score.paired_comparison(self.ids, self.tasks, baseline, baseline, records, resamples=100)
        self.assertEqual(silent["brier"]["verdict"], "not exercised")
        self.assertAlmostEqual(silent["treatment_fired_rate"], 1 / 12)

    def test_d_by_hand_on_four_questions(self):
        ids = ["a", "b", "c", "d"]
        tasks = {"a": {"series": "x", "forecast_date": "2026-08-03"}, "b": {"series": "x", "forecast_date": "2026-08-10"},
                 "c": {"series": "y", "forecast_date": "2026-08-03"}, "d": {"series": "y", "forecast_date": "2026-08-10"}}
        outcomes = {"a": True, "b": False, "c": True, "d": False}
        base = score.question_scores(ids, score.arm_forecasts([record(t, 0.5) for t in ids]), outcomes)
        treat = score.question_scores(ids, score.arm_forecasts([record("a", 0.7), record("b", 0.6), record("c", 0.5),
                                                                 record("d", 0.1)]), outcomes)
        result = score.paired_comparison(ids, tasks, base, treat, resamples=200)
        # (0.09-0.25) + (0.36-0.25) + (0.25-0.25) + (0.01-0.25) = -0.29 over 4
        self.assertAlmostEqual(result["brier"]["D"], -0.0725)

    def test_calibration_table_and_ece(self):
        scores = {"a": {"p": 0.1, "committed": True, "outcome": False}, "b": {"p": 0.15, "committed": True, "outcome": True},
                  "c": {"p": 0.9, "committed": True, "outcome": True}, "d": {"p": 0.5, "committed": False, "outcome": True}}
        table = score.calibration(scores)
        self.assertEqual([row["n"] for row in table["table"]], [2, 0, 0, 0, 1])
        self.assertAlmostEqual(table["ece"], 2 / 3 * abs(0.125 - 0.5) + 1 / 3 * abs(0.9 - 1.0))


class OneShotTests(unittest.TestCase):
    def test_vendored_prompt_is_the_pinned_pastcast_function(self):
        self.assertEqual(oneshot_forecast.build_prompt_sha256(), oneshot_forecast.BUILD_PROMPT_SHA256)

    def test_prompt_has_the_question_but_no_data(self):
        tasks = json.loads((ROOT / "experiments" / "forecast_tasks" / "tasks.forecast.json")
                           .read_text(encoding="utf-8"))["tasks"]
        task = next(t for t in tasks if t["template"] == "direction")
        prompt = oneshot_forecast.oneshot_prompt(task)
        self.assertIn(task["title"], prompt)
        self.assertIn(f"Today is {task['forecast_date']}.", prompt)
        self.assertNotIn("resolve.py", prompt)
        self.assertNotIn(".csv", prompt.replace(f"data/{task['series']}.csv", ""))
        self.assertEqual(oneshot_forecast.parse_probability("x Probability: 30% y Probability: 100%"), 0.99)
        self.assertIsNone(oneshot_forecast.parse_probability("no number"))


if __name__ == "__main__":
    unittest.main()
