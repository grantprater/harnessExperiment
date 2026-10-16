"""Explicit twelve-call conditional observation probe; no automatic retries."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reticle.cognitive.chatgpt_subscription import ChatGPTSubscriptionClient
from reticle.runtime.controller import ModelClientError
from reticle.runtime.observation_delta import VERSION, encoded, fingerprint, reconstruct, select_observation
from reticle.runtime.refinements import RefinementRecords
from reticle.runtime.session import LocalRuntime
from reticle.storage.artifacts import atomic_write_json

PROTOCOL = 'conditional-observation-probe-v1'


def fixtures():
    cases = []
    for domain in ['checks', 'ui']:
        original = {f'{domain}_{i:02d}':
                    ({'status': 'passed', 'contract': 'Restart preserves delivery identity.', 'revision': 1}
                     if domain == 'checks' else
                     {'status': 'passed', 'font': 'Project Sans', 'radius_px': 8,
                      'contrast_pass': True, 'revision': 1}) for i in range(8)}
        original[f'{domain}_03']['status'] = 'failed'
        original[f'{domain}_06']['status'] = 'failed'
        middle = deepcopy(original)
        middle[f'{domain}_03']['status'] = 'passed'
        middle[f'{domain}_07']['status'] = 'failed'
        for condition in ['sparse', 'dense', 'missing-baseline']:
            current = deepcopy(middle)
            current[f'{domain}_07']['status'] = 'passed'
            current[f'{domain}_05']['status'] = 'failed'
            if condition == 'dense':
                for record in current.values():
                    record['revision'] = 2
            cases.append({'id': domain+'-'+condition, 'domain': domain, 'condition': condition,
                          'original': original, 'baseline': middle, 'current': current,
                          'retained': condition != 'missing-baseline',
                          'expected': {'failed_keys': [f'{domain}_05', f'{domain}_06'], 'next_action': 'repair'}})
    return cases


def request(case, arm):
    full, _ = select_observation(case['current'])
    selected, selection = select_observation(case['current'], baseline=case['baseline'],
        retained_baselines=[fingerprint(case['baseline'])] if case['retained'] else [], stable_ids=True)
    latest = full if arm == 'full' else selected
    messages = [
        {'role': 'system', 'content': 'Interpret exact structured observations. Full observations replace the '
         'current snapshot. Delta observations replace/remove listed records against the identified retained '
         'baseline; omitted records are unchanged. Return only JSON: failed_keys (sorted array of IDs whose '
         'current status is failed), next_action (repair if any current record failed, otherwise accept).'},
        {'role': 'user', 'content': ('Inspect the latest '+case['domain']+' observation after revisions. '
         'Report current failures, including those unchanged by the latest revision. '
         'Historical failures that have passed are resolved. UI measurements do not establish aesthetic quality.')},
    ]
    if case['retained']:
        for index, snapshot in enumerate([case['original'], case['baseline']]):
            observation, _ = select_observation(snapshot)
            call = f'prior_{index}'
            messages += [
                {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': call, 'type': 'function', 'function': {'name': 'observe', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': call, 'content': encoded(observation).decode()},
            ]
    messages += [
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'current', 'type': 'function', 'function': {'name': 'observe', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'current', 'content': encoded(latest).decode()},
    ]
    return messages, selection


def preflight(cases):
    for case in cases:
        full, _ = request(case, 'full')
        adaptive, selection = request(case, 'adaptive')
        assert full[:-1] == adaptive[:-1]
        observation = json.loads(adaptive[-1]['content'])
        if observation['kind'] == 'delta':
            assert reconstruct(case['baseline'], observation) == case['current']
        else:
            assert full == adaptive
        expected = {'sparse': 'retained_sparse_smaller', 'dense': 'changes_not_sparse',
                    'missing-baseline': 'baseline_not_retained'}[case['condition']]
        assert selection['reason'] == expected
    return {'exact_reconstruction': True, 'identical_pair_prefixes': True,
            'dense_and_missing_baseline_use_identical_full_requests': True}


def summarize(trials, expected_count):
    totals = {}
    complete = len(trials) == expected_count
    for trial in trials:
        usage = trial.get('usage') or {}
        values = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
        if any(type(v) is not int or v < 0 for v in values):
            complete = False
        else:
            totals[trial['arm']] = totals.get(trial['arm'], 0) + sum(values)
    all_accepted = len(trials) == expected_count and all(t.get('accepted') is True for t in trials)
    decision = 'inconclusive'
    if complete and all_accepted and totals.get('adaptive', 0) < totals.get('full', 0):
        decision = 'scoped_support'
    elif len(trials) == expected_count and any(t.get('accepted') is False and t['arm'] == 'adaptive' for t in trials):
        decision = 'rejected'
    return {'protocol_id': PROTOCOL, 'scope': 'Fixed two-revision structured fixtures; one sample per cell.',
            'decision': decision, 'usage_complete': complete, 'all_accepted': all_accepted,
            'total_tokens_by_arm': totals if complete else None, 'trials': trials,
            'limitations': ['No interactive task completion or visual review.',
                           'Checks are development domain; UI is a predeclared transfer domain.',
                           'No evidence of agent-discovered conditions or broad generalization.']}


def specification():
    return {'id': 'structured-observation-delta',
        'hypothesis': 'Sparse exact deltas reduce decision cost when their baseline is retained.',
        'weakness': 'Repeated snapshots return unchanged records and obscure changes.',
        'implementation': {'version': VERSION, 'source_sha256': hashlib.sha256(
            (ROOT/'reticle/runtime/observation_delta.py').read_bytes()).hexdigest()},
        'conditions': ['Stable record IDs are explicitly declared by the observer.',
                       'Baseline hash is present in the caller supplied retained-prefix inventory.',
                       'At most 25 percent of record identities changed.',
                       'Serialized delta is smaller than a full observation.'],
        'verified_properties': ['Exact reconstruction verified on fixtures and edge-case tests.',
                                'Full fallback when conditions do not hold.'],
        'limitations': ['Byte savings are not guaranteed token savings.',
                        'Semantic relevance, aesthetic quality and complete dependency coverage are unknown.',
                        'Sparse threshold is a chosen parameter, not a derived optimum.'],
        'prior_evidence': {'path': 'experiments/observation_probe/runs/live-001/summary.json',
                           'sha256': fingerprint(json.loads((ROOT/'experiments/observation_probe/runs/live-001/summary.json').read_text()))},
        'status': 'proposed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--model', default='gpt-6.1-sol')
    options = parser.parse_args()
    run = options.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    cases = fixtures()
    checks = preflight(cases)
    atomic_write_json(run/'fixtures.json', {'protocol_id': PROTOCOL, 'cases': cases})
    atomic_write_json(run/'protocol.json', {'id': PROTOCOL, 'model': options.model, 'seed': 41,
        'max_provider_attempts': 12, 'retries': 0, 'preflight': checks,
        'arms': ['full', 'adaptive'], 'development_domain': 'checks', 'transfer_domain': 'ui',
        'decision_rule': 'Scoped support only if all twelve decisions pass and adaptive total tokens are lower.'})
    runtime = LocalRuntime(run/'session', run)
    records = RefinementRecords(runtime)
    spec = specification()
    proposed = records.save(spec)
    jobs = [(case, arm) for case in cases for arm in ['full', 'adaptive']]
    random.Random(41).shuffle(jobs)
    client = ChatGPTSubscriptionClient(options.model, calls_path=run/'calls.jsonl', timeout=90)
    report = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
              'proposed_record_artifact': proposed, 'trials': []}
    atomic_write_json(run/'summary.json', report)
    for case, arm in jobs:
        messages, selection = request(case, arm)
        atomic_write_json(run/(case['id']+'-'+arm+'-request.json'), messages)
        row = {'case': case['id'], 'domain': case['domain'], 'condition': case['condition'], 'arm': arm,
               'selection': selection if arm == 'adaptive' else {'selected': 'full', 'reason': 'control'},
               'latest_observation_bytes': len(messages[-1]['content'].encode()),
               'request_bytes': len(encoded(messages))}
        if not options.offline:
            try:
                response = client.complete(messages, [])
                row.update(response=response.message, usage=response.usage)
                try:
                    answer = json.loads(response.message.get('content') or '')
                    row['accepted'] = answer == case['expected']
                except ValueError:
                    row['accepted'] = False
            except ModelClientError as exc:
                row.update(error=str(exc), provider_error=getattr(exc, 'provider_details', {}), usage=None)
        report['trials'].append(row)
        atomic_write_json(run/'summary.json', report)
        print(json.dumps(row), flush=True)
        if row.get('error'):
            report['status'] = 'blocked_provider_error'
            break
    else:
        report['status'] = 'offline_complete' if options.offline else 'complete'
    evidence = summarize(report['trials'], len(jobs))
    spec['status'] = evidence['decision']
    if options.offline:
        spec['status'] = 'proposed'
    final_id = records.save(spec, evidence=evidence, previous_artifact_id=proposed)
    atomic_write_json(run/'refinement-record.json', records.load(final_id))
    atomic_write_json(run/'evaluation.json', evidence)
    report.update(final_record_artifact=final_id, decision=spec['status'],
                  finished_at=datetime.now(timezone.utc).isoformat())
    atomic_write_json(run/'summary.json', report)


if __name__ == '__main__':
    main()
