"""Reproducible reading-interface pilot, driven by fresh native Luna agents.

Agent interface: python controlled.py RUN_ID view|edit|verify|finish ...
Edits use base64 UTF-8 text to avoid shell-quoting differences. This is an
experimental interface, not a security sandbox for hostile Python code.
"""
from __future__ import annotations
import ast
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from perception import extract_outline

HOME = ROOT / 'experiments' / 'pilot'
PYTHON = sys.executable
LIMIT = 24

TASKS = {
    'billing': 'Fix billing so sales tax is calculated on the amount remaining after discounts. Preserve existing checkout, shipping, and discount behavior.',
    'kv': 'Implement the missing KVEntry and KVStore methods according to their docstrings. JSON snapshots are objects mapping string keys to string values; import merges them into the store without TTL. Preserve expiration and deletion contracts.',
    'pagination': 'Fix list_records: filter by owner and optional status before pagination, order by descending created_at with ascending id as tie-breaker, and return total matching records independent of the page. Pages are one-based; page and page_size must be positive. Preserve input records.',
}

PAGINATION = {
    'models.py': '''from dataclasses import dataclass

@dataclass(frozen=True)
class Record:
    id: int
    owner: str
    status: str
    created_at: int
''',
    'query.py': '''def matching(records, owner, status=None):
    """Select records belonging to owner and, when supplied, matching status."""
    return [r for r in records if r.owner == owner and (status is None or r.status == status)]

def ordered(records):
    """Newest first, with ascending id for identical timestamps."""
    return sorted(records, key=lambda r: r.created_at, reverse=True)

def page_slice(records, page, page_size):
    """Return a one-based page; reject nonpositive page or page_size."""
    start = page * page_size
    return records[start:start + page_size]
''',
    'service.py': '''from query import matching, ordered, page_slice

def list_records(records, owner, status=None, page=1, page_size=2):
    """Return {'items': list[Record], 'total': matching count} without changing input."""
    selected = page_slice(ordered(records), page, page_size)
    selected = matching(selected, owner, status)
    return {"items": selected, "total": len(selected)}
''',
    'test_contract.py': '''import unittest
from models import Record
from service import list_records

class Contract(unittest.TestCase):
    def setUp(self):
        self.rows = [Record(8,'b','open',90), Record(3,'a','open',20), Record(1,'a','open',20), Record(2,'a','closed',30), Record(4,'a','open',10)]
    def test_filter_then_page(self):
        result = list_records(self.rows,'a','open',1,2)
        self.assertEqual([r.id for r in result['items']], [1,3])
    def test_total(self):
        self.assertEqual(list_records(self.rows,'a','open',2,2)['total'],3)
    def test_second_page(self):
        self.assertEqual([r.id for r in list_records(self.rows,'a','open',2,2)['items']],[4])
    def test_no_status(self):
        self.assertEqual([r.id for r in list_records(self.rows,'a',page_size=4)['items']],[2,1,3,4])
    def test_empty_page(self):
        self.assertEqual(list_records(self.rows,'a',page=9)['items'],[])
        self.assertEqual(list_records(self.rows,'a',page=9)['total'],4)
    def test_invalid(self):
        for page,size in [(0,2),(-1,2),(1,0),(1,-1)]:
            with self.assertRaises(ValueError): list_records(self.rows,'a',page=page,page_size=size)
    def test_preserves_input(self):
        before = list(self.rows)
        list_records(self.rows,'a')
        self.assertEqual(self.rows,before)
    def test_missing_owner(self):
        self.assertEqual(list_records(self.rows,'z'),{'items': [], 'total': 0})
''',
}

def write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')

def digest(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob('*.py'))}

