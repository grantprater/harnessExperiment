# E5 transfer to forecasting 022: design for review (no build, no run)

Date: 2026-09-28  
Status: design proposed for owner review. Nothing is built. No model call was made for it. Card number 022 is
tentative.  
Stage: E5 (plan 5.2). S6's acceptance rule asks for held-out tasks. This card asks the harder question:
**do harness changes selected on code repair transfer to a graded domain the selection never saw?**

## 0. Decisions in one screen

1. **Metaculus text questions would make the test vacuous.** The agent reads a paragraph and writes one number
   (the pastcast probe does exactly that in one reply). There is nothing to investigate, no artefact to check,
   and no budget to run out of, so none of the code-selected changes (finish guard, midpoint nudge, check
   oracle, statement-derived verifier) has a trigger. Both arms would behave identically, and the null result
   would say nothing about transfer.
2. **Workspace forecasting is the version that works.** Each question comes from a public time series. The
   workspace holds only data published on or before the forecast date `T`. The agent must write two files:
   `forecast.json` (the probability) and `resolve.py` (its reading of the resolution criteria, as code). The
   score is the Brier score against data published after `T`. With this setup the task has all four phases
   of the harness process: investigation, commitment, verification and stopping.
3. **Held-out domains, best first, for this question:**
   1. near transfer: mutation repair on another repository (a prerequisite, not a replacement);
   2. workspace forecasting (this card);
   3. data-analysis questions with computable answers;
   4. Metaculus text questions, which are only useful for the memorisation probe (section 3).
4. **Leakage control.**
   - The time cutoff is the model's release, not a guessed training cutoff. `claude-sonnet-5` was already
     listed on 2026-06-24, so every forecast date is on or after 2026-07-06.
   - The live network is removed. The runs go on the host's OCI backend (`--network none`, only the
     workspace mounted).
   - The resolutions are not on disk during the runs. Scoring happens afterwards against a file whose sha256
     is pinned in the card beforehand.
   - A recall probe with a pre-cutoff positive control tests for memorisation.
5. **Question bank.** 200 binary questions (40 calibration, 120 sealed, 40 reserve), all chosen by a seeded
   rule that looks at data before `T` only. That rule is frozen, with its sha256, before any run.
6. **Power.** The planning SD of the paired per-question Brier difference is σ_d = 0.07. It is derived below,
   because the 6-question pastcast ledger cannot pin it down. A gain of Δ = 0.02 Brier (one-sided α 0.05)
   then needs 76 questions for 80% power. With N = 120 the power is 93% at σ_d = 0.07 and 71% at 0.10.
7. **Arms.** The incumbent against the code-selected change(s), paired per question with seeded arm order.
   The decision rule in section 5 takes the treatment only from changes that pass S6 acceptance on code. If
   none passes, only phase A runs.
8. **Cost.** About $0.25 per forecast run at list price (code repair: $0.69-0.85). Phase A costs about $19 and
   phase B $60-120, about $79-139 in total, with a $150 cap.
9. **The intuition instrument is worth testing, in a fixed order.**
   1. First, retrospectively on about 144 existing code trajectories, at no agent-run cost.
   2. Then as structured, judge-free predictions attached to tool calls, with a reactivity arm.
   3. Only then as a surprise-triggered treatment, and only if that treatment first wins on code.

## 1. Why the text version is vacuous, and what the transfer test needs

The harness changes on the table act on the process: when the agent commits, whether it verifies, and whether
it stops before its budget runs out. Card 007/019 failures were (a) finishing with an unverified wrong fix and
(b) running out of budget without committing. Card 020's early result is that a counts-only check turns hard
failures into accepts, so verification limits the incumbent more than fixing does. A transfer domain therefore
needs each of the following to have a real counterpart:

