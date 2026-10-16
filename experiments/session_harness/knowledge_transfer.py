"""Bounded three-arm pilot: acquired procedures, fresh tasks, abrupt protocol changes.

--prepare creates synthetic fixtures and verifies gold/noop evaluator controls.
--execute acquires one shared knowledge snapshot, then runs 18 serial paired trials.
No evaluator details are sent to the model. No production patch is promoted.
"""
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import ast
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
OUT = ROOT / '.runtime/knowledge-transfer-002'
ARMS = ('transcript', 'graph', 'valid')
TIMEOUT_V1 = '''"""Convert incoming timeouts to seconds; reject negative values.
Missing values use DEFAULT_SECONDS. Zero is valid.
"""
FIELD = "timeout_ms"
SECONDS_PER_UNIT = 0.001
DEFAULT_SECONDS = 2.5
'''
TIMEOUT_V2 = TIMEOUT_V1.replace('"timeout_ms"', '"deadline_seconds"').replace('0.001', '1.0').replace('2.5', '7.0')
ROWS_V1 = '''"""Parse reply rows into names.
Ignore blank lines. Skip HEADER_LINES nonblank lines, split on SEPARATOR,
select FIELD_INDEX, strip surrounding whitespace, and skip rows missing that field.
"""
SEPARATOR = ","
FIELD_INDEX = 1
HEADER_LINES = 0
'''
ROWS_V2 = ROWS_V1.replace('","', '"|"').replace('FIELD_INDEX = 1', 'FIELD_INDEX = 2').replace('HEADER_LINES = 0', 'HEADER_LINES = 1')
GOLD = '''def build_timeout(values):
    import timeout_protocol as protocol
    if protocol.FIELD not in values:
        return protocol.DEFAULT_SECONDS
    value = float(values[protocol.FIELD])
    if value < 0:
        raise ValueError("negative timeout")
    return value * protocol.SECONDS_PER_UNIT

def parse_reply(text):
    import rows_protocol as protocol
    lines = [line for line in text.splitlines() if line.strip()][protocol.HEADER_LINES:]
    return [fields[protocol.FIELD_INDEX].strip() for line in lines
            for fields in [line.split(protocol.SEPARATOR)] if len(fields) > protocol.FIELD_INDEX]
'''
NOOP = 'def build_timeout(values):\n    return 0\n\ndef parse_reply(text):\n    return []\n'

EVALUATOR = '''import importlib, json, sys
module = importlib.import_module("client")
cases = json.load(sys.stdin)
results = []
for case in cases:
    try:
        value = getattr(module, case["function"])(case["input"])
        passed = value == case.get("expected") and not case.get("raises")
    except ValueError:
        passed = case.get("raises") == "ValueError"
    except Exception:
        passed = False
    results.append(bool(passed))
print(json.dumps({"passed": all(results), "checks": len(results), "outcomes": results}))
'''


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def environment(pythonpath):
    return dict(os.environ, PYTHONPATH=str(pythonpath), PYTHONIOENCODING='utf-8')


def cases(family, condition):
    if family == 'timeout':
        key, factor, default = ('deadline_seconds', 1.0, 7.0) if condition == 'regime' else ('timeout_ms', .001, 2.5)
        return ([{'function': 'build_timeout', 'input': {key: value}, 'expected': float(value) * factor}
                 for value in (0, 1, 37, 1500, '2500', .5)] +
                [{'function': 'build_timeout', 'input': {}, 'expected': default},
                 {'function': 'build_timeout', 'input': {key: -1}, 'raises': 'ValueError'}])
    prefix = 'id|ignored|name\n' if condition == 'regime' else ''
    sep, index = ('|', 2) if condition == 'regime' else (',', 1)
    def row(name):
        return sep.join(['1', 'unused', ' ' + name + ' '] if index == 2 else ['1', ' ' + name + ' '])
    return [{'function': 'parse_reply', 'input': prefix + row('Ada') + '\n' + row('Lin'), 'expected': ['Ada', 'Lin']},
            {'function': 'parse_reply', 'input': '', 'expected': []},
            {'function': 'parse_reply', 'input': '\n' + prefix + '\n' + row('Kay') + '\n', 'expected': ['Kay']},
            {'function': 'parse_reply', 'input': prefix + 'malformed\n' + row('Zoe'), 'expected': ['Zoe']},
            {'function': 'parse_reply', 'input': prefix + row(''), 'expected': ['']},
            {'function': 'parse_reply', 'input': prefix + row('Ren') + '\n\n' + row('Dee'), 'expected': ['Ren', 'Dee']}]


