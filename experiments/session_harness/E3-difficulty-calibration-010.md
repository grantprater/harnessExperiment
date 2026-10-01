# E3 difficulty calibration 010: a harder mutation bank with a dev/eval split

Date: 2026-09-30  
Status: **completed 2026-10-01 (stage 1).** 60 valid runs on `claude-sonnet-5` (CLI 2.1.286), 48/60 accepted
(0.80); 2 adapter-failure attempts voided and rerun. The keep/drop rule gives an eval split of 12 tasks (predicted
acceptance 0.42) and moves 18 to dev. Twelve is below every power-table design, so per the bank stopping rule the next
stage (2a) needs an amended card and approval. [Report](E3-difficulty-calibration-010-report.md),
[split](E3-difficulty-calibration-010.split.json). Stage 1 was built offline: 30 candidates selected, gold/noop
controls passed on all 30, twice each.  
Owner decision (2026-09-30, verbatim): "1. Yes we can do that first."  
Owner decision (2026-09-30, verbatim): "Sure, I agree with your recommendations". This approves, from the open
decisions below: (1) the stage-1 calibration, 60 runs, at most 1,680 attempts, about $52 list on the CLI subscription;
(2) Sonnet 5 via the Claude CLI as the model and provider for both this calibration and the ontology experiment;
(3) the ontology run as a *pilot* on the stage-1 eval split (about 30 tasks x 2 rollouts x 3 arms), with stage 2a and a
powered confirmation only if the pilot is promising; (5) no separate lesson-store eval split until lesson-store work
starts. Decision (4) follows from (3): stage 2a is not run now.  
Owner decision (2026-09-30, verbatim): "Yeah we can pin sonnet 5 for now, though I think we pivot after this initial test run that we've gotten the comparison for to harder tasks and see if they extend/generalize".  
Model: pinned by full ID `claude-sonnet-5` after alias drift (2026-09-30): CLI 2.1.286 resolved the alias `sonnet` to `claude-sonnet-5-5`.  
Amendment 1 (2026-10-01): stage 2a generation approved by the owner ("Stage 2a first (Recommended)") and run in the
cloud (DETERMINISM: PASS-ADDRESS-ONLY). After generation the owner accepted the address-only exception and the
selection rule, and approved the stage-2a calibration, 78 runs (2026-10-01; [A1.5](#a15-owner-decisions-and-stage-2a-build-2026-10-01)).
Machine card [`cards/010-stage2a.json`](cards/010-stage2a.json); not yet launched.  
Stage: S6a follow-up (proposed in the [card 007 report](E3-calibration-007-report.md)). Machine card:
[`cards/010.json`](cards/010.json).

## Alias drift (2026-09-30)

- The first calibration attempt passed the CLI alias `--models sonnet`. After the CLI update (2.1.283 to 2.1.286)
  the alias resolved to `claude-sonnet-5-5`; c007, c013 and c018 ran on `claude-sonnet-5`. The protocol hash held
  the CLI version and the alias, not the model that answered, so nothing caught it. The model ID is in each run's
  `calls.jsonl` (stream-json `"model"` fields).
- That attempt ran on `claude-sonnet-5-5` and stood at 26/30 accepted on rollout 1.
- Its 39 completed runs, plus 1 run interrupted when the driver was stopped (40 folders), were voided as `*.void-model-sonnet-5-5`. They are kept as side data, not calibration outcomes.
- The calibration restarts from scratch on the pinned ID `claude-sonnet-5`. The runner now refuses aliases for
  live claude-cli runs and stops a run as `model_mismatch` (an adapter failure, void) if the CLI reports any other
  model than the pinned one.

## Question

Can we build a bank of mutation-repair tasks where the Reticle incumbent (Sonnet 5 via the CLI, `pressure-recent-v3`,
20 responses) accepts about **30-60%** of runs? The bank also needs a dev split for tuning and an eval split for
confirmation, disjoint from each other.

Why this is needed: on card 007's 20 tasks, the incumbent accepted 32/40 (0.80). The native Claude Code arm (c018)
accepted 29/40. Fifteen tasks were solved in every Sonnet run. At a base rate that high, about 40 runs cannot detect
a 10-15-point effect. The first user of this bank is the 3-arm evidence-ontology experiment (incumbent / `--reasoning
memory` / `--reasoning symbolic`; primary outcome: accepted repairs within budget;
[protocol](../neurosymbolic/README.md)). Cards 014, 015 and 009 come after it.

## What the history says

Per-task outcomes across every recorded run on the bank. Void runs and controls are excluded. Command:
`python experiments/session_harness/tally_task_outcomes_010.py`. Cells show accepted/runs.

| Task | Kind | f2p | c007 | c011 (40 resp) | c012 (Nemotron Super) | c013 inc | c013 guard | c017 (Nemotron Ultra) | c018 native | Sonnet pooled |
|---|---|--:|---|---|---|---|---|---|---|---|
| mut-001 | compare_flip | 1 | 1/2 | | 0/1 | 1/2 | 0/2 | 0/1 | 0/2 | 2/8 |
| mut-002 | drop_not | 9 | 2/2 | | 0/1 | | | 0/1 | 2/2 | 4/4 |
| mut-022 | negate_condition | 41 | 1/2 | | 0/1 | 1/2 | 1/2 | | 0/2 | 3/8 |
| mut-023 | drop_not | 34 | 2/2 | | 0/1 | | | | 2/2 | 4/4 |
| mut-024 | off_by_one | 2 | 2/2 | | 0/1 | | | | 2/2 | 4/4 |
| mut-025 | remove_guard | 1 | 2/2 | | 0/1 | 2/2 | 2/2 | | 2/2 | 8/8 |
| mut-032 | remove_guard | 1 | 0/2 | 0/2 | 0/1 | 0/2 | 0/2 | | 0/2 | 0/10 |
| mut-033 | swap_branches | 43 | 2/2 | | 0/1 | | | | 1/2 | 3/4 |
| mut-034 | compare_flip | 2 | 2/2 | | 0/1 | 2/2 | 2/2 | | 2/2 | 8/8 |
| mut-040 | compare_flip | 2 | 2/2 | | 1/1 | 2/2 | 2/2 | | 2/2 | 8/8 |
| mut-042 | off_by_one | 3 | 2/2 | | 0/1 | | | | 2/2 | 4/4 |
| mut-043 | remove_guard | 11 | 2/2 | | 0/1 | | | | 2/2 | 4/4 |
| mut-044 | swap_branches | 3 | 2/2 | | | | | | 2/2 | 4/4 |
| mut-046 | negate_condition | 4 | 2/2 | | | | | | 2/2 | 4/4 |
| mut-057 | off_by_one | 1 | 0/2 | 0/2 | | 0/2 | 0/2 | | 0/2 | 0/10 |
| mut-060 | negate_condition | 2 | 2/2 | | | | | | 1/2 | 3/4 |
| mut-061 | drop_not | 15 | 0/2 | 0/2 | | 0/2 | 0/2 | | 1/2 | 1/10 |
| mut-073 | swap_branches | 2 | 2/2 | | | | | | 2/2 | 4/4 |
| mut-075 | negate_condition | 22 | 2/2 | | | | | | 2/2 | 4/4 |
| mut-076 | drop_not | 26 | 2/2 | | | | | | 2/2 | 4/4 |
| **Column total** | | | 32/40 | 0/6 | 1/12 | 8/16 | 7/16 | 0/2 | 29/40 | 76/118 |

"Sonnet pooled" covers every Sonnet arm: c007, c011, both c013 arms and c018. Readings used below:

- **Single-test failing sets are the hard ones.** Sonnet pooled 10/36 (0.28). Without `mut-025`, whose statement
  names the mutated class, it is 2/28 (0.07). Multi-test tasks: 66/82 (0.80); in c007 alone, 29/32.
- **Mutation kind does not predict difficulty** (card 007 report).
- **The card-007 categories regress, and strongly for mixed tasks.** Later incumbent-style runs at 20 responses
  (c013 incumbent and c018) give these rates:
  - tasks that were 2/2 in c007: 34/36 = **0.94**;
  - the two tasks that were 1/2: 2/8 = **0.25**;
  - the three that were 0/2: 1/12 = **0.08**.

  These three numbers are the preregistered category predictors below. They rest on 2-15 tasks each.
- **Free models are far below the band on this bank:** Nemotron Super 1/12, Ultra 0/2. A bank calibrated for
  Sonnet does not transfer to them.

## Where candidates come from

| Stage | Source | Tooling | Status |
|---|---|---|---|
| 1 | Fresh single-site tasks already in `tasks.mutations.json` (55 never run in a campaign), filtered and deduplicated; multi-test tasks split between the generated statement and a weak-signal statement without the failure message | existing bank + `build_bank_010.py` (selection only, standard library) | **built**: 30 candidates, controls passed |
| 2a | More single-site tasks: run `generate.py` over its 431 untried candidates | existing generator, no new code | **specified, not run** (about 47 min single-threaded CPU plus OCI controls) |
| 2b | Two-site composites: two kept mutations in different functions, same file or cross-file | new composer, spec below | **specified, not built** |
| 3 | Other upstream repos in `.runtime/bug-mining/repos` (11 besides sqlparse) | generator parameterisation (mutation-report weakness 11) | **specified, not built** |
| dev only | Card-007 tasks with observed mixed or failed outcomes (001, 022, 033, 060 mixed; 032, 057, 061 hard) | existing | in the dev core |

### Stage 1 rule (run once, seed 10, before any calibration run)

Command: `python experiments/mutation_tasks/build_bank_010.py`. The `--check` flag reproduces the outputs byte for byte.

1. **Dev core (21).** The 20 card-007 tasks, which have been run, mined and inspected, plus `mut-006` (the S6a smoke saw it
   for one response).
2. **Excluded (3).** Tasks whose statement names the mutated function: `mut-049`, `mut-063`, `mut-072`.
3. **Dev pool (22).** Two kinds of fresh task go here:
   - 12 tasks share a mutated function with a dev-core task, e.g. `mut-028` and `mut-070`,
     which share `Function.get_window` and its test with `mut-057`;
   - 10 tasks duplicate a candidate's function in the seeded walk (next step).
4. **Candidates.** Shuffle the other fresh tasks (seed 10) and walk them. Take a task only when both its mutated
   function and its failing set are new. This gives 30 candidates in 30 distinct functions.
5. **Statement form.** Split the 22 multi-test candidates by a seeded shuffle (`"10:statement-form"`):
   - 11 get the generated statement;
   - 11 become `<id>-nm`, the same task with the sentence "The first failing check reports: `...`." removed. This is
     the generator's own `with_message=False` form. Mutation, gold patch and tests are unchanged.

   The 8 single-test candidates keep their statement.

Output files:
- [`tasks.difficulty010.json`](../mutation_tasks/tasks.difficulty010.json): LF sha256 `ccec2be28765...`
- [`E3-difficulty-calibration-010.sets.json`](E3-difficulty-calibration-010.sets.json): sha256 `ab81215601fd...`.
  It holds the calibration order, strata, dev core, dev pool with reasons, and exclusions.

| Stratum | Candidates |
|---|---|
| single test (8) | 005, 009, 012, 017, 020, 038, 041, 058 |
| multi-test, message (11) | 004, 010, 015, 027, 030, 031, 037, 050, 059, 069, 074 |
| multi-test, no message (11) | 016-nm, 035-nm, 036-nm, 039-nm, 045-nm, 048-nm, 052-nm, 053-nm, 062-nm, 064-nm, 065-nm |

**Prediction, stated before any run** (falsifiable):

| Stratum | Predicted acceptance |
|---|---|
| single test | 0.10-0.40 |
| multi-test with message | 0.75-0.95 |
| no message | 0.45-0.85 |
| all 60 runs | 0.50-0.75 |

The raw calibration rate is therefore expected to sit *above* the band. The keep rule, not the raw rate, builds the
eval split.

Known leak in the set: `mut-038`'s statement quotes the exact error string beside the deleted guard (mutation-report
weakness 3). It stays in the set; if it proves easy, the keep rule moves it to dev.

### Stage 2a (specified, not run)

Command:

```
generate.py --max-candidates 531 --budget-seconds 3600 --out tasks.mutations.full.json --log generation_log.full.json
```

The schedule is deterministic, and I checked it with no suite runs: the first 100 scheduled candidates equal the
100 in `generation_log.json`. So the first 76 kept tasks should reappear with the same ids. Verify this by comparing
`mutation_patch` and `statement` before using any new id.

AST-only count of headroom (this run, no suites):
- 431 untried candidates;
- they span 104 functions, 62 of which no bank task uses;
- 174 of the untried candidates fall in those 62 functions.

At card 007's 76% keep rate, expect about 45-55 new function-distinct candidates. **Single-site sqlparse therefore caps
the eval split at about 80 candidates before calibration, and roughly 30-40 after the keep rule.**

### Stage 2b composer (specified, not built)

`compose_bank.py` would reuse `generate.py`'s `materialize`, `run_suite`, `classify` and `build_statement`.

Pairing:
- Pair two kept tasks with different mutated functions: same file, or cross-file.
- Apply both `mutation_patch`es with `git apply`.

Keep a pair only if all of these hold:
- the suite passes the 90% rule;
- it shows no timeout;
- reverting either site alone leaves at least one of the pair's failing tests failing, so both sites are necessary.

Task fields:
- gold = both reverse diffs;
- `gold_source_files` = both files;
- the statement is built from the union failing set.

The runner's `task_contract` hashes a single `mutation_file`. A list value must be checked to serialise stably, or
the runner needs a small change.

### Stage 3 (specified, not built)

Parameterise `generate.py` (source task, library root, test root, `PYTHONPATH=src`) for another P6 repo. Keep
markdown-it-py (missing linkify dependency) and more-itertools (slow in OCI) out, as E3 already does.

## Offline filters (no model)

Commands:
- `run_pilot.py --client gold|noop --backend oci --arm pressure-recent-v3` over the whole bank, with the card's
  budgets, at idle priority with thread variables set to 1;
- `python experiments/session_harness/check_controls_010.py`.

A candidate passes when every recorded control run shows all of these:
- gold is accepted: fail-to-pass passes, pass-to-pass passes, no collection error, no pytest timeout;
- noop is rejected, and its failing fail-to-pass list equals the task's recorded `fail_to_pass` exactly, with nothing
  missing or skipped;
- there are at least 2 gold and 2 noop runs with identical outcomes (determinism);
- every control evaluation took at most 60 s.

**Result: 30/30 pass.** The recorded runs are:
- `c010-control-gold` and `c010-control-noop` (30 tasks each), planned hashes `8a5a064bb6c8` and `036ba507d467`;
  `run_card.py --plan` gives the same values;
- the repeats `-gold-rep2` and `-noop-rep2`;
- the 3-task `-sample` runs, done first.

All runs used OCI image `8b74015e5079` at commit `2fbc714`. The slowest evaluation took 17.8 s. The DoS timing test in
`mut-041` behaved deterministically: 3 of 3 gold runs passed it and 3 of 3 noop runs failed it. Summary:
[`E3-difficulty-calibration-010-controls.json`](E3-difficulty-calibration-010-controls.json).

Not filtered: statement leaks beyond "names the mutated function"; the calibration deals with easy tasks.

## Preregistered calibration run (stage 1)

- **Arm.** Card 007's incumbent, unchanged:
  - runner v8, `--client claude-cli --models claude-sonnet-5` (pinned by full ID after the alias drift; card 007
    passed the alias `sonnet`, which then resolved to this model), `pressure-recent-v3`, `reticle-tools-v3`;
  - OCI `8b74015e5079`, repeat guard off, no treatment;
  - 20 responses, 24 attempts, 1,200 active seconds, `max_tokens` 4096.

  The CLI was 2.1.283 for c007, c013 and c018, and is 2.1.286 today. Its version is a hash input, so pin the one
  current at launch and use the same one for the ontology experiment.
- **Units.** 30 candidates x 2 rollouts = 60 runs, `c010-<task>-r<k>`, rollout-major (all of rollout 1 first).
- **Void and rerun** (not outcomes): runs ended by a usage limit, an adapter failure or a machine sleep (the card 018
  practice).
- **Keep/drop rule.** Fixed now and applied mechanically. The output goes to
  `E3-difficulty-calibration-010.split.json`.
  1. Classify each task by its 2 valid runs: **solved** 2/2, **mixed** 1/2, **hard** 0/2.
  2. Start the eval split with every mixed and every hard task.
  3. Predicted acceptance of a composition = the task-weighted mean of the category predictors (0.94 solved,
     0.25 mixed, 0.08 hard, from the history above).
  4. Add solved tasks, in calibration-list order, while the predicted acceptance is below **0.40**.
  5. If it is still below 0.30 when no solved task is left, move hard tasks to dev from the end of the list until it
     reaches 0.30.
  6. Every task not in eval goes to dev.
  7. Statements, tasks and budgets are never changed after the first run.
  8. Calibration outcomes select tasks only. They are never reused as incumbent data, because selection on them
     biases the incumbent downward.
- **Secondary report.** Acceptance by stratum, which shows whether dropping the message moves difficulty. It uses
  11 vs 11 tasks, so treat it as a screen, not a test.

## Stopping rule

- **Campaign.** The run stops at 60 valid runs or on any fast stop in card 007:
  - evaluator leakage;
  - evidence loss;
  - authority escape;
  - 3 consecutive adapter failures;
  - a failed control.

  Running out of attempts (cap 1,680) also stops it. Extension needs a new approval.
- **Bank.** Calibration is finished when the eval split reaches the n of the owner's chosen design (power table).
  Otherwise the next stage (2a, then 2b or 3) is proposed as an amended card with its own approval.
- **Program.** Declare the 15-point design infeasible on this bank, and report it, if either of these happens:
  - two consecutive stages each add fewer than 5 eval tasks;
  - calibration spend reaches a cap the owner sets.

## Split

**Dev.** The dev core (21), the dev pool (22), and every calibration task not kept for eval. It includes all 7
tasks with observed mixed or failed outcomes. This is where ontology development, tool-description tuning and any
diagnosis happen, as the protocol's "develop on the inspected mutation failures" asks.

**Eval.** The kept calibration tasks. Nobody reads their trajectories for tuning.

The eval split is disjoint from dev in task, mutated function and exact failing set. It is not disjoint in file or
repository: 13 of 30 candidates are in `sql.py`. Transfer is therefore within one repo and one generator.

**Lesson store (learn/eval).** Yes, the bank can provide the split the 2026-09-30 amendment requires:
- learning = dev pool plus the calibration tasks moved to dev;
- selection = dev core;
- evaluation = eval split.

Caveats:
- dev skews easy: card 007 was 80% solved;
- if the ontology and lesson-store experiments both confirm on one eval split, the second is chosen after seeing the
  first's results on it. A strictly untouched lesson-store eval needs its own stage-2 tasks. (Open decision.)

## Power note

Design:
- Every arm runs every eval task r times.
- Unit = task. D_i = treatment minus incumbent acceptance rate on task i.
- Two confirmatory comparisons (memory vs incumbent, symbolic vs incumbent), Bonferroni alpha = 0.025 two-sided,
  power 0.80, delta = 0.15.

```
Var(D_i) = tau2 + [ (p0(1-p0) - sigma2) + (p1(1-p1) - sigma2) ] / r
n_tasks  = (z_0.9875 + z_0.80)^2 * Var / delta^2 = (2.2414 + 0.8416)^2 * Var / 0.0225 = 9.505 * Var / 0.0225
```

sigma2 is the between-task variance of true acceptance. Card 007 gives 0.117 (one-way ANOVA: MSB 0.2842, MSW 0.0500,
ICC 0.70). Central value: 0.10. tau2 is the task-by-treatment variance. c018 minus c007 gives a per-task difference
variance of 0.0599 at r = 2, about what binomial noise alone predicts, so tau2 near 0 is consistent. With a real
15-point effect it will not be 0: central 0.02 (effect SD 0.14).

Central worked example, p0 = 0.45, p1 = 0.60, r = 2:
- Var = 0.02 + (0.1475 + 0.14)/2 = 0.1637;
- n = 9.505 x 0.1637 / 0.0225 = 69.2, so **70 tasks, 420 runs**.

| p0 | Scenario (sigma2, tau2) | r = 2 | r = 3 | r = 4 |
|---|---|---|---|---|
| 0.45 | optimistic (0.15, 0.00) | 40 tasks / 240 runs | 27 / 243 | 20 / 240 |
| 0.45 | **central (0.10, 0.02)** | **70 / 420** | **49 / 441** | **39 / 468** |
| 0.45 | pessimistic (0.05, 0.04) | 99 / 594 | 72 / 648 | 58 / 696 |
| 0.30 | central | 63 / 378 | 45 / 405 | 36 / 432 |
| 0.60 | central | 57 / 342 | 41 / 369 | 33 / 396 |

Other points:
- One primary comparison (alpha 0.05): 58 / 348 at r = 2.
- delta = 0.20 (central): 38 / 228 at r = 2, and 22 / 264 at r = 4.
- Unpaired reference (no task pairing): 210 runs per arm, 630 in all.
- With stage 1 alone (at most about 30 eval tasks), the minimum detectable effect is about 0.23 at r = 2 and 0.17 at
  r = 4.

Reading:
- The paired design needs **about 40-70 eval tasks and 420-470 runs** for 15 points.
- Stage 1 cannot supply that, and single-site sqlparse (1 + 2a) reaches it only near r = 4.
- Tasks are not independent (shared files), so the effective n is lower than the count.

Recompute: `python experiments/session_harness/power_010.py`.

## Calls and cost

Basis: c013 incumbent runs, recomputed from `results.jsonl`:
- 16.19 provider attempts per run (12.38 accepted, 20.00 rejected);
- mean prompt tokens 217,057 (132,278 accepted, 301,837 rejected);
- list price $0.94 per run (given).

I scaled cost by prompt tokens, which assumes no price table: **$0.57 per accepted run, $1.31 per rejected run.**

**Calibration run (stage 1), 60 runs:**

| | Model attempts | List price |
|---|--:|--:|
| Expected at the predicted 60% acceptance | about 930 | about $52 |
| All accepted | | $34 |
| All rejected | | $79 |

- The hard cap is 1,440 planned attempts (1,680 with retry room).
- Wall time is about 4-5 h serial (card 007: 229 s mean per run; rejected runs take longer).
- On the CLI subscription nothing is billed, but usage limits apply; c018 lost 3 runs to them.

**Then the ontology experiment:**
- central design: about 420-470 runs, **about $410-460 list** at $0.98 per run for p0 = 0.45, and about 7,000 attempts;
- delta = 0.20: about $220-260.

The reasoning tools may add tokens per run: the finish guard added 14% attempts.

**What the model and provider choice depends on:**
1. **Difficulty is model-specific.** The calibration must use the ontology experiment's incumbent: same model, harness,
   budgets and CLI version. Nemotron Super scored 1/12 where Sonnet scored 32/40, on the same tasks.
2. **CLI subscription vs API.** The CLI route is unbilled but rate-limited, and serialises about 4 min per run. The API
   route is billed.
3. **Caching.** The Reticle CLI adapter flattens the whole context into each response, so nothing caches. Native Claude
   Code on the same tasks reported **$0.128 per run** (c018 `total_cost_usd`, 40 runs), about 7x less. An API client with
   card 008's cache-stable layout could cut the cost of both runs, but it changes the incumbent protocol, so the bank
   would need recalibration.
4. **The ontology treatments live in uncommitted runner changes.** Verify at launch that the incumbent's hash is
   unchanged by them.

## Open decisions for the owner

1. Approve the stage-1 calibration: 60 runs, at most 1,680 attempts, about $52 list, run on the CLI subscription.
2. Model and provider for the ontology experiment. The calibration must match it.
3. Target design: delta 15 vs 20 points, r = 2 vs 4, one or two primary comparisons. This sets the eval n (22-70).
4. Whether to run stage 2a now (no model; about 47 min CPU plus about 1-2 h of OCI controls) and calibrate stages 1 and
   2a in a single approval.
5. Whether the lesson store gets its own untouched eval tasks.

## Amendment 1 (2026-10-01): stage 2a

Owner question (2026-10-01, verbatim): "Card 010's keep/drop rule left only 12 eval tasks, not the ~30 the 4-arm pilot
was sized for. How should the pilot proceed?"

Owner answer (verbatim): "Stage 2a first (Recommended)". That option read: "Generate ~45-55 new sqlparse mutation tasks
(CPU only, ~47 min, as a one-shot cloud routine, no model calls), then calibrate them: ~90-110 runs on Sonnet 5 (roughly
$95-115 at list). At the 12/30 yield that adds ~18-22 eval tasks, ~30-34 in total. Then the 4-arm pilot as approved:
~240 runs. Each step's calls and cost are confirmed with you before it runs."

What this approves now: the generation step (A1.1) and its determinism check (A1.2), which make no model call. The
selection (A1.3) and the calibration protocol (A1.4) are fixed here before any output exists, but no calibration run is
approved: its run count and cost are set after generation and go to the owner first.

Stage 1 is not changed: `cards/010.json`, `tasks.difficulty010.json`, the sets file and the split file stay as they
are. Rechecked 2026-10-01 with `apply_split_010.py` (offline): every stage-1 run's hash still equals the hash
`run_card.py --plan` computes for it.

### A1.1 Generation (approved; no model calls)

- **Where.** A one-shot cloud routine (4-core Linux VM, no GPU), prompt
  [`experiments/cloud/RUN_IN_CLOUD-010-stage2a.md`](../cloud/RUN_IN_CLOUD-010-stage2a.md). Results go to branch
  `cloud-results-010-stage2a`.
- **Code.** Branch `exp/ontology-pilot` at the amendment commit. The generator,
  [`generate.py`](../mutation_tasks/generate.py), is unchanged: `GENERATOR_VERSION` 1, seed 865, source task
  `sqlparse-865`, upstream sqlparse `f66d12c245412f28c58f045b646eb53c0e691b8b`.
- **Command.** The card's stage-2a command, run from the repository root:

  ```
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 nice -n 19 .runtime/bugs-venv/bin/python \
    experiments/mutation_tasks/generate.py --python "$PWD/.runtime/bugs-venv/bin/python" --work-dir /tmp/c010-2a-work \
    --max-candidates 531 --budget-seconds 3600 \
    --out experiments/mutation_tasks/tasks.mutations.full.json \
    --log experiments/mutation_tasks/generation_log.full.json
  ```

  It differs from the card's literal command in three ways, none of which changes what is generated:
  - `--python`: the generator's default task interpreter is the Windows venv path; it must be absolute, because the generator runs suites from inside the workspace (the first cloud attempt, 2026-10-01 06:34Z, stopped after 22 s on the relative path, before any candidate ran);
  - `--work-dir`: an explicit scratch directory;
  - output paths: the card gave bare file names; these put the outputs beside the bank.

  `--gold-check` stays at its default of 2.
- **Budget.** A 3600 s wall cap on the candidate loop, as in the card. At the host's recorded 5.35 s per candidate,
  531 candidates take about 47 min. If the VM is slower, the cap stops the loop early, and the result file records how
  many were tried. A rerun or a larger budget needs a new approval.
- **Platform.** The recorded bank was generated on the Windows host. This run is on Linux:
  - task Python 3.13.15 from `setup_cloud.sh`, the host's version;
  - `bugs-venv` installed exactly from the host's freeze, without pytest-timeout, as in the recorded run.

  The stage-1 controls ran on Linux (OCI) and reproduced every recorded `fail_to_pass` set. The determinism check in
  A1.2 is the test that applies here.

### A1.2 Determinism check

The card's requirement is: "the first 76 kept tasks should reappear with the same ids. Verify this by comparing
`mutation_patch` and `statement` before using any new id."

**Before launch (done 2026-10-01, on the host, no suites).** Command:
`python experiments/mutation_tasks/check_stage2a_010.py --schedule`, with `--repo-dir` pointing at the main checkout's
sqlparse clone.
- Result: `SCHEDULE: SAME`.
- Candidate pool 531, of which 431 untried.
- The first 100 scheduled candidates equal `generation_log.json` in file, line, kind, detail and function.
- All 76 kept patches equal the recorded `mutation_patch`.

**After generation (in the cloud run).** Command:
`python experiments/mutation_tasks/check_stage2a_010.py --compare --result experiments/mutation_tasks/stage2a-010-result.txt`.

The check passes when both of these hold:
- (a) at least 100 candidates were tried, and the first 100 log entries equal the recorded ones in file, line, kind,
  detail, function and verdict;
- (b) the full output's first 76 tasks are `sqlparse-mut-001` to `-076`, in order, with byte-identical
  `mutation_patch` and `statement`.

**Known exception (approved 2026-10-01).** `sqlparse-mut-072`'s statement quotes an object repr with a
CPython memory address: `<DML 'select' at 0x24ED3E03B80>`. The address changes in every process. A full regeneration
on 2026-09-28 saw exactly this difference ([REPORT.md](../mutation_tasks/REPORT.md) weakness 11, on branch
`integration/2026-10`). The script therefore reports `PASS-ADDRESS-ONLY` when every statement difference disappears
after replacing `0x[0-9A-Fa-f]+`. `PASS-ADDRESS-ONLY` counts as a pass (approved 2026-10-01; A1.5). `mut-072` is excluded from every
split, because its statement names the mutated function. Before that approval, `PASS-ADDRESS-ONLY` was handled
like a failure for the purpose of using new ids.

That regeneration also lost `sqlparse-mut-044` to the 60 s timeout, on a heavily loaded host (75.9 s against 3.2 s).
On the VM, the generator is the only job.

**If the check fails:** stop and report.
- No new id (`sqlparse-mut-077` onward) is used, nothing is calibrated, and `tasks.mutations.json` stays the reference.
- The cloud run still commits its outputs and the result file to `cloud-results-010-stage2a`, for diagnosis only.
- A rerun or fix needs a further amendment.

### A1.3 Selection of new candidates for calibration (approved 2026-10-01)

The card has no selection rule for stage 2a. It only expects "about 45-55 new function-distinct candidates", from the
"62 [functions] no bank task uses". The rule it does have is stage 1's (section "Stage 1 rule";
[`build_bank_010.py`](../mutation_tasks/build_bank_010.py) docstring), quoted:

