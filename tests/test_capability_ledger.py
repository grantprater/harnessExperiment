import json
import math
import tempfile
import unittest
from pathlib import Path

from reticle.cognitive.capability_ledger import CapabilityLedger


class CapabilityLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "capabilities.json"
        self.action = {"type": "craft", "params": {"recipe": "stick"}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_is_not_repeatability_denominator(self):
        ledger = CapabilityLedger(self.path, min_trials=2)
        result = ledger.record_trial(self.action, {"oak_log": 1}, duration_s=4)
        self.assertEqual(result["status"], "discovery")
        summary = ledger.summaries()[0]
        self.assertEqual(summary["discovery_count"], 1)
        self.assertEqual(summary["known_trials"], 0)
        self.assertIsNone(summary["reliability"])

    def test_success_failure_and_unknown_are_separate(self):
        ledger = CapabilityLedger(self.path, min_trials=1)
        ledger.record_trial(self.action, {"oak_log": 1})
        self.assertEqual(ledger.record_trial(self.action, {"oak_log": 1})["status"], "success")
        self.assertEqual(ledger.record_trial(self.action, {})["status"], "failure")
        self.assertEqual(ledger.record_trial(self.action, None)["status"], "unknown")
        summary = ledger.summaries()[0]
        self.assertEqual((summary["successes"], summary["failures"], summary["unknown"]), (1, 1, 1))
        self.assertEqual(summary["known_trials"], 2)

    def test_simultaneous_positive_gains_are_independent_outcomes(self):
        ledger = CapabilityLedger(self.path, min_trials=1)
        result = ledger.record_trial(self.action, {"oak_log": 1, "stick": 2})
        self.assertEqual(result["status"], "discovery")
        self.assertEqual({s["outcome"] for s in ledger.summaries()},
                         {"inventory:oak_log:positive", "inventory:stick:positive"})

    def test_different_known_outcome_fails_prior_outcome(self):
        ledger = CapabilityLedger(self.path)
        ledger.record_trial(self.action, {"oak_log": 1})
        ledger.record_trial(self.action, {"stick": 1})
        rows = {s["outcome"]: s for s in ledger.summaries()}
        self.assertEqual(rows["inventory:oak_log:positive"]["failures"], 1)
        self.assertEqual(rows["inventory:stick:positive"]["discovery_count"], 1)

    def test_coverage_deduplicates_same_outcome_across_routines(self):
        ledger = CapabilityLedger(self.path, min_trials=1)
        ledger.record_trial(self.action, {"oak_log": 1})
        ledger.record_trial(self.action, {"oak_log": 1})
        other = {"type": "mine", "params": {"skill_id": "pick", "skill_version": "2"}}
        ledger.record_trial(other, {"oak_log": 1})
        ledger.record_trial(other, {"oak_log": 1})
        self.assertEqual(ledger.coverage(), 1)

    def test_persistence_recipe_and_skill_identity(self):
        ledger = CapabilityLedger(self.path, min_trials=1)
        ledger.record_trial(self.action, {"oak_log": 1})
        ledger.record_trial(self.action, {"oak_log": 1})
        other = {"type": "craft", "params": {"recipe": "planks", "skill_id": "craft", "skill_version": "2"}}
        ledger.record_trial(other, {"oak_log": 1})
        loaded = CapabilityLedger(self.path, min_trials=1)
        self.assertEqual(len(loaded.summaries()), 2)
        self.assertEqual(loaded.coverage(), 1)
        self.assertIn("craft:planks:craft@2", {s["routine"] for s in loaded.summaries()})

    def test_condition_variants_are_retained_as_observed_context(self):
        ledger = CapabilityLedger(self.path)
        ledger.record_trial(self.action, {"oak_log": 1}, pre_state={"health": 20, "yaw": 0})
        ledger.record_trial(self.action, {"oak_log": 1}, pre_state={"health": 18, "yaw": 90})
        summary = ledger.summaries()[0]
        self.assertEqual(len(summary["condition_variants"]), 1)
        self.assertEqual(summary["condition_variants"][0]["yaw"], 90)

    def test_corrupt_file_is_rejected(self):
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            CapabilityLedger(self.path)

    def test_nonfinite_observation_is_unknown(self):
        ledger = CapabilityLedger(self.path)
        result = ledger.record_trial(self.action, {"oak_log": math.nan})
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(ledger.coverage(), 0)


if __name__ == "__main__":
    unittest.main()
