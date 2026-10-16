"""Counterfactual request-size replay, not a model-quality/token-use experiment.

Keeps historical actions fixed. No provider requests; source run stays unchanged.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reticle.context import MinimalContextPolicy, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime
from reticle.tools.style import check_summary
from reticle.storage.artifacts import atomic_write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    if options.output.exists():
        raise ValueError('Use a new output path')
    source = options.run_dir / 'workspace/.reticle/session'
    lines = (source/'events.jsonl').read_bytes().splitlines(keepends=True)
    events = [json.loads(line) for line in lines]
    rows = []
    with tempfile.TemporaryDirectory(prefix='reticle-minimal-replay-') as directory:
        clone = Path(directory)/'session'
        shutil.copytree(source, clone)
        for index, event in enumerate(events):
            if event['kind'] != 'model_request_intent':
                continue
            (clone/'events.jsonl').write_bytes(b''.join(lines[:index]))
            runtime = LocalRuntime(clone)
            request = json.loads(runtime.artifacts.read(event['payload']['request_artifact_id']))
            description = next(m['content'] for m in request['messages'] if m['role']=='user')
            task = TaskEnvelope(event['payload']['task_id'], description,
                authority={'filesystem': str(runtime.workspace.root), 'execution':'trusted-local'},
                budgets={'model_responses':20, 'model_attempts':20, 'tool_actions':200})
            transcript = TranscriptStore(runtime).load()
            for message in transcript:
                tool = message.get('_reticle_output', {}).get('tool')
                if tool not in {'style_check', 'style_apply'}:
                    continue
                result = json.loads(message['content'])
                if tool == 'style_check':
                    compact = check_summary(result)
                else:
                    compact = {'profile_id':result['profile_id'], 'output_path':result['output_path'],
                               'change_count':len(result['changes']), 'after':check_summary(result['after'])}
                compact['report_path'] = '.reticle/style-reports/<full-report>.json'
                message['content'] = json.dumps(compact, separators=(',', ':'))
            built = MinimalContextPolicy().build(runtime, task, transcript, request['tools'], 32000)
            rows.append({'sequence':event['sequence'], 'task_id':task.task_id,
                'original_request_bytes':len(runtime.artifacts.read(event['payload']['request_artifact_id'])),
                'minimal_request_bytes':built.manifest.request_bytes, 'over_budget':built.over_budget})
    old = sum(row['original_request_bytes'] for row in rows)
    new = sum(row['minimal_request_bytes'] for row in rows)
    report = {'measurement':'Serialized request bytes, fixed historical actions; not measured provider tokens or task quality',
              'scope':'Compact style outputs, minimal context policy, 32000-byte limit',
              'original_bytes':old, 'minimal_bytes':new, 'reduction_fraction':round(1-new/old, 4), 'calls':rows}
    atomic_write_json(options.output, report)
    print(json.dumps({key:value for key,value in report.items() if key!='calls'}, indent=2))


if __name__ == '__main__':
    main()
