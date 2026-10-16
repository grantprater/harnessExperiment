"""Current decisions are compact; prior evidence remains recoverable on resume."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reticle.context import MinimalContextPolicy, PressureRecentContextPolicyV4, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime
from reticle.runtime.queries import SessionQueryService
from tests.test_interactive import args, ScriptedClient
from reticle.interactive import launch
from tests.test_pressure_context_v4 import exchange


class MinimalContextTests(unittest.TestCase):
    def test_bounds_observation_without_waiting_for_pressure_and_preserves_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'workspace').mkdir()
            runtime = LocalRuntime(Path(directory)/'session', Path(directory)/'workspace')
            store = TranscriptStore(runtime)
            exchange(store, 1, 'BEGIN\n' + 'detail\n'*4000 + 'FAILED important diagnostic\nEND', tool='run', status='error')
            task = TaskEnvelope('task', 'Fix the command')
            minimal = MinimalContextPolicy().build(runtime, task, store.load(), [], 32000)
            full = PressureRecentContextPolicyV4().build(runtime, task, store.load(), [], 120000)
            result = next(m for m in minimal.messages if m['role']=='tool')
            self.assertLess(len(result['content'].encode()), 1200)
            self.assertIn('FAILED important diagnostic', result['content'])
            self.assertIn('read_output', result['content'])
            self.assertLess(minimal.manifest.request_bytes, full.manifest.request_bytes/4)
            self.assertEqual([c['id'] for m in minimal.messages for c in m.get('tool_calls', [])], [result['tool_call_id']])
            self.assertEqual(store.load()[-1]['content'].count('detail'), 4000)

    def test_minimal_handoff_survives_resume_and_exact_prior_prompt_is_retrievable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root/'.reticle/session'
            client = ScriptedClient()
            with patch('reticle.interactive.connection', return_value=client), patch('builtins.input', side_effect=['Explain result', '/exit']), contextlib.redirect_stdout(io.StringIO()):
                launch(args('Create result', '-C', directory, '--session-dir', str(session)))
            combined = json.dumps(client.requests[-1])
            self.assertIn('Prior-task handoff', combined)
            self.assertIn('Create result', combined)
            self.assertIn('result.txt', combined)
            self.assertNotIn('edited by harness', combined)
            self.assertEqual(sum(m.get('role')=='user' for m in client.requests[-1]), 1)
            with patch('reticle.interactive.connection', return_value=client), contextlib.redirect_stdout(io.StringIO()):
                launch(args('Check again', '--resume', str(session), '--once'))
            self.assertIn('Explain result', json.dumps(client.requests[-1]))
            runtime = LocalRuntime(session)
            projection = next(e for e in runtime.journal.read_all() if e.kind=='observation_view' and e.payload.get('source_transcript_artifact_id'))
            self.assertIn('Create result', json.dumps(SessionQueryService(runtime).read_artifact(projection.payload['view_artifact']['artifact_id'])))
            self.assertEqual(args().max_context_bytes, 32000)

    def test_current_turn_corrections_are_not_treated_as_task_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'workspace').mkdir()
            runtime = LocalRuntime(Path(directory)/'session', Path(directory)/'workspace')
            store = TranscriptStore(runtime)
            store.append({'role':'user', 'content':'Build it', '_reticle_task_id':'t'})
            exchange(store, 1, 'result')
            store.append({'role':'user', 'content':'Correction: use olive'})
            built = MinimalContextPolicy().build(runtime, TaskEnvelope('t','Build it'), store.load(), [], 32000)
            self.assertTrue(any(m.get('content')=='Correction: use olive' for m in built.messages))
            self.assertEqual(sum(m.get('content')=='Build it' for m in built.messages), 1)

    def test_only_older_successful_mutations_become_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'workspace').mkdir()
            runtime = LocalRuntime(Path(directory)/'session', Path(directory)/'workspace')
            store = TranscriptStore(runtime)
            def write(index, content, status):
                store.append({'role':'assistant', 'content':None, 'tool_calls':[
                    {'id':f'w{index}', 'type':'function', 'function':{'name':'write_file',
                     'arguments':json.dumps({'path':f'{index}.py','content':content})}}]})
                store.append({'role':'tool', 'tool_call_id':f'w{index}', 'content':'write result',
                              '_reticle_output':{'handle':f'out_{index}', 'tool':'write_file', 'status':status}})
            write(1, 'LARGE_OLD_GENERATION_SOURCE', 'success')
            write(2, 'FAILED_EDIT_SOURCE', 'error')
            write(3, 'LATEST_EDIT_SOURCE', 'success')
            built = MinimalContextPolicy().build(runtime, TaskEnvelope('t','Generate'), store.load(), [], 32000)
            content = json.dumps(built.messages)
            self.assertNotIn('LARGE_OLD_GENERATION_SOURCE', content)
            self.assertIn('1.py', content)
            self.assertIn('out_1', content)
            self.assertIn('FAILED_EDIT_SOURCE', content)
            self.assertIn('LATEST_EDIT_SOURCE', content)
            self.assertEqual([c['id'] for m in built.messages for c in m.get('tool_calls', [])], ['w2','w3'])


if __name__ == '__main__':
    unittest.main()