def check(directory):
    started = time.monotonic()
    try:
        result = subprocess.run([PYTHON, '-B', '-m', 'unittest', 'test_contract.py'], cwd=directory, capture_output=True, text=True, timeout=15)
        return {'passed': result.returncode == 0, 'exit_code': result.returncode, 'output': result.stdout + result.stderr, 'seconds': time.monotonic()-started}
    except subprocess.TimeoutExpired:
        return {'passed': False, 'exit_code': -1, 'output': 'Verification timed out.', 'seconds': time.monotonic()-started}

def fixtures():
    for task in TASKS:
        target = HOME / 'fixtures' / task
        target.mkdir(parents=True, exist_ok=False)
        if task == 'pagination':
            sources = PAGINATION
        else:
            source_dir = ROOT / ('project_bench' if task == 'billing' else 'greenfield_bench')
            sources = {p.name: p.read_text(encoding='utf-8') for p in source_dir.glob('*.py')}
            sources['test_contract.py'] = sources.pop('test_suite.py')
            if task == 'billing':
                sources['pricing.py'] = '\n'.join(line for line in sources['pricing.py'].splitlines() if 'BUG IS HERE' not in line) + '\n'
            else:
                for name in ['models.py', 'engine.py']:
                    source = sources[name]
                    lines = source.splitlines()
                    tree = ast.parse(source)
                    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name != '__init__']
                    for method in sorted(methods, key=lambda n: n.lineno, reverse=True):
                        doc = method.body[0]
                        start = doc.end_lineno if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str) else method.lineno
                        lines[start:method.end_lineno] = ['        raise NotImplementedError']
                    sources[name] = '\n'.join(lines) + '\n'
        for name, source in sources.items():
            (target / name).write_text(source, encoding='utf-8')
    originals = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for directory in ['project_bench','greenfield_bench'] for p in (ROOT / directory).glob('*.py')}
    write_json(HOME / 'original_hashes.json', originals)

def reference_check(task):
    target = HOME / 'reference' / task
    shutil.copytree(HOME / 'fixtures' / task, target)
    if task == 'billing':
        p = target / 'pricing.py'
        p.write_text(p.read_text().replace('tax_amount = round(subtotal * tax_rate, 2)', 'tax_amount = round(discounted_subtotal * tax_rate, 2)'), encoding='utf-8')
    elif task == 'kv':
        for name in ['models.py','engine.py']:
            source = (ROOT / 'greenfield_bench' / name).read_text()
            if name == 'engine.py':
                source = source.replace("for item in data:\n            key = item['key']\n            value = item['value']", 'for key, value in data.items():')
            (target / name).write_text(source, encoding='utf-8')
    else:
        p = target / 'query.py'
        p.write_text(p.read_text().replace('key=lambda r: r.created_at, reverse=True', 'key=lambda r: (-r.created_at, r.id)').replace('    start = page * page_size', '    if page <= 0 or page_size <= 0:\n        raise ValueError("Positive page and size required")\n    start = (page - 1) * page_size'), encoding='utf-8')
        p = target / 'service.py'
        p.write_text('from query import matching, ordered, page_slice\n\ndef list_records(records, owner, status=None, page=1, page_size=2):\n    selected = ordered(matching(records, owner, status))\n    return {"items": page_slice(selected, page, page_size), "total": len(selected)}\n', encoding='utf-8')
    return check(target)