| Process element | Code repair (selection domain) | Metaculus text question | Workspace forecasting (proposed) |
|---|---|---|---|
| Investigation | read/search the repo, reproduce the failure | none (the background is the whole input) | read `question.md`, inspect `data/*.csv`, compute history-only frequencies and conditioning variables |
| Commitment | edit library source | write a number | write `forecast.json` and `resolve.py` |
| Failure (a): wrong, unverified | wrong fix finished without verification | not observable | a misread criterion (strict versus inclusive, the last value on or before a date, units, a window instead of a point) or an untested method; measured objectively by comparing `resolve.py` with the true resolver on past windows |
| Failure (b): no commitment | budget spent with no edit | not possible in one reply | budget spent with no valid `forecast.json` |
| Verification | run the tests you wrote | none | backtest `resolve.py` and the method on past windows; check the file parses; the independent-reading check (treatment) |
| Stopping | `finish` | the reply ends | `finish` |
| Grade | hidden tests (pass/fail) | proper score | proper score (Brier primary, log secondary) |

Whether a treatment can transfer at all depends on whether it has a counterpart that leaks nothing:

| Code-side change | Status on code | Counterpart in forecasting | In 022? |
|---|---|---|---|
| Finish guard (013, self-chosen checks) | rejected (7/16 vs 8/16) | "first finish after a deliverable edit rejected once unless `resolve.py` or the method ran after it" | no: only selected changes transfer |
| Midpoint nudge (014) | proposed, not run | the trigger becomes "no deliverable written after half the responses" instead of "no source edit" | only if it passes S6 on code |
| Hidden-test check oracle (015/020) | changes the task, so it is never promoted | its only counterpart is the outcome itself, which would be leakage | never |
| Statement-derived verifier (021) | planned | a separate model invocation reads only the question statement and the data schema and writes an independent `resolve.py`. `check()` (K=3) runs both resolvers on the past windows of the frozen data and returns only the number of windows where they disagree. Like tests written from the statement, this checks the agent's reading of the specification against an independent reading, without revealing the answer. | yes, if 021 passes S6 on code |
| Predict-before-act (intuition) | not built | same mechanism, same prediction kinds | a separate reactivity arm (section 7) |

Requiring `resolve.py` in **both** arms is a deliberate task choice. It gives the verifier something to check,
and it lets a post-hoc diagnostic count misreadings (the counterpart of a wrong fix) without any judge. The file
is not graded.

**A typical trajectory** (planning estimate, confirmed in phase A):
1. `read_file question.md`, then `glob_files data/*`;
2. read the header and tail of the series;
3. `write_file analysis.py`: the event's history-only frequency over past windows, plus a regime conditioning;
4. `run`;
5. `write_file resolve.py` and `forecast.json`;
6. `run` a self-check (parse, backtest agreement);
7. `finish`.

That is 6-10 replies. The per-run budget is 12 responses, so failure (b) remains possible.

## 2. Task format in the harness

- **Task kind.** A new `kind: forecast` in the task file. The contract enters the protocol hash like a mutation
  task's. It records the template id, the series ids, `T`, the horizon, the snapshot sha256, the statement
  digest and the instructions digest. Code tasks' hashes do not change (incumbent `b0fda8c921ad` still
  reproduces).
- **Workspace.** It contains:
  - `question.md`: title, resolution criteria, fine print, `T`, horizon;
  - `data/<series>.csv`: rows published on or before `T` only (for daily market series, values dated `T-1` or
    earlier), 3-10 years of history;
  - `data/README.md`: source, units, missing-value and publication rules;
  - one or two related series per question, so that investigation involves choices.

  No git repository, no resolution, no data after `T`.
- **Instructions.** A forecast-kind template, hashed through the contract: "Today is {T}. … Write
  `forecast.json` as `{"probability": p}` and `resolve.py` defining `outcome(rows, T, horizon) -> bool` for
  your reading of the criteria. Python standard library only. Forecasts are scored by Brier score against data
  published after today. Call finish when done." The tools (reticle-tools-v3), the context policy
  (`pressure-recent-v3`), the budget handling and the `finish` semantics are unchanged. Only the task text
  differs from the code instructions.
