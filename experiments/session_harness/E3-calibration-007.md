# E3 calibration 007: mutation-task bank with a capable model through the Reticle interface

Date: 2026-09-27  
Status: proposed (awaits owner approval; no model runs yet)  
Stage: S6a. Prerequisite: `materialize_workspace` applies `mutation_patch` and removes `hidden_paths`; `run_pilot.py` accepts `--tasks experiments/mutation_tasks/tasks.mutations.json`.

## Hypothesis

A capable model succeeds on some mutation tasks and fails on others under the incumbent harness, so a
subset of the 76 tasks lands in the 30-70% acceptance zone where harness comparisons have power. If
acceptance is near 100%, the tasks are too easy (fix: fewer hints in statements, two-site mutations); if near
0%, the failure is in the wiring or the statements, not the model (the positive control excludes the interface).

## Arms

One arm: incumbent bundle = runner v8, `--client claude-cli` (adapter v2, model `sonnet`), `pressure-recent-v3`,
`reticle-tools-v3`, OCI image `8b74015e...` (trusted-local only if the image is missing, recorded). No treatment.

## Tasks

20 tasks from `tasks.mutations.json`, one per distinct `fail_to_pass` set, stratified across the six mutation
kinds (3-4 each), chosen by a seeded shuffle recorded in the card before the first run. Tasks whose statement
names the mutated function (`statement_names_mutated_function: true`) are excluded. Hidden tests are removed
from the workspace; the evaluator restores the healthy `tests/` root from `fix_commit`.

## Budgets and stop rules

- Per run: 20 responses, 1,200 active seconds, 120 s command timeout (600 s max), no monetary cap (CLI on
  subscription; billing recorded as unknown).
- Campaign: 20 tasks x 2 rollouts = 40 runs, serialised, plus gold/noop controls once before the batch.
- Fast stop: evaluator leakage, evidence loss, authority escape, or 3 consecutive adapter failures stops the
  campaign. Three identical observation calls trigger the diagnostic flag; in this calibration the run
  continues (the flag is recorded), because the calibration measures the incumbent as it is.
- Rate: no more than one live run at a time on this machine (`.runtime/locks/live-run.lock`).

## Measurements

Per task: accepted (0/1/2 of 2), stop reason, responses used, first edit response, rejected calls, repeat
flags, edit inside `gold_source_files` or not, verification before finish (pytest run or not), wall seconds.
Campaign: acceptance rate with a 95% interval, distribution of per-task outcomes (2/2, 1/2, 0/2), the
evolution set (tasks with 1/2, plus 0/2 tasks whose trajectories show a fixable mechanism), and a difficulty
ordering by kind and by `fail_to_pass` size.

## What counts

Pass for the card: 40 runs complete with evidence, and at least 5 contrastive tasks (1/2). Otherwise report
the distribution and propose the difficulty change under a new card; do not tune statements on these tasks
after seeing results (they become the held-in set).

## Reporting

`experiments/session_harness/E3-calibration-007-report.md`: acceptance table, evolution set, trajectories
handed to S6b for labelling, and the seed. Register row "Mutation-generated repair tasks" moves to
"calibrated (N in zone)".

## Selected tasks

Recorded 2026-09-27, before any calibration run. Selector:
[`select_calibration_tasks.py`](select_calibration_tasks.py) `--seed 7` (the card's number; the only seed
run). Output: [`E3-calibration-007-tasks.json`](E3-calibration-007-tasks.json). Bank: `tasks.mutations.json`, sha256 of its
LF content `fa185723735d56e7...`.

The rule as applied:

1. Drop the 3 tasks whose statement names the mutated function (`sqlparse-mut-049`, `sqlparse-mut-063`,
   `sqlparse-mut-072`). That leaves 73 tasks with 62 distinct `fail_to_pass` sets.
2. Give each kind 3 tasks, plus a fourth for two kinds drawn with the seed (`drop_not`, `negate_condition`).
3. Shuffle the 73 tasks with the seed, starting from task-id order.
4. Walk the shuffled list. Take a task when its kind is under quota and its failing set is new.

Result: 20 tasks, with 20 distinct failing sets and 20 distinct statements.

