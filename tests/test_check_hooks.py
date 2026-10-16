from pathlib import Path
import sys
import tempfile
import unittest

from reticle.runtime.check_hooks import FixedUnittestCheck
from reticle.runtime.session import LocalRuntime
from reticle.tools.check_hooks import ARMS, CheckHookTools
from experiments.check_hook_probe.run_probe import FixedTranscriptPolicy, comparison
from reticle.runtime.contracts import TaskEnvelope


class CheckHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root/'work'
        self.workspace.mkdir()
        (self.workspace/'core.py').write_text('def value():\n    return 0\n')
        (self.workspace/'test_contract.py').write_text(
            'import unittest\nfrom core import value\nclass Check(unittest.TestCase):\n'
            '    def test_value(self):\n        self.assertEqual(value(), 1)\n')
        self.runtime = LocalRuntime(self.root/'session', self.workspace)

    def tools(self, arm, checker=None):
        return CheckHookTools(self.runtime, interpreter=sys.executable,
            checker=checker or FixedUnittestCheck(self.workspace, sys.executable),
            source_paths=['core.py'], arm=arm)

    def test_only_successful_source_changes_trigger_automatic_checks(self):
        calls = []
        def checker():
            calls.append(1)
            return {'status': 'passed', 'tests_run': 1, 'output': 'verbose passing output'}
        tools = self.tools('automatic-selective', checker)
        tools.dispatch('read_file', {'path': 'core.py'}, 'read')
        tools.dispatch('replace_text', {'path': 'core.py', 'old_text': 'missing', 'new_text': 'x'}, 'rejected')
        tools.dispatch('write_file', {'path': 'core.py', 'content': (self.workspace/'core.py').read_bytes().decode()}, 'unchanged')
        self.assertEqual(calls, [])
        result = tools.dispatch('replace_text', {'path': 'core.py', 'old_text': 'return 0', 'new_text': 'return 1'}, 'changed')
        self.assertEqual(len(calls), 1)
        self.assertIn('Check passed', result.content)
        self.assertNotIn('verbose passing output', result.content)
        event = next(e for e in self.runtime.journal.read_all() if e.kind == 'post_edit_check')
        full = tools.dispatch('read_output', {'id': event.payload['evidence_handle']}, 'retrieve')
        self.assertIn('verbose passing output', full.content)

    def test_failure_diagnostics_survive_and_manual_verify_is_available(self):
        tools = self.tools('automatic-selective')
        result = tools.dispatch('replace_text', {'path': 'core.py', 'old_text': 'return 0', 'new_text': 'return 2'}, 'edit')
        self.assertIn('Check failed', result.content)
        self.assertIn('AssertionError', result.content)
        result = tools.dispatch('verify', {}, 'verify')
        self.assertIn('test_value', result.content)
        self.assertIn('FAILED', result.content)

    def test_manual_arm_and_protected_tests_and_unavailable_commands(self):
        tools = self.tools('manual')
        schemas = tools.schemas()
        for arm in ARMS:
            self.assertEqual(schemas, self.tools(arm).schemas())
        tools.dispatch('replace_text', {'path': 'core.py', 'old_text': 'return 0', 'new_text': 'return 1'}, 'edit')
        self.assertFalse(any(e.kind == 'post_edit_check' for e in self.runtime.journal.read_all()))
        before = (self.workspace/'test_contract.py').read_bytes()
        self.assertEqual(tools.dispatch('write_file', {'path': 'test_contract.py', 'content': ''}, 'test-edit').status, 'rejected')
        self.assertEqual(tools.dispatch('run', {'command': 'python -c "print(1)"'}, 'command').status, 'rejected')
        self.assertEqual((self.workspace/'test_contract.py').read_bytes(), before)
        self.assertIn('Check passed', tools.dispatch('verify', {}, 'verify').content)

    def test_execution_error_timeout_and_stale_results_are_visible(self):
        for status in ('error', 'timeout'):
            tools = self.tools('automatic-selective', lambda: {'status': status, 'output': 'actual execution issue'})
            result = tools.dispatch('verify', {}, status)
            self.assertIn('Check '+status, result.content)
            self.assertIn('actual execution issue', result.content)
        def mutating():
            (self.workspace/'core.py').write_text('changed during check')
            return {'status': 'passed', 'tests_run': 1, 'output': 'OK'}
        result = self.tools('automatic-selective', mutating).dispatch('verify', {}, 'stale')
        self.assertIn('Check stale', result.content)
        self.assertIn('evidence is stale', result.content)

    def test_empty_suite_and_timeout_are_not_success(self):
        (self.workspace/'test_contract.py').write_text('')
        self.assertEqual(FixedUnittestCheck(self.workspace, sys.executable)()['status'], 'error')
        (self.workspace/'test_contract.py').write_text('import time\ntime.sleep(1)\n')
        self.assertEqual(FixedUnittestCheck(self.workspace, sys.executable, timeout=0.05)()['status'], 'timeout')

    def test_full_transcript_policy_does_not_rewrite_observations(self):
        messages = [{'role': 'user', 'content': 'read'},
                    {'role': 'tool', 'content': 'x'*10000, 'tool_call_id': 'call'}]
        result = FixedTranscriptPolicy().build(self.runtime, TaskEnvelope('task', 'fix'), messages, [], 200000)
        self.assertEqual(result.messages[1:], messages)


if __name__ == '__main__':
    unittest.main()