- **In-run evaluator** (`evaluate_forecast.py`, hashed like `evaluate_task.py`). It checks that
  `forecast.json` holds exactly one number in [0, 1] and that `resolve.py` imports and returns a bool on one
  past window, inside the container. Its only output is `committed` (true/false), recorded as run_card's
  `accepted`. No outcome is known at run time.
- **Post-hoc scorer** (`score_forecasts.py`, after the campaign). It computes Brier and log score. Log score
  clips p to [0.01, 0.99], as pastcast does, and a missing forecast is scored as p = 0.5 and also counted as
  not committed. It also computes reading agreement (`resolve.py` against the true resolver over the last 52
  past windows) and the paired tables.
- **Scripted controls** (no model):
  - `gold`: the base-rate forecaster, which writes the true resolver's history-only frequency; expect
    committed;
  - `noop`: expect not committed;
  - `gamer`: writes `{"probability": 1.7}` or two numbers; expect not committed;
  - `peeker`: reads outside the workspace, opens a socket and requests a URL; expect every attempt to fail and
    be logged.

  `gold` also sets the reference Brier that the model arms must beat.

## 3. Leakage control

**Model cutoff.** The local references record no training cutoff for `claude-sonnet-5`. (Opus 5.5 records June
2026.) The model table cached on 2026-06-24 already lists Sonnet 5 as active, so its training data ends before
then. Every forecast date `T` is therefore on or after 2026-07-06, and every resolution date is on or before
2026-09-25. This relies on the fact that a model cannot be trained on data that did not exist when it was
released, so no cutoff has to be guessed. Residual risk: the unversioned id `claude-sonnet-5` could be
re-snapshotted later. The adapter's model pin checks the id, not the snapshot, so the card records
`reported_model` and the CLI version, and runs the recall probe again if either changes.

**Memorisation probe (a control arm, every question).**
- One isolated `claude -p` call per question, through the adapter's flags: "This question has already
  resolved. If you know the outcome, state it with a probability; otherwise say unknown."
- Positive control: 20 matched questions with `T` in 2025 (before the cutoff), where recall should beat
  chance.
- Stop rule: if, on the post-cutoff bank, the model names an outcome for more than 10% of questions and does so
  more accurately than the `gold` base-rate forecaster on the same questions, stop and treat the bank as
  leaked.
- If the positive control shows no recall either, the probe is insensitive, and the report says so instead of
  claiming no leakage.
- Cost is about $0.01 per call, so about $2 in total.

**The live network is removed rather than audited.** The CLI's built-in tools are already disabled
(`--tools ""`), so the only way to reach the internet is the `run` tool.
- **On the host's OCI backend** it is removed entirely: `--network none` and a single workspace mount
  (`IsolatedOCIBackend`, S2b probes 24/24). The native file tools are confined to the workspace path.
- **The trusted-local cloud VM cannot give the same guarantee**, as card 020's review note shows: the model's
  commands can read the VM's filesystem and reach the network. The cloud variant is therefore restricted
  (section 8).
- On both backends:
  - the `peeker` control runs before any model run;
  - a post-run audit greps every command for `http`, `socket`, `urllib`, `curl`, `wget` and `pip`, and every
    tool result for any date after `T`;
  - one hit stops the campaign.

**Frozen, date-bounded information.**
- Each question's snapshot is cut at build time, and the materializer asserts that no row is after `T`.
- Resolutions and the complete series stay outside the checkout until scoring (`~/harness-sealed/022/`, sha256
  pinned in the card).
- Only non-revised series are used: market prices, weather reanalysis, counts, pageviews. Revised statistics
  such as payrolls would carry information from after `T` inside earlier values.
- No research tool is offered. The frozen data is the research.
- The CLI's environment note shows the real date, so the model can tell the question has resolved. This is the
  same in both arms, and the recall probe measures what it can do with that knowledge.

## 4. Question bank

**Why not Metaculus as the primary source.**
- A read-only API count on 2026-09-28 found 276 binary and 109 numeric questions opened on or after 2026-07-01
  and resolved by 2026-09-28: 91 `summer-futureeval-2026`, 6 `metaculus-cup-summer-2026`, 179 with no
  tournament tag.
