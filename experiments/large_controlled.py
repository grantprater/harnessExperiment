"""Larger repository experiment with full, foveated, and adaptive observation."""
from __future__ import annotations
import ast
import base64
import difflib
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from large_fixture import HIDDEN, MUTATIONS, TASKS, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from perception import extract_outline, extract_symbol

HOME = ROOT/'experiments'/'large_v1'
MODES = ['full','foveated','adaptive']
REPEATS = [1,2]
LIMIT = 36
OBSERVATIONS = {'tree','search','outline','region','file','symbol'}
ALLOWED = {'full':{'tree','search','file'},'foveated':{'tree','search','outline','region','symbol'},'adaptive':OBSERVATIONS}

def save(path,data): path.write_text(json.dumps(data,indent=2),encoding='utf-8')
def hashes(directory):
    return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}

def check(work,hidden=False):
    started = time.monotonic()
    if hidden:
        code = "import os,runpy,sys; path=sys.argv.pop(); sys.path.insert(0,os.getcwd()); runpy.run_path(path,run_name='__main__')"
        cmd = [sys.executable,'-B','-c',code,str(HOME/'held_out.py')]
    else:
        cmd = [sys.executable,'-B','-m','unittest','test_contract.py']
    try:
        result = subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=20)
        return {'passed':result.returncode==0,'exit_code':result.returncode,'output':result.stdout+result.stderr,'seconds':time.monotonic()-started}
    except subprocess.TimeoutExpired:
        return {'passed':False,'exit_code':-1,'output':'Verification timed out.','seconds':time.monotonic()-started}

def protocol(state):
    return f'''Task: {TASKS[state['task']]}
Run: {state['run_id']}. Assigned observation mode: {state['mode']}.
This is a synthetic Python repository. Find relevant code yourself.
Observation commands:
  tree [PREFIX]: list repository files and line counts (all modes).
  search LITERAL [PREFIX]: case-insensitive literal search; up to 30 matching lines (all modes).
  file PATH: entire file with line numbers (full and adaptive only).
  outline PATH: AST symbol outline (foveated and adaptive only).
  symbol PATH SYMBOL_NAME: exact symbol definition with line numbers (foveated and adaptive only).
  region PATH START END: inclusive numbered source, at most 40 lines (foveated and adaptive only).
Adaptive mode may freely choose and combine all observation types. No requirement to outline before reading.
Shared actions:
  edit PATH OLD_BASE64 NEW_BASE64: replace one unique exact UTF-8 snippet. Preserve indentation; syntax is checked atomically. No line-number editing.
  verify: run the fixed public test suite.
  finish: independently rerun public tests and finalize, even if unsolved.
Tests and documentation are read-only. Only existing dispatchdesk/*.py descendants may be edited.
Budget: {LIMIT} actions after start, plus finish. No editorial pass. Stop after solving and call finish.
Use only this interface; do not read the runner, other trials, fixtures, reference solutions, or logs.
No direct file access, arbitrary commands, browsing, delegation, or parent help. In-memory base64 computation in PowerShell is allowed.
Call one interface action per exec_command, max_output_tokens=24000 to preserve complete observations.
'''

def participant_prompt(run_id):
    python = ROOT/'.runtime/python/cpython-3.13.15-windows-x86_64-none/python.exe'
    script = ROOT/'experiments/large_controlled.py'
    return f"""You are a benchmark participant. Solve the task returned by start, using ONLY the controlled interface. Do not use direct file access, other perception/editing tools, delegation, browsing, or read benchmark implementation, other runs, logs, or reference solutions. Do not ask the parent for hints. Start immediately with this PowerShell command through functions exec/exec_command: & '{python}' -B '{script}' {run_id} start. The response documents task, observation mode, and all allowed commands. Subsequently call the same command with start replaced by an allowed verb and arguments. You may compute UTF-8 base64 replacement snippets in memory using PowerShell here-strings and [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($snippet)); no other shell operations are allowed. One interface action per exec_command. Set max_output_tokens=24000 so observations are not truncated. Always call finish, even if unable to solve. Final answer should state only whether verification passed."""

