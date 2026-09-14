"""Summarize frozen large-repository trial logs without estimating API tokens."""
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
import large_controlled as driver

home = driver.HOME
rows = json.loads((home/'summary.json').read_text())
assert len(rows)==18, 'Run and audit all 18 trials first'
manifest = json.loads((home/'manifest.json').read_text())
groups = {mode:[r for r in rows if r['mode']==mode] for mode in driver.MODES}

def total(mode,key): return sum(r[key] for r in groups[mode])
def mean(mode,key): return statistics.mean(r[key] for r in groups[mode])

choices = {}
adaptive_reads = []
for mode in driver.MODES:
    attempted,successful = Counter(),Counter()
    for row in groups[mode]:
        state = json.loads((home/'runs'/row['run_id']/'state.json').read_text())
        for action in state['actions']:
            if action['verb'] in driver.OBSERVATIONS:
                attempted[action['verb']]+=1
                if not action['error']:
                    successful[action['verb']]+=1
                    if mode=='adaptive' and action['verb'] in ['file','outline','region']:
                        adaptive_reads.append({'run_id':row['run_id'],'kind':action['verb'],'file':action['file'],'file_lines':action['file_lines'],'args':action['args'][1:],'characters':action['returned_characters']})
    choices[mode] = {'attempted':dict(attempted),'successful':dict(successful),'rejected':sum(attempted.values())-sum(successful.values())}
driver.save(home/'observation_choices.json',{'by_mode':choices,'adaptive_reads':adaptive_reads})

lines = ['# Larger-repository Luna observation experiment','',
    f"Generated DispatchDesk: {manifest['python_files']} Python files, {manifest['source_lines']:,} package source lines. Ran 18 fresh GPT-5.6 Luna agents (low reasoning effort): three tasks, three observation modes, two repetitions each.",'',
    '| Metric | Full files | Foveated | Adaptive choice |',
    '|---|---:|---:|---:|',
    '| Public-suite passes | '+' | '.join(f"{total(m,'public_passed')}/6" for m in driver.MODES)+' |',
    '| Held-out-suite passes | '+' | '.join(f"{total(m,'hidden_passed')}/6" for m in driver.MODES)+' |',
    '| Observation characters | '+' | '.join(f"{total(m,'observation_characters'):,}" for m in driver.MODES)+' |',
    '| Source-view characters | '+' | '.join(f"{total(m,'source_view_characters'):,}" for m in driver.MODES)+' |',
    '| Actions (excluding start, including finish) | '+' | '.join(str(total(m,'actions')) for m in driver.MODES)+' |',
    '| Rejected edits | '+' | '.join(str(total(m,'edit_errors')) for m in driver.MODES)+' |',
    '| Unavailable observation attempts | '+' | '.join(str(choices[m]['rejected']) for m in driver.MODES)+' |',
    '| Mean elapsed seconds | '+' | '.join(f"{mean(m,'elapsed_seconds'):.1f}" for m in driver.MODES)+' |',
    '| API tokens/cost | Unavailable | Unavailable | Unavailable |','',
    'Observation characters include tree, search, outlines, regions, and full reads. Source-view characters include only outlines, regions, and full reads. These are returned text, not cumulative context tokens or billed usage. Rejected observation attempts consume actions but reveal no forbidden source.','',
    '## Paired task results','',
    '| Task | Mode | Held-out passes | Observation characters | Actions |',
    '|---|---|---:|---:|---:|',
]
for task in driver.TASKS:
    for mode in driver.MODES:
        subset = [r for r in groups[mode] if r['task']==task]
        lines.append(f"| {task} | {mode} | {sum(r['hidden_passed'] for r in subset)}/2 | {sum(r['observation_characters'] for r in subset):,} | {sum(r['actions'] for r in subset)} |")
lines += ['', '## What the model chose','',
    '| Successful observation | Full files | Foveated | Adaptive choice |',
    '|---|---:|---:|---:|',
]
for kind in ['tree','search','file','outline','region']:
    lines.append('| '+kind+' | '+' | '.join(str(choices[m]['successful'].get(kind,0)) for m in driver.MODES)+' |')
lines += ['', '| Adaptive trial | Observation | File | File length | Requested region |',
    '|---|---|---|---:|---|']
for read in adaptive_reads:
    lines.append(f"| {read['run_id']} | {read['kind']} | {read['file']} | {read['file_lines']} | {'-'.join(read['args']) or '—'} |")
lines += ['', '## Interpretation and limits','',
    'The concrete hypothesis is whether letting the model choose observation scale can preserve correctness while reducing retrieval overhead. The adaptive quote trial in repetition 1 read the small billing service in full, searched for the tax helper, then requested a short region of the large pricing module. That is an observed use of mixed resolution, not an imposed outline-first policy.','',
    'Repository size alone is not task difficulty. These defects have localized fixes, named public APIs, regular generated code, and tests exposing concrete failures. Common search lets every mode avoid most unrelated files. Perfect scores therefore indicate a ceiling on this task set, not equivalence on difficult real repositories. Two repetitions per task are insufficient for broad causal or statistical claims.','',
    'Adaptive retrieval is not guaranteed to choose economically: extra test reads, redundant searches, or full reads of large modules can erase savings. Inspect the per-task totals and recorded choices before interpreting aggregate results. Character reductions do not establish lower token cost or latency.','',
    'The next useful benchmark would be a pinned real repository with a reproducible regression, plus tasks that require following cross-module invariants. Keep search and exact-snippet edits identical across arms. Measure API tokens when direct model access is available. Do not add memory pruning or an editorial pass until observation choice is measured independently.','',
    '## Validation and reproducibility','',
    f"All initial and final snapshots match their recorded hashes: {all(r['snapshots_match'] for r in rows)}. Protected tests/docs remained unchanged: {all(r['protected_integrity'] for r in rows)}.",'',
    'The public and held-out tests were fixed before any trial started. Golden code passed both; each seeded fixture failed both. Six interface tests passed, covering mode restrictions, adaptive views, exact edits, atomic failures, protected paths/tests, and independent final verification.','',
    'The held-out hash is over UTF-8 text normalized to LF, matching the generator source. An audit-only correction accounted for Windows CRLF storage; held-out content and participant interface behavior were unchanged.','',
    'Native agents received fresh contexts and no parent hints, but interface-only access is a protocol constraint, not OS-level isolation. The runner does not expose exact model snapshots, seeds, API token usage, or total system-context overhead. Up to three trials shared the runner, and elapsed time includes scheduling delays.','',
    'Shared exact-snippet edits and search differ from the earlier pilot. Do not attribute cross-pilot changes solely to repository size. No original harness or earlier trial files were changed.','',
    'Protocol: [LARGE_PROTOCOL.md](../LARGE_PROTOCOL.md). Dataset: [manifest.json](manifest.json). Metrics: [summary.json](summary.json). Observation choices: [observation_choices.json](observation_choices.json). Browse the [generated source](reference/README.md). Each run folder contains its exact prompt, protocol, complete action/result logs, final source snapshot, public/held-out audit, and diff.','',
    '## Per-trial metrics','',
    '| Trial | Public | Held-out | Actions | Observation characters | Edit errors | Seconds |',
    '|---|---|---|---:|---:|---:|---:|',
]
for row in rows:
    lines.append(f"| {row['run_id']} | {row['public_passed']} | {row['hidden_passed']} | {row['actions']} | {row['observation_characters']:,} | {row['edit_errors']} | {row['elapsed_seconds']:.1f} |")
(home/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:18]))