- The API returned `resolution: null` for every resolved question checked with the bot token (7 posts across
  tournaments, including 45153, whose outcome is known to be YES). Outcomes would have to be entered by hand.
- These questions also lack a workspace (section 1).

The Metaculus family is therefore secondary: only the recall probe and the instrument's text-domain calibration,
and only if the owner can supply the outcomes (open question 1).

**Primary source.** Workspace questions built from four keyless public sources:
- FRED CSV: 10-year yield, EUR/USD, WTI, S&P 500, VIX, gold;
- Open-Meteo archive: daily maximum temperature and precipitation for 8 cities;
- USGS FDSN earthquake counts;
- Wikimedia pageviews: 6 articles.

That is about 25 series. The templates, all binary:
- **direction**: the last value published on or before `T+h` is strictly greater than the last on or before
  `T`;
- **touch**: the series exceeds `c` on any published date in (`T`, `T+h`], where `c` is the maximum over the 90
  days before `T` or the nearest round number;
- **window mean**: the mean over (`T`, `T+h`] is above the mean over the `h` days before `T`;
- **count**: at least `k` qualifying events in (`T`, `T+7d`], where `k` is the median of the weekly history.

The horizons are 7, 14 and 28 days, and the forecast dates are 8 Mondays from 2026-07-06 to 2026-08-24.

**Frozen selection rule** (`build_bank.py`, seed 22). A candidate is kept only when its history-only base rate
(the true resolver over past windows ending before `T`) lies in [0.2, 0.8]; this rule never looks at the
outcome. The bank keeps at most one question per (series, `T`), and at most 2 per series in the sealed set, and
is then drawn stratified by source and template. It is split into:
- calibration: `T` in July, 40 questions;
- sealed: `T` in August, 120 questions;
- reserve: 40 questions, drawn only by the re-estimation rule below.

The task file and the resolutions file are both pinned by sha256 in the card before phase A. Binary only: CRPS
for numeric questions needs a distribution output and is deferred.

**Variance, from the pastcast ledgers** (6 MiniBench questions, `probe/ledger_*.jsonl`):

| Quantity | Value |
|---|---|
| Per-question Brier, Claude arm (**model was `fable`, not Sonnet 5**) | mean 0.083, SD 0.063 |
| Per-question Brier, Nemotron free | mean 0.087, SD 0.074 |
| Paired difference, Claude - Nemotron (medians of 5) | mean -0.004, SD 0.068 (log score: SD 0.159) |
| SD of p across the 5 samples of one question (Claude) | 0.00-0.047 |
| Same-arm Brier difference between two single samples, RMS (fixed prompt) | 0.029 |
| 95% CI of any SD estimated from n=6 | 0.62x to 2.45x the estimate (0.068 → 0.042-0.167) |

**Planning SD.** `σ_d² = 2σ_w² + σ_int²`.
- σ_w, the run-to-run noise in one arm: at least 0.021 (the fixed-prompt 0.029 / √2). An agent trajectory
  varies more, so the plan assumes σ_w = 0.045 (p SD about 0.05 at |p−o| about 0.45).
- σ_int, the treatment-by-question interaction: bounded above by the cross-model 0.068; a harness variant of
  one model is assumed at 0.03.
- Result: σ_d = √(2·0.045² + 0.03²) = **0.070**.

Pairing is what makes this affordable: unpaired, with a per-question Brier SD of about 0.15 at base rates of
0.2-0.8, the same Δ would need about 700 questions per arm.

**N** = ((z_α + z_β)·σ_d / Δ)², one-sided α = 0.05, power 0.80, so z_α + z_β = 2.487:

| σ_d \ Δ | 0.01 | 0.02 | 0.03 |
|---|---:|---:|---:|
| 0.05 | 155 | 39 | 18 |
| 0.07 | 303 | **76** | 34 |
| 0.10 | 619 | 155 | 69 |

