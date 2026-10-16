"""Only numeric provider-reported token measurements, with explicit missing-data counts."""
import math
from pathlib import Path

from reticle.storage.artifacts import atomic_write_json


def token_measurement(usage, field):
    if not isinstance(usage, dict):
        return None
    if field == 'cached_input':
        details = usage.get('prompt_tokens_details')
        value = details.get('cached_tokens') if isinstance(details, dict) else None
    else:
        value = usage.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return value


def aggregate_tokens(records):
    result = {'calls': len(records)}
    for field in ('prompt_tokens', 'completion_tokens', 'cached_input'):
        values = [token_measurement(usage, field) for usage in records]
        known = [value for value in values if value is not None]
        result[field] = {'reported': sum(known) if known or not records else None,
                         'missing_calls': len(values)-len(known)}
    return result


def model_token_usage(runtime, task_id):
    events = runtime.journal.read_all()
    requests = {e.payload.get('attempt_id'): e.payload.get('task_id')
                for e in events if e.kind == 'model_request_intent'}
    calls = [e.payload for e in events if e.kind in ('model_call', 'model_call_failed')]
    task = [call.get('usage') for call in calls
            if call.get('task_id', requests.get(call.get('attempt_id'))) == task_id]
    return {'task': aggregate_tokens(task),
            'session': aggregate_tokens([call.get('usage') for call in calls]),
            'last_call': aggregate_tokens(task[-1:]) if task else None}


def render_model_token_usage(usage):
    def scope(name, record):
        parts = []
        for field, label in (('prompt_tokens', 'input'), ('completion_tokens', 'output'), ('cached_input', 'cached input')):
            item = record[field]
            count = 'unreported' if item['reported'] is None else f'{item["reported"]:,}'
            if item['reported'] is not None and item['missing_calls']:
                count += f' (partial; {item["missing_calls"]} call(s) unreported)'
            parts.append(f'{label} {count}')
        return f'{name} ({record["calls"]} recorded request(s)): ' + ', '.join(parts)
    text = 'Provider-reported token usage from previous calls; cumulative spend, not current context occupancy or a token allowance; cached input is included in input. '
    text += scope('Task', usage['task']) + '; ' + scope('Session', usage['session'])
    if usage['last_call']:
        text += '; ' + scope('Last call', usage['last_call'])
    return text


