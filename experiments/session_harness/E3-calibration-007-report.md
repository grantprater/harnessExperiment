# E3 calibration 007 report: mutation-task bank, Claude Sonnet 5 through the Reticle interface

Date: 2026-09-28 (campaign 2026-09-28 00:07 to 02:40 UTC)  
Card: [E3-calibration-007](E3-calibration-007.md). Approved by the owner in session on 2026-09-27; launched by
the owner from a terminal with [`run_card007.py`](run_card007.py) `--execute` (the session's permission
classifier refused to launch the campaign from inside the session, twice; see "Provenance").  
Status: **complete, 40 of 40 runs, no crashes, no adapter failures. The card's pass rule (at least 5
contrastive tasks) is not met: 2 contrastive, 3 negative, 15 solved twice.**  
Protocol: runner v8, `--client claude-cli` (adapter v2, `claude-sonnet-5`, CLI 2.1.283), `pressure-recent-v3`,
`reticle-tools-v3`, isolated OCI image `8b74015e5079`, materializer `mutation-workspace-v2`, repeat guard off,
protocol hash `b0fda8c921ad` for every calibration run (per-task contract differs; see `config.json`).
Task file `tasks.mutations.json` (LF sha256 `fa185723735d...`), selection seed 7
([`E3-calibration-007-tasks.json`](E3-calibration-007-tasks.json)). Evidence: `experiments/p6_pilot/runs/c007-*`,
[`c007-campaign.jsonl`](c007-campaign.jsonl).

## Acceptance table

| Task | Kind | `fail_to_pass` | Accepted of 2 | Rollout 1 | Rollout 2 |
|---|---|---:|:---:|---|---|
| sqlparse-mut-001 | compare_flip | 1 | **1** | rejected, finish | accepted, finish (731 s) |
| sqlparse-mut-002 | drop_not | 9 | 2 | accepted | accepted |
| sqlparse-mut-022 | negate_condition | 41 | **1** | rejected, budget | accepted, finish |
| sqlparse-mut-023 | drop_not | 34 | 2 | accepted | accepted |
| sqlparse-mut-024 | off_by_one | 2 | 2 | accepted | accepted |
| sqlparse-mut-025 | remove_guard | 1 | 2 | accepted (60 s) | accepted |
| sqlparse-mut-032 | remove_guard | 1 | **0** | rejected, budget | rejected, budget |
| sqlparse-mut-033 | swap_branches | 43 | 2 | accepted | accepted |
| sqlparse-mut-034 | compare_flip | 2 | 2 | accepted | accepted |
| sqlparse-mut-040 | compare_flip | 2 | 2 | accepted | accepted |
| sqlparse-mut-042 | off_by_one | 3 | 2 | accepted (490 s) | accepted |
| sqlparse-mut-043 | remove_guard | 11 | 2 | accepted | accepted |
| sqlparse-mut-044 | swap_branches | 3 | 2 | accepted | accepted |
| sqlparse-mut-046 | negate_condition | 4 | 2 | accepted | accepted |
| sqlparse-mut-057 | off_by_one | 1 | **0** | rejected, finish | rejected, finish |
| sqlparse-mut-060 | negate_condition | 2 | 2 | accepted | accepted |
| sqlparse-mut-061 | drop_not | 15 | **0** | rejected, finish | rejected, budget |
| sqlparse-mut-073 | swap_branches | 2 | 2 | accepted | accepted |
| sqlparse-mut-075 | negate_condition | 22 | 2 | accepted | accepted |
| sqlparse-mut-076 | drop_not | 26 | 2 | accepted | accepted |

"finish" = the model called `finish`; "budget" = `model_call_limit` at 20 responses. Every accepted run passed
its full `fail_to_pass` set and all `pass_to_pass` tests.

## Campaign numbers