The assumed effect is Δ = 0.02 Brier. That is about the gap between leading LLM forecasters and
superforecasters on public benchmarks, and a process change worth adopting should reach it. Anything smaller
is not a useful gain at this cost.

The sealed set's size follows from this: N = 120 gives 93% power at σ_d = 0.07 and 71% at 0.10. Two rollouts
per arm would cut σ_d to 0.054 but double the cost, so one rollout per arm on more questions is better.

**Re-estimation rule.** Phase A runs 20 calibration questions twice with the incumbent, which estimates σ̂_w.
Then:
- if (2.487·√(2σ̂_w² + 0.03²)/0.02)² > 120, draw the reserve up to that value, at most 160 in total;
- the rule uses only incumbent-versus-incumbent variance, so it is blind to the treatment effect;
- the reserve is never used after phase B starts.

## 5. Arms, schedule, budgets, cost

**Which change goes into phase B.** This rule is fixed now, because card 020's outcome and card 021's design
are still pending.
1. The candidates are the harness changes that passed S6 acceptance on code: `delta_in ≥ 0`, `delta_oh ≥ 0`,
   and `max > 0` after the no-change spread is subtracted, on a held-out set that includes the near-transfer
   repository (open question 2).
2. A candidate that changes the task (the hidden-test oracle) is excluded.
3. A candidate whose trigger cannot be stated without code-specific terms is excluded, and the exclusion is
   reported. That exclusion is itself a finding about transfer.
4. Card 021's statement-derived verifier, if it passes step 1, is the primary treatment.
5. At most two treatments are tested, with Holm's correction.
6. If no candidate passes, phase B does not run. Testing an unpromoted change for transfer answers nothing.

**Phase A: domain calibration and positive control** (40 calibration questions).
- Arms:
  - the incumbent (1 rollout, plus a second rollout on 20 questions);
  - a one-shot, no-data comparator: pastcast's `build_prompt` (vendored, sha256 recorded), with
    `claude-sonnet-5` pinned and 1 sample;
  - the scripted `gold` forecaster;
  - the recall probe on all 200 questions plus the 20 pre-cutoff questions.
- **Gates** (all must pass before phase B):
  1. committed in at least 90% of incumbent runs;
  2. the process is exercised: median responses of at least 4, and at least one `run` in at least 60% of runs;
  3. the harness beats the one-shot by at least 0.02 Brier (paired point estimate). If data and process do not
     help, process changes cannot show transfer here;
  4. leakage checks clean;
  5. the incumbent is no worse than `gold` by more than 0.02.

  A failed gate stops the card and is reported as a finding about the domain.

**Phase B: transfer test** (120 sealed questions).
- Arms: the incumbent and the selected change(s), optionally with arm C (section 7).
- 1 rollout each, arm order seeded per (question, rollout) with seed 22, `rollout-major`.
- Sampling cannot be seeded: Sonnet 5 rejects sampling parameters. The seeds fix the bank and the arm order.

**Budgets per run.** 12 responses, 15 model attempts, 600 active seconds, 80,000 context bytes, 4,096 max
tokens, command timeout 120 s, 1,200 s invocation wall time. The stop rules are the plan's 5.3 rules (2 retries,
3 consecutive failures), plus the leakage and network stops above and `model_pin_violation`.

**Cost at CLI list price.**
- Measured on 1,109 calls from cards 007 and 013: $0.055 per call and $0.85 per run on average (15.4 calls per
  run). Card 007 alone: first calls about $0.007 (median); all calls $0.041 (median) and $0.099 (p90).
- A forecast context grows more slowly. The planning figure is $0.03 per response, so about $0.25 per run
  (p90 about $0.50).

| Item | Runs/calls | Estimate |
|---|---|---:|
| Phase A incumbent (40 + 20) | 60 runs | $15 |
| One-shot comparator; recall probe (220); smoke/controls | 40 + 220 + 3 calls | $4 |
| Phase B, 2 arms × 120 | 240 runs | $60 |
| Verifier construction (only if 021 is the treatment) | 120 calls | $6 |
| Arm C, intuition instrument (optional) | 120 runs | $34 |
| Reserve growth to 160 (if triggered) | ≤ 80 runs | ≤ $20 |
| **Total** | | **$79 (phase A + two arms) to $139 (every option); cap $150** |