def usage_report(runtime):
    """Machine-readable measurements for batch comparisons; never export prompts or credentials."""
    events = runtime.journal.read_all()
    requests = {e.payload.get('attempt_id'): e.payload for e in events if e.kind == 'model_request_intent'}
    results = {e.payload['result']['task_id']: e.payload['result']
               for e in events if e.kind == 'agent_run_result'}
    finished = {e.payload.get('attempt_id') for e in events if e.kind in ('model_call', 'model_call_failed')}
    measured = [e for e in events if e.kind in ('model_call', 'model_call_failed') or
                (e.kind == 'model_request_intent' and e.payload.get('attempt_id') not in finished)]
    rows, task_usage = [], {}
    for event in measured:
        call = event.payload
        request = {**requests.get(call.get('attempt_id'), {}), **call}
        task_id = request.get('task_id')
        metadata = call.get('metadata') if isinstance(call.get('metadata'), dict) else {}
        usage = call.get('usage')
        task_usage.setdefault(task_id, []).append(usage)
        rows.append({'sequence': event.sequence, 'task_id': task_id,
                     'status': {'model_call': 'response', 'model_call_failed': 'failed',
                                'model_request_intent': 'incomplete'}[event.kind],
                     'call_index': call.get('call_index'),
                     'runtime_version': request.get('runtime_version', 'unversioned'),
                     'extension_versions': request.get('extension_versions', {}),
                     'style_profile_id': request.get('style_profile_id'),
                     'tool_schema_hash': request.get('tool_schema_hash'),
                     'context_policy_version': request.get('context_policy_version'),
                     'request_bytes': request.get('request_bytes'),
                     'decision_state_event_id': request.get('decision_state_event_id'),
                     'token_target': request.get('token_target'),
                     'usage_feedback_enabled': request.get('usage_feedback_enabled', False),
                     'model': metadata.get('model'), 'provider': metadata.get('provider'),
                     'prompt_tokens': token_measurement(usage, 'prompt_tokens'),
                     'completion_tokens': token_measurement(usage, 'completion_tokens'),
                     'cached_input_tokens': token_measurement(usage, 'cached_input'),
                     'reported_cost_usd': token_measurement(usage, 'cost')})
    tasks = []
    for task_id in dict.fromkeys([*task_usage, *results]):
        result = results.get(task_id, {})
        tasks.append({'task_id': task_id, 'stop_reason': result.get('stop_reason'),
                      'model_calls': result.get('model_calls'), 'tool_calls': result.get('tool_calls'),
                      'provider_attempts': result.get('provider_attempts'),
                      'resource_limits': (result.get('task_resources') or {}).get('limits'),
                      'totals': aggregate_tokens(task_usage.get(task_id, []))})
    def invocation_key(payload):
        return payload.get('invocation_id') or (payload.get('task_id'), payload.get('call_id'))
    invocation_ends = {invocation_key(e.payload): e.payload for e in events if e.kind == 'extension_invocation_finished'}
    invocations = []
    for event in events:
        if event.kind == 'extension_invocation_started':
            start = event.payload
            end = invocation_ends.get(invocation_key(start), {})
            invocations.append({key: start.get(key) for key in ('invocation_id', 'task_id', 'call_id', 'name', 'version')}
                               | {'status': end.get('status', 'incomplete'), 'duration_ms': end.get('duration_ms')})
    extension_versions = {}
    for row in invocations:
        key = (row['name'], row['version'])
        summary = extension_versions.setdefault(key, {'name': row['name'], 'version': row['version'],
                                                       'invocations': 0, 'successful': 0, 'incomplete': 0})
        summary['invocations'] += 1
        summary['successful'] += row['status'] == 'success'
        summary['incomplete'] += row['status'] == 'incomplete'
    return {'report_version': 1, 'session': str(runtime.session_dir),
            'measurement': 'provider-reported; cached input is included in prompt_tokens; missing values are null',
            'totals': aggregate_tokens([e.payload.get('usage') for e in measured]),
            'failed_model_calls': sum(row['status'] == 'failed' for row in rows),
            'incomplete_model_calls': sum(row['status'] == 'incomplete' for row in rows),
            'provider_attempts_recorded': sum(e.kind == 'provider_attempt_started' for e in events),
            'failed_provider_attempts_recorded': sum(e.kind == 'provider_attempt_finished'
                     and e.payload.get('outcome') != 'response' for e in events),
            'retry_usage_note': 'Failed/retried provider attempts can consume tokens without a reported measurement; totals cover reported request usage only.',
            'runtime_worker_interruptions': sum(e.kind == 'runtime_worker_interrupted' for e in events),
            'journal_truncated_tail': runtime.journal.truncated_tail_detected,
            'tasks': tasks, 'calls': rows,
            'extensions': {'invocations': invocations, 'versions': list(extension_versions.values()),
                           'turn_snapshots': [e.payload for e in events if e.kind == 'extension_turn_snapshot']},
            'policy': {'decision_snapshots': [dict(e.payload, event_id=e.event_id) for e in events if e.kind == 'decision_state_snapshot'],
                       'versions': sorted({row['context_policy_version'] for row in rows if row['context_policy_version']})},
            'style': {'turn_snapshots': [e.payload for e in events if e.kind == 'style_turn_snapshot'],
                      'checks': [e.payload for e in events if e.kind == 'style_check'],
                      'applications': [e.payload for e in events if e.kind == 'style_applied'],
                      'profiles_extracted': [e.payload for e in events if e.kind == 'style_profile_extracted']}}


def write_usage_report(runtime, path):
    atomic_write_json(Path(path), usage_report(runtime))
