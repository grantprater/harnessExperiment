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
