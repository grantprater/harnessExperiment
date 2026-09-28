# E4 finish guard 013: demand a reproduced failure that the fix turns into a pass, once

Date: 2026-09-28  
Status: proposed; awaiting owner approval  
Stage: S6 (task-completion-detection module, "pre-finish verification rule" surface). Machine-readable card:
[`cards/013.json`](cards/013.json).

## Evidence (weakness to address)

Card 007 ([report](E3-calibration-007-report.md) and its 2026-09-28 correction from weakness mining of all 40
journals): 4 of 8 rejections ended with `finish`, 4 at the response budget. Every run that finished (001-r1, 057-r1,
057-r2, 061-r1) had run a check after its last edit: an exit-0 `python -c` that imports `sqlparse` on inputs the
model chose (confirmed here from their `calls.jsonl`). In 3 of 4 the reported failure was never reproduced. "pytest
found no tests" happened in 19 of the 32 accepted runs too. So neither "a check ran after the edit" nor "no tests
ran" separates the failures; what is missing is a reproduced failure that the fix turns into a pass.

## Candidate (runner flag `--completion finish-guard`, `finish-guard-v2`, fail-then-pass)

After an edit to a pre-existing source file, `finish` is accepted only if the run shows a `run` command that
failed before the first source edit (non-zero exit, or a traceback or AssertionError in its output) and the same
command, or the same script path, passing after the latest edit (exit 0, no traceback). A run that executed no check
is neither: a command that could not start (exit 126/127, "can't open file"), a test runner that ran no tests (kept
as a journal fact), a timeout or rejected call. Otherwise the first such `finish` is rejected with a message that
says so: reproduce the reported failure with a failing command, then run the same command after the fix and show it
passing; the next `finish` is accepted regardless and recorded as forced. Nothing else changes: same instructions,
same tool schemas (`reticle-tools-v3`), same context policy (`pressure-recent-v3`). Implementation:
[`reticle/tools/finish_guard.py`](../../reticle/tools/finish_guard.py); "source file" is
[`reticle/runtime/source_edits.py`](../../reticle/runtime/source_edits.py) (`pre-existing-python-source-v1`). The rule
name, rejection text, reasons and rule version enter the protocol hash under `treatments.completion`.
(`finish-guard-v1`, "a check ran since the edit", was replaced before any run: it would not have fired on any of the
four runs above.)

Journal: one `finish_guard` event per decision (`guard_triggered`, `guard_reason` or the `matched_pair` of failing and
passing commands, `forced_finish`, edited files, run counts before the first and after the latest edit, and the
test-runner calls that ran no tests); `results.jsonl` carries `treatments.completion`.

Expected firing rate, from an offline replay of the rule over card 007's journals (rebuilt from `calls.jsonl`): it
fires on all 4 rejected runs that finished and on 30 of the 32 accepted runs (2 accepted runs did fail-then-pass
unprompted). The rule does not separate outcomes; the card measures what demanding the pair changes. Its cost is at
least one response on nearly every run, which the efficiency set measures.

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
what the model did after the rejection (reproduced and reran, edited again, forced finish), how many forced
finishes the evaluator rejected, and responses and active seconds per run. The candidate earns a larger held-out
card only if it loses no accepted run on the efficiency set, its median responses per run there rise by at most 2,
and on the evolution set its accepted count is at least the incumbent's. Otherwise reject and log.

## Fast stops

Plan section 5.3 and card 007's rules. Additionally stop if a treatment run's recorded protocol hash or
`treatments` record differs from the plan, or if a guard rejection ever repeats within a run (the guard fires at
most once by construction).

## Reporting

`experiments/session_harness/E4-finish-guard-013-report.md` (skeleton written by `run_card.py`), with the paired
table, the guard's decisions from the journals, and the decision.