def prepare():
    if HOME.exists(): raise ValueError('Dataset exists; choose a new HOME to rerun')
    HOME.mkdir(parents=True)
    sources = repository()
    golden = HOME/'reference'
    for name,source in sources.items():
        path = golden/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(source,encoding='utf-8')
    (HOME/'held_out.py').write_text(HIDDEN,encoding='utf-8')
    public,hidden = check(golden),check(golden,True)
    assert public['passed'] and hidden['passed'], (public,hidden)
    validation = {'reference_public':public,'reference_hidden':hidden,'fixtures':{}}
    for task in TASKS:
        target = HOME/'fixtures'/task
        shutil.copytree(golden,target)
        for name,old,new in MUTATIONS[task]:
            path = target/name
            source = path.read_text(encoding='utf-8')
            assert source.count(old)==1
            path.write_text(source.replace(old,new,1),encoding='utf-8')
        initial,heldout = check(target),check(target,True)
        assert not initial['passed'] and not heldout['passed'], task+' must fail both suites'
        validation['fixtures'][task] = {'public':initial,'hidden':heldout,'hashes':hashes(target)}
        for repeat in REPEATS:
            for mode in MODES:
                run_id = f'{task}_{repeat}_{mode}'
                run = HOME/'runs'/run_id
                shutil.copytree(target,run/'work')
                state = {'run_id':run_id,'task':task,'repeat':repeat,'mode':mode,'model':'gpt-5.6-luna','reasoning_effort':'low','initial_hashes':hashes(target),'started':None,'finished':False,'actions':[]}
                save(run/'state.json',state)
                (run/'participant_prompt.txt').write_text(participant_prompt(run_id),encoding='utf-8')
                (run/'protocol.txt').write_text(protocol(state),encoding='utf-8')
    save(HOME/'fixture_validation.json',validation)
    save(HOME/'manifest.json',{'model':'gpt-5.6-luna','reasoning_effort':'low','modes':MODES,'repeats':REPEATS,'action_limit':LIMIT,'files':len(sources),'python_files':sum(name.endswith('.py') for name in sources),'lines':sum(len(source.splitlines()) for source in sources.values()),'source_lines':sum(len(source.splitlines()) for name,source in sources.items() if name.startswith('dispatchdesk/')),'heldout_hash':hashlib.sha256(HIDDEN.encode()).hexdigest(),'harness_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'generator_hash':hashlib.sha256((ROOT/'experiments/large_fixture.py').read_bytes()).hexdigest(),'created_at':time.time()})
    print(json.dumps(json.loads((HOME/'manifest.json').read_text()),indent=2))

def action(run_id,verb,args):
    valid = {f'{t}_{r}_{m}' for t in TASKS for r in REPEATS for m in MODES}
    if run_id not in valid: raise ValueError('Unknown run')
    run = HOME/'runs'/run_id
    state = json.loads((run/'state.json').read_text())
    if state['finished']: raise ValueError('Run already finished')
    started = time.time()
    if state['started'] is None: state['started'] = started
    result,error = '',False
    details = {}
    try:
        used = sum(a['verb'] not in ['start','finish'] for a in state['actions'])
        if used >= LIMIT and verb!='finish': raise ValueError('Action budget exhausted; call finish')
        if verb in OBSERVATIONS and verb not in ALLOWED[state['mode']]:
            raise ValueError('Observation not available in assigned mode')
        work = run/'work'
        names = sorted(state['initial_hashes'])
        if verb=='start':
            if state['actions']: raise ValueError('Start is only allowed once')
            result = protocol(state)
        elif verb=='tree':
            prefix = args[0] if args else ''
            result = '\n'.join(f"{name} ({len((work/name).read_text(encoding='utf-8').splitlines())} lines)" for name in names if name.startswith(prefix))
        elif verb=='search':
            query = args[0]
            if len(query.strip())<2 or len(query)>100: raise ValueError('Use a literal query of 2-100 characters')
            prefix = args[1] if len(args)>1 else ''
            matches = []
            for name in names:
                if not name.startswith(prefix): continue
                for i,line in enumerate((work/name).read_text(encoding='utf-8').splitlines(),1):
                    if query.lower() in line.lower(): matches.append(f'{name}:{i}: {line}')
            result = '\n'.join(matches[:30])+f'\nMatches: {len(matches)}; returned: {min(30,len(matches))}. Narrow with PREFIX if needed.'
        elif verb in ['file','outline','region','symbol','edit']:
            name = args[0]
            if name not in state['initial_hashes']: raise ValueError('Unknown repository file')
            path = work/name
            source = path.read_text(encoding='utf-8')
            lines = source.splitlines()
            details = {'file':name,'file_lines':len(lines)}
            if verb=='file':
                result = '\n'.join(f'{i:4d} | {line}' for i,line in enumerate(lines,1))
            elif verb=='outline':
                if not name.endswith('.py'): raise ValueError('AST outline requires Python source')
                result = extract_outline(path, inline_small=False)
            elif verb=='symbol':
                if not name.endswith('.py'): raise ValueError('Symbol extraction requires Python source')
                if len(args)<2: raise ValueError('Specify SYMBOL_NAME to extract')
                result = extract_symbol(path, args[1])
            elif verb=='region':
                start,end = map(int,args[1:3])
                if start<1 or end<start or end-start+1>40: raise ValueError('Use a positive inclusive range of at most 40 lines')
                result = '\n'.join(f'{i:4d} | {lines[i-1]}' for i in range(start,min(end,len(lines))+1))
            else:
                if not name.startswith('dispatchdesk/') or not name.endswith('.py'): raise ValueError('Tests and docs are read-only')
                old,new = [base64.b64decode(value,validate=True).decode('utf-8').replace('\r\n','\n') for value in args[1:3]]
                if not old or source.count(old)!=1: raise ValueError('Old snippet must match exactly once')
                candidate = source.replace(old,new,1)
                ast.parse(candidate)
                path.write_text(candidate,encoding='utf-8')
                result = 'Edit applied.'
        elif verb in ['verify','finish']:
            verification = check(work)
            result = json.dumps(verification)
            if verb=='finish':
                final = hashes(work)
                state.update(finished=True,verification=verification,final_hashes=final,elapsed_seconds=time.time()-state['started'])
                state['protected_integrity'] = all(final.get(name)==sha for name,sha in state['initial_hashes'].items() if not name.startswith('dispatchdesk/'))
                state['success'] = verification['passed'] and state['protected_integrity']
        else: raise ValueError('Unknown action')
    except Exception as exception:
        error = True
        result = f'{type(exception).__name__}: {exception}'
    state['actions'].append({'index':len(state['actions'])+1,'verb':verb,'args':args,'result':result,'returned_characters':len(result),'error':error,'timestamp':started,'duration_seconds':time.time()-started,**details})
    save(run/'state.json',state)
    print(result)

def audit():
    rows = []
    manifest = json.loads((HOME/'manifest.json').read_text())
    # The prelaunch digest was computed from LF-normalized generator text.
    assert hashlib.sha256((HOME/'held_out.py').read_text(encoding='utf-8').encode('utf-8')).hexdigest()==manifest['heldout_hash']
    for path in sorted((HOME/'runs').glob('*/state.json')):
        state = json.loads(path.read_text())
        if not state['finished']: continue
        work = path.parent/'work'
        initial = HOME/'fixtures'/state['task']
        public,hidden = check(work),check(work,True)
        actions = state['actions']
        row = {key:state[key] for key in ['run_id','task','mode','repeat','elapsed_seconds']}
        row.update(public_passed=public['passed'],hidden_passed=hidden['passed'],protected_integrity=state['protected_integrity'],snapshots_match=state['initial_hashes']==hashes(initial) and state['final_hashes']==hashes(work),actions=sum(a['verb']!='start' for a in actions),observation_characters=sum(a['returned_characters'] for a in actions if a['verb'] in OBSERVATIONS),source_view_characters=sum(a['returned_characters'] for a in actions if a['verb'] in ['file','outline','region']),returned_characters=sum(a['returned_characters'] for a in actions),edit_errors=sum(a['error'] for a in actions if a['verb']=='edit'),observation_choices=dict(Counter(a['verb'] for a in actions if a['verb'] in OBSERVATIONS)),api_tokens=None)
        save(path.parent/'audit.json',{'public':public,'hidden':hidden,'summary':row})
        diff = ''.join(''.join(difflib.unified_diff((initial/name).read_text().splitlines(True),(work/name).read_text().splitlines(True),fromfile='before/'+name,tofile='after/'+name)) for name in state['initial_hashes'])
        (path.parent/'candidate.diff').write_text(diff,encoding='utf-8')
        rows.append(row)
    save(HOME/'summary.json',rows)
    print(json.dumps(rows,indent=2))

if __name__=='__main__':
    if sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='audit': audit()
    elif sys.argv[1]=='prompt': print(participant_prompt(sys.argv[2]))
    else: action(sys.argv[1],sys.argv[2],sys.argv[3:])