> 2. Excluded: tasks whose statement names the mutated function (statement_names_mutated_function).
> 3. Dev pool (untried, but correlated with the dev core): tasks whose mutated_function or whose exact fail_to_pass
>    set equals a dev-core task's.
> 4. The remaining fresh tasks are shuffled with random.Random(SEED) from task-id order and walked; a task is a
>    calibration candidate when both its mutated_function and its sorted fail_to_pass set are new among candidates;
>    otherwise it joins the dev pool as a duplicate.
> 5. Statement form: candidates with one failing test keep the generated statement. Candidates with two or more are
>    sorted by id, shuffled with random.Random(f"{SEED}:statement-form"), and the first half (rounded down) become
>    weak-signal variants `<id>-nm` [...]

Minimal adaptation (approved 2026-10-01), the same rule with three substitutions:
1. **Pool.** The kept tasks of `tasks.mutations.full.json` after `sqlparse-mut-076`, and only after the determinism
   check passes.
2. **Excluded.** Step 2, unchanged.
3. **Dev pool.** Step 3, with "a dev-core task" read as **any of the 76 recorded bank tasks**: dev core, dev pool,
   excluded and stage-1 candidates alike. After stage 1, every recorded task is in dev or eval, so a new task that
   shares a function or failing set with any of them is not new.
