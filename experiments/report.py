"""Regenerate the pilot report from recorded measurements and audits."""
import json
import statistics
import controlled

home = controlled.HOME
controlled.summarize()
rows = json.loads((home/'summary.json').read_text())
audit = json.loads((home/'audit.json').read_text())
assert len(rows)==12 and all(r['finished'] for r in rows), 'Finish all trials first'
assert len(audit['runs'])==12, 'Audit all trials first'
groups = {mode:[r for r in rows if r['mode']==mode] for mode in ['full','foveated']}

def total(mode,key): return sum(r[key] for r in groups[mode])
def mean(mode,key): return statistics.mean(r[key] for r in groups[mode])

reduction = 100*(1-total('foveated','view_characters')/total('full','view_characters'))
overhead = 100*(total('foveated','actions')/total('full','actions')-1)
lines = [
    '# Luna reading-interface pilot', '',
    'Twelve fresh GPT-5.6 Luna agents (low reasoning effort), three tasks, two repetitions per reading mode. No conversation history was forked into participants.', '',
    f"Both modes passed {total('full','success')}/6 and {total('foveated','success')}/6 trials respectively. Foveation returned {reduction:.1f}% less source-view text in aggregate, while requiring {overhead:.1f}% more interface actions. This pilot measures a reading-efficiency tradeoff; it does not demonstrate a correctness advantage.", '',
    '| Measurement | Full file | Outline + bounded regions |',
    '|---|---:|---:|',
    f"| Public-suite successes | {total('full','success')}/6 | {total('foveated','success')}/6 |",
    f"| Source-view characters, total | {total('full','view_characters'):,} | {total('foveated','view_characters'):,} |",
    f"| All tool-returned characters, total | {total('full','returned_characters'):,} | {total('foveated','returned_characters'):,} |",
    f"| Interface actions, total | {total('full','actions')} | {total('foveated','actions')} |",
    f"| Mean actions per trial | {mean('full','actions'):.1f} | {mean('foveated','actions'):.1f} |",
    f"| Rejected edits | {total('full','edit_errors')} | {total('foveated','edit_errors')} |",
    f"| Mean elapsed seconds | {mean('full','elapsed_seconds'):.1f} | {mean('foveated','elapsed_seconds'):.1f} |",
    '| API token usage | Unavailable | Unavailable |', '',
    '## Per-trial results', '',
    '| Task | Repeat | Mode | Passed | Actions | View characters | Rejected edits | Seconds |',
    '|---|---:|---|---|---:|---:|---:|---:|',
]
for row in rows:
    lines.append(f"| {row['task']} | {row['repeat']} | {row['mode']} | {row['success']} | {row['actions']} | {row['view_characters']:,} | {row['edit_errors']} | {row['elapsed_seconds']:.1f} |")
lines += ['', '## Interpretation', '',
    'The billing task has enough irrelevant source that an outline can help select a smaller region. The KV task requires implementing most methods in a small file, so reading much of that file is useful. One foveated KV trial incurred four rejected edits involving stale or incorrect line ranges; it recovered and passed. A full-file pagination trial also incurred a rejected edit. These outcomes motivate testing stable edit anchors separately from reading mode.', '',
    'All tasks were solvable with both interfaces under the shared budget. A useful next test would increase repository size and irrelevant code while retaining a small required change. Include a third adaptive mode that permits full reads of small files. Use a direct API runner when credentials are available to measure actual input, output, and reasoning tokens; character reductions alone cannot establish lower cost.', '',
    '## Validation', '',
    f"Original source files preserved: {audit['original_files_preserved']}. Initial and final snapshot hashes match for every audited trial: {all(r['initial_snapshot_matches'] and r['final_snapshot_matches'] for r in audit['runs'])}.", '',
    f"Independent public-suite rechecks passed for {sum(r['public_recheck']['passed'] for r in audit['runs'])}/12 candidates. Supplementary contract checks passed for {sum(r['supplementary_passed'] for r in audit['runs'])}/12 candidates. These extra checks cover billing combinations, KV expiration and import boundaries, and generated pagination combinations. They were added during the pilot, not preregistered as the primary endpoint.", '',
    'Five driver tests passed, covering bounded reads, atomic rejection of invalid syntax, protected tests and paths, failing final verification, and genuinely passing final verification.', '',
    '## Scope and access', '',
    'The configured OpenRouter connection rejected Luna with HTTP 402 and its free Liquid model with a daily-quota HTTP 429. Benchmark work therefore used the native agent runner with the requested `gpt-5.6-luna` alias, rather than the original HTTP harness. The exact model snapshot and API token counts are not exposed.', '',
    'The controlled CLI equalizes file operations, tests, and action budgets. Native-agent system context and generic shell-tool access remain present; interface-only access is instructed rather than secured by OS isolation. Agents were not given task solutions or parent findings. Up to three independent trials shared the runner, so elapsed time is descriptive, not a clean latency comparison. Time starts at the first interface action and ends at final verification, excluding startup and final prose.', '',
    'Two repeats on three small tasks are a pilot, not a statistically persuasive estimate of general capability. Source-view characters count each returned view once; they are not cumulative context usage. The experiment omits editorial refactoring, prediction pruning, and memory consolidation.', '',
    'Protocol: [README](../README.md). Measurements: [summary.json](summary.json). Validation: [audit.json](audit.json). Each `runs/<run_id>/` directory contains complete interface action/result logs, the final source snapshot, and a candidate diff.',
]
(home/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:18]))
