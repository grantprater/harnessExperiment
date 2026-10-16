import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from reticle.context import DecisionContextPolicy, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime
from reticle.runtime.decision_state import decision_state
from reticle.runtime.telemetry import usage_report
from reticle.interactive import launch
from tests.test_interactive import args, ScriptedClient
from experiments.policy_bench.compare_runs import compare_runs
from experiments.policy_bench.run_sweep import main as sweep


def result(store, index, name, arguments, status='success', content='result'):
    store.append({'role':'assistant', 'content':None, 'tool_calls':[
        {'id':str(index), 'type':'function', 'function':{'name':name, 'arguments':json.dumps(arguments)}}]})
    store.append({'role':'tool','tool_call_id':str(index),'content':content,
                  '_reticle_output':{'handle':f'out_{index}','tool':name,'status':status}})


class DecisionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.root/'session', self.workspace)
        self.store = TranscriptStore(self.runtime)
        self.task = TaskEnvelope('t','Generate', budgets={'token_target':5000})
        self.store.append({'role':'user','content':'Generate','_reticle_task_id':'t'})

    def test_state_escalates_repeated_failures_across_reads_then_resolves_matching_success(self):
        result(self.store, 1, 'run', {'command':'python build.py'}, 'error')
        result(self.store, 2, 'read_file', {'path':'build.py'})
        result(self.store, 3, 'run', {'command':'python build.py'}, 'error')
        state = decision_state(self.runtime, self.task, self.store.load())
        self.assertIn('repeated_failure_of_same_action', state['escalation_reasons'])
        self.assertEqual(state['acceptance'],'unverified')
        self.assertNotIn('python build.py', json.dumps(state))
        result(self.store, 4, 'run', {'command':'python build.py'})
        state = decision_state(self.runtime, self.task, self.store.load())
        self.assertEqual(state['unresolved_failures'],[])
        self.assertEqual(state['escalation_reasons'],[])

    def test_retrieval_escalation_and_byte_limit_include_state(self):
        for index in range(3):
            result(self.store, index, 'read_file', {'path':f'{index}.py'}, content='x\n'*4000)
        built = DecisionContextPolicy().build(self.runtime, self.task, self.store.load(), [], 6000)
        self.assertLessEqual(built.manifest.request_bytes,6000)
        self.assertFalse(built.over_budget)
        snapshot = [e for e in self.runtime.journal.read_all() if e.kind=='decision_state_snapshot'][-1]
        self.assertIn('retrieval_streak_without_execution',snapshot.payload['escalation_reasons'])
        self.assertEqual(snapshot.payload['routine_view_bytes'],4096)
        self.assertIn('Decision state', built.messages[-1]['content'])
        self.assertEqual(built.manifest.max_context_bytes,6000)

    def test_style_pass_is_measured_evidence_not_acceptance_and_missing_usage_is_unknown(self):
        result(self.store, 1, 'style_check', {'candidate':'a.png'}, content=json.dumps({'measured_checks_passed':False}))
        self.assertEqual(decision_state(self.runtime,self.task,self.store.load())['next_step_hint'],'diagnose')
        result(self.store, 2, 'style_check', {'candidate':'a.png'}, content=json.dumps({'measured_checks_passed':True}))
        self.runtime.journal.append('model_call',{'task_id':'t','usage':None})
        state = decision_state(self.runtime,self.task,self.store.load())
        self.assertEqual(state['unresolved_failures'],[])
        self.assertEqual(state['acceptance'],'unverified')
        self.assertIsNone(state['reported_total_tokens'])
        self.assertFalse(state['usage_complete'])

    def test_model_token_feedback_remains_opt_in(self):
        task = TaskEnvelope('t','Generate')
        built = DecisionContextPolicy().build(self.runtime,task,self.store.load(),[],6000)
        state_text = built.messages[-1]['content']
        self.assertNotIn('reported_total_tokens',state_text)
        self.assertNotIn('usage_complete',state_text)
        with_target = DecisionContextPolicy().build(self.runtime,self.task,self.store.load(),[],6000)
        self.assertIn('reported_total_tokens',with_target.messages[-1]['content'])

    def test_controller_records_policy_state_and_request_size(self):
        client = ScriptedClient()
        with patch('reticle.interactive.connection', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch(args('Create', '-C',str(self.workspace), '--resume',str(self.runtime.session_dir),
                                       '--context-policy','decision','--token-target','5000','--once','--quiet')),0)
        report = usage_report(self.runtime)
        self.assertEqual(report['policy']['versions'],['decision-v1'])
        self.assertEqual(len(report['policy']['decision_snapshots']),2)
        for call in report['calls']:
            self.assertIsNotNone(call['decision_state_event_id'])
            self.assertEqual(call['token_target'],5000)
            self.assertGreater(call['request_bytes'],0)
        self.assertTrue(list((self.runtime.session_dir/'decision-state').glob('*.json')))

    def run_artifact(self, name, accepted, tokens, measured=True):
        path = self.root/name
        path.mkdir()
        (path/'summary.json').write_text(json.dumps({'context_policy':'decision','model':'stub','status':'complete',
                                                    'all_measured_checks_passed':measured}))
        (path/'usage.json').write_text(json.dumps({'totals':{'prompt_tokens':{'reported':tokens,'missing_calls':0},
            'completion_tokens':{'reported':0,'missing_calls':0}},'calls':[{}]}))
        if accepted is not None:
            (path/'evaluation.json').write_text(json.dumps({'accepted':accepted,'source':'independent reviewer','protocol_id':'p1'}))
        return path

    def test_comparison_charges_failed_attempts_and_does_not_infer_quality(self):
        first = self.run_artifact('accepted',True,100)
        second = self.run_artifact('failed',False,200)
        report = compare_runs([first,second])
        self.assertEqual(report['conditions'][0]['tokens_per_accepted_attempt'],300)
        third = self.run_artifact('unknown',None,50)
        report = compare_runs([first,second,third])
        self.assertIsNone(report['conditions'][0]['tokens_per_accepted_attempt'])
        self.assertEqual(report['conditions'][0]['acceptance_unknown'],1)

    def test_comparison_keeps_total_and_uncached_input_separate(self):
        path = self.run_artifact('cached',True,100)
        usage_path = path/'usage.json'
        usage = json.loads(usage_path.read_text())
        usage['totals']['cached_input'] = {'reported':80,'missing_calls':0}
        usage_path.write_text(json.dumps(usage))
        report = compare_runs([path])
        self.assertEqual(report['conditions'][0]['reported_total_tokens_all_attempts'],100)
        self.assertEqual(report['conditions'][0]['reported_uncached_input_all_attempts'],20)

    def test_runner_finished_is_not_model_task_completion(self):
        path = self.run_artifact('limited',True,100)
        summary_path = path/'summary.json'
        summary = json.loads(summary_path.read_text())
        summary['tasks'] = [{'exit_code':1,'usage':{'stop_reason':'model_call_limit'}}]
        summary_path.write_text(json.dumps(summary))
        report = compare_runs([path])
        self.assertFalse(report['runs'][0]['model_tasks_completed'])
        self.assertEqual(report['conditions'][0]['unfinished_attempts'],1)
        self.assertTrue(report['runs'][0]['accepted'])

    def test_sweep_runs_driver_and_preserves_failed_trial_cost(self):
        driver = self.root/'driver.py'
        driver.write_text('''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run-dir');p.add_argument('--variant');a=p.parse_args()
r=Path(a.run_dir);r.mkdir()
(r/'summary.json').write_text(json.dumps({'status':'complete','context_policy':a.variant,'model':'stub','all_measured_checks_passed':True}))
(r/'usage.json').write_text(json.dumps({'totals':{'prompt_tokens':{'reported':100,'missing_calls':0},'completion_tokens':{'reported':20,'missing_calls':0}},'calls':[]}))
raise SystemExit(1 if a.variant=='failed' else 0)
''')
        config = self.root/'config.json'
        config.write_text(json.dumps({'driver':str(driver),'repetitions':1,'variants':[
            {'name':'ok','arguments':['--variant','ok']},{'name':'failed','arguments':['--variant','failed']}]}))
        output = self.root/'sweep'
        with patch.object(sys,'argv',['sweep','--config',str(config),'--output-dir',str(output)]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sweep(),0)
        progress = json.loads((output/'progress.json').read_text())
        self.assertEqual(sorted(row['exit_code'] for row in progress['jobs']),[0,1])
        comparison = json.loads((output/'comparison.json').read_text())
        self.assertEqual(sum(row['reported_total_tokens_all_attempts'] for row in comparison['conditions']),240)
        self.assertEqual(sum(row['acceptance_unknown'] for row in comparison['conditions']),2)
        self.assertEqual(sum(row['unfinished_attempts'] for row in comparison['conditions']),1)


if __name__ == '__main__':
    unittest.main()
