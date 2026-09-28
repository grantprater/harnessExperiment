# E3 calibration 007: mutation-task bank with a capable model through the Reticle interface

Date: 2026-09-27  
Status: **complete 2026-09-28**: 40/40 runs, acceptance 0.80, 2 contrastive + 3 negative tasks; below the pass rule (5 contrastive); difficulty change proposed. [Report](E3-calibration-007-report.md). Approved by the owner in session 2026-09-27; launched by the owner from a terminal.  
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

### Controls and smoke (no batch run)

The no-API controls ran with the wired runner at `34723a3` (materializer `mutation-workspace-v2`). They used OCI
image `8b74015e5079`, `pressure-recent-v3`, and this card's flags. The workspaces had no `tests/` and contained the
mutated line. The evaluator installed the healthy `tests/` from `fix_commit`.

| Control | `sqlparse-mut-001` (1 failing test) | `sqlparse-mut-006` (11 failing tests) |
|---|---|---|
| gold (`s6a-control-gold-mut-v2`) | accepted: fail-to-pass 1/1 pass, pass-to-pass 490/490 pass, 493 tests | accepted: 11/11 pass, 480/480 pass, 493 tests |
| noop (`s6a-control-noop-mut-v2`) | rejected: fail-to-pass 1/1 fail, pass-to-pass 490/490 pass | rejected: 11/11 fail, 480/480 pass |

Smoke `s6a-smoke-claude-cli-mut`, a smoke and not a run:

- One claude-cli attempt on `sqlparse-mut-006`, which is not in the set, with `--max-total-calls 1` and the lock held.
- The init event listed only the `StructuredOutput` tool. There were no MCP servers, `apiKeySource` was `none`, and
  the model was `claude-sonnet-5`.
- The model's first message called `search_text` for `class ReindentFilter`. The harness ran it in the mutated
  workspace (59 files, no `tests/`) and got 1 match, `sqlparse/filters/reindent.py:13`.
- The next request hit the attempt cap.

The smoke and the first controls (`s6a-control-*-mut`, at `352c1ae`) used materializer v1. In v1 the mutated file and
its directory kept the time of `git apply`, so `ls -lt` in the workspace named the mutated file. v2 closes this: inside
the container, all 70 entries share one mtime and one ctime, and `find -newer` finds nothing. The smoke's one call did
not look at timestamps, and the smoke was not repeated.

Two runtime behaviours remain. Neither leaks the hidden tests or the gold patch:

- A host-side tool error (for example `read_file` on a missing path) quotes the absolute host path. That path names
  the run and the task id.
- A symlink made by a `run` command in the container is unreadable on the Windows host (WinError 1920). Every later
  tool call then raises out of `revision()`, which would end the campaign as an evidence loss.

Command as run (amendment 2026-09-28, before the first run): one invocation per run, named `c007-<task>-r<k>`,
sequential under `.runtime/locks/live-run.lock`, via the committed driver:

```powershell
.\.runtime	est-venv\Scripts\python.exe experiments/session_harness/run_card007.py --execute
```

Each invocation passes `--client claude-cli --models sonnet --backend oci --arm pressure-recent-v3 --max-calls-per-run 20
--max-attempts-per-run 24 --elapsed-cap-seconds 1200 --max-tokens 4096 --max-total-calls 48 --tasks <bank> <task>`.
The earlier 20-task-per-invocation form was not used.

The runner does not do these; they need an operator or a change before the batch:

- **Repeat flags.** Without `--stop-on-repeats`, the runner does not record the repeat flag. With it, the run stops,
  which this card does not want. Derive the flags from the transcripts instead.
- **Campaign fast stop.** The runner does not stop the campaign after 3 consecutive adapter failures.
- **Live-run lock.** The runner does not take the lock.
- **Symlink crash.** A model that creates a symlink stops the campaign (above). Resume re-runs the interrupted task
  and keeps the partial session.
