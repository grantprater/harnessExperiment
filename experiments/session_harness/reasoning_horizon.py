"""Paired, three-stage evidence-memory versus symbolic reasoning pilot.

Evaluator inputs and gold implementation stay outside candidate workspaces.
Prepare verifies gold/noop controls; execute never changes the frozen protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/reasoning-horizon-002'
IMAGE = 'docker.io/library/python:3.13-alpine'
ARMS = ('memory', 'symbolic')
STEPS = 18

LEDGER_GOLD = '''def reconcile(events, holds, now):
    import policy
    chosen = {}
    for e in events:
        if not policy.DEDUP_BEFORE_TIME_FILTER and e['at'] > now:
            continue
        key = (e['id'], e['sku']) if policy.DEDUP_PER_SKU else e['id']
        if policy.DUPLICATES == 'last' or key not in chosen:
            chosen[key] = e
    balances = {}
    for e in chosen.values():
        if e['at'] > now:
            continue
        key = e['sku']
        balances[key] = balances.get(key, 0) + (e['qty'] if e['kind'] == 'credit' else -e['qty'])
    if policy.HOLDS_ENABLED:
        for h in holds:
            active = h['expires'] >= now if policy.EXPIRY_INCLUSIVE else h['expires'] > now
            if active:
                balances[h['sku']] = balances.get(h['sku'], 0) - h['qty']
    return balances
'''
SCHEDULER_GOLD = '''def schedule(jobs, now, capacity, completed=()):
    import policy
    chosen = {}
    for j in jobs:
        if policy.DUPLICATES == 'last' or j['id'] not in chosen:
            chosen[j['id']] = j
    eligible = []
    for j in chosen.values():
        live = j['deadline'] >= now if policy.DEADLINE_INCLUSIVE else j['deadline'] > now
        if j['release'] <= now and live:
            eligible.append(j)
    eligible.sort(key=lambda j: (j['priority'] if policy.LOW_PRIORITY_FIRST else -j['priority'], j['deadline'], j['id']))
    result = []
    for j in eligible:
        ready = set(completed) | (set(result) if policy.SAME_ROUND_DEPENDENCIES else set())
        if policy.DEPENDENCIES_ENABLED and not set(j.get('deps', [])) <= ready:
            continue
        if j['weight'] <= capacity:
            result.append(j['id'])
            capacity -= j['weight']
    return result
'''
GOLD = {'ledger': LEDGER_GOLD, 'scheduler': SCHEDULER_GOLD}
NOOP = {'ledger': 'def reconcile(events, holds, now):\n    return {}\n',
        'scheduler': 'def schedule(jobs, now, capacity, completed=()):\n    return []\n'}
SPEC = {
    'ledger': '''Implement client.reconcile(events, holds, now) -> dict[str,int].
Inputs have valid types: ids/skus are strings, qty/at/expires/now are integers;
qty is nonnegative and kind is credit or debit. Do not mutate caller inputs.
Ignore events with at > now BEFORE deduplication. Deduplicate globally by event id,
retaining the first or last eligible entry IN INPUT ORDER according to policy.DUPLICATES.
Sum credits minus debits per sku, keeping zero and negative totals in the result.
When HOLDS_ENABLED, subtract every active hold's qty from its sku, even if the sku
has no events. Holds are not deduplicated. Active means expires >= now when
EXPIRY_INCLUSIVE, otherwise expires > now. Disabled holds are ignored.
These exact field names and rules are the complete contract. Read policy.py.
''',
    'scheduler': '''Implement client.schedule(jobs, now, capacity, completed=()) -> list[str].
Each job has string id, integer release/deadline/priority, nonnegative integer weight,
and optional deps: list[str]. now and capacity are nonnegative integers.
Do not mutate inputs. Deduplicate globally by id first, retaining the first or last
entry IN INPUT ORDER according to policy.DUPLICATES, then filter eligibility.
Eligible means release <= now and deadline >= now when DEADLINE_INCLUSIVE,
otherwise deadline > now. If DEPENDENCIES_ENABLED, all deps must be in the INPUT
completed set; jobs selected this round do not satisfy dependencies this round.
Order eligible jobs by priority descending, or ascending when LOW_PRIORITY_FIRST,
then deadline ascending, then id lexicographically ascending. Walk that order:
select a job if weight <= remaining capacity and deduct weight; skip oversized
jobs and continue. Zero weight jobs are allowed. Return selected ids in order.
These exact field names and rules are the complete contract. Read policy.py.
'''}


def policy(family, stage):
    values = ({'DUPLICATES': 'last' if stage == 2 else 'first',
               'HOLDS_ENABLED': stage >= 1, 'EXPIRY_INCLUSIVE': stage != 2,
               'DEDUP_PER_SKU': stage == 2, 'DEDUP_BEFORE_TIME_FILTER': stage == 2}
              if family == 'ledger' else
              {'DUPLICATES': 'last' if stage == 2 else 'first', 'DEPENDENCIES_ENABLED': stage >= 1,
               'DEADLINE_INCLUSIVE': stage != 2, 'LOW_PRIORITY_FIRST': stage == 2,
               'SAME_ROUND_DEPENDENCIES': stage == 2})
    return ''.join(f'{key} = {value!r}\n' for key, value in values.items())


def specification(family, stage):
    text = SPEC[family]
    if family == 'ledger':
        if stage == 0:
            begin = text.index('When HOLDS_ENABLED')
            text = text[:begin] + 'Holds are ignored in this release.\n' + text[text.index('These exact'):]
        if stage == 2:
            text = text.replace('Ignore events with at > now BEFORE deduplication. Deduplicate globally by event id,',
                                'Deduplicate by (event id, sku) pair BEFORE excluding events with at > now,')
            text = text.replace('eligible entry IN INPUT ORDER', 'entry IN INPUT ORDER')
    else:
        if stage == 0:
            begin, end = text.index('If DEPENDENCIES_ENABLED'), text.index('Order eligible')
            text = text[:begin] + 'Ignore deps and completed in this release.\n' + text[end:]
        if stage == 2:
            begin, end = text.index('If DEPENDENCIES_ENABLED'), text.index('Order eligible')
            text = text[:begin] + ('Dependencies are checked during the sorted selection walk: all deps must be in the INPUT '
                'completed set or in ids ALREADY selected earlier this round. A skipped job is never reconsidered.\n') + text[end:]
    return text


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def gold_result(family, stage, args):
    import types
    namespace = {}
    old = sys.modules.get('policy')
    module = types.ModuleType('policy')
    exec(policy(family, stage), module.__dict__)
    sys.modules['policy'] = module
    try:
        exec(GOLD[family], namespace)
        return namespace['reconcile' if family == 'ledger' else 'schedule'](*args)
    finally:
        if old is None:
            sys.modules.pop('policy', None)
        else:
            sys.modules['policy'] = old


def cases(family, stage, seed=7319):
    rng = random.Random(seed)
    args = []
    if family == 'ledger':
        def event(id, sku='A', qty=5, kind='credit', at=10):
            return dict(id=id, sku=sku, qty=qty, kind=kind, at=at)
        args = [[[], [], 10], [[event('x')], [], 10],
                [[event('x'), event('x', qty=9)], [], 10],
                [[event('x', at=11), event('x', qty=7)], [], 10],
                [[event('x'), event('y', kind='debit')], [], 10],
                [[event('x'), event('x', sku='B', kind='debit')], [], 10]]
        for expiry in (9, 10, 11):
            args.append([[event('x')], [dict(sku='B', qty=3, expires=expiry)], 10])
        for _ in range(24):
            events = [event(str(rng.randrange(6)), rng.choice('ABC'), rng.randrange(10),
                            rng.choice(('credit', 'debit')), rng.randrange(8, 13)) for _ in range(12)]
            holds = [dict(sku=rng.choice('ABCD'), qty=rng.randrange(6), expires=rng.randrange(8, 13)) for _ in range(6)]
            args.append([events, holds, 10])
    else:
        def job(id, **kw):
            return dict(id=id, release=kw.get('release', 10), deadline=kw.get('deadline', 12),
                        priority=kw.get('priority', 2), weight=kw.get('weight', 1), deps=kw.get('deps', []))
        args = [[[], 10, 3, []], [[job('x')], 10, 1, []],
                [[job('x', deadline=10)], 10, 1, []],
                [[job('x', release=11), job('x')], 10, 1, []],
                [[job('a', deps=['b']), job('b')], 10, 2, []],
                [[job('a', deps=['b'])], 10, 2, ['b']],
                [[job('a', weight=4, priority=9), job('b')], 10, 1, []],
                [[job('a', weight=0)], 10, 0, []],
                [[job('z'), job('a')], 10, 1, []]]
        for _ in range(24):
            jobs = [job(str(rng.randrange(8)), release=rng.randrange(8, 13), deadline=rng.randrange(9, 15),
                        priority=rng.randrange(5), weight=rng.randrange(5),
                        deps=rng.choice(([], ['done'], ['missing']))) for _ in range(14)]
            args.append([jobs, 10, rng.randrange(1, 12), ['done']])
    return [{'args': a, 'expected': gold_result(family, stage, a)} for a in args]


EVALUATOR = '''import copy, json, client, sys
cases = json.load(sys.stdin)
outcomes = []
fn = getattr(client, sys.argv[1])
for case in cases:
    arguments = copy.deepcopy(case['args'])
    before = copy.deepcopy(arguments)
    try:
        outcomes.append(fn(*arguments) == case['expected'] and arguments == before)
    except Exception:
        outcomes.append(False)
print(json.dumps({'passed': all(outcomes), 'checks': len(outcomes), 'outcomes': outcomes}))
'''


def evaluate(workspace, family, stage):
    run = subprocess.run([sys.executable, '-c', EVALUATOR, 'reconcile' if family == 'ledger' else 'schedule'],
                         input=json.dumps(cases(family, stage)), text=True, capture_output=True,
                         cwd=workspace, timeout=30,
                         env=dict(os.environ, PYTHONPATH=str(workspace), PYTHONDONTWRITEBYTECODE='1'))
    try:
        result = json.loads(run.stdout)
        if run.returncode or result['checks'] != len(cases(family, stage)):
            raise ValueError('invalid evaluator result')
        return result
    except (ValueError, KeyError):
        return {'passed': False, 'error': 'evaluator failed', 'stderr': run.stderr[-2000:]}


def evaluate_container(backend, workspace, family, stage):
    from reticle.execution import ExecutionRequest
    save(workspace / 'cases.json', cases(family, stage))
    function = 'reconcile' if family == 'ledger' else 'schedule'
    code = (f'import sys; sys.dont_write_bytecode=True; sys.argv=["evaluate", {function!r}]; '
            'sys.stdin=open("cases.json", encoding="utf-8");\n' + EVALUATOR)
    (workspace / 'evaluate.py').write_bytes(code.encode())
    checked = backend.run(ExecutionRequest(command=['python', 'evaluate.py'],
        working_directory=workspace, timeout_seconds=30, output_limit_bytes=30000))
    try:
        evaluation = json.loads(checked.stdout)
        if checked.exit_code or evaluation['checks'] != len(cases(family, stage)):
            raise ValueError('Invalid evaluation')
        return evaluation
    except (ValueError, KeyError):
        return {'passed': False, 'error': 'container evaluator failed',
                'stderr': checked.stderr.decode(errors='replace')[-2000:]}


def fixture(workspace, family, stage):
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / 'policy.py').write_bytes(policy(family, stage).encode())
    (workspace / 'SPEC.md').write_bytes(specification(family, stage).encode())
    # Visible checks cover multiple nontrivial examples; hidden inputs use another seed.
    samples = cases(family, stage, seed=173)[:9]
    function = 'reconcile' if family == 'ledger' else 'schedule'
    smoke = 'import client\n' + ''.join(f'assert client.{function}(*{c["args"]!r}) == {c["expected"]!r}\n' for c in samples)
    (workspace / 'smoke.py').write_bytes(smoke.encode())
    if not (workspace / 'client.py').exists():
        (workspace / 'client.py').write_bytes(NOOP[family].encode())


def sources():
    roots = [ROOT / 'reticle', Path(__file__)]
    files = [p for root in roots for p in (root.rglob('*.py') if root.is_dir() else [root])]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def prepare(out):
    if (out / 'protocol.json').exists():
        raise RuntimeError('Output already prepared; select a fresh --out directory.')
    controls = []
    for family in GOLD:
        for stage in range(3):
            workspace = out / 'controls' / family / str(stage)
            fixture(workspace, family, stage)
            for label, implementation in (('gold', GOLD[family]), ('noop', NOOP[family])):
                (workspace / 'client.py').write_bytes(implementation.encode())
                result = evaluate(workspace, family, stage)
                if result['passed'] != (label == 'gold'):
                    raise RuntimeError(f'Bad evaluator control: {family}/{stage}/{label}')
                controls.append({'family': family, 'stage': stage, 'control': label, **result})
    order = []
    for index, family in enumerate(GOLD):
        arms = ARMS if index == 0 else tuple(reversed(ARMS))
        order.extend({'family': family, 'arm': arm} for arm in arms)
    save(out / 'controls.json', controls)
    save(out / 'protocol.json', {'name': out.name, 'model': 'gpt-6.1-sol', 'backend': 'isolated-oci',
        'engine': 'podman', 'image': IMAGE, 'order': order, 'stages': 3, 'max_responses_per_stage': STEPS,
        'maximum_responses': len(order) * 3 * STEPS, 'context_bytes': 60000,
        'source_hashes': sources(), 'primary': 'independent correctness and integrity within budget',
        'secondary': ['phase correctness', 'responses', 'actions', 'tokens', 'rule exposures', 'graph usage'],
        'limits': 'Two task families, one trajectory per arm per family; pilot, not statistical evidence.'})
    save(out / 'state.json', {'status': 'prepared', 'completed': 0, 'total': 12})


def update_report(out, rows, status):
    save(out / 'results.json', rows)
    save(out / 'state.json', {'status': status, 'completed': len(rows), 'total': 12})
    lines = ['# Symbolic versus evidence-memory horizon pilot', '', f'Status: {status}.', '',
             '| Mode | Accepted stages | Independently correct | Responses |', '|---|---:|---:|---:|']
    for arm in ARMS:
        selected = [r for r in rows if r['arm'] == arm]
        lines.append(f'| {arm} | {sum(r["accepted"] for r in selected)}/{len(selected)} | '
                     f'{sum(r["evaluation"]["passed"] for r in selected)}/{len(selected)} | '
                     f'{sum(r["responses"] for r in selected)} |')
    lines.extend(['', 'Each trajectory spans implementation, extension, and a policy regime change in one durable session.',
                  'All checks run in Podman; model calls and the controller stay on the host.',
                  'Evidence-memory and symbolic modes share tools, schemas, instructions and budgets.',
                  'Only symbolic mode returns rule-derived findings. Outcomes never enter subsequent model contexts.',
                  'This small pilot measures implemented advisory rules, not general symbolic reasoning capability.'])
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def execute(out):
    from reticle.execution import ExecutionRequest, IsolatedOCIBackend
    protocol = json.loads((out / 'protocol.json').read_text())
    if sources() != protocol['source_hashes']:
        raise RuntimeError('Sources changed after prepare; use a fresh protocol.')
    if (out / 'results.json').exists():
        raise RuntimeError('Already executed; automatic replay is disabled.')
    backend = IsolatedOCIBackend(IMAGE, engine='podman')
    probe = out / 'probe'
    probe.mkdir(exist_ok=True)
    result = backend.run(ExecutionRequest(command=['python', '-c', 'print("container ready")'],
                        working_directory=probe, timeout_seconds=30, output_limit_bytes=10000))
    if result.exit_code != 0:
        raise RuntimeError('Container preflight failed: ' + result.stderr.decode(errors='replace'))
    image = subprocess.run(['podman', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'],
                           text=True, capture_output=True, check=True, timeout=20)
    # Record resolved image identity; no image download or changes are permitted.
    save(out / 'execution-environment.json', {'image_id': image.stdout.strip(), 'image': IMAGE})
    pinned_image = image.stdout.strip()
    backend = IsolatedOCIBackend(pinned_image, engine='podman')
    rows = []
    update_report(out, rows, 'running')
    for item in protocol['order']:
        family, arm = item['family'], item['arm']
        run_root = out / 'runs' / f'{family}-{arm}'
        workspace, session = run_root / 'workspace', run_root / 'session'
        for stage in range(3):
            fixture(workspace, family, stage)
            protected = {p.name: p.read_bytes() for p in workspace.iterdir() if p.name != 'client.py' and p.is_file()}
            phase = run_root / f'phase-{stage}'
            phase.mkdir(parents=True)
            task = (f'Stage {stage + 1}/3: ' + ('Implement the system.' if stage == 0 else
                    'Extend the system; holds/dependencies are now enabled.' if stage == 1 else
                    'The policy regime has changed. Earlier conclusions and checks may no longer apply.') +
                    '\nRead SPEC.md and policy.py. Only client.py may be edited; preserve the API and caller inputs. '
                    'Use python smoke.py and additional focused tests via python -c; do not add files. '
                    'Keep durable evidence using reasoning tools: record requirements/case classes, competing hypotheses, '
                    'checks with predictions and observed outcomes, and revise conclusions when evidence changes. '
                    'Use reasoning_state or assess_check before relying on earlier evidence and before finish. '
                    'Graph entries and findings are advisory; verify by running code. Finish when implemented and checked.')
            argv = [sys.executable, '-u', '-m', 'reticle', task, '-C', str(workspace), '--once',
                    '--client', 'chatgpt-subscription', '--model', protocol['model'], '--reasoning', arm,
                    '--max-steps', str(STEPS), '--max-context-bytes', '60000', '--backend', 'isolated-oci',
                    '--container-engine', 'podman', '--container-image', pinned_image,
                    '--resume' if stage else '--session-dir', str(session)]
            save(phase / 'invocation.json', {'argv': argv})
            started = time.monotonic()
            with (phase / 'stdout.txt').open('w', encoding='utf-8') as stdout, (phase / 'stderr.txt').open('w', encoding='utf-8') as stderr:
                run = subprocess.run(argv, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8'),
                                     stdout=stdout, stderr=stderr, timeout=1800)
            evaluation_workspace = phase / 'evaluation-workspace'
            evaluation_workspace.mkdir()
            shutil.copyfile(workspace / 'client.py', evaluation_workspace / 'client.py')
            (evaluation_workspace / 'policy.py').write_bytes(policy(family, stage).encode())
            evaluation = evaluate_container(backend, evaluation_workspace, family, stage)
            integrity = all((workspace / name).exists() and (workspace / name).read_bytes() == raw for name, raw in protected.items())
            extra = [p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.relative_to(workspace).as_posix() not in {*protected, 'client.py'}]
            events = [json.loads(line) for line in (session / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
            previous = rows[-1]['high_water'] if stage else 0
            current = [e for e in events if e['sequence'] > previous]
            calls = [e for e in current if e['kind'] == 'model_call']
            from reticle.runtime.session import LocalRuntime
            runtime = LocalRuntime(session)
            exposures = {}
            for e in current:
                if e['kind'] != 'tool_output' or e['payload']['tool'] not in {'reasoning_state', 'assess_check'}:
                    continue
                try:
                    state = json.loads(runtime.artifacts.read(e['payload']['artifact_id']))
                    for finding in state.get('findings', []):
                        exposures[finding['rule']] = exposures.get(finding['rule'], 0) + 1
                except (ValueError, KeyError):
                    continue
            row = dict(item, stage=stage, agent_exit_code=run.returncode, evaluation=evaluation,
                       integrity=integrity, extra_files=extra, accepted=run.returncode == 0 and evaluation['passed'] and integrity and not extra,
                       responses=len(calls), actions=sum(e['kind'] == 'action_intent' for e in current),
                       graph_updates=sum(e['kind'] == 'reasoning_update' for e in current),
                       rule_exposures=exposures,
                       input_tokens=sum((e['payload'].get('usage') or {}).get('prompt_tokens') or 0 for e in calls),
                       elapsed_seconds=time.monotonic() - started, high_water=events[-1]['sequence'])
            # Immutable per-stage artifact before later edits; evaluator outcomes never join session journals.
            (phase / 'client.py').write_bytes((workspace / 'client.py').read_bytes())
            save(phase / 'result.json', row)
            rows.append(row)
            update_report(out, rows, 'running')
    update_report(out, rows, 'complete')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        (prepare if args.prepare else execute)(out)
    except Exception as exc:
        save(out / 'failure.json', {'type': type(exc).__name__, 'message': str(exc)})
        raise


if __name__ == '__main__':
    main()
