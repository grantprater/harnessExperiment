# Pooled task registry (cards 007, 023, 010 stage 1 + 2a)

File: [task_registry.json](task_registry.json), built by [build_task_registry.py](build_task_registry.py)
(stdlib, deterministic; `--check` rebuilds and diffs against the committed file). One record per task id across
the sqlparse bank (`tasks.mutations.full.json`, its 76-task recorded subset, and the `-nm` statement variants in
`tasks.difficulty010*.json`) and the boltons bank (`tasks.boltons.json`). Offline only: no model calls, no tests.

Card 023 has not been merged into this branch, so its three inputs (`tasks.boltons.json`,
`E3-calibration-023-tasks.json`, `E3-calibration-023.sets.json`) are read with `git show` from commit
`57161e64ff28c9600c856cf5393701f755299754` (analysis/c023, "boltons calibration 36/40"). The sha256 of every
input is in the registry's `sources` block.

Each record has: id, bank, task-definition file (the card-specific file first, then the recorded bank, then the
full bank), source cards and memberships, stratum (`single` / `multi-msg` / `multi-nm`), calibration outcome per
source card (accepted, runs, category; `null` where the card listed the task but never ran it), mutated file and
function, sha256 of the sorted fail-to-pass set, `same_mutation_as`, `role`, `role_source`, `tags`, and
`overlaps_eval`.

## Counts (bank x role)

| Bank | Role | Tasks |
|---|---|---|
| sqlparse | eval-010-combined | 31 |
| sqlparse | evolution-contrastive (card 007; tag `dev`) | 2 |
| sqlparse | evolution-negative (card 007; tag `dev`) | 3 |
| sqlparse | dev | 296 |
| sqlparse | excluded-statement-names-function | 19 |
| sqlparse | uncalibrated-pool | 28 |
| boltons | near-transfer-boltons | 17 |
| boltons | boltons-evolution-excluded (015, 023, 056) | 3 |
| boltons | excluded-statement-names-function | 26 |
| boltons | uncalibrated-pool | 17 |
| | **total** | **442** (379 sqlparse, 63 boltons) |

Roles not in the brief's list: `excluded-statement-names-function` comes from the `excluded` lists of the card 010
sets files (stage 1: 3, stage 2a: 16) and the selector exclusion of cards 007 and 023 (statement names the mutated
function). Eval tasks in a stage's evolution lists carry `evolution-contrastive` (12) or `evolution-negative` (9) as
tags; all 21 are eval, as both stage reports say.

## Reconciliation

| Card | Set | Source file | Registry |
|---|---|---|---|
| 010 stage 1 | eval | 12 | 12 |
| 010 stage 1 | dev | 61 | 61 |
| 010 stage 2a | eval | 19 | 19 |
| 010 stage 2a | dev | 240 | 240 |
| 007 | tasks / accepted | 20 / 32 of 40 | 20 / 32 of 40 |
| 023 | tasks / accepted | 20 / 36 of 40 | 20 / 36 of 40 |

The 31 eval ids appear first, in the combined file's order. No id appears twice.

## Overlap with eval (tag only; nothing moved)

- Restricted to the 301 card-010 dev tasks: **38 same-function pairs, 26 same-failing-set pairs**, the figures in the
  stage-2a report.
- Over every non-eval task: 53 function pairs and 41 failing-set pairs (64 tasks: 49 dev, 15 uncalibrated-pool).
  The extra 15 are the base ids of the 15 `-nm` eval tasks (below). Boltons shares nothing with eval.
- Comparison is within a bank, by mutated function name and exact sorted fail-to-pass set, as in
  `apply_split_010_stage2a.py`.

## Flags and ambiguities

- **Same mutation under two ids (28 pairs).** Every `-nm` task is the same mutation patch as its base id, with a
  statement that drops the failure message. For the 15 `-nm` eval tasks, the base id (e.g. `sqlparse-mut-016`) is
  in no card list and lands in `uncalibrated-pool`; for the 13 `-nm` dev tasks, the base id is likewise
  uncalibrated. All 28 sqlparse `uncalibrated-pool` tasks are such base ids. They carry the tag
  `same-mutation-as-other-id`; whether the 15 eval twins must be withheld from development is open (owner).
- **Card 007's role.** Its 20 tasks are card 010 stage-1 dev core (with `sqlparse-mut-006`). Its report names an
  evolution set (contrastive 001, 022; negative 032, 057, 061) that cards 011 and 013-015 used. The registry gives
  those five role `evolution-contrastive` / `evolution-negative` (source: card 007 report, hard-coded in the builder
  because no machine file holds the hand-chosen set) with tag `dev`; the other 15 are `dev`. Card 007 has no
  `category` field; its categories use card 010's mapping (2/2 solved, 1/2 mixed, 0/2 hard). Its `sets.json` holds
  card 011's derived block, so outcomes come from `c007-campaign.jsonl`.
- **Boltons outside the 20.** The 17 eligible but uncalibrated boltons tasks are `uncalibrated-pool`, not
  near-transfer; no card defines them as either.
- **`sqlparse-mut-072`** differs in statement between `tasks.mutations.json` and the full bank; it is excluded in
  every card and its mutation and failing set agree.
