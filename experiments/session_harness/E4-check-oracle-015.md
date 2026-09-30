# E4 bounded check oracle 015: a `check` tool with three hidden-test counts per run

Date: 2026-09-28  
Status: approved; owner approved 2026-09-28 (cards/015.json, commit 52e6685); confirmed 2026-09-30: "I approved them"  
Stage: S6 (tool-use module). This treatment changes the task (the model gets a bounded acceptance signal), so it is
an arm of its own and its result is not a harness improvement on the same task; it measures how much of the
incumbent's failure is verification it cannot do. Machine-readable card: [`cards/015.json`](cards/015.json).

## Evidence (weakness to address)

Card 007 ([report](E3-calibration-007-report.md)): the hidden tests are the only reliable check and the model cannot
run them; in 057 it tried (pytest on the absent test root), and in 001 and 061 it finished a wrong fix without
checking. Register row "verification allocation".

## Candidate (runner flag `--oracle hidden-tests:3`, `hidden-test-oracle-v1`)

A tool `check()` with no arguments runs the task's hidden `fail_to_pass` tests on the current workspace and returns
only `{"failing": N, "passing": M, "calls_left": K}`: never test names, never output. At most 3 calls per run; a
fourth is refused with the count and runs nothing. Implementation:
[`reticle/tools/check_oracle.py`](../../reticle/tools/check_oracle.py). The tool schema is appended to the toolset's
(`reticle-tools-v3` itself is unchanged) and enters the protocol hash with the name, version and call cap.

How the model is kept from the tests: the evaluator bundle (the fix commit's test roots) stays outside the
workspace, as for final acceptance. Each check copies the bundle and a snapshot of the workspace into a fresh
directory under the session directory, runs `evaluate_task.py` there through the run's own backend (under OCI a
separate `--rm` container whose only mount is that directory; the model's commands mount only the workspace), and
deletes the directory before returning. The evaluator's output is parsed in memory and dropped: it is not journaled
through the execution controller, so no model-visible action, artifact, or history record holds it. The journal
gets one `oracle_check` event per call (counts, status, duration, whether the scratch copy was removed), a kind the
history tools do not expose.

## Arms and tasks

As [card 013](E4-finish-guard-013.md): incumbent versus incumbent plus `--oracle hidden-tests:3`, evolution set
(`sqlparse-mut-001`, `-022`, `-032`, `-057`, `-061`) and three solved-twice tasks (`-025`, `-034`, `-040`), 2
rollouts, arm order seeded per task and rollout (seed 15), scripted gold and noop controls under the treatment arm
first.

## Budgets

32 runs plus 2 controls, 20 responses and 24 attempts each (campaign cap 900 attempts). Each check runs the
evaluator once (the same pytest targets as final acceptance), inside the run's 1,200 active seconds.

## Acceptance rule

Mechanism check. Report per arm and set: accepted runs, checks used, the counts each check returned, what the model
did after a failing count, and runs that finished while their last check still reported failures. The oracle arm
is expected to raise acceptance; the question is by how much on the evolution set and at what cost on the
efficiency set. A large gain says verification, not diagnosis, limits the incumbent and argues for a verification
treatment that does not reveal hidden tests (card 013); a small one says the model cannot find the fault even when
told it has not.

## Fast stops

Plan section 5.3 and card 007's rules. Stop the campaign if any hidden test name or test output appears in a
request, a tool result, or the workspace of a treatment run (trajectory review), if an `oracle_check` event records
`scratch_removed: false`, or if a treatment run's recorded hash or `treatments` record differs from the plan.

## Reporting

`experiments/session_harness/E4-check-oracle-015-report.md`.