4. **Walk.** Step 4 with seed `"10:stage-2a"` in place of `10`.
5. **Statement form.** Step 5 with seed `"10:stage-2a:statement-form"`.
6. **No cap.** Every candidate that passes is calibrated.
7. **Controls first.** Before calibration, every candidate goes through the card's "Offline filters": gold and noop in
   OCI, twice each, checked against the `check_controls_010.py` criteria. A candidate that fails is dropped and
   reported. This needs no model, but about 1-2 h of local OCI time.

`check_stage2a_010.py --compare` applies steps 1-4 and reports counts only. The stage-2a bank and sets files are
written by [`build_bank_010_stage2a.py`](../mutation_tasks/build_bank_010_stage2a.py), made after approval (A1.5).

### A1.4 Calibration of the new candidates (protocol fixed; 78 runs approved 2026-10-01)

**Protocol.** Identical to "Preregistered calibration run (stage 1)":
- runner v8, `--client claude-cli --models claude-sonnet-5`, Claude CLI 2.1.286;
- `pressure-recent-v3`, `reticle-tools-v3`, OCI image `8b74015e5079`, repeat guard off, no treatment;
- 20 responses, 24 attempts, 1,200 active seconds, `max_tokens` 4096;
- 2 rollouts, rollout-major, runs named `c010b-<task>-r<k>` (prefix `c010b`, set when the machine card was drafted, so
  that no stage-2a folder can collide with a stage-1 `c010-` folder; the run name is not a protocol-hash input);
