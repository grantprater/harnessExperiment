"""Exact structured observation refinement; opt-in and independent of compaction.

The caller supplies hashes of baselines actually retained in the model request.
Disk availability alone never permits a delta. Stable record IDs are a caller
contract, not something inferred by comparing keys.
"""
from copy import deepcopy
import hashlib
import json

VERSION = 'structured-observation-delta-v1'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def exact_delta(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError('Snapshots must map stable string record IDs to JSON values')
    if any(not isinstance(key, str) for key in before.keys() | after.keys()):
        raise ValueError('Record IDs must be strings')
    changes = []
    for key in sorted(before.keys() | after.keys()):
        if key not in before or key not in after or encoded(before[key]) != encoded(after[key]):
            item = {'key': key, 'removed': key not in after}
            if key in after:
                item['value'] = deepcopy(after[key])
            changes.append(item)
    return {'kind': 'delta', 'version': VERSION, 'baseline_sha256': fingerprint(before),
            'current_sha256': fingerprint(after), 'changes': changes}


def reconstruct(before, observation):
    if observation.get('version') != VERSION or observation.get('kind') != 'delta':
        raise ValueError('Unsupported delta')
    if fingerprint(before) != observation['baseline_sha256']:
        raise ValueError('Baseline mismatch')
    result = deepcopy(before)
    seen = set()
    for change in observation['changes']:
        key = change['key']
        if not isinstance(key, str) or key in seen or type(change['removed']) is not bool:
            raise ValueError('Invalid or duplicate change')
        seen.add(key)
        if change['removed']:
            if key not in result:
                raise ValueError('Cannot remove absent record')
            del result[key]
        else:
            result[key] = deepcopy(change['value'])
    if fingerprint(result) != observation['current_sha256']:
        raise ValueError('Reconstructed snapshot mismatch')
    return result


def select_observation(current, *, baseline=None, retained_baselines=(),
                       stable_ids=False, max_changed_fraction=0.25):
    if (isinstance(max_changed_fraction, bool) or not isinstance(max_changed_fraction, (int, float))
            or not 0 <= max_changed_fraction <= 1):
        raise ValueError('Changed fraction must be between zero and one')
    # Validate JSON and IDs even when falling back to a full snapshot.
    exact_delta({}, current)
    full = {'kind': 'full', 'version': VERSION, 'current_sha256': fingerprint(current),
            'records': deepcopy(current)}
    selection = {'policy_version': VERSION, 'selected': 'full', 'reason': None,
                 'full_bytes': len(encoded(full)), 'changed_fraction': None}
    if not stable_ids:
        selection['reason'] = 'stable_ids_not_declared'
    elif baseline is None or fingerprint(baseline) not in retained_baselines:
        selection['reason'] = 'baseline_not_retained'
    else:
        candidate = exact_delta(baseline, current)
        fraction = len(candidate['changes']) / max(1, len(baseline.keys() | current.keys()))
        selection.update(changed_fraction=fraction, delta_bytes=len(encoded(candidate)),
                         baseline_sha256=candidate['baseline_sha256'])
        if fraction > max_changed_fraction:
            selection['reason'] = 'changes_not_sparse'
        elif selection['delta_bytes'] >= selection['full_bytes']:
            selection['reason'] = 'delta_not_smaller'
        else:
            selection.update(selected='delta', reason='retained_sparse_smaller')
            return candidate, selection
    return full, selection
