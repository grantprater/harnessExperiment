import copy
import json
from pathlib import Path
import tempfile
import unittest

from reticle.runtime.observation_delta import exact_delta, fingerprint, reconstruct, select_observation
from reticle.runtime.refinements import RefinementRecords
from reticle.runtime.session import LocalRuntime
from experiments.observation_probe.run_refinement_probe import fixtures, preflight, specification, summarize


class ObservationRefinementTests(unittest.TestCase):
    def test_exact_changes_include_add_remove_null_and_json_type_changes(self):
        before = {'remove': 4, 'null': None, 'typed': 1, 'nested': {'a': [1, 2]}}
        after = {'add': None, 'null': None, 'typed': True, 'nested': {'a': [1, 3]}}
        change = exact_delta(before, after)
        self.assertEqual(reconstruct(before, change), after)
        self.assertEqual([v['key'] for v in change['changes']], ['add', 'nested', 'remove', 'typed'])
        after['nested']['a'].append(4)
        self.assertEqual(reconstruct(before, change)['nested']['a'], [1, 3])

    def test_reject_wrong_baseline_corruption_and_duplicate_changes(self):
        change = exact_delta({'a': 1}, {'a': 2})
        with self.assertRaises(ValueError):
            reconstruct({'a': 0}, change)
        bad = copy.deepcopy(change)
        bad['changes'][0]['value'] = 3
        with self.assertRaises(ValueError):
            reconstruct({'a': 1}, bad)
        bad = copy.deepcopy(change)
        bad['changes'] *= 2
        with self.assertRaises(ValueError):
            reconstruct({'a': 1}, bad)

    def test_conditions_and_small_snapshot_fallback(self):
        before = {str(i): 'long unchanged value '*30 for i in range(8)}
        after = {**before, '0': 'changed'}
        kwargs = dict(baseline=before, retained_baselines=[fingerprint(before)], stable_ids=True)
        selected, metadata = select_observation(after, **kwargs)
        self.assertEqual(metadata['selected'], 'delta')
        self.assertEqual(reconstruct(before, selected), after)
        for altered, reason in [({'stable_ids': False}, 'stable_ids_not_declared'),
                                ({'retained_baselines': []}, 'baseline_not_retained'),
                                ({'max_changed_fraction': 0}, 'changes_not_sparse')]:
            result, selection = select_observation(after, **{**kwargs, **altered})
            self.assertEqual(result['records'], after)
            self.assertEqual(selection['reason'], reason)
        _, selection = select_observation({'a': 1}, baseline={'a': 1},
            retained_baselines=[fingerprint({'a': 1})], stable_ids=True)
        self.assertEqual(selection['reason'], 'delta_not_smaller')
        with self.assertRaises(ValueError):
            select_observation({'a': float('nan')})

    def test_frozen_probe_conditions_and_unchanged_failures(self):
        self.assertTrue(all(preflight(fixtures()).values()))
        for case in fixtures():
            self.assertIn(case['domain']+'_06', case['expected']['failed_keys'])
            self.assertNotIn(case['domain']+'_07', case['expected']['failed_keys'])

    def test_incomplete_usage_and_failed_candidate_are_not_support(self):
        trials = [{'case': 'a', 'arm': 'full', 'accepted': True,
                   'usage': {'prompt_tokens': 100, 'completion_tokens': 10}},
                  {'case': 'a', 'arm': 'adaptive', 'accepted': True,
                   'usage': {'prompt_tokens': 50, 'completion_tokens': 10}}]
        self.assertEqual(summarize(trials, 2)['decision'], 'scoped_support')
        trials[1]['usage'] = None
        self.assertEqual(summarize(trials, 2)['decision'], 'inconclusive')
        trials[1]['accepted'] = False
        self.assertEqual(summarize(trials, 2)['decision'], 'rejected')

    def test_records_preserve_immutable_evidence_and_reject_unsupported_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = LocalRuntime(root/'session', root)
            records = RefinementRecords(runtime)
            spec = specification()
            initial = records.save(spec)
            spec['status'] = 'scoped_support'
            with self.assertRaises(ValueError):
                records.save(spec)
            evidence = summarize([
                {'case': 'a', 'arm': 'full', 'accepted': True,
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 10}},
                {'case': 'a', 'arm': 'adaptive', 'accepted': True,
                 'usage': {'prompt_tokens': 50, 'completion_tokens': 10}}], 2)
            final = records.save(spec, evidence=evidence, previous_artifact_id=initial)
            restored = RefinementRecords(LocalRuntime(root/'session', root)).load(final)
            self.assertEqual(restored['previous_artifact_id'], initial)
            self.assertEqual(records.load(initial)['record']['status'], 'proposed')
            self.assertEqual(json.loads(runtime.artifacts.read(restored['evidence_artifact_id'])), evidence)
            mismatched = copy.deepcopy(evidence)
            mismatched['trials'][1]['case'] = 'b'
            with self.assertRaises(ValueError):
                records.save(spec, evidence=mismatched)


if __name__ == '__main__':
    unittest.main()