def prepare():
    fixtures()
    validation = {}
    for task in TASKS:
        validation[task] = {'initial': check(HOME / 'fixtures' / task), 'reference': reference_check(task)}
        assert not validation[task]['initial']['passed'], task + ' must start failing'
        assert validation[task]['reference']['passed'], task + ' reference must pass'
        for repeat in [1,2]:
            for mode in ['full','foveated']:
                run_id = f'{task}_{repeat}_{mode}'
                run = HOME / 'runs' / run_id
                shutil.copytree(HOME / 'fixtures' / task, run / 'work')
                write_json(run / 'state.json', {'run_id': run_id, 'task': task, 'mode': mode, 'repeat': repeat, 'model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'initial_hashes': digest(run / 'work'), 'started': None, 'actions': [], 'finished': False})
    write_json(HOME / 'fixture_validation.json', validation)
    print(json.dumps(validation, indent=2))

def action(run_id, verb, args):
    if run_id not in {f'{t}_{r}_{m}' for t in TASKS for r in [1,2] for m in ['full','foveated']}:
        raise ValueError('Unknown run')
    run = HOME / 'runs' / run_id
    state = json.loads((run / 'state.json').read_text())
    if state['finished']:
        raise ValueError('Run is finished')
    started = time.time()
    if state['started'] is None:
        state['started'] = started
    result = ''
    error = False
    try:
        if len(state['actions']) >= LIMIT and verb != 'finish':
            raise ValueError('Action budget exhausted; call finish')
        work = run / 'work'
        if verb in ['view', 'edit']:
            name = args[0]
            if name not in state['initial_hashes']:
                raise ValueError('Unknown file')
            path = work / name
            lines = path.read_text(encoding='utf-8').splitlines()
        if verb == 'view':
            if state['mode'] == 'full':
                result = '\n'.join(f'{i:4d} | {line}' for i,line in enumerate(lines,1))
            elif len(args) == 1:
                result = extract_outline(path)
            else:
                start, end = map(int,args[1:3])
                if start < 1 or end < start or end-start+1 > 40:
                    raise ValueError('Use a positive inclusive range of at most 40 lines')
                result = '\n'.join(f'{i:4d} | {lines[i-1]}' for i in range(start,min(end,len(lines))+1))
        elif verb == 'edit':
            if name == 'test_contract.py':
                raise ValueError('Tests are read-only')
            start,end = map(int,args[1:3])
            if start < 1 or end < start or end > len(lines):
                raise ValueError('Invalid inclusive line range')
            content = base64.b64decode(args[3], validate=True).decode('utf-8')
            candidate = '\n'.join(lines[:start-1] + content.splitlines() + lines[end:])+'\n'
            ast.parse(candidate)
            path.write_text(candidate, encoding='utf-8')
            result = 'Edit applied. Line numbers may have changed.'
        elif verb in ['verify','finish']:
            verification = check(work)
            result = json.dumps(verification)
            if verb == 'finish':
                state['finished'] = True
                state['verification'] = verification
                state['final_hashes'] = digest(work)
                state['test_integrity'] = state['final_hashes']['test_contract.py'] == state['initial_hashes']['test_contract.py']
                state['success'] = verification['passed'] and state['test_integrity']
                state['elapsed_seconds'] = time.time()-state['started']
        else:
            raise ValueError('Unknown action')
    except Exception as exception:
        result = f'{type(exception).__name__}: {exception}'
        error = True
    state['actions'].append({'index': len(state['actions'])+1, 'verb': verb, 'args': args, 'result': result, 'returned_characters': len(result), 'error': error, 'timestamp': started, 'duration_seconds': time.time()-started})
    write_json(run / 'state.json', state)
    print(result)

def summarize():
    summaries = []
    for path in sorted((HOME / 'runs').glob('*/state.json')):
        state = json.loads(path.read_text())
        summaries.append({key: state.get(key) for key in ['run_id','mode','task','repeat','finished','success','elapsed_seconds']} | {'actions': len(state['actions']), 'edit_errors': sum(a['error'] for a in state['actions'] if a['verb']=='edit'), 'returned_characters': sum(a['returned_characters'] for a in state['actions']), 'view_characters': sum(a['returned_characters'] for a in state['actions'] if a['verb']=='view'), 'api_tokens': None})
    write_json(HOME / 'summary.json', summaries)
    print(json.dumps(summaries,indent=2))

if __name__ == '__main__':
    if sys.argv[1] == 'prepare': prepare()
    elif sys.argv[1] == 'summarize': summarize()
    else: action(sys.argv[1], sys.argv[2], sys.argv[3:])
