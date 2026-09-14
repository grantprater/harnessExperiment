"""Independently check snapshots, original-file preservation, and final candidates."""
import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import controlled

home = controlled.HOME
originals = json.loads((home / 'original_hashes.json').read_text())
preserved = all(hashlib.sha256((controlled.ROOT/name).read_bytes()).hexdigest()==sha for name,sha in originals.items())
results = []
for path in sorted((home/'runs').glob('*/state.json')):
    state = json.loads(path.read_text())
    if not state['finished']: continue
    work = path.parent/'work'
    fixture = home/'fixtures'/state['task']
    extra = subprocess.run([sys.executable,'-B',str(Path(__file__).parent/'extra_checks.py'),state['task'],str(work)],capture_output=True,text=True,timeout=20)
    diff = ''.join(''.join(difflib.unified_diff((fixture/name).read_text().splitlines(True),(work/name).read_text().splitlines(True),fromfile='before/'+name,tofile='after/'+name)) for name in state['initial_hashes'])
    (path.parent/'candidate.diff').write_text(diff,encoding='utf-8')
    results.append({'run_id':state['run_id'],'initial_snapshot_matches':state['initial_hashes']==controlled.digest(fixture),'final_snapshot_matches':state['final_hashes']==controlled.digest(work),'public_recheck':controlled.check(work),'supplementary_passed':extra.returncode==0,'supplementary_output':extra.stdout+extra.stderr})
report = {'original_files_preserved':preserved,'runs':results}
controlled.write_json(home/'audit.json',report)
print(json.dumps({'original_files_preserved':preserved,'completed_runs':len(results),'public_passes':sum(r['public_recheck']['passed'] for r in results),'supplementary_passes':sum(r['supplementary_passed'] for r in results),'snapshot_matches':all(r['initial_snapshot_matches'] and r['final_snapshot_matches'] for r in results)},indent=2))