| Task | Kind | Mutation site | `fail_to_pass` |
|---|---|---|---:|
| `sqlparse-mut-001` | compare_flip | `sqlparse/filters/others.py`:128 | 1 |
| `sqlparse-mut-002` | drop_not | `sqlparse/sql.py`:268 | 9 |
| `sqlparse-mut-022` | negate_condition | `sqlparse/filters/reindent.py`:62 | 41 |
| `sqlparse-mut-023` | drop_not | `sqlparse/sql.py`:277 | 34 |
| `sqlparse-mut-024` | off_by_one | `sqlparse/sql.py`:509 | 2 |
| `sqlparse-mut-025` | remove_guard | `sqlparse/tokens.py`:23 | 1 |
| `sqlparse-mut-032` | remove_guard | `sqlparse/filters/reindent.py`:107 | 1 |
| `sqlparse-mut-033` | swap_branches | `sqlparse/engine/grouping.py`:189 | 43 |
| `sqlparse-mut-034` | compare_flip | `sqlparse/sql.py`:433 | 2 |
| `sqlparse-mut-040` | compare_flip | `sqlparse/filters/output.py`:37 | 2 |
| `sqlparse-mut-042` | off_by_one | `sqlparse/filters/reindent.py`:196 | 3 |
| `sqlparse-mut-043` | remove_guard | `sqlparse/utils.py`:89 | 11 |
| `sqlparse-mut-044` | swap_branches | `sqlparse/formatter.py`:198 | 3 |
| `sqlparse-mut-046` | negate_condition | `sqlparse/formatter.py`:201 | 4 |
| `sqlparse-mut-057` | off_by_one | `sqlparse/sql.py`:646 | 1 |
| `sqlparse-mut-060` | negate_condition | `sqlparse/engine/statement_splitter.py`:54 | 2 |
| `sqlparse-mut-061` | drop_not | `sqlparse/filters/reindent.py`:139 | 15 |
| `sqlparse-mut-073` | swap_branches | `sqlparse/filters/aligned_indent.py`:75 | 2 |
| `sqlparse-mut-075` | negate_condition | `sqlparse/engine/statement_splitter.py`:75 | 22 |
| `sqlparse-mut-076` | drop_not | `sqlparse/filters/reindent.py`:80 | 26 |

- `fail_to_pass` sizes:
  - 1 test: 4 tasks
  - 2-3 tests: 7 tasks
  - 4-10 tests: 2 tasks
  - 11-25 tests: 3 tasks
  - 26-49 tests: 4 tasks
- 10 of the 20 mutations are in `sql.py` or `filters/reindent.py` (5 each).
- The statement for `sqlparse-mut-025` names `_TokenType`, the mutated class (weakness 3 in
  [the mutation-task report](../mutation_tasks/REPORT.md)). The card's rule does not exclude it.
- `sqlparse-mut-001` was also a gold/noop control task; no model was involved. The one-response smoke used
  `sqlparse-mut-006`, which is not in the set.

No-API controls, run with the wired runner at `352c1ae` (OCI image `8b74015e5079`, `pressure-recent-v3`, this
card's budgets). The workspaces had no `tests/` and contained the mutated line. The evaluator installed the healthy
`tests/` from `fix_commit`.

| Control | `sqlparse-mut-001` (1 failing test) | `sqlparse-mut-006` (11 failing tests) |
|---|---|---|
| gold (`s6a-control-gold-mut`) | accepted: fail-to-pass 1/1 pass, pass-to-pass 490/490 pass, 493 tests | accepted: 11/11 pass, 480/480 pass, 493 tests |
| noop (`s6a-control-noop-mut`) | rejected: fail-to-pass 1/1 fail, pass-to-pass 490/490 pass | rejected: 11/11 fail, 480/480 pass |

Command for rollout k (k = 1, 2), run one at a time from the repo root while holding
`.runtime/locks/live-run.lock`:

```powershell
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client claude-cli --models sonnet `
  --tasks experiments/mutation_tasks/tasks.mutations.json `
  sqlparse-mut-001 sqlparse-mut-002 sqlparse-mut-022 sqlparse-mut-023 sqlparse-mut-024 sqlparse-mut-025 sqlparse-mut-032 `
  sqlparse-mut-033 sqlparse-mut-034 sqlparse-mut-040 sqlparse-mut-042 sqlparse-mut-043 sqlparse-mut-044 sqlparse-mut-046 `
  sqlparse-mut-057 sqlparse-mut-060 sqlparse-mut-061 sqlparse-mut-073 sqlparse-mut-075 sqlparse-mut-076 `
  --backend oci --arm pressure-recent-v3 --max-calls-per-run 20 --max-attempts-per-run 24 `
  --elapsed-cap-seconds 1200 --max-tokens 4096 --max-total-calls 480 --run-name e3-cal007-sonnet-rk
```

The runner does not do these; they need an operator or a change before the batch:

- **Repeat flags.** Without `--stop-on-repeats`, the runner does not record the repeat flag. With it, the run stops,
  which this card does not want. Derive the flags from the transcripts instead.
- **Campaign fast stop.** The runner does not stop the campaign after 3 consecutive adapter failures.
- **Live-run lock.** The runner does not take the lock.