| Measure | Value |
|---|---|
| Runs | 40 (20 tasks x 2 rollouts), all completed, 0 crash retries, 0 adapter stops |
| Accepted | 32 of 40 = **0.80** (95% interval 0.68 to 0.92) |
| Per task | 15 at 2/2, 2 at 1/2 (contrastive), 3 at 0/2 (negative) |
| Wall time | 2 h 33 min; per run mean 229 s, median 194 s, min 58 s, max 731 s |
| Duration by outcome | accepted mean 189 s; rejected mean 390 s |
| Rejections by stop | 4 after `finish`, 4 at the response budget (corrected 2026-09-28 by [weakness mining](weakness-mining-c007.md); this report first said 5 and 3) |
| Monetary cost | none billed (CLI on the owner's subscription); billing recorded as unknown |

By mutation kind (accepted of runs): swap_branches 6/6, negate_condition 7/8, compare_flip 5/6, drop_not 6/8,
off_by_one 4/6, remove_guard 4/6. Kind is not where the difficulty is.

By `fail_to_pass` size: **1 test: 3/8**; 2-3 tests: 14/14; 4-10: 4/4; 11-25: 4/6; 26+: 7/8. Single-test tasks
are the hard ones. Three of the four single-test tasks in the set (001, 032, 057) account for 5 of the 8
rejections, and their statements carry the least information (one humanized test name and, for 001, a
truncated string diff that reads the same on both sides).


> **Correction (2026-09-28, after weakness mining of all 40 journals; see [weakness-mining-c007.md](weakness-mining-c007.md)).** The rejected runs split 4 finish / 4 budget, not 5 / 3. Every run that finished had run a check after its last edit, so "finished without verification" is wrong; the check covered inputs the model chose, and in 3 of 4 the reported failure was never reproduced. "Pytest found no tests" occurred in 19 of the 32 accepted runs as well and does not separate the failures. 061 failed on a pass-to-pass regression in both runs (r2 a near miss: 13 of 15 target tests fixed at the budget). The two-mechanism reading survives in a sharper form: (A) finishing on a self-chosen check that never reproduced the reported failure, 4 runs on 3 tasks; (B) no commitment within the budget, 3 runs on 2 tasks. The treatment implied by A is a reproduce-first completion rule, not a "did a check run" rule.

## What the rejected runs did

| Run | Gold file | Edited | Ran pytest | Mechanism |
|---|---|---|---|---|
| 001-r1 | filters/others.py | filters/reindent.py | no | wrong-file fix, finished without verification |
| 022-r1 | filters/reindent.py | nothing | no | explored and reproduced until the budget |
| 032-r1 | filters/reindent.py | nothing | no | explored until the budget |
| 032-r2 | filters/reindent.py | nothing (3 new scratch files) | no | reproduced until the budget |
| 057-r1 | sql.py | engine/grouping.py | yes | wrong-file fix; pytest found no tests (hidden), finished anyway |
| 057-r2 | sql.py | engine/grouping.py | yes | same as r1 |
| 061-r1 | filters/reindent.py | filters/reindent.py | no | right file, wrong fix, finished without verification |
| 061-r2 | filters/reindent.py | filters/reindent.py | yes | right file, wrong fix, budget |

Two mechanisms recur. First, a confident wrong fix (5 of 8): the model edits, sometimes in the wrong file, and
calls `finish`. In 057 it ran pytest on a workspace whose tests are hidden, saw no tests, and finished anyway.
This is the "verification allocation" failure the register already lists, with a sharper form: the model
treats "no tests ran" as a pass. Second, budget exhaustion without an edit (3 of 8): long exploration or
reproduction with no commitment to a cause. Both map onto card 009's candidate (diagnostic commitment) and
onto the register's verification-allocation idea.

## Evolution set (card rule applied)

Contrastive (1/2): `sqlparse-mut-001`, `sqlparse-mut-022`. Negative (0/2) with a fixable mechanism visible in
the trajectory: `sqlparse-mut-032` (no commitment), `sqlparse-mut-057` (wrong file, false verification),
`sqlparse-mut-061` (wrong fix in the right file). Evolution set: those 5 tasks. The 15 tasks solved twice leave
the set. This is below the card's pass rule of at least 5 contrastive tasks, so per the card the next step is a
difficulty change under a new card, not tuning on these tasks. These 20 tasks are now held-in for any harness
treatment; the other 56 in the bank remain unused.

## Reading

- The interface is not the limit: 80% acceptance with a capable model, against 0% for the weak models of
  E3 runs 1-4, and 100% on the upstream task in the positive control.
- The bank as generated is too easy for Sonnet to separate harnesses on: the useful zone is 30-70% and the
  bank sits at 80% with only 5 usable tasks. Difficulty concentrates in single-test mutations with
  uninformative failure messages, which is a property of the statement template, not of the mutation kind.
- The two recurring failure mechanisms are exactly the ones the S6 loop is built to mine, and there is now
  paired evidence (same task, one accepted, one rejected) for two of them.

## Proposed next card (010, difficulty)

Regenerate a second bank under a new protocol with three changes, each a separate arm so their effect is
measurable: (a) statements carry only the humanized test names, no failure message; (b) two-site mutations in
one file; (c) mutations restricted to single-test failing sets. Calibrate on 20 fresh tasks (not the 20 above)
with the same arm and budgets. Target: at least 5 contrastive tasks or a 40-60% rate. In parallel, card 009
can run on the 5-task evolution set as a mechanism check only; it cannot claim an effect at that size.

## Provenance and departures

- The card's approval was given by the owner in chat; the session's permission classifier refused to launch
  the campaign from a subagent and then from the orchestrating session ("Auto-Mode Bypass"), so the owner ran
  the driver from a terminal. The driver is committed ([`run_card007.py`](run_card007.py)) and its rules are
  recorded in its docstring: strictly sequential, live-run lock, idle priority, evidence committed every 10 runs.
- The card's original 20-task-per-invocation command was replaced by one invocation per run (`c007-<task>-r<k>`)
  so that runs are individually named and resumable; the machine-readable card
  (`cards/007.json`, branch wt/s6d-cards) matches this form and plans the recorded hash `b0fda8c921ad`.
- Repeat flags were not recorded live (the runner records them only by stopping); they can be derived from the
  journals with `weakness_mining.py`.
- Not done: labelling of these 40 trajectories (S6b's next input), card 008 gate 3 (needs an evolution set of
  at least 3 tasks; 5 exist now), card 009 (blocked on S6b signatures for these runs).