- the same void-and-rerun rule.

If the CLI version changes before launch, stop and ask; do not re-pin it silently.

**Keep/drop rule.** The card's rule, as quoted in the report's "Decision rule (from the card)":

> Per task after 2 valid rollouts: solved 2/2, mixed 1/2, hard 0/2. Eval starts as every mixed and hard task.
> Predicted acceptance of a composition = task-weighted mean of the preregistered category predictors (solved 0.94,
> mixed 0.25, hard 0.08 [...]). Add solved tasks in calibration-list order (the sets file) while predicted acceptance
> < 0.40; if still < 0.30 with no solved task left, move hard tasks to dev from the end of the list until it reaches
> 0.30. Every other task goes to dev. Nothing about the tasks, statements or budgets changes after the first run;
> calibration outcomes are never reused as incumbent data.

The card gives no rule for applying this to a later stage. **Approved 2026-10-01:**
- Apply the rule unchanged to the stage-2a tasks alone, in the order of the stage-2a calibration list.
- Add the resulting eval tasks to stage 1's 12. Stage 1's split file stays as written.
- Report the predicted acceptance per stage and for the union.

Why not the pooled alternative (one rule over stage 1 + 2a, with stage 1 first in list order)? It would first pull
stage-1 solved tasks that are already in dev (`mut-009`, `-074`, `-058`, ... in that order) back into eval, before any
stage-2a solved task. That would change a split the pilot's development already uses. The owner chose the per-stage
rule (A1.5).

