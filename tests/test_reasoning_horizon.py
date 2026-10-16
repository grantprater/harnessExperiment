"""Independent boundary checks for the staged experiment's reference contract."""
import tempfile
from pathlib import Path
import unittest

from experiments.session_harness.reasoning_horizon import gold_result, prepare


class HorizonControlsTests(unittest.TestCase):
    def test_inventory_regime_changes_dedup_scope_time_order_and_expiry(self):
        events = [{'id': 'x', 'sku': 'A', 'qty': 5, 'kind': 'credit', 'at': 10},
                  {'id': 'x', 'sku': 'B', 'qty': 7, 'kind': 'credit', 'at': 10},
                  {'id': 'x', 'sku': 'A', 'qty': 9, 'kind': 'credit', 'at': 11}]
        holds = [{'sku': 'C', 'qty': 2, 'expires': 10}]
        self.assertEqual(gold_result('ledger', 0, [events, holds, 10]), {'A': 5})
        self.assertEqual(gold_result('ledger', 1, [events, holds, 10]), {'A': 5, 'C': -2})
        self.assertEqual(gold_result('ledger', 2, [events, holds, 10]), {'B': 7})

    def test_scheduler_regime_changes_selection_and_dependency_timing(self):
        def job(id, priority, deps=(), deadline=12):
            return dict(id=id, priority=priority, deps=list(deps), deadline=deadline, release=10, weight=1)
        jobs = [job('dependent', 2, ['root']), job('root', 1), job('expired', 0, deadline=10)]
        self.assertEqual(gold_result('scheduler', 0, [jobs, 10, 3, []]), ['dependent', 'root', 'expired'])
        self.assertEqual(gold_result('scheduler', 1, [jobs, 10, 3, []]), ['root', 'expired'])
        self.assertEqual(gold_result('scheduler', 2, [jobs, 10, 3, []]), ['root', 'dependent'])

    def test_all_evaluator_controls_and_frozen_output_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            prepare(out)
            self.assertTrue((out / 'controls.json').exists())
            with self.assertRaisesRegex(RuntimeError, 'already prepared'):
                prepare(out)


if __name__ == '__main__':
    unittest.main()
