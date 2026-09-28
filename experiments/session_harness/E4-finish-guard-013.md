# E4 finish guard 013: reject the first unverified finish after a source edit, once

Date: 2026-09-28  
Status: proposed; awaiting owner approval  
Stage: S6 (task-completion-detection module, "pre-finish verification rule" surface). Machine-readable card:
[`cards/013.json`](cards/013.json).

## Evidence (weakness to address)

Card 007 ([report](E3-calibration-007-report.md)): 5 of 8 rejections were a confident wrong fix. The model edited
library code and called `finish` without a check that exercised the edit: 001-r1 and 061-r1 ran no tests at all;
057-r1 and 057-r2 ran pytest on the hidden (absent) test root, saw that no tests ran, and finished anyway. This is
the register's "verification allocation" failure in its sharpest form: "no tests ran" read as a pass.

## Candidate (runner flag `--completion finish-guard`, `finish-guard-v1`)

The first `finish` after an edit to a pre-existing source file is rejected, once, unless a `run` since that edit
shows a test or check executing: a pytest or unittest summary reporting at least one test, or a Python command
that imports the edited package and prints something (a reproduction script). "no tests ran", "collected 0 items",
a missing test file, a collection error alone, and a print-only command do not count. The rejection names the
edited files, why nothing counted, and what would count, and says the next `finish` will be accepted regardless;
that finish is recorded as forced. Nothing else changes: same instructions, same tool schemas (`reticle-tools-v3`),
same context policy (`pressure-recent-v3`). Implementation: [`reticle/tools/finish_guard.py`](../../reticle/tools/finish_guard.py);
the rule for "source file" is [`reticle/runtime/source_edits.py`](../../reticle/runtime/source_edits.py)
(`pre-existing-python-source-v1`). The rejection text, the reasons, and the rule version enter the protocol hash
under `treatments.completion`.

Journal: one `finish_guard` event per decision (`guard_triggered`, `guard_reason`, `forced_finish`, edited files,
runs since the edit); `results.jsonl` carries `treatments.completion`.

## Arms and tasks

Incumbent (card 007's arm: Sonnet via `claude-cli`, `pressure-recent-v3`, isolated OCI, repeat guard off) versus
the same arm with `--completion finish-guard`. Tasks: card 007's evolution set (`sqlparse-mut-001`, `-022`, `-032`,
`-057`, `-061`) and three tasks card 007 solved twice (`-025`, `-034`, `-040`) for the efficiency measure. 2
rollouts per task per arm, arm order seeded per task and rollout (seed 13). Scripted gold and noop controls on
`sqlparse-mut-001` under the treatment arm run first (the gold client's first finish is rejected by the guard and
its second is forced; both must still be judged as expected).

Note on the efficiency tasks: by card 007 wall time the three fastest solved-twice tasks are 034, 025 and 044
(040 is fifth; 044 and 073 are faster); the set follows the owner's stated list.

## Budgets

(5 + 3) tasks x 2 rollouts x 2 arms = 32 runs plus 2 scripted controls, serialised under the live-run lock, 20
responses and 24 attempts each (campaign cap 900 attempts). At card 007's mean of 229 s per run, about two hours.
No monetary cost (CLI on the subscription).

## Acceptance rule

A mechanism check, not a promotion: 8 tasks x 2 rollouts cannot resolve effects below roughly 15 points (S6 noise
budget), and the evolution set is held-in. Report per arm and per set: accepted runs, how often the guard fired,
what the model did after the rejection (ran a check, edited again, forced finish), how many forced finishes the
evaluator rejected, and responses and active seconds per run. The candidate earns a larger held-out card only if
it loses no accepted run on the efficiency set, its median responses per run there rise by at most 2, and on the
evolution set its accepted count is at least the incumbent's. Otherwise reject and log.

## Fast stops

Plan section 5.3 and card 007's rules. Additionally stop if a treatment run's recorded protocol hash or
`treatments` record differs from the plan, or if a guard rejection ever repeats within a run (the guard fires at
most once by construction).

## Reporting

`experiments/session_harness/E4-finish-guard-013-report.md` (skeleton written by `run_card.py`), with the paired
table, the guard's decisions from the journals, and the decision.
