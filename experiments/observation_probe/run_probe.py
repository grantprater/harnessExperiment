"""Four one-decision calls: retained baseline + full result versus exact delta.

This measures observation interpretation, not end-to-end editing/generation.
No context compaction, manager model, automatic retries, or harness changes.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reticle.cognitive.chatgpt_subscription import ChatGPTSubscriptionClient
from reticle.runtime.controller import ModelClientError
from reticle.storage.artifacts import atomic_write_json


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def delta(before, after):
    # Flat, stable keys make exact changes mechanical; no semantic summarization.
    return {'baseline_sha256': digest(before), 'current_sha256': digest(after),
            'changes': [{'key': key, 'before': before.get(key), 'after': after.get(key),
                         'removed': key not in after}
                        for key in sorted(before.keys() | after.keys())
                        if (key in before) != (key in after) or before.get(key) != after.get(key)]}


def reconstruct(before, change):
    if digest(before) != change['baseline_sha256']:
        raise ValueError('Baseline mismatch')
    result = copy.deepcopy(before)
    for item in change['changes']:
        if item['removed']:
            result.pop(item['key'])
        else:
            result[item['key']] = item['after']
    if digest(result) != change['current_sha256']:
        raise ValueError('Reconstruction mismatch')
    return result


def cases():
    tests = {f'check_{i:02d}': {'status': 'passed', 'scope': f'module_{i:02d}',
                             'details': 'Existing compatibility contract remains satisfied.'}
             for i in range(24)}
    tests['check_03']['status'] = 'failed'
    current = copy.deepcopy(tests)
    current['check_03']['status'] = 'passed'
    current['check_19']['status'] = 'failed'
    current['check_19']['details'] = 'Duplicate delivery after restart; replay lacks deduplication.'
    assets = {f'asset_{i:02d}': {'dimensions': [768, 768], 'opaque': True,
                              'palette_pass': True, 'outline_px': 6,
                              'subject_check': 'passed', 'source_revision': 1}
              for i in range(24)}
    newer = copy.deepcopy(assets)
    newer['asset_07']['source_revision'] = 2
    newer['asset_07']['outline_px'] = 12
    newer['asset_07']['palette_pass'] = False
    newer['asset_07']['outside_palette_fraction'] = 0.28
    return [
        {'id': 'test-regression', 'baseline': tests, 'current': current,
         'task': 'After a code edit, choose the next action. Current failed checks require investigation. '
                 'Passed checks need no action. Identify every changed record.',
         'expected_keys': ['check_03', 'check_19'], 'expected_action': 'investigate_check_19'},
        {'id': 'generated-asset-revision', 'baseline': assets, 'current': newer,
         'task': 'After regenerating one illustration in a cozy autumn asset collection, choose the next action. '
                 'The project requires palette_pass=true and outline_px=6. Composition may vary. '
                 'Identify every changed record. These are mechanical measurements; they do not establish aesthetic quality.',
         'expected_keys': ['asset_07'], 'expected_action': 'repair_asset_07_palette_and_outline'},
    ]


def messages(case, arm):
    baseline = case['baseline']
    result = ({'kind': 'full', 'current_sha256': digest(case['current']), 'records': case['current']}
              if arm == 'full' else {'kind': 'delta', **delta(baseline, case['current'])})
    prefix = [
        {'role': 'system', 'content': 'Interpret tool observations. Return only JSON with changed_keys '
         '(sorted array) and next_action (string). Choose exactly one of: investigate_check_19, '
         'repair_asset_07_palette_and_outline, accept, investigate_check_03. '
         'A delta replaces listed records against the identified baseline; omitted records are unchanged.'},
        {'role': 'user', 'content': case['task']},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'baseline_call', 'type': 'function', 'function': {'name': 'observe', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'baseline_call', 'content': packed(
            {'kind': 'baseline', 'sha256': digest(baseline), 'records': baseline})},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'current_call', 'type': 'function', 'function': {'name': 'observe', 'arguments': '{}'}}]},
    ]
    return prefix + [{'role': 'tool', 'tool_call_id': 'current_call', 'content': packed(result)}]


def preflight():
    for case in cases():
        change = delta(case['baseline'], case['current'])
        assert reconstruct(case['baseline'], change) == case['current']
        assert [v['key'] for v in change['changes']] == case['expected_keys']
        assert messages(case, 'full')[:-1] == messages(case, 'delta')[:-1]
        try:
            reconstruct({}, change)
        except ValueError:
            pass
        else:
            raise AssertionError('Wrong baseline accepted')
    return {'exact_reconstruction': True, 'identical_retained_prefix': True,
            'wrong_baseline_rejected': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--offline', action='store_true')
    options = parser.parse_args()
    run = options.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    checks = preflight()
    jobs = [(case, arm) for case in cases() for arm in ['full', 'delta']]
    random.Random(23).shuffle(jobs)
    client = ChatGPTSubscriptionClient(options.model, calls_path=run/'calls.jsonl', timeout=90)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'model': options.model,
              'scope': 'One next-decision per arm and case; no end-to-end completion inference.',
              'preflight': checks, 'status': 'running', 'trials': []}
    for case, arm in jobs:
        request = messages(case, arm)
        name = case['id'] + '-' + arm
        atomic_write_json(run/(name+'-request.json'), request)
        row = {'case': case['id'], 'arm': arm,
               'latest_observation_bytes': len(request[-1]['content'].encode()),
               'request_bytes': len(packed(request).encode())}
        if not options.offline:
            try:
                response = client.complete(request, [])
                row.update(response=response.message, usage=response.usage)
                content = response.message.get('content') or ''
                try:
                    answer = json.loads(content)
                    row['accepted'] = (answer.get('changed_keys') == case['expected_keys']
                                       and answer.get('next_action') == case['expected_action'])
                except (ValueError, AttributeError):
                    row['accepted'] = False
            except ModelClientError as exc:
                row.update(error=str(exc), provider_error=getattr(exc, 'provider_details', {}), usage=None)
        report['trials'].append(row)
        atomic_write_json(run/'summary.json', report)
        print(packed(row), flush=True)
        if row.get('error'):
            report['status'] = 'blocked_provider_error'
            break
    else:
        report['status'] = 'offline_complete' if options.offline else 'complete'
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(run/'summary.json', report)


if __name__ == '__main__':
    main()
