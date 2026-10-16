"""Three-arm, eighteen-run post-edit check experiment. Live runs are explicit."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.controlled import TASKS
from reticle.context.baseline import BaselineContextPolicy
from reticle.cognitive.chatgpt_subscription import ChatGPTSubscriptionClient
from reticle.runtime.check_hooks import FixedUnittestCheck, VERSION
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.runtime.session import LocalRuntime
from reticle.runtime.telemetry import usage_report
from reticle.storage.artifacts import atomic_write_json
from reticle.tools.check_hooks import ARMS, CheckHookTools

PROTOCOL = 'post-edit-check-probe-v1'
FIXTURES = ROOT/'experiments/pilot/fixtures'
REFERENCES = ROOT/'experiments/pilot/reference'
INSTRUCTIONS = '''Work through the provided tools to repair the project according to the task.
Existing source files may be edited; tests are read-only. outline provides Python
structure; read_file provides exact numbered source. verify runs the fixed tests
and returns full results in every condition. finish ends your attempt; acceptance
is evaluated separately on a fresh snapshot using the original tests.
Automatic conditions run those same tests synchronously after each successful
source-changing edit. Check receipts and failures describe the check, not task
acceptance. An unchanged edit or rejected edit does not run a hook. An execution
error, timeout or stale check must be investigated. Full evidence handles can be
retrieved through read_output/search_output. Choose economical steps; finish once
you have evidence your implementation satisfies the task.
'''


class FixedTranscriptPolicy(BaselineContextPolicy):
    """Retain the complete transcript: representation is the only output treatment."""
    policy_version = 'check-probe-full-transcript-v1'

    def build(self, runtime, task, transcript, tools, max_context_bytes,
              diagnostics=None, resource_status=None):
        messages = [{'role': 'system', 'content': task.description}, *transcript]
        if resource_status:
            messages.append({'role': 'user', 'content': 'Resources: '+json.dumps(resource_status),
                             '_context_id': 'resource-status'})
        return self._record(runtime, task, messages, tools, max_context_bytes,
            [{'kind': 'full_transcript', 'message_count': len(transcript)}], [], diagnostics or [])


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(directory).glob('*.py'))}


def source_paths(task):
    return sorted(name for name in hashes(FIXTURES/task) if name != 'test_contract.py')


def prepare(run, task, arm):
    workspace = run/'workspace'
    shutil.copytree(FIXTURES/task, workspace)
    runtime = LocalRuntime(run/'session', workspace)
    checker = FixedUnittestCheck(workspace, sys.executable)
    tools = CheckHookTools(runtime, interpreter=sys.executable, checker=checker,
                           source_paths=source_paths(task), arm=arm)
    return runtime, tools


def independent_evaluation(workspace, task):
    # The evaluator receives only whitelisted candidate source plus original tests.
    with tempfile.TemporaryDirectory(prefix='check-probe-eval-') as directory:
        snapshot = Path(directory)
        for name in source_paths(task):
            shutil.copyfile(workspace/name, snapshot/name)
        shutil.copyfile(FIXTURES/task/'test_contract.py', snapshot/'test_contract.py')
        result = FixedUnittestCheck(snapshot, sys.executable)()
    return {'accepted': result['status'] == 'passed', 'source': 'Fresh-snapshot original public test suite',
            'protocol_id': PROTOCOL, 'result': result}


def action(name, arguments, index):
    return {'id': f'control_{index}', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}


class ControlClient:
    def __init__(self, task, kind):
        writes = []
        if kind == 'gold':
            writes = [('write_file', {'path': name, 'content': (REFERENCES/task/name).read_text(encoding='utf-8')})
                      for name in source_paths(task)
                      if (REFERENCES/task/name).read_bytes() != (FIXTURES/task/name).read_bytes()]
        elif kind == 'breaker':
            writes = [('write_file', {'path': source_paths(task)[0], 'content': 'this is invalid python !!!\n'})]
        elif kind != 'noop':
            raise ValueError('Unknown control')
        self.responses = [[action(name, args, i)] for i, (name, args) in enumerate(writes)]
        self.responses.append([action('finish', {'summary': kind+' control'}, len(writes))])

    def complete(self, messages, tools):
        return ModelResponse({'role': 'assistant', 'content': None,
                              'tool_calls': self.responses.pop(0)}, usage=None)


def run_attempt(run, task_name, arm, client, *, max_calls=12, max_context_bytes=200000):
    runtime, tools = prepare(run, task_name, arm)
    condition = {'manual': 'No automatic checks. Invoke verify when useful.',
                 'automatic-full': 'Automatic checks return full test output after source-changing edits.',
                 'automatic-selective': 'Automatic checks return a success receipt or failure diagnostics after source-changing edits.'}[arm]
    description = INSTRUCTIONS + '\nCondition: '+condition+'\nTask: '+TASKS[task_name]+\
        '\nFiles: '+', '.join(hashes(runtime.workspace.root))
    task = TaskEnvelope(run.name, description, budgets={'model_responses': max_calls,
        'model_attempts': max_calls, 'tool_actions': 48, 'active_seconds': 240})
    result = AgentController(runtime, task, tools, client, AgentLimits(max_calls, max_context_bytes),
                             policy=FixedTranscriptPolicy()).run()
    evaluation = independent_evaluation(runtime.workspace.root, task_name)
    original_tests = hashes(FIXTURES/task_name)['test_contract.py']
    if hashes(runtime.workspace.root).get('test_contract.py') != original_tests:
        evaluation.update(accepted=False, integrity_error='Protected tests changed')
    usage = usage_report(runtime)
    events = runtime.journal.read_all()
    checks = [e.payload for e in events if e.kind == 'post_edit_check']
    outputs = [e for e in events if e.kind == 'tool_output']
    retrievals = [e for e in outputs if e.payload['tool'] in {'read_output', 'search_output'}]
    summary = {'status': 'complete' if result.stop_reason == 'finish_requested' else 'incomplete',
        'task': task_name, 'context_policy': arm, 'model': getattr(client, 'model', 'offline-control'),
        'result': result.to_dict(), 'initial_hashes': hashes(FIXTURES/task_name),
        'final_hashes': hashes(runtime.workspace.root),
        'check_invocations': len(checks), 'automatic_checks': sum(c['trigger']=='post_edit' for c in checks),
        'manual_checks': sum(c['trigger']=='manual_verify' for c in checks),
        'check_duration_s': sum(c.get('duration_s') or 0 for c in checks),
        'check_full_bytes': sum(c['full_bytes'] for c in checks),
        'check_visible_bytes': sum(c['visible_bytes'] for c in checks),
        'output_retrievals': len(retrievals), 'check_events': checks,
        'independent_evaluation_duration_s': evaluation['result'].get('duration_s')}
    atomic_write_json(run/'summary.json', summary)
    atomic_write_json(run/'usage.json', usage)
    atomic_write_json(run/'evaluation.json', evaluation)
    return summary, evaluation


def preflight(root):
    before = {task: hashes(FIXTURES/task) for task in TASKS}
    rows = []
    for task in TASKS:
        initial = FixedUnittestCheck(FIXTURES/task, sys.executable)()
        reference = FixedUnittestCheck(REFERENCES/task, sys.executable)()
        if initial['status'] != 'failed' or reference['status'] != 'passed':
            raise ValueError('Fixture/reference validation failed: '+task)
        for arm in ARMS:
            for kind in ('gold', 'noop', 'breaker'):
                summary, evaluation = run_attempt(root/f'{task}-{arm}-{kind}', task, arm, ControlClient(task, kind))
                expected = kind == 'gold'
                if evaluation['accepted'] != expected:
                    raise ValueError('Offline acceptance control failed')
                if kind == 'noop' and summary['check_invocations'] != 0:
                    raise ValueError('Noop unexpectedly ran a check')
                if arm == 'manual' and summary['automatic_checks'] != 0:
                    raise ValueError('Manual arm ran an automatic check')
                if kind == 'gold' and arm != 'manual' and summary['automatic_checks'] < 1:
                    raise ValueError('Automatic arm missed edits')
                rows.append({'task': task, 'arm': arm, 'control': kind,
                             'accepted': evaluation['accepted'], 'checks': summary['check_invocations']})
    if before != {task: hashes(FIXTURES/task) for task in TASKS}:
        raise ValueError('Original fixtures changed')
    value = {'status': 'passed', 'controls': rows, 'fixture_hashes': before,
             'original_fixtures_unchanged': True}
    atomic_write_json(root/'preflight.json', value)
    return value


def comparison(runs):
    groups = []
    for arm in ARMS:
        rows = []
        for run in runs:
            summary = json.loads((run/'summary.json').read_text())
            if summary['context_policy'] != arm:
                continue
            evaluation = json.loads((run/'evaluation.json').read_text())
            usage = json.loads((run/'usage.json').read_text())
            totals = usage['totals']
            values = [totals[k] for k in ('prompt_tokens', 'completion_tokens')]
            known = not usage['failed_model_calls'] and all(v.get('missing_calls') == 0 and
                    isinstance(v.get('reported'), (int, float)) for v in values)
            tokens = sum(v['reported'] for v in values) if known else None
            rows.append({'run': run.name, 'task': summary['task'], 'accepted': evaluation['accepted'],
                'stop_reason': summary['result']['stop_reason'], 'tokens': tokens,
                'model_calls': summary['result']['model_calls'], 'tool_calls': summary['result']['tool_calls'],
                **{key: summary[key] for key in ('automatic_checks', 'manual_checks',
                                                'output_retrievals', 'check_duration_s')}})
        accepted = sum(r['accepted'] for r in rows)
        total = sum(r['tokens'] for r in rows) if rows and all(r['tokens'] is not None for r in rows) else None
        groups.append({'arm': arm, 'attempts': len(rows), 'accepted': accepted,
                       'total_tokens': total, 'tokens_per_accepted': total/accepted if total is not None and accepted else None,
                       'runs': rows})
    return {'protocol_id': PROTOCOL, 'arms': groups,
            'interpretation': 'All attempted-run costs count; incomplete usage stays unknown. Two repeats per task cannot establish broad generality.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Explicitly spend model calls on eighteen runs')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--max-calls', type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 24:
        parser.error('--max-calls must be between 1 and 24')
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    jobs = [(task, arm, repeat) for repeat in (1, 2) for task in TASKS for arm in ARMS]
    random.Random(53).shuffle(jobs)
    config = {'protocol_id': PROTOCOL, 'hook_version': VERSION, 'model': args.model,
        'seed': 53, 'max_calls_per_attempt': args.max_calls, 'max_provider_attempts': 18*args.max_calls,
        'max_context_bytes': 200000, 'instructions': INSTRUCTIONS, 'context_policy': FixedTranscriptPolicy.policy_version,
        'jobs': [{'task': task, 'arm': arm, 'repeat': repeat} for task, arm, repeat in jobs],
        'fixture_hashes': {task: hashes(FIXTURES/task) for task in TASKS},
        'source_hashes': {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in
                         ['reticle/runtime/check_hooks.py', 'reticle/tools/check_hooks.py',
                          'experiments/check_hook_probe/run_probe.py']},
        'decision_rule': 'Report accepted completion and all-attempt cost; no automatic promotion.'}
    atomic_write_json(root/'protocol.json', config)
    preflight(root/'controls')
    atomic_write_json(root/'progress.json', {'status': 'ready', 'completed': 0, 'planned': 18})
    if not args.execute:
        print('Offline preflight passed; eighteen-run schedule saved. No model calls made.')
        return
    runs = []
    for index, (task, arm, repeat) in enumerate(jobs):
        run = root/f'{index:02d}-{task}-{arm}-r{repeat}'
        client = ChatGPTSubscriptionClient(args.model, calls_path=run/'calls.jsonl', timeout=90)
        summary, evaluation = run_attempt(run, task, arm, client, max_calls=args.max_calls)
        runs.append(run)
        atomic_write_json(root/'comparison.json', comparison(runs))
        stopped = summary['result']['stop_reason'] == 'model_error'
        status = 'blocked_provider_error' if stopped else ('complete' if len(runs)==18 else 'running')
        atomic_write_json(root/'progress.json', {'status': status, 'completed': len(runs), 'planned': 18,
                                                'updated_at': datetime.now(timezone.utc).isoformat()})
        print(run.name+': '+summary['result']['stop_reason']+', accepted='+str(evaluation['accepted']), flush=True)
        if stopped:
            break


if __name__ == '__main__':
    main()
