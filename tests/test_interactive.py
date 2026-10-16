"""Interactive launcher exercised against real runtime/tools without paid calls."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reticle.interactive import add_arguments, launch, load_key, connection, selected_model, execution_config, usage_summary
from reticle.runtime.controller import ModelResponse
from reticle.runtime.workspace import WorkspaceTracker


class ScriptedClient:
    def __init__(self):
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        n = len(self.requests)
        calls = ([('write_file', {'path': 'result.txt', 'content': 'edited by harness'})]
                 if n == 1 else [('finish', {'summary': 'Done'})])
        return ModelResponse({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': f'call-{n}-{i}', 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(arguments)}}
            for i, (name, arguments) in enumerate(calls)]})


def args(*argv):
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    return parser.parse_args(argv)


class InteractiveTests(unittest.TestCase):
    def test_usage_is_reported_per_step_turn_and_resumed_session(self):
        class MeteredClient(ScriptedClient):
            def complete(self, messages, tools):
                response = super().complete(messages, tools)
                return ModelResponse(response.message, {'prompt_tokens': 100, 'completion_tokens': 20,
                                                       'prompt_tokens_details': {'cached_tokens': 40}})
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / '.reticle/session'
            client = MeteredClient()
            with patch('reticle.interactive.connection', return_value=client), \
                    patch('builtins.input', side_effect=['Explain', '/usage', '/exit']), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                launch(args('Create', '-C', tmp, '--session-dir', str(session)))
            text = output.getvalue()
            self.assertEqual(text.count('[step 1]'), 2)
            self.assertIn('Turn: 2 model calls, 2 tool calls', text)
            self.assertIn('Session: tokens: input 300, output 60, cached input 120', text)
            with patch('reticle.interactive.connection', return_value=client), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                launch(args('Again', '--resume', str(session), '--once', '--quiet'))
            self.assertNotIn('Thinking', output.getvalue())
            self.assertIn('Done', output.getvalue())
            self.assertIn('Session: tokens: input 400, output 80, cached input 160', output.getvalue())

    def test_missing_usage_is_not_claimed_to_be_zero(self):
        self.assertIn('input unreported', usage_summary([None]))
        self.assertIn('input 100 (partial)', usage_summary([{'prompt_tokens': 100}, None]))
        self.assertIn('cached input unreported', usage_summary([{'prompt_tokens': 100}]))

    def test_container_backend_requires_explicit_image_and_does_not_fallback(self):
        with self.assertRaisesRegex(ValueError, 'requires --container-image'):
            execution_config(args('--backend', 'isolated-oci'))
        with patch('reticle.interactive.IsolatedOCIBackend') as backend:
            backend.return_value.availability.return_value = (False, 'engine offline')
            with self.assertRaisesRegex(RuntimeError, 'engine offline'):
                execution_config(args('--backend', 'isolated-oci', '--container-image', 'local:test'))

    def test_container_python_and_backend_reach_tools(self):
        with patch('reticle.interactive.IsolatedOCIBackend') as backend:
            backend.return_value.availability.return_value = (True, 'available')
            actual, interpreter = execution_config(args('--backend', 'isolated-oci', '--container-image', 'local:test',
                                                       '--container-python', '/usr/local/bin/python'))
            self.assertIs(actual, backend.return_value)
            self.assertEqual(interpreter, '/usr/local/bin/python')
            backend.assert_called_once_with('local:test', engine=None)

    def test_default_is_previous_openai_subscription_model(self):
        parsed = args()
        self.assertEqual(parsed.client, 'chatgpt-subscription')
        self.assertEqual(selected_model(parsed), 'gpt-6.1-sol')
        self.assertEqual(selected_model(args('--client', 'codex')), 'gpt-6.1-sol')

    def test_subscription_check_uses_reticle_login_without_reading_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('reticle.cognitive.chatgpt_auth.ChatGPTAuth') as auth, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                auth.return_value.path = Path(tmp) / 'credentials.dat'
                auth.return_value.path.write_bytes(b'protected')
                connection(args('--check'))
                auth.return_value.access_token.assert_not_called()
                self.assertIn('OpenAI subscription', output.getvalue())

    def test_edit_followup_and_resume_keep_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / '.reticle/session'
            client = ScriptedClient()
            with patch('reticle.interactive.connection', return_value=client), \
                    patch('builtins.input', side_effect=['Explain result', '/exit']), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(launch(args('Create result', '-C', tmp, '--session-dir', str(session), '--context-policy', 'pressure-v4')), 0)
            self.assertEqual((root / 'result.txt').read_text(), 'edited by harness')
            self.assertTrue(any(m.get('content') == 'Create result' for m in client.requests[-1]))
            self.assertTrue(any(m.get('content') == 'Explain result' for m in client.requests[-1]))
            with patch('reticle.interactive.connection', return_value=client), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(launch(args('Check again', '--resume', str(session), '--once', '--context-policy', 'pressure-v4')), 0)
            self.assertTrue(any(m.get('content') == 'Explain result' for m in client.requests[-1]))

    def test_check_does_not_create_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / 'session'
            with patch('reticle.interactive.connection') as connect:
                self.assertEqual(launch(args('--check', '--session-dir', str(session))), 0)
                connect.assert_called_once()
            self.assertFalse(session.exists())

    def test_missing_resume_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Saved session'):
                launch(args('--resume', tmp))

    def test_environment_key_wins(self):
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'private-test-value'}):
            self.assertEqual(load_key('OPENROUTER_API_KEY'), 'private-test-value')

    def test_revision_skips_runtime_and_tracks_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source.py').write_text('old')
            tracker = WorkspaceTracker(root)
            before = tracker.revision()
            for name in ['.git', '.venv', '.runtime', '.reticle']:
                (root / name).mkdir()
                (root / name / 'cache').write_text('irrelevant')
            self.assertEqual(before, tracker.revision())
            (root / 'source.py').write_text('new')
            self.assertNotEqual(before, tracker.revision())
