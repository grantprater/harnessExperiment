"""Deterministic task observations; hints never establish acceptance or execute tools."""
import hashlib
import json

from reticle.runtime.telemetry import aggregate_tokens

RETRIEVAL = {'read_file', 'read_output', 'search_output', 'search_history', 'history',
             'read_artifact', 'read_note', 'search', 'search_text', 'glob_files', 'style_profile'}
MUTATIONS = {'write_file', 'replace_text', 'apply_patch', 'style_apply', 'run', 'run_sequence'}


def current_messages(runtime, task_id, transcript):
    boundary = next((i for i, m in enumerate(transcript) if m.get('_reticle_task_id') == task_id), None)
    if boundary is None:
        results = [e for e in runtime.journal.read_all() if e.kind == 'agent_run_result'
                   and e.payload['result']['task_id'] != task_id]
        if results:
            after = {e.payload['artifact_id'] for e in runtime.journal.read_all()
                     if e.kind == 'transcript_message' and e.sequence > results[-1].sequence}
            boundary = next((i for i, m in enumerate(transcript) if m.get('_reticle_artifact_id') in after), len(transcript))
    return transcript[boundary or 0:]


def decision_state(runtime, task, transcript):
    messages = current_messages(runtime, task.task_id, transcript)
    calls, outstanding, artifacts, recent, failure_counts = {}, {}, [], [], {}
    failure_streak = 0
    retrievals_since_action = 0
    for message in messages:
        for call in message.get('tool_calls', []):
            function = call.get('function', {})
            raw = function.get('arguments', '{}')
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls[call['id']] = (function.get('name'), arguments)
        if message.get('role') != 'tool':
            continue
        name, arguments = calls.get(message.get('tool_call_id'), (None, {}))
        if not name:
            continue
        output = message.get('_reticle_output', {})
        status = output.get('status', 'unknown')
        signature = hashlib.sha256(json.dumps([name, arguments], sort_keys=True).encode()).hexdigest()
        path = arguments.get('candidate') or arguments.get('output_path') or arguments.get('path')
        # Do not put raw commands, code, prompts or diagnostic text in compact state.
        row = {'tool':name, 'status':status, 'output':output.get('handle')}
        if isinstance(path, str):
            row['path'] = path[:160]
        failed = status in {'error', 'timeout', 'rejected', 'cancelled'}
        if name == 'style_check' and status == 'success':
            try:
                check = json.loads(message['content'])
                failed = not check['measured_checks_passed']
                row['measured_check_passed'] = not failed
                row['check_scope'] = 'style measurements only'
            except (ValueError, KeyError, TypeError):
                pass
        if failed:
            outstanding[signature] = row
            failure_counts[signature] = failure_counts.get(signature, 0) + 1
            failure_streak += 1
        elif status == 'success':
            outstanding.pop(signature, None)
            failure_counts.pop(signature, None)
            failure_streak = 0
        if status == 'success' and name in MUTATIONS:
            retrievals_since_action = 0
            if isinstance(path, str) and path not in artifacts:
                artifacts.append(path[:160])
        elif name in RETRIEVAL:
            retrievals_since_action += 1
        recent.append(row)
    reasons = []
    if failure_streak >= 2:
        reasons.append('consecutive_failed_observations')
    if any(failure_counts.get(signature, 0) >= 2 for signature in outstanding):
        reasons.append('repeated_failure_of_same_action')
    if retrievals_since_action >= 3:
        reasons.append('retrieval_streak_without_execution')
    mode = 'broaden_or_replan' if reasons else 'diagnose' if outstanding else 'act_or_validate'
    events = runtime.journal.read_all()
    usage = aggregate_tokens([e.payload.get('usage') for e in events
                             if e.kind in {'model_call', 'model_call_failed'} and e.payload.get('task_id') == task.task_id])
    complete = not usage['prompt_tokens']['missing_calls'] and not usage['completion_tokens']['missing_calls']
    total = (usage['prompt_tokens']['reported'] or 0) + (usage['completion_tokens']['reported'] or 0) if complete else None
    return {'state_version':1, 'task_id':task.task_id, 'next_step_hint':mode,
            'escalation_reasons':reasons, 'recent_observations':recent[-2:],
            'unresolved_failures':list(outstanding.values())[-2:], 'artifact_paths':artifacts[-4:],
            'acceptance':'unverified', 'reported_total_tokens':total,
            'token_target':task.budgets.get('token_target'), 'usage_complete':complete}