def evaluate(workspace, test_cases):
    run = subprocess.run([sys.executable, '-c', EVALUATOR], input=json.dumps(test_cases),
                         cwd=workspace, env=environment(workspace), capture_output=True, text=True, timeout=30)
    try:
        result = json.loads(run.stdout)
        if type(result.get('passed')) is not bool or result.get('checks') != len(test_cases):
            raise ValueError('Invalid evaluator output')
    except (ValueError, TypeError):
        result = {'passed': False, 'checks': len(test_cases), 'error': 'evaluator_process_failed'}
    return result


def fixture(workspace, family, condition):
    workspace.mkdir(parents=True)
    (workspace / 'timeout_protocol.py').write_text(TIMEOUT_V2 if family == 'timeout' and condition == 'regime' else TIMEOUT_V1)
    (workspace / 'rows_protocol.py').write_text(ROWS_V2 if family == 'rows' and condition == 'regime' else ROWS_V1)
    (workspace / 'notes.txt').write_text('Unrelated note changed\n' if condition == 'unrelated' else 'Original note\n')
    (workspace / 'client.py').write_text(NOOP)
    smoke = cases(family, condition)[0]
    (workspace / 'check.py').write_text('import client\nassert client.' + smoke['function'] + '(' + repr(smoke['input']) +
                                      ') == ' + repr(smoke['expected']) + '\nprint("smoke passed")\n')


def prepare(out):
    if out.exists():
        raise SystemExit('Output already exists; use a new --out directory.')
    out.mkdir(parents=True)
    order, controls = [], []
    generator = random.Random(20261002)
    for family in ('timeout', 'rows'):
        for condition in ('stable', 'unrelated', 'regime'):
            workspace = out / 'fixtures' / (family + '-' + condition)
            fixture(workspace, family, condition)
            expected = cases(family, condition)
            noop = evaluate(workspace, expected)
            (workspace / 'client.py').write_text(GOLD)
            gold = evaluate(workspace, expected)
            (workspace / 'client.py').write_text(NOOP)
            if noop['passed'] or not gold['passed']:
                raise RuntimeError('Evaluator controls failed')
            controls.append({'family': family, 'condition': condition, 'gold': gold['passed'], 'noop': noop['passed']})
            arms = list(ARMS)
            generator.shuffle(arms)
            order.extend({'family': family, 'condition': condition, 'arm': arm} for arm in arms)
    source = out / 'acquisition/workspace'
    fixture(source, 'timeout', 'stable')
    (source / 'client.py').unlink()
    (source / 'check.py').unlink()
    save(out / 'controls.json', controls)
    goal = ('Inspect timeout_protocol.py and rows_protocol.py and learn their rules for future coding tasks. '
            'Do not edit files. Use reasoning_state to obtain the authorized evidence event IDs after reading. '
            'Use reasoning_update to record one code_entity per protocol with its path, one procedure per protocol '
            'describing the full algorithm including boundary cases, applicability conditions, and depends_on links '
            'from each procedure to its code_entity. Record what the files actually say, including units, defaults, '
            'delimiter, header handling, malformed rows, and whitespace. Finish after both procedures are stored.')
    (out / 'acquisition/goal.txt').write_text(goal)
    from reticle.runtime.knowledge import VERSION
    from reticle.runtime.reasoning import REASONING_VERSION
    sources = ('reticle/runtime/knowledge.py', 'reticle/tools/knowledge.py', 'reticle/runtime/reasoning.py',
               'reticle/tools/reasoning.py', 'reticle/interactive.py', 'reticle/cognitive/chatgpt_subscription.py',
               'reticle/context/baseline.py', 'reticle/tools/primitives.py', 'reticle/tools/toolset_v4.py',
               'experiments/session_harness/knowledge_transfer.py')
    protocol = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'name': 'knowledge-transfer-002', 'client': 'chatgpt-subscription', 'model': 'gpt-6.1-sol',
                'arms': list(ARMS), 'order': order, 'max_acquisition_responses': 6,
                'max_responses_per_trial': 5, 'maximum_total_responses': 96,
                'context_bytes': 120000, 'knowledge_bytes': 10000, 'backend': 'trusted-local',
                'ontology_version': REASONING_VERSION, 'knowledge_version': VERSION,
                'source_hashes': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources},
                'fixture_hashes': {path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in (out / 'fixtures').rglob('*') if path.is_file() and '__pycache__' not in path.parts},
                'evaluator_sha256': hashlib.sha256(EVALUATOR.encode()).hexdigest(),
                'primary': 'Independent correctness within budget, with only client.py changed',
                'secondary': ['responses', 'actions', 'tokens', 'elapsed_seconds', 'needs_recheck_findings', 'knowledge_queries'],
                'limitations': ['synthetic tasks', 'one rollout per task/arm', 'single acquisition session',
                                'shared source experience and token-overlap ranker; index representation differs',
                                'file-change signals, not statistical change-point detection', 'no statistical efficacy claim']}
    save(out / 'protocol.json', protocol)
    save(out / 'state.json', {'status': 'prepared', 'completed': 0, 'total': len(order)})
    print(json.dumps({'prepared': str(out), 'controls_passed': len(controls), 'trials': len(order),
                      'maximum_total_responses': 96}, indent=2))