**Run count and cost: approved 2026-10-01 (78 runs; A1.5).**
- They are fixed after generation and controls: runs = 2 x the number of candidates that pass controls; attempt cap
  28 per run, as in stage 1 (1,680 / 60).
- Cost basis: stage 1, $0.57 per accepted run and $1.31 per rejected run at list. At about 50 candidates (100 runs),
  that is about $65-80 at stage 1's observed 0.80 acceptance, and $57-131 from all accepted to all rejected. The
  owner's option text estimated about $95-115.
- The figure went to the owner before any run: 39 tasks x 2 = 78 runs, about $70 at list, approved 2026-10-01.

**Machine card.** `cards/010.json` is not edited. The stage-2a calibration gets a new machine card,
`cards/010-stage2a.json` (named like `006-replay.json`). It is drafted after generation, once its task and sets files
exist to be hash-pinned, and checked with `run_card.py --validate` only. Nothing is executed until approval.
Drafted 2026-10-01 after the owner's approval (A1.5); status `approved`.

**Stopping.** The card's stopping rules apply unchanged. Under the program rule, the design is declared infeasible if
two consecutive stages each add fewer than 5 eval tasks; stage 1 added 12.

### A1.5 Owner decisions and stage-2a build (2026-10-01)

**Generation result** (cloud, branch `cloud-results-010-stage2a`, commit `bdf7db9`, merged into `exp/ontology-pilot`;
[`stage2a-010-result.txt`](../mutation_tasks/stage2a-010-result.txt)): 531 of 531 candidates tried, 351 kept, 275 new
after `sqlparse-mut-076`; both gold checks pass; `DETERMINISM: PASS-ADDRESS-ONLY`, with `mut-072` the only difference.
The cloud task interpreter was Python 3.13.14; the host bank used 3.13.15.