**Wall time.** About 2 minutes per run serialised (card 007: 3.8 minutes per 20-response code run), so phase B
takes about 8-12 hours on the host, one run at a time, at idle priority.

## 6. Evaluator, scoring, acceptance

- **Primary endpoint.** `D` = mean over sealed questions of (Brier_treatment − Brier_incumbent); negative is
  better. The 95% CI comes from a cluster bootstrap over series (10,000 resamples). A two-way (series × `T`)
  version is reported as a sensitivity analysis, because market series share one realised week.
- **Decision rule** (pre-registered, applied once):

  | Verdict | Condition |
  |---|---|
  | **Transfers, with gain** | one-sided 95% upper bound of D < 0 |
  | **Transfers, no harm** | upper bound < +0.01 (non-inferiority margin), and the commitment rate is not more than 5 points lower |
  | **Harms** | lower bound > 0 |
  | **Inconclusive** | otherwise |

  Non-inferiority power at a true D of 0 is only about 47% at N = 120. A "no harm" verdict is therefore likely
  only when there is a small real gain, and the report must say so.
- **Vacuity check** (reported before the verdict). The treatment must have fired in at least 20% of its runs:
  `check()` called, or the nudge delivered. Below that, the verdict is "not exercised", not "does not
  transfer".
- **Secondary measures.**
  - log score (same rule, margin 0.04 nats);
  - commitment rate;
  - reading agreement (the counterpart of a wrong fix);
  - responses, seconds and list-price cost per question;
  - calibration: a reliability table by quintile and ECE;
  - Brier skill against `gold` and against the one-shot comparator.
- **Across domains.** Acceptance and Brier are not in the same units, so the report states the standardised
  effect size (mean/SD) of the code-side delta and of D side by side. It never states a "transfer ratio".
- **Scorer check.** `score_forecasts.py` must reproduce the pastcast ledgers' 0.0832 and 0.0870 from
  `results.json` as a unit-test fixture.

## 7. The intuition instrument

**What it is.** Each tool call may carry a prediction, `expect`, with a `confidence` between 0.5 and 1.0. The
harness scores it against the observation itself, without a judge, because only predictions of these kinds are
allowed:
- `exit_code`: zero or non-zero;
- `contains`: the result contains a given string;
- `count_range`: number of search hits or test failures;
- `number_range`: a number printed by `run`;
- `file_exists`.

`claude -p` returns no logprobs, so this verbalised, checkable prediction is the only source of surprise. A
free-text expectation is optional and scored only post hoc, on a labelled subset.

**Per-step measures.** Hit or miss, and the Brier score of the stated confidence. A *surprise* is a miss at
confidence ≥ 0.8.

**Per-run measures.**
- prediction Brier;
- surprise rate;
- *unresolved surprise at finish*: a surprise on a check run after the last deliverable edit, followed by
  `finish` with no later hit of the same kind;
- calibration slope.

Predictions that are trivially right (for example, "tests fail before the fix") inflate hit rates, so every
measure is also reported per kind, and for *informative* steps only: checks after an edit, and computed
numbers.

**(1) As an observational, grader-free measure.** The measure itself needs no grader; its predictive value
must be validated against the grader once per domain.
- **Step 0: retrospective, no agent runs.** The existing code trajectories (cards 007, 019, 013, 020: about 144
  runs, about 35-45 rejected) already carry implicit predictions in `content` ("this should now pass").
  - Extract them with a labeller (rules plus the S6b classifier). S6b showed Jev misses hypotheses carried
    between turns, so Claude spot-checks 50.
  - Pre-registered hypothesis H1: an unresolved surprise at finish predicts rejection with odds ratio ≥ 3, and
    run-level prediction Brier predicts rejection with AUC ≥ 0.65.
  - Precision: with about 40 failures, the AUC's standard error is about 0.05, which separates 0.70 from 0.50.
  - This costs only the labeller's calls, and it decides whether the instrument is worth building.
