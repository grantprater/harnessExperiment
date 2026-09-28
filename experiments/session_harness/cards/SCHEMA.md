# Executable run cards (S6d)

A run card in this folder is the machine-readable restatement of one markdown card in
`experiments/session_harness/`. The markdown card states intent and is the one the owner approves; the JSON card is
what [`run_card.py`](../run_card.py) plans and executes. Where the JSON has to choose something the markdown leaves
open, or cannot express something the markdown asks for, the choice is written in its `notes` or `stop_rules.manual`.

Structure: [`card.schema.json`](card.schema.json) (JSON Schema keywords, checked by a stdlib interpreter in
`run_card.py`). Meaning and semantic checks: this file.

| File | Markdown card | State |
|---|---|---|
| `006-replay.json` | [E3-positive-control-006](../E3-positive-control-006.md), Arm R run 2 | `completed`; exists for the replay-hash check |
| `007.json` | [E3-calibration-007](../E3-calibration-007.md) | `proposed`; blocked on S6a's task-file flag and approval |
| `008.json` | [E1-cache-layout-008](../E1-cache-layout-008.md), gate 3 only | `proposed`; blocked on gates 1-2, the v4 policy, card 007's evolution set |
| `009.json` | [E4-diagnostic-commitment-009](../E4-diagnostic-commitment-009.md) | `proposed`; blocked on held-in/held-out lists, a candidate runner, the wording |

## Commands

```
python experiments/session_harness/run_card.py CARD --validate
python experiments/session_harness/run_card.py CARD --plan [--limit N] [--json] [--replay RUN_DIR]
python experiments/session_harness/run_card.py CARD --execute [--resume]
python experiments/session_harness/run_card.py CARD --report
```

`--plan` runs nothing. It prints the resolved task sets, each arm's expected protocol hash, every invocation with
its exact command line, and the **blockers**: everything that makes `--execute` refuse (status not `approved` or
`running`, an unfinished prerequisite, an `{"unresolved": ...}` placeholder, a task set that cannot be resolved, a
runner flag the runner does not accept, a pinned hash or file hash that differs, a plan larger than the campaign
cap). Exit codes: 0 done, 2 invalid/blocked/refused, 3 checkpoint stop, 4 integrity stop, 5 lock held.

## Fields

| Field | Meaning |
|---|---|
| `schema_version` | `1` |
| `id`, `title`, `markdown`, `hypothesis` | identity; `markdown` is the human card's path |
| `status` | `proposed`, `approved`, `running`, `completed`, `invalidated`, `inconclusive`; only `approved` and `running` execute |
| `run_prefix` | run directories are `<run_prefix>-<task>-r<rollout>-<arm>` and `<run_prefix>-control-<name>` |
| `runner` | `script` (default runner), `runner_version` (must equal the script's `RUNNER_VERSION`), `task_file_flag` (the flag that selects a task file other than the runner's default `tasks.json`; `null` if the card uses the default) |
| `environment.claude_cli_version` | the `claude --version` string the protocol hash is computed with; `null` only when no arm uses `claude-cli` |
| `prerequisites` | `{text, done}`; any `done: false` blocks execution |
| `arms[]` | see below |
| `controls[]` | scripted-client runs before the arms: `{name, client: gold/noop/breaker/gamer/tester, task_set, like_arm, expect: accepted/rejected}`; one invocation over the whole set, with the named arm's policy, backend and guards. A control whose outcome differs from `expect` is an integrity stop |
| `tasks` | `file` (task JSON), `file_sha256` (sha256 with CRLF folded to LF, the bytes git stores), `sets` (named task sets, below) |
| `blocks[]` | `{name, task_set, arms, rollouts, arm_order: {rule: fixed or seeded, seed}}` |
| `schedule` | `rollout-major` (default: rollout 1 of every task before rollout 2, so an early stop leaves balanced evidence) or `task-major` |
| `budgets.per_run` | below |
| `budgets.campaign` | `max_runs`, `max_model_attempts` (checked at plan time and before every attempt), `monetary_cap_usd` (recorded; the CLI has no billing), `note` |
| `stop_rules` | `max_retries_per_invocation` (0-2), `retry_backoff_seconds` (one per retry), `consecutive_failures_to_stop` (1-3), `repeat_rule` and `manual` (text the runner cannot enforce) |
| `measurements` | `per_run` and `campaign` names from the vocabulary below |
| `decision_rule` | text, copied into the report |
| `report` | `path` (report skeleton), `sets_path` (optional JSON file for derived task categories; hand-chosen lists live in the same file) |
| `notes` | choices made in the JSON that the markdown did not state |

### Arms