**Owner decisions (2026-10-01), each with its question.** The question texts are as relayed to this record; "..." marks
text elided in the relay.

1. Question: "Accept the reproducibility exception? Tasks 001-076 regenerated identically on the cloud machine except task 072, whose description differs only by a Python memory address. Task 072 is already excluded from every set."
   Answer (verbatim): "Accept (Recommended)" (option text: "PASS-ADDRESS-ONLY counts as a pass, so the new task ids (077 onward) may be used.")
2. Question: "Accept the proposed selection rule for stage 2a? ... leaving 39 function-distinct tasks (5 single-test, 34 multi-test). The keep/drop rule is applied to those 39 alone, and the tasks it keeps are added to stage 1's 12."
   Answer (verbatim): "Accept (Recommended)" (option text: "Calibrate all 39 and apply the keep/drop rule to stage 2a separately. Pooling would pull round-1 tasks that were dropped back in ahead of any new task.")
3. Question: "Approve the stage 2a calibration: 39 tasks x 2 rollouts = 78 runs on claude-sonnet-5 (CLI 2.1.286, local OCI backend, same protocol as stage 1). It costs about $70 at list (stage 1 averaged $0.90 a run; range about $55-95), plus model-free gold/no-op controls first. ..."
   Answer (verbatim): "Approve 78 runs (Recommended)" (option text: "Run the model-free controls, then the 78 calibration runs locally, one process at a time. The stage-1 stopping rules apply.")