- **Step 1: explicit instrument.** It is a prompt and schema change, so it is itself a treatment. It needs a
  reactivity arm: incumbent against incumbent + `--predict structured-v1`, on code first (card 007's
  evolution set, E4 size).
  - Gate: at least 90% of tool calls carry a parseable prediction, and acceptance is not lower.
  - In 022 it is arm C, instrument on, same questions.
  - H2 (forecasting): the Spearman correlation between run-level prediction Brier and forecast Brier is
    ≥ 0.23, which N = 120 detects at 80% power.
  - H3 (domain generality): the calibration slope of informative predictions differs between the domains by
    less than 0.2.

**(2) As a treatment.** Surprise-triggered re-planning and verification.
- On a surprise, the harness adds one fixed message ("Your expectation … did not hold; observed … State what
  this changes before continuing."), at most 2 per run.
- Variant: `finish` is rejected once while there is an unresolved surprise.
- The trigger is self-generated, like card 013's self-chosen checks, which did not help, so the prior is
  modest.
- It is an E4 candidate on code (after step 1). It enters 022 only through section 5's rule, like any other
  change.

**Verdict.** As an instrument it is cheap, and it can be falsified quickly on data that already exists: run step
0 first. As a treatment it is plausible but unproven, and it is not part of this card until code selects it.
The risks are reactivity, overconfident verbal confidence, and hit rates dominated by trivial predictions. The
design above measures each of these rather than assuming it away.

## 8. Build plan (after approval; nothing here is built)

**harnessExperiment, slice 1** (domain, controls, scorer). About 1,650 lines including tests; 1-2 days for
one Opus implementation agent in a worktree.

| File | Change | Size |
|---|---|---:|
| `experiments/forecast_tasks/sources.json` | series list: source URL template, units, publication rule | data |
| `experiments/forecast_tasks/resolvers.py` | true resolvers per template, shared by builder, `gold`, and the reading-agreement check | 150 |
| `experiments/forecast_tasks/build_bank.py` | fetch (network, build time only), cut at `T`, generate, base-rate filter, seeded draw; writes `tasks.forecast.json` and the sealed resolutions outside the checkout | 350 |
| `experiments/forecast_tasks/evaluate_forecast.py` | in-run validity check (`committed`) | 100 |
| `experiments/forecast_tasks/score_forecasts.py` | Brier/log, paired table, cluster bootstrap, decision rule, calibration, reading agreement | 250 |
| `experiments/forecast_tasks/probe_recall.py`, `oneshot_forecast.py` | recall probe; one-shot comparator (vendored pastcast `build_prompt`, sha256 recorded), both through `claude_cli.py`'s isolation and model pin | 200 |
| `experiments/p6_pilot/run_pilot.py` | `kind: forecast`: materializer from the snapshot (asserts no row after `T`), forecast instructions hashed through the contract, evaluator selection, scripted `gold`/`noop`/`gamer`/`peeker` for the kind | 200 |
| `experiments/session_harness/cards/022.json`, `SCHEMA.md` row, markdown card | the run card, split into phases A and B | - |
| `tests/test_forecast_bank.py`, `test_forecast_runner.py`, `test_forecast_scoring.py` | details below | 400 |

What the three test files cover:
- the builder is deterministic (sha256);
- no snapshot row is after `T`, checked as a property over the whole bank;
- the workspace holds no resolution;
- the scorer reproduces pastcast's 0.0832 and 0.0870;
- code-task protocol hashes are unchanged;
- the evaluator's pass and fail cases.

**Slice 2** (after card 021 or 014 decides). About 200 lines:
- the verifier module gets a domain slot, `statement-resolver:3`: the verifier invocation sees the statement
  and the data schema, and `check()` returns disagreement counts;
- `SourceEditTracker` generalised to "deliverable paths", for the nudge's counterpart.

**Slice 3** (instrument; after step 0 is positive). About 400 lines:
- the `expect` field in the reply schema (adapter plus controller);
- the scorer, journal events and run-level measures;
- the `--predict structured-v1` flag, hashed as a treatment.

**metac-bot.** No change is required. `pastcast.py`'s prompt is vendored with its sha256, and `score.py`'s
arithmetic is re-implemented and regression-tested against its ledgers. Two problems were found there and not
fixed, since that repo was out of scope:
- `score.py` crashes on the Windows cp1252 console at the İ in question 45153, so its summary line is lost;
  `PYTHONIOENCODING=utf-8` avoids this;
- the pastcast "Claude" ledger is `fable`, not Sonnet 5.

**Offline, before any model call:**
- bank build (public data, no model);
- all tests;
- the `gold`/`noop`/`gamer`/`peeker` controls in OCI;
- the scorer regression;
- an egress check: `run python -c "urllib.request.urlopen('https://example.com')"` must fail.

**Smoke.** 1 incumbent run, 3 recall probes and 3 one-shots with the pinned model; under $1.

**Where it runs.** On the host's OCI backend, recommended, because it is the only backend with a tested
workspace-only, no-network boundary. The load is light: the model calls are remote, and the commands are
standard-library Python on small CSVs, serialised under the live-run lock at idle priority. This does not
conflict with the rule that CPU-heavy work goes to the cloud.

The cloud VM (`campaign.py run` unchanged, `trusted-local` with `vm-sandbox`) is acceptable only for a
restricted variant:
- a single forecast date `T` per campaign, so that no file on the VM holds data after `T`;
- per-question snapshots only;
- resolutions never on the VM, with scoring done locally after pulling the results branch;
- a `setup_cloud.sh` probe that `unshare -rn true` works, and the `run` tool wrapped in it; without it, no
  cloud run.

## 9. What this design did not do

- It made no model or API call of any kind.
- It did not verify Sonnet 5's training cutoff from a primary source; the date bound rests on the skill's model
  table being cached on 2026-06-24.
- It did not confirm that the OCI image's Python standard library is all a forecast needs, or that `unshare`
  works on the cloud VM.
- It did not fetch any time series or build any question, so the claim that the [0.2, 0.8] filter leaves 200
  questions is unverified.
- It did not estimate per-response cost on a forecast context: $0.03 is extrapolated from code-repair calls.
- It did not get Metaculus outcomes: the API hides them from the bot token.
- It did not examine card 020's partial results (10 of 32 runs on `cloud-results-020`) beyond their existence.
- It did not size the near-transfer repository bank. The generator is sqlparse-specific as written; retargeting
  it to another repository in the P6 task list is a separate slice.

## 10. Open questions for the owner (recommended answer first)

1. **Replace Metaculus text questions with workspace time-series questions as 022's bank?** *Yes.* Text
   questions cannot trigger any process change. Keep Metaculus only for the recall probe, and only if you can
   supply outcomes, since the API hides them from the bot token.
2. **Require near transfer (mutation repair on a second repository) before 022's phase B?** *Yes.* It is the
   held-out set S6 acceptance needs anyway, and a change that does not survive another codebase will not
   survive another domain.
3. **Run 022 on the host's OCI backend rather than the cloud VM?** *Yes.* It is the only tested boundary that
   blocks both the network and reads outside the workspace, and the load is light. The cloud is acceptable
   only in the single-`T` variant.
4. **Minimum useful gain Δ = 0.02 Brier, non-inferiority margin 0.01, sealed N = 120 (up to 160 by the blind
   re-estimation rule)?** *Yes.* It is affordable (about $60-80 for phase B), and 93% power at the planning
   SD.
5. **Order for the intuition instrument: retrospective step 0 now, explicit instrument on code next, arm C in
   022 only if step 1 passes?** *Yes.* Step 0 needs no agent runs and falsifies the idea quickly, and arm C adds
   about $34 only once the instrument has shown it is usable.
