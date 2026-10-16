"""Optional model feedback and batch measurements without real provider calls."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reticle.context import PressureRecentContextPolicyV4
from reticle.runtime.session import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError, ModelResponse
from reticle.runtime.telemetry import aggregate_tokens, usage_report, model_token_usage
from reticle.tools.primitives import ToolSuite
from reticle.interactive import launch
from tests.test_interactive import ScriptedClient, args


class MeteredClient(ScriptedClient):
    def complete(self, messages, tools):
        response = super().complete(messages, tools)
        return ModelResponse(response.message, {'prompt_tokens': 100, 'completion_tokens': 20,
                             'prompt_tokens_details': {'cached_tokens': 40}}, {'model': 'offline', 'provider': 'stub'})


class UsageTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.root / 'session', self.workspace)

    def test_unknown_and_invalid_measurements_are_not_zero(self):
        result = aggregate_tokens([{'prompt_tokens': 100, 'completion_tokens': 0,
                                    'prompt_tokens_details': {'cached_tokens': 40}}, None])
        self.assertEqual(result['prompt_tokens'], {'reported': 100, 'missing_calls': 1})
        self.assertEqual(result['completion_tokens'], {'reported': 0, 'missing_calls': 1})
        self.assertEqual(result['cached_input'], {'reported': 40, 'missing_calls': 1})
        self.assertIsNone(aggregate_tokens([None])['prompt_tokens']['reported'])
        self.assertIsNone(aggregate_tokens([{'prompt_tokens': True}])['prompt_tokens']['reported'])
        self.assertIsNone(aggregate_tokens([{'prompt_tokens': float('nan')}])['prompt_tokens']['reported'])

    def test_model_feedback_is_optional_and_comes_after_the_cacheable_prefix(self):
        for enabled in (False, True):
            runtime = LocalRuntime(self.root / f'session-{enabled}', self.workspace)
            client = MeteredClient()
            AgentController(runtime, TaskEnvelope('task', 'Create a result'),
                            ToolSuite(runtime, interpreter=sys.executable), client, AgentLimits(3, 120000),
                            policy=PressureRecentContextPolicyV4(), expose_usage=enabled).run()
            second = client.requests[1]
            feedback = [m['content'] for m in second if 'Provider-reported token usage' in str(m.get('content'))]
            self.assertEqual(bool(feedback), enabled)
            if enabled:
                self.assertEqual(feedback[0], second[-1]['content'])
                self.assertIn('input 100, output 20, cached input 40', feedback[0])
                self.assertIn('not current context occupancy', feedback[0])
            report = usage_report(runtime)
            self.assertEqual(report['totals']['prompt_tokens']['reported'], 200)
            self.assertEqual(report['totals']['cached_input']['reported'], 80)
            self.assertTrue(all(row['usage_feedback_enabled'] == enabled for row in report['calls']))

    def test_failed_calls_and_legacy_task_mapping_are_explicit(self):
        self.runtime.journal.append('model_request_intent', {'task_id': 'legacy', 'attempt_id': 'r1'})
        self.runtime.journal.append('model_call', {'attempt_id': 'r1', 'usage': {'prompt_tokens': 100},
                                                 'metadata': {'model': 'offline'}})
        self.runtime.journal.append('model_request_intent', {'task_id': 'legacy', 'attempt_id': 'r2'})
        self.runtime.journal.append('model_call_failed', {'attempt_id': 'r2', 'error': 'private text'})
        report = usage_report(self.runtime)
        self.assertEqual(report['failed_model_calls'], 1)
        self.assertEqual(report['totals']['prompt_tokens'], {'reported': 100, 'missing_calls': 1})
        self.assertEqual(report['tasks'][0]['task_id'], 'legacy')
        self.assertIsNone(report['calls'][1]['prompt_tokens'])
        self.assertNotIn('private text', json.dumps(report))
        feedback = model_token_usage(self.runtime, 'legacy')
        self.assertEqual(feedback['task']['calls'], 2)
        self.assertIsNone(feedback['last_call']['prompt_tokens']['reported'])

    def test_cli_report_and_saved_session_export_are_machine_readable(self):
        session = self.root / 'launch-session'
        report_path = self.root / 'usage.json'
        with patch('reticle.interactive.connection', return_value=MeteredClient()), \
                contextlib.redirect_stdout(io.StringIO()):
            code = launch(args('Create result', '-C', str(self.workspace), '--session-dir', str(session),
                               '--once', '--quiet', '--model-usage', '--usage-report', str(report_path)))
        self.assertEqual(code, 0)
        report = json.loads(report_path.read_text())
        self.assertEqual(report['tasks'][0]['stop_reason'], 'finish_requested')
        self.assertEqual(report['calls'][0]['model'], 'offline')
        self.assertTrue(report['calls'][0]['usage_feedback_enabled'])
        completed = subprocess.run([sys.executable, '-m', 'reticle', 'usage', str(session)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), report)

    def test_failed_provider_run_still_writes_a_usage_report(self):
        class FailedClient:
            def complete(self, messages, tools):
                raise ModelClientError('offline failure')
        report_path = self.root / 'failed.json'
        with patch('reticle.interactive.connection', return_value=FailedClient()), \
                contextlib.redirect_stdout(io.StringIO()):
            code = launch(args('Fail', '-C', str(self.workspace), '--session-dir', str(self.root / 'failed-session'),
                               '--once', '--quiet', '--usage-report', str(report_path)))
        self.assertEqual(code, 1)
        report = json.loads(report_path.read_text())
        self.assertEqual(report['tasks'][0]['stop_reason'], 'model_error')
        self.assertEqual(report['failed_model_calls'], 1)
        self.assertIsNone(report['totals']['prompt_tokens']['reported'])

    def test_unfinished_model_request_has_unknown_usage_instead_of_zero(self):
        self.runtime.journal.append('model_request_intent', {'task_id': 'incomplete', 'attempt_id': 'r1'})
        report = usage_report(self.runtime)
        self.assertEqual(report['incomplete_model_calls'], 1)
        self.assertEqual(report['calls'][0]['status'], 'incomplete')
        self.assertEqual(report['totals']['prompt_tokens'], {'reported': None, 'missing_calls': 1})
