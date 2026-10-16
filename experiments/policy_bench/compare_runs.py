"""Compare full attempts; measured checks and independent acceptance stay separate."""
import argparse
import json
from pathlib import Path
import statistics


def read_run(path):
    path = Path(path)
    summary = json.loads((path/'summary.json').read_text(encoding='utf-8'))
    usage = json.loads((path/'usage.json').read_text(encoding='utf-8')) if (path/'usage.json').exists() else {}
    totals = usage.get('totals', {})
    measures = [totals.get(key, {}) for key in ('prompt_tokens', 'completion_tokens')]
    complete = all(isinstance(m.get('reported'), (int,float)) and not m.get('missing_calls') for m in measures)
    tokens = sum(m['reported'] for m in measures) if complete else None
    evaluation = json.loads((path/'evaluation.json').read_text(encoding='utf-8')) if (path/'evaluation.json').exists() else {}
    accepted = evaluation.get('accepted')
    if not isinstance(accepted, bool):
        accepted = None
    versions = usage.get('policy', {}).get('versions') or sorted({r['context_policy_version'] for r in usage.get('calls', []) if r.get('context_policy_version')})
    trial = json.loads((path/'trial.json').read_text(encoding='utf-8')) if (path/'trial.json').exists() else {}
    tasks = summary.get('tasks', [])
    task_completion = all(t.get('exit_code')==0 and (t.get('usage') or {}).get('stop_reason')=='finish_requested'
                          for t in tasks) if tasks else None
    model_service_errors = sum((t.get('usage') or {}).get('stop_reason')=='model_error' for t in tasks)
    target = summary.get('token_target_total')
    cached = totals.get('cached_input', {})
    prompt = totals.get('prompt_tokens', {})
    uncached = (prompt['reported']-cached['reported'] if isinstance(prompt.get('reported'),(int,float))
                and isinstance(cached.get('reported'),(int,float)) and not prompt.get('missing_calls')
                and not cached.get('missing_calls') and 0<=cached['reported']<=prompt['reported'] else None)
    return {'run_dir':str(path.resolve()), 'condition':summary.get('context_policy') or ','.join(versions) or 'unknown',
            'model':summary.get('model'), 'status':summary.get('status'), 'total_tokens':tokens,
            'driver_exit_code':trial.get('exit_code'),
            'model_tasks_completed':task_completion, 'model_service_errors':model_service_errors,
            'token_target_total':target, 'token_target_met':tokens<=target if tokens is not None and isinstance(target,(int,float)) else None,
            'reported_usage_complete':complete, 'cached_input_tokens':totals.get('cached_input',{}).get('reported'),
            'uncached_input_tokens':uncached,
            'model_calls':len(usage.get('calls', [])),
            'failed_model_calls':usage.get('failed_model_calls'),
            'escalations':sum(bool(s.get('escalation_reasons')) for s in usage.get('policy',{}).get('decision_snapshots',[])),
            'measured_checks_passed':summary.get('all_measured_checks_passed'),
            'accepted':accepted, 'acceptance_source':evaluation.get('source'),
            'evaluation_protocol':evaluation.get('protocol_id'),
            'unmeasured_retry_usage_possible':bool(usage.get('failed_provider_attempts_recorded'))}


def compare_runs(paths):
    runs = [read_run(path) for path in paths]
    groups = {}
    for row in runs:
        groups.setdefault((row['condition'], row['model']), []).append(row)
    conditions = []
    for (condition, model), rows in groups.items():
        known = [r['total_tokens'] for r in rows if r['total_tokens'] is not None]
        accepted = sum(r['accepted'] is True for r in rows)
        protocols = {r['evaluation_protocol'] for r in rows if r['accepted'] is not None}
        acceptance_known = all(r['accepted'] is not None for r in rows) and len(protocols)==1 and None not in protocols
        conditions.append({'condition':condition, 'model':model, 'attempts':len(rows),
            'accepted_attempts':accepted, 'acceptance_unknown':sum(r['accepted'] is None for r in rows),
            'evaluation_protocols':sorted(str(p) for p in protocols),
            'median_tokens_per_attempt':statistics.median(known) if known else None,
            'reported_total_tokens_all_attempts':sum(known) if len(known)==len(rows) else None,
            'reported_uncached_input_all_attempts':sum(r['uncached_input_tokens'] for r in rows)
                 if all(r['uncached_input_tokens'] is not None for r in rows) else None,
            'tokens_per_accepted_attempt':sum(known)/accepted if accepted and acceptance_known and len(known)==len(rows) else None,
            'measured_passes':sum(r['measured_checks_passed'] is True for r in rows),
            'unfinished_attempts':sum(r['status']!='complete' or r['driver_exit_code'] not in (None,0)
                                      or r['model_tasks_completed'] is False for r in rows),
            'attempts_with_model_service_errors':sum(r['model_service_errors']>0 for r in rows),
            'token_target_met_attempts':sum(r['token_target_met'] is True for r in rows),
            'usage_incomplete':len(rows)-len(known)})
    return {'report_version':1, 'runs':runs, 'conditions':conditions,
            'interpretation':'All attempts count toward cost. Automated measured passes do not imply independent acceptance. Unknown usage remains unknown; cached input is included in total tokens. No automatic policy promotion.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    report = compare_runs(options.runs)
    text = json.dumps(report, indent=2)
    if options.output:
        if options.output.exists():
            raise ValueError('Use a new report path')
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