| Field | Runner flag | Notes |
|---|---|---|
| `name` | part of the run name | unique |
| `client` | `--client` | `claude-cli` and `openrouter` are live; the others are scripted |
| `model` | `--models` (one) | required for live clients |
| `provider` | `--provider MODEL=SLUG` | OpenRouter only |
| `policy` | `--arm` | must be one of the runner's `ARMS` |
| `toolset` | none | asserted equal to the runner's `TOOLSET_VERSION`; not selectable |
| `backend` | `--backend`, `--oci-image` | `{kind: trusted-local}` or `{kind: oci, image, image_id, engine}`; `image_id` and `engine` are hash inputs the card pins |
| `guards` | `--stop-on-repeats`, `--resume-after-provider-stop`, `--resume-wait-seconds` | the runner's `guards` record |
| `extra_args` | appended verbatim | may not repeat a flag the card sets from structured fields; plan hashes do not see them, the preflight does |
| `runner` | the script this arm runs | overrides the card's runner, for a candidate bundle that lives in its own worktree |
| `bundle` | none | descriptive record of a candidate's changed surface |
| `expected_protocol_hash` | none | if set, planning fails when the computed hash differs |

### Per-run budgets

| Field | Runner flag |
|---|---|
| `responses` | `--max-calls-per-run` |
| `model_attempts` | `--max-attempts-per-run`, and `--max-total-calls` = `model_attempts` x tasks for live clients |
| `active_seconds` | `--elapsed-cap-seconds` |
| `tool_actions` | `--max-tool-actions-per-run` |
| `cost_usd`, `attempt_cost_reservation_usd` | `--cost-ceiling-usd`, `--attempt-cost-reservation-usd` (the reservation is explicit, never priced at run time) |
| `context_bytes`, `max_tokens`, `pytest_timeout_seconds` | `--max-context-bytes`, `--max-tokens`, `--pytest-timeout` |
| `command_timeout_seconds` | none: checked against the runner's fixed `ToolSuite` defaults (120 s, max 600 s) |
| `invocation_wall_seconds` | none: `run_card.py` kills a runner process after this long (a failure, retried) |

### Task sets

Each set has exactly one source, optionally followed by `take: {count, seed}` (a seeded sample):

- `ids`: explicit task ids.
- `rule`: `{kind: stratified-distinct, count, seed, distinct_by, stratify_by, exclude_if_true}`. Drop tasks whose
  `exclude_if_true` fields are true; shuffle with `random.Random(seed)`; keep the first task for each distinct value
  of `distinct_by` (lists compared sorted); group by `stratify_by`, shuffle the group order, and take round-robin
  across groups until `count`. Deterministic for a given task file, which `file_sha256` pins.
- `ref`: `{path, key, sha256}`: the id list under `key` in a JSON file a person or an earlier card writes (for
  example `E3-calibration-007.sets.json`, keys `evolution_set`, `held_in`, `held_out`). Missing until written;
  pin `sha256` once it is.
- `from_sets`: the ordered union of other sets.
- `unresolved`: a reason; the set blocks execution.

### Arm order

`fixed` runs a block's arms in the listed order. `seeded` shuffles the arms of each unit (block, task, rollout)
with `random.Random("<seed>:<block>:<task>:<rollout>")`, so a unit's order is reproducible and independent of the
other tasks in the set. Every unit contains every arm once (plan section 5.5: interleave arm order within task
blocks, no model-major scheduling).

### Measurements

Per run, filled from `results.jsonl`: `accepted`, `stop_reason`, `responses_used`, `provider_attempts`,
`tool_calls`, `active_seconds`, `wall_seconds`, `criterion_outcomes`, `tokens`, `diagnostic_termination`.
Per run, listed as pending until S6b derives them from the session journal: `first_edit_response`,
`rejected_calls`, `repeat_flags`, `edit_in_gold_files`, `verification_before_finish`, `references_remaining_budget`.
Campaign: `acceptance_rate_ci` (Wilson 95%), `per_task_outcomes`, `outcome_distribution`, `evolution_set` (the
all/mixed/none categories; the set itself is chosen by hand), `paired_table`, `acceptance_by:<task field>`,
`acceptance_by_size:<list field>`, `delta:<arm>:<arm>` (mean per-task difference in acceptance rate, per task set).

### Placeholders