def invoke(out, name, workspace, prompt, *options):
    record = out / 'runs' / name
    record.mkdir(parents=True)
    argv = [sys.executable, '-u', '-m', 'reticle', prompt, '-C', str(workspace), '--once',
            '--client', 'chatgpt-subscription', '--model', 'gpt-6.1-sol', '--reasoning', 'memory',
            '--session-dir', str(record / 'session'), *options]
    save(record / 'invocation.json', {'argv': argv})
    started = time.monotonic()
    with (record / 'stdout.txt').open('w', encoding='utf-8') as stdout, (record / 'stderr.txt').open('w', encoding='utf-8') as stderr:
        run = subprocess.run(argv, cwd=ROOT, env=environment(ROOT), stdout=stdout, stderr=stderr, timeout=900)
    return record, run.returncode, time.monotonic() - started


def metrics(record):
    path = record / 'session/events.jsonl'
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    calls = [event for event in events if event['kind'] == 'model_call']
    retrievals = [event['payload'] for event in events if event['kind'] == 'knowledge_retrieval']
    return {'model_responses': len(calls), 'tool_actions': sum(event['kind'] == 'action_intent' for event in events),
            'input_tokens': sum((event['payload'].get('usage') or {}).get('prompt_tokens') or 0 for event in calls),
            'output_tokens': sum((event['payload'].get('usage') or {}).get('completion_tokens') or 0 for event in calls),
            'knowledge_queries': len(retrievals), 'needs_recheck': sum(len(item['needs_recheck']) for item in retrievals),
            'retrieval_truncations': sum(item['truncated'] for item in retrievals),
            'model_errors': sum(event['kind'] == 'model_call_failed' for event in events)}


def report(out, rows, status):
    aggregate = {}
    for arm in ARMS:
        selected = [row for row in rows if row['arm'] == arm]
        aggregate[arm] = {'accepted': sum(row['accepted'] for row in selected), 'trials': len(selected),
                          'by_condition': {condition: {'accepted': sum(row['accepted'] for row in selected if row['condition'] == condition),
                                                       'trials': sum(row['condition'] == condition for row in selected)}
                                           for condition in ('stable', 'unrelated', 'regime')},
                          'model_responses': sum(row['model_responses'] for row in selected),
                          'tool_actions': sum(row['tool_actions'] for row in selected),
                          'input_tokens': sum(row['input_tokens'] for row in selected),
                          'needs_recheck': sum(row['needs_recheck'] for row in selected)}
    save(out / 'summary.json', {'status': status, 'completed': len(rows), 'arms': aggregate,
                               'interpretation': 'Mechanism/transfer pilot; insufficient for a general capability claim.'})
    lines = ['# Knowledge transfer and regime-change pilot', '', 'Status: ' + status + '.', '',
             '| Arm | Accepted | Responses | Tool actions | Input tokens | Recheck findings |',
             '|---|---:|---:|---:|---:|---:|']
    for arm, item in aggregate.items():
        lines.append(f"| {arm} | {item['accepted']}/{item['trials']} | {item['model_responses']} | {item['tool_actions']} | {item['input_tokens']} | {item['needs_recheck']} |")
    lines += ['', 'Six synthetic tasks, one rollout per arm, one shared acquired snapshot.',
              'The transcript control retrieves authorized transcript/tool-output excerpts. Graph arms retrieve evidence-linked assertions from the same source session. All arms use the same token-overlap ranker, source experience, tools, model and resource caps.',
              'This tests explicit dependency changes and learned-procedure transfer; it does not implement Bayesian change-point inference.',
              'Independent evaluator outcomes never entered agent context. No production code was changed.']
    (out / 'report.md').write_text('\n'.join(lines) + '\n')