**Bank and sets.** [`build_bank_010_stage2a.py`](../mutation_tasks/build_bank_010_stage2a.py) applies A1.3 (seeds
`"10:stage-2a"` and `"10:stage-2a:statement-form"`; it imports `no_message` from the unchanged stage-1 builder) and
stops unless its count equals `check_stage2a_010.py`'s `candidates_function_distinct` (39). Outputs:
- [`tasks.difficulty010-stage2a.json`](../mutation_tasks/tasks.difficulty010-stage2a.json), 39 tasks;
- [`E3-difficulty-calibration-010-stage2a.sets.json`](E3-difficulty-calibration-010-stage2a.sets.json): calibration
  order, strata (5 single-test, 17 multi-test with message, 17 multi-test without, `-nm`), dev pool 220 (182 sharing a
  function or failing set with the 76 recorded tasks, 38 duplicates among new), excluded 16.

Rerun: `python experiments/mutation_tasks/build_bank_010_stage2a.py --check` (both files `same`).

**Machine card.** [`cards/010-stage2a.json`](cards/010-stage2a.json): stage 1's arm, budgets, image and stop rules;
39 x 2 = 78 runs, prefix `c010b`; campaign cap 2,184 attempts (stage 1's 28 per run: 1,680 / 60). `--plan` lists 78
runs plus the 2 controls, with no blockers. Stage 1's plan is unchanged: every recorded stage-1 run's hash (60 runs,
2 retries, 2 controls) equals `run_card.py cards/010.json --plan --json`, and `apply_split_010.py` reports the same.

**Controls.** **39/39 pass** (`python experiments/session_harness/check_controls_010.py --stage 2a`; criteria unchanged from
"Offline filters"), so no task is dropped. Runs, OCI image `8b74015e5079`, podman, one container at a time at Idle
priority with thread variables set to 1, no model:
- `c010b-control-gold` and `c010b-control-noop` (39 tasks each), recorded hashes `d80ec15e5757` and `5aca4f18f1c4`,
  equal to `run_card.py cards/010-stage2a.json --plan --replay`;
- the repeats `-gold-rep2` and `-noop-rep2`, same commands under another run name;
- the 3-task `-sample` runs, done first.

Every gold run accepted, every noop run rejected on exactly the recorded `fail_to_pass` set; the slowest evaluation
took 18.7 s. Summary: [`E3-difficulty-calibration-010-stage2a-controls.json`](E3-difficulty-calibration-010-stage2a-controls.json).
Not done: the calibration itself (78 runs) is not launched.

## Not done (as of approval, before the calibration run; results are in the report)

- No model calls, and no calibration run.
- Stage 2a (generator continuation), 2b (composer) and 3 (other repos) were not run or built.
- No leak filter beyond the existing "names the mutated function" flag.
- No human review of the 11 no-message statements beyond one spot check (`mut-064-nm`).
- `experiments/REGISTER.md` and `IMPLEMENTATION_PLAN.md` were not edited.