Any value may be `{"unresolved": "<what is missing>"}` where the schema allows it (CLI version, OCI image ID, an
arm's runner, a set). `--plan` lists every placeholder as a blocker, so an incomplete card can be planned and
reviewed but never executed.

## Protocol hash and replay

`run_card.py` loads the runner script as a module and calls the runner's own `protocol_hash`, `resolve_execution`,
and `cli_contract`, so the plan cannot drift from the runner's definition. Three hash inputs are properties of the
machine rather than the card; the card pins them and `--execute` checks them:

1. the Claude CLI version (`environment.claude_cli_version`),
2. the OCI image ID and engine (`backend.image_id`, `backend.engine`; the engine sets `container_user_arguments`),
3. the bytes of `experiments/p6_pilot/evaluate_task.py` **as checked out**. On this Windows checkout
   (`core.autocrlf=true`) they have CRLF line endings; a Linux checkout of the same commit has LF and records a
   different hash for the same protocol. `--plan` prints the other-line-ending hash after the arms.

Before the first run, `--execute` runs the runner with `--dry-run` once per live arm and requires the printed hash
to equal the planned one (scripted clients print no hash; their recorded `config.json` is checked after the run).
After every invocation the recorded `config.json` (16 fields: protocol hash, arm, client, models, routing, tasks,
budgets, execution, guards, and limits) and every result's `protocol_hash` must match the plan, or the campaign
stops as `corrupted_protocol`.

The protocol hash itself covers the runner version, context policy, instructions, tool schemas, evaluator bytes,
managed root files, routing, execution, guards and toolset version. It does **not** cover budgets, task ids, or
`max_tokens`, so the replay check compares the full recorded config, not only the hash.

Replay: `--plan --replay RUN_DIR` compares a one-run card's planned config with `RUN_DIR/config.json`.
`006-replay.json` against `experiments/p6_pilot/runs/pc-reticle-sonnet-2` gives `6f1061c028c8`, identical to the
recorded hash, with all 16 fields matching.

## Execution

- **Lock.** `<main checkout>/.runtime/locks/live-run.lock`, created exclusively (shared by every worktree through
  the git common directory). A held lock fails the command (exit 5) and is never broken automatically.
- **Order.** Controls first, then blocks in card order, units by `schedule`, arms by `arm_order`; strictly one
  runner process at a time.
- **Evidence.** Each invocation writes its own run directory under `experiments/p6_pilot/runs/`. The campaign log is
  `runs/card-<id>/campaign.jsonl` (start, preflight, every invocation start/end with exit code and classification,
  backoffs, skips, stop); runner output goes to `runs/card-<id>/logs/<run>.log`.
- **Failures (plan 5.3).** A provider/model error (the runner's `model_error` stop), a crash without a record, or a
  wall-time kill is a failed attempt: retried at most `max_retries_per_invocation` times after
  `retry_backoff_seconds`, each retry in a new run directory `<run>-a2`, `<run>-a3` (a crash with no results reruns
  in place, which the runner itself archives). `consecutive_failures_to_stop` failed attempts in a row checkpoint
  and stop (exit 3). Retries are counted from the campaign log, so a resume never grants fresh retries.
- **Integrity stops (exit 4).** Protocol or config mismatch, exit 0 without a result record (evidence loss), a run
  over its response or attempt budget, a failed control, a preflight hash mismatch.
- **Campaign cap.** The plan's allocation (`model_attempts` x runs) must fit `max_model_attempts`. Before every
  attempt, attempts already spent (all `calls.jsonl` lines) plus the next allocation must fit; the first run of a
  unit must leave room for every arm of the unit, so a pair is never split by the cap.
- **Resume.** `--execute` refuses if any planned run directory exists; `--execute --resume` skips invocations with a
  complete, non-failed record (all tasks present in `results.jsonl`, after re-checking its protocol), skips
  invocations whose retries are exhausted, and reruns interrupted ones.
- **Report.** At every stop and at the end, the report skeleton is written to `report.path` with the protocol, task
  sets, controls, per-run table, per-arm summary, per-task outcomes, declared measurements, paired units, deltas,
  campaign log summary, and the decision rule. Once a person edits it, regeneration writes `*.skeleton.md` beside it.

## What a card cannot express (runner v8)

- **Opening instructions and other bundle surfaces.** `INSTRUCTIONS`, the CLI adapter constants (`CLI_MAX_TURNS`,
  `CLI_TIMEOUT_SECONDS`, the adapter version), `MAX_ATTEMPTS` per request, temperature, and `render_output_view`
  parameters are module constants. A candidate that changes them (card 009) needs a runner flag or its own runner
  script (`arm.runner`).
- **Toolset version and command timeout.** Asserted, not selected: the card fails to plan if they differ from the
  runner's.
- **Task file.** Runner v8 reads only `experiments/p6_pilot/tasks.json`; cards 007-009 need the flag S6a adds.
- **Record repeats without stopping.** The runner flags three identical observations only with `--stop-on-repeats`,
  which also stops the run; card 007 runs without the guard and derives repeat flags afterwards.
- **Fallbacks that change the protocol**, such as card 007's "trusted-local if the image is missing": a different
  backend is a different arm, so a missing image stops the preflight.
- **Several models in one invocation.** The runner accepts `--models A B`; a card arm has one model, one invocation
  per task x rollout x arm.
- **Judgement rules**: evaluator leakage, authority escape, held-out exposure, the bundle-surface check, and one-off
  amendments (card 006's single rerun) are text in `stop_rules.manual`.
- **Journal measurements** (first edit, rejected calls, verification before finish) are declared but filled later.