def execute(out):
    sys.path.insert(0, str(ROOT))
    from reticle.runtime.knowledge import KnowledgeLibrary, load_snapshot, propose_experiments
    from reticle.runtime.reasoning import EvidenceOntology
    from reticle.runtime.session import LocalRuntime
    protocol = json.loads((out / 'protocol.json').read_text())
    for path, expected in protocol['source_hashes'].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen protocol source changed: ' + path)
    for path, expected in protocol['fixture_hashes'].items():
        if hashlib.sha256((out / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen fixture changed: ' + path)
    save(out / 'state.json', {'status': 'acquiring', 'completed': 0, 'total': 18})
    record, code, elapsed = invoke(out, 'acquisition', out / 'acquisition/workspace',
                                   (out / 'acquisition/goal.txt').read_text(), '--max-steps', '6', '--learn',
                                   '--knowledge-library', str(out / 'library'))
    snapshot = KnowledgeLibrary(out / 'library').latest()
    if code or snapshot is None:
        raise RuntimeError('Acquisition did not finish; inspect the source session.')
    data = load_snapshot(snapshot)
    procedures = [item for item in data['entities'].values() if item['kind'] == 'procedure']
    dependencies = [item for item in data['relations'] if item['relation'] == 'depends_on']
    if len(procedures) < 2 or len(dependencies) < 2:
        raise RuntimeError('Acquisition did not produce both procedures with dependencies.')
    save(out / 'acquisition.json', {'snapshot': str(snapshot), 'snapshot_id': json.loads(snapshot.read_text())['snapshot_id'],
                                   'procedures': len(procedures), 'dependencies': len(dependencies), 'elapsed_seconds': elapsed,
                                   **metrics(record)})
    rows = []
    for index, item in enumerate(protocol['order']):
        name = f"{index+1:02d}-{item['family']}-{item['condition']}-{item['arm']}"
        save(out / 'state.json', {'status': 'running', 'current': name, 'completed': len(rows), 'total': 18})
        workspace = out / 'workspaces' / name
        shutil.copytree(out / 'fixtures' / (item['family'] + '-' + item['condition']), workspace)
        before = {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
        function = 'build_timeout' if item['family'] == 'timeout' else 'parse_reply'
        task = (f'Implement {function} in client.py according to the protocol file for this function in this workspace. '
                'Previously acquired evidence is available, but its applicability must be assessed against current inputs. '
                'Change only client.py. Preserve the other function. Handle the full protocol, including boundary cases. '
                'Use python check.py for the available smoke check. Finish when implemented and checked.')
        record, code, elapsed = invoke(out, name, workspace, task, '--max-steps', '5', '--knowledge', str(snapshot),
                                       '--knowledge-mode', item['arm'])
        checked = evaluate(workspace, cases(item['family'], item['condition']))
        protected = all((workspace / path).is_file() and (workspace / path).read_bytes() == content
                        for path, content in before.items() if path != 'client.py')
        other = 'parse_reply' if function == 'build_timeout' else 'build_timeout'
        try:
            original_node = next(node for node in ast.parse(before['client.py']).body
                                 if isinstance(node, ast.FunctionDef) and node.name == other)
            actual_node = next(node for node in ast.parse((workspace / 'client.py').read_text()).body
                               if isinstance(node, ast.FunctionDef) and node.name == other)
            other_preserved = ast.dump(original_node) == ast.dump(actual_node)
        except (SyntaxError, StopIteration, OSError):
            other_preserved = False
        extra = [path.relative_to(workspace).as_posix() for path in workspace.rglob('*') if path.is_file()
                 and '__pycache__' not in path.parts and path.relative_to(workspace).as_posix() not in before]
        row = {**item, 'run': name, 'agent_exit_code': code, 'elapsed_seconds': elapsed,
               'accepted': code == 0 and checked['passed'] and protected and other_preserved and not extra,
               'other_function_preserved': other_preserved,
               'evaluation': checked, 'protected_files_unchanged': protected, 'new_files': extra, **metrics(record)}
        save(record / 'result.json', row)
        rows.append(row)
        save(out / 'results.json', rows)
        # Consolidate only after independent evaluation; never feed confirmation outcomes into later trials.
        runtime = LocalRuntime(record / 'session')
        KnowledgeLibrary(out / 'post-trial-library').consolidate(runtime, EvidenceOntology(runtime, 'memory'))
        report(out, rows, 'running')
    final_snapshot = KnowledgeLibrary(out / 'post-trial-library').latest()
    save(out / 'outer-loop-proposals.json', propose_experiments(final_snapshot))
    report(out, rows, 'complete')
    save(out / 'state.json', {'status': 'complete', 'completed': len(rows), 'total': 18})
    print((out / 'report.md').read_text())


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    try:
        (prepare if args.prepare else execute)(args.out.resolve())
    except Exception as exc:
        if args.out.exists():
            save(args.out / 'state.json', {'status': 'failed', 'error': str(exc), 'type': type(exc).__name__})
        raise
