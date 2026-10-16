"""Versioned activation and provider IPC exercised with real workers and no paid calls."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reticle.interactive import ROOT, add_arguments, launch
from reticle.runtime.controller import ModelResponse
from reticle.runtime.session import LocalRuntime
from reticle.runtime.supervisor import RuntimeSupervisor
from reticle.runtime.upgrades import RuntimeBundles

WRITE_REGION = 'raw = content.encode("utf-8")\n        self.runtime.workspace.write(path, raw)'
UPDATED_WRITE_REGION = 'raw = (content + "\\nversion two").encode("utf-8")\n        self.runtime.workspace.write(path, raw)'


def args(*values):
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    return parser.parse_args(values)


def response(index, name, arguments):
    return ModelResponse({'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': f'call-{index}', 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments)}}]},
        {'prompt_tokens': 100, 'completion_tokens': 20})


class FinishClient:
    def __init__(self):
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        return response(len(self.requests), 'finish', {'summary': 'Done'})


class RuntimeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / 'workspace'
        self.workspace.mkdir()
        shutil.copytree(ROOT / 'reticle', self.workspace / 'reticle',
                        ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        self.session = self.workspace / '.reticle/session'
        LocalRuntime(self.session, self.workspace)
        self.options = args('--runtime-updates', '-C', str(self.workspace), '--resume', str(self.session), '--quiet')

    def supervisor(self, client=None):
        return RuntimeSupervisor(self.session, self.workspace, self.options, client or FinishClient(), ROOT)

    def change_tools(self):
        file = self.workspace / 'reticle/tools/primitives.py'
        source = file.read_text(encoding='utf-8')
        source = source.replace(WRITE_REGION, UPDATED_WRITE_REGION)
        file.write_text(source, encoding='utf-8')

    def test_content_addressing_protected_core_and_tampering(self):
        bundles = RuntimeBundles(self.session, ROOT)
        self.assertEqual(bundles.snapshot(self.workspace), bundles.state['baseline'])
        self.change_tools()
        version = bundles.snapshot(self.workspace)
        self.assertNotEqual(version, bundles.state['baseline'])
        self.assertEqual(version, bundles.snapshot(self.workspace))
        core = self.workspace / 'reticle/runtime/budgets.py'
        core.write_text(core.read_text(encoding='utf-8') + '\n# changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Protected.*budgets'):
            bundles.snapshot(self.workspace)
        staged = bundles.path(version) / 'reticle/tools/primitives.py'
        staged.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed after staging'):
            bundles.verify(version)

    def test_self_edit_activation_then_followup_runs_new_code_with_history(self):
        class EditingClient(FinishClient):
            def complete(inner, messages, tools):
                inner.requests.append(messages)
                n = len(inner.requests)
                actions = [
                    ('replace_text', {'path': 'reticle/tools/primitives.py',
                                      'old_text': WRITE_REGION,
                                      'new_text': UPDATED_WRITE_REGION}),
                    ('activate_runtime', {'reason': 'Exercise live update'}),
                    ('finish', {'summary': 'Staged'}),
                    ('write_file', {'path': 'result.txt', 'content': 'hello'}),
                    ('finish', {'summary': 'Updated'}),
                ]
                self.assertIn('activate_runtime', [t['function']['name'] for t in tools])
                return response(n, *actions[n-1])
        client = EditingClient()
        with patch('reticle.interactive.connection', return_value=client), \
                patch('builtins.input', side_effect=['Use the new tools', '/usage', '/exit']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = launch(args('Improve the harness', '--runtime-updates', '-C', str(self.workspace),
                               '--resume', str(self.session), '--quiet', '--model-usage',
                               '--usage-report', str(self.workspace / 'usage.json')))
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual((self.workspace / 'result.txt').read_text(), 'hello\nversion two')
        self.assertIn('Runtime activated:', output.getvalue())
        self.assertIn('input 500', output.getvalue())
        self.assertIn('Improve the harness', json.dumps(client.requests[-1]))
        self.assertIn('Prior-task handoff', json.dumps(client.requests[-1]))
        state = RuntimeBundles(self.session, ROOT).state
        events = LocalRuntime(self.session).journal.read_all()
        calls = [e.payload for e in events if e.kind == 'model_call']
        self.assertEqual([c['runtime_version'] for c in calls[:3]], [state['baseline']]*3)
        self.assertEqual([c['runtime_version'] for c in calls[3:]], [state['active']]*2)
        self.assertTrue(all(len(c['tool_schema_hash']) == 64 for c in calls))
        self.assertEqual(len([e for e in events if e.kind == 'runtime_activated']), 1)
        report = json.loads((self.workspace / 'usage.json').read_text())
        self.assertEqual(report['totals']['prompt_tokens']['reported'], 500)
        self.assertTrue(all(row['usage_feedback_enabled'] for row in report['calls']))
        sequences = [e.sequence for e in events]
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_import_failure_leaves_active_version_and_session_unchanged(self):
        supervisor = self.supervisor()
        initial = supervisor.bundles.state['active']
        before = (self.session / 'events.jsonl').read_bytes()
        file = self.workspace / 'reticle/tools/primitives.py'
        file.write_text('raise RuntimeError("candidate import failed")\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'candidate import failed'):
            supervisor.stage(self.workspace)
        self.assertEqual(supervisor.bundles.state['active'], initial)
        self.assertIsNone(supervisor.bundles.state['pending'])
        self.assertEqual((self.session / 'events.jsonl').read_bytes(), before)

    def test_pending_startup_failure_falls_back_before_dispatch(self):
        client = FinishClient()
        supervisor = self.supervisor(client)
        self.change_tools()
        version = supervisor.stage(self.workspace)
        file = supervisor.bundles.path(version) / 'reticle/tools/primitives.py'
        file.write_text('tampered\n', encoding='utf-8')
        # Resume must still be possible when a pending candidate is damaged.
        supervisor = self.supervisor(client)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(supervisor.run_turn('Continue'), 0)
        self.assertIn('keeping', output.getvalue())
        self.assertEqual(len(client.requests), 1)
        self.assertIsNone(supervisor.bundles.state['pending'])
        self.assertEqual(supervisor.bundles.state['active'], supervisor.bundles.state['baseline'])

    def test_snapshot_is_fixed_until_explicit_activation_and_survives_resume(self):
        supervisor = self.supervisor()
        initial = supervisor.bundles.state['active']
        self.change_tools()
        with contextlib.redirect_stdout(io.StringIO()):
            supervisor.run_turn('Keep using the old runtime')
        self.assertEqual(supervisor.bundles.state['active'], initial)
        candidate = supervisor.stage(self.workspace)
        resumed = self.supervisor()
        with contextlib.redirect_stdout(io.StringIO()):
            resumed.run_turn('Activate now')
        self.assertEqual(resumed.bundles.state['active'], candidate)

    def test_provider_attempt_callbacks_are_charged_once_in_worker(self):
        class AttemptClient(FinishClient):
            reports_provider_attempts = True
            def complete(inner, messages, tools, *, attempts):
                failed = attempts.begin({'attempt': 1})
                attempts.finish(failed, outcome='mock failure')
                attempts.begin({'attempt': 2})
                return super(AttemptClient, inner).complete(messages, tools)
        options = args('--runtime-updates', '-C', str(self.workspace), '--resume', str(self.session),
                       '--quiet', '--max-steps', '3')
        supervisor = RuntimeSupervisor(self.session, self.workspace, options, AttemptClient(), ROOT)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(supervisor.run_turn('Finish'), 0)
        events = LocalRuntime(self.session).journal.read_all()
        self.assertEqual(len([e for e in events if e.kind == 'provider_attempt_started']), 2)
        self.assertEqual(len([e for e in events if e.kind == 'provider_attempt_finished']), 2)
        configured = [e for e in events if e.kind == 'task_budget_configured']
        self.assertEqual(len(configured), 1)

    def test_attempt_limit_is_not_reset_by_provider_retry(self):
        class RetryClient(FinishClient):
            reports_provider_attempts = True
            def complete(inner, messages, tools, *, attempts):
                first = attempts.begin({'attempt': 1})
                attempts.finish(first, outcome='failure')
                attempts.begin({'attempt': 2})
                self.fail('The second provider attempt must be refused')
        options = args('--runtime-updates', '-C', str(self.workspace), '--resume', str(self.session),
                       '--quiet', '--max-steps', '1')
        supervisor = RuntimeSupervisor(self.session, self.workspace, options, RetryClient(), ROOT)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(supervisor.run_turn('Finish'), 1)
        self.assertIn('task_budget_exhausted', output.getvalue())
        events = LocalRuntime(self.session).journal.read_all()
        self.assertEqual(len([e for e in events if e.kind == 'provider_attempt_started']), 1)

    def test_failure_after_dispatch_never_replays_under_old_version(self):
        client = FinishClient()
        supervisor = self.supervisor(client)
        file = self.workspace / 'reticle/runtime/controller.py'
        source = file.read_text(encoding='utf-8').replace(
            'message = self._normalize(response.message, model_calls)',
            'if self.task.description == "crash-test":\n'
            '                raise RuntimeError("failure after dispatch")\n'
            '            message = self._normalize(response.message, model_calls)')
        file.write_text(source, encoding='utf-8')
        supervisor.stage(self.workspace)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'failure after dispatch'):
            supervisor.run_turn('crash-test')
        self.assertEqual(len(client.requests), 1)
        events = LocalRuntime(self.session).journal.read_all()
        self.assertTrue(any(e.kind == 'runtime_worker_interrupted' and e.payload['replay'] is False for e in events))

    def test_supervisor_caps_model_calls_when_candidate_increases_its_limits(self):
        class ContinuingClient(FinishClient):
            def complete(inner, messages, tools):
                inner.requests.append(messages)
                return response(len(inner.requests), 'note', {'name': 'progress', 'content': 'continue'})
        client = ContinuingClient()
        options = args('--runtime-updates', '-C', str(self.workspace), '--resume', str(self.session),
                       '--quiet', '--max-steps', '1')
        supervisor = RuntimeSupervisor(self.session, self.workspace, options, client, ROOT)
        file = self.workspace / 'reticle/interactive.py'
        source = file.read_text(encoding='utf-8').replace('def launch(args):',
                                                       'def launch(args):\n    args.max_steps = 100')
        file.write_text(source, encoding='utf-8')
        supervisor.stage(self.workspace)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'supervisor model-response limit'):
            supervisor.run_turn('Continue')
        self.assertEqual(len(client.requests), 1)

    def test_active_startup_failure_restores_previous_version(self):
        supervisor = self.supervisor()
        self.change_tools()
        version = supervisor.stage(self.workspace)
        with contextlib.redirect_stdout(io.StringIO()):
            supervisor.run_turn('Promote')
        file = supervisor.bundles.path(version) / 'reticle/tools/primitives.py'
        file.write_text('tampered\n', encoding='utf-8')
        resumed = self.supervisor()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(resumed.run_turn('Use fallback'), 0)
        self.assertIn('restored', output.getvalue())
        self.assertEqual(resumed.bundles.state['active'], resumed.bundles.state['baseline'])
        self.assertTrue(any(e.kind == 'runtime_rolled_back' for e in LocalRuntime(self.session).journal.read_all()))

    def test_activation_waits_for_unknown_external_effects(self):
        client = FinishClient()
        supervisor = self.supervisor(client)
        self.change_tools()
        supervisor.stage(self.workspace)
        runtime = LocalRuntime(self.session)
        runtime.begin_action('unfinished', 'execute', {'command': ['unknown-command']})
        runtime.mark_action_dispatched('unfinished', 'workspace_mutation')
        with self.assertRaisesRegex(RuntimeError, 'reconciled'):
            supervisor.run_turn('Do not dispatch')
        self.assertEqual(client.requests, [])
        self.assertIsNotNone(supervisor.bundles.state['pending'])

    def test_recovery_launcher_imports_saved_code_when_checkout_is_broken(self):
        supervisor = self.supervisor()
        (self.workspace / 'reticle/__init__.py').write_text('invalid python !\n', encoding='utf-8')
        completed = subprocess.run([sys.executable, str(supervisor.bundles.root / 'resume.py'), '--help'],
                                   cwd=self.workspace, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('--runtime-updates', completed.stdout)

    def test_check_mode_does_not_create_a_supervisor_or_session(self):
        missing = self.workspace / '.reticle/new-session'
        with patch('reticle.interactive.connection') as client:
            self.assertEqual(launch(args('--runtime-updates', '--check', '--session-dir', str(missing))), 0)
        self.assertFalse(missing.exists())
