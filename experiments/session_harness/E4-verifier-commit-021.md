# E4 verifier + commitment 021: a realistic check() and a mid-budget commitment prompt, paired, on the cloud VM

Date: 2026-09-29 (UTC)  
Status: proposed; the idea was approved by the owner on 2026-09-29 ("yes, approved"); running it needs the owner's
approval of this card (pasting [`RUN_IN_CLOUD-021.md`](../cloud/RUN_IN_CLOUD-021.md)) and the VM smoke  
Stage: S6 (tool use + agent loop) on cloud compute. Machine-readable card: [`cards/021.json`](cards/021.json).  

## Where we are

| Evidence | Finding |
|---|---|
| Cards 007 (host) and 019 (cloud): incumbent calibration, 20 tasks x 2 | 32/40 and 31/40; five hard tasks: 001, 022, 032, 057, 061 |
| Hard-task incumbent over cards 007, 019, 020 | **6 of 30** accepted: 001 2/6, 022 3/6, 032 0/6, 057 0/6, 061 1/6 |
| How those 24 rejections ended | **16 at the response budget** (`model_call_limit`), 8 by a wrong `finish` |
| Card 020 (cloud): incumbent vs + hidden-test oracle (`check()`, counts only, 3 calls) | hard 3/10 vs 4/10; easy 6/6 both (oracle arm ~20% fewer replies). Oracle arm: 0 wrong finishes (incumbent 2); the 5 hard runs that never called `check()` all hit the budget with no candidate fix |
| Observation audit (`origin/wt/observation-audit`) | 17 of 22 hard rejections **saw the mutated line**; only 057 is a locating failure |
| Rollout noise (card 020) | rollout 1: oracle 3/5 vs incumbent 0/5; rollout 2: 1/5 vs 3/5 |

Verification removes wrong finishes, but the dominant hard failure is running out of budget without committing to a
hypothesis and a fix, usually after the model has already looked at the fault.

## Hypothesis

On the five hard tasks, a bundle of two treatments raises acceptance over the incumbent:

1. **a realistic verifier**: `check()` with card 020's interface, backed not by the hidden tests but by one
   reproduction test per task that a separate model call wrote in advance from the problem statement and the
   pre-edit source only;
2. **a mid-budget commitment prompt** (the owner's "intuition" idea, first form): at half the response budget the
   model states its leading hypothesis (file, function, line, mechanism) and a concrete prediction of what one
   specific observation will show, makes that observation, and records whether it matched; on a mismatch it records
   the surprise and revises. The check tool is then the verifier of the resulting fix.

Card 020's oracle is the ceiling for the verifier half; how much of it a realistic verifier can reach is measured
per task by the frozen test's validity (below), independent of the campaign's noise.

## Design decisions

### Arms: two (incumbent, verifier-commit); attribution deferred

`incumbent` is card 020's arm unchanged (same planned hash per task on the VM, `cace7960248d` for 001 on this
checkout), so card 020's ten hard incumbent runs are an extra, unpaired reference. `verifier-commit` adds
`--verifier repro-test:3 --verifier-manifest experiments/session_harness/verifiers/021/manifest.json --nudge commit`.
Both arms keep `--cli-reply-recovery lenient-json+second-turn-on-retry`, trusted-local in the VM (`vm-sandbox`), the
model pinned as `claude-sonnet-5`, CLI 2.1.284.

Why not verifier-only and commit-only arms as well: with one success in five per hard run and $60, every arm split
halves the runs per comparison. Four arms at 5 tasks x 2 rollouts is 40 hard runs (about $50) with 10 runs per arm,
enough to detect nothing (below). The bundle is the owner's idea as one mechanism (the commitment produces a fix, the
verifier checks it), so the card asks first whether the bundle moves the hard block at all. Each half leaves its own
trace in every treatment run, which attributes without arm contrasts: the commitment record (was a hypothesis
committed after the nudge, did it name the mutated function, was a fix made after it) and the verifier record (checks
used, counts, what followed a failing count, finishes with a failing last check). If the bundle gains, card 022
splits it; if it does not, splitting it is moot.

### Realistic verifier construction

- **Who writes the test.** One headless `claude -p` process per task
  ([`repro_verifiers.py generate`](../p6_pilot/repro_verifiers.py)): the card's pinned model, a fresh context, the
  adapter's isolation flags (`--safe-mode --setting-sources "" --strict-mcp-config --disable-slash-commands
  --no-session-persistence`) with `--tools Read,Glob,Grep` in place of `--tools ""`, `--permission-mode dontAsk`, and
  the working directory set to a temporary copy of the **pre-edit workspace** outside the repository: the tree the
  agent starts from (mutation applied, test roots removed, no git history). It sees the problem statement and that
  tree; never the hidden tests, the gold patch or the mutation. Every attempt is checked like an agent attempt (init
  tools exactly Read, Glob, Grep and StructuredOutput; no MCP; no API key from the environment; the model pin in
  init, messages and `modelUsage`), and every Read/Glob/Grep call that named a path outside the copy and was not
  refused stops generation (`read_outside_workspace`). Each attempt's stream is kept for review.
- **Gold-free acceptance of a test, with feedback.** The harness runs the returned file on a copy of the same
  pre-edit tree through [`run_repro_test.py`](../p6_pilot/run_repro_test.py) (the path `check()` uses). The file is
  frozen if it compiles, collects at least one case without a collection error, and **at least one case fails** (the
  reported bug is present in that tree). Otherwise a fresh call gets the file, its counts and the tail of pytest's
  output, up to 3 calls per task. This is what a real deployment could do (reproduce before fixing); no step reads the
  gold tree. If no attempt qualifies, the task's verifier is **unavailable**: `check()` is still offered with the
  same schema and returns an error without running anything or spending a call.
- **Per task, cached; not per run.** Per-run generation is the more realistic deployment, but it would add a second
  random draw (the verifier) inside every run, which the arm comparison cannot separate from the agent's own
  variance, and it would cost about 30 more generation calls. A per-task test frozen before the campaign makes the
  verifier a fixed property of the task: every treatment rollout of a task sees the same test, validity is scored
  once per task, and the manifest's sha256 enters the protocol hash. The price: with 5 hard tasks, verifier quality
  varies only between tasks (5 draws), which the report states.
- **What `check()` returns.** Card 020's interface exactly: no arguments, `{"failing": N, "passing": M,
  "calls_left": K}`, 3 calls per run, never the test or its output; passing counts the test's cases that pass,
  failing the others of the cases collected on the pre-edit tree (a broken package counts every case as failing).
  The test runs on a scratch copy outside the workspace, with the bundle's own empty pytest ini and `--noconftest`, so
  a conftest or pytest configuration the model writes cannot rewrite the counts. The schema tells the model that the
  test was written in advance from the statement, is not an acceptance test, and **may itself be wrong** (true, and
  the realistic condition).
- **Validity, the key diagnostic** ([`repro_verifiers.py score`](../p6_pilot/repro_verifiers.py)): each frozen test
  through the `check()` path on the mutated tree and on the gold tree. **Valid** = at least one case fails on the
  mutated tree and every case passes on the gold tree. A valid test gives the oracle's verdict at both ends (unfixed,
  fixed), so the share of hard tasks with a valid test bounds the fraction of the oracle's gain a realistic verifier
  can carry; an invalid one can mislead (a test that fails on gold tells the model a correct fix is wrong). After the
  campaign, [`repro_verifiers.py agree`](../p6_pilot/repro_verifiers.py) runs each frozen test on a copy of every
  run's final workspace (both arms) against that run's acceptance: a confusion matrix of the realistic verdict and the
  hidden tests' on about 36 real candidate trees, not only the two endpoints. Validity is never used to choose,
  regenerate, edit or drop a test, and is scored only after the campaign.
- **Leakage and authority.** On trusted-local the model's commands can read the VM's filesystem, including
  `experiments/session_harness/verifiers/021` (the frozen tests) and the task clone. The test is not hidden from a
  determined reader, only not shown; reads of the verifier directory are reported separately in the trajectory review
  (card 020's review rule, extended).

### Commitment prompt

- **Surface.** `--nudge commit` ([`reticle/runtime/nudges.py`](../../reticle/runtime/nudges.py), `commit-nudge-v1`),
  on the midpoint-nudge machinery (`--nudge-fraction`, default 0.5; one harness message after the latest tool results,
  journaled as `harness_message`, marked in the context manifest, once per run across resumes). Unlike
  `midpoint-nudge-v1` it fires **whether or not a source file was edited**: the commitment is also the card's
  instrument, and conditioning it on "no edit yet" would leave the prediction record missing exactly in the runs that
  had committed to a fix.
- **Text** (hashed; the share follows the fraction): "Half of the response budget is spent. Commit to your leading
  hypothesis now: call commit_hypothesis with the file, function, line and mechanism you believe cause the reported
  behavior, one specific observation you will make next (a command or a read), and exactly what it will show if you
  are right. Make that observation, then call record_observation with what it showed and whether it matched; if it
  did not, say what surprised you and revise the hypothesis. Then edit the most likely cause and verify the fix."
  It does not name `check()`, so the same text serves a commit-only arm later.
- **Structured fields** ([`reticle/tools/commitment.py`](../../reticle/tools/commitment.py), `commitment-tools-v1`):
  `commit_hypothesis(file, function, line, mechanism, observation, prediction)` and
  `record_observation(observed, matched, surprise, revised_hypothesis)` (surprise required when `matched` is
  false), offered from the first request so the tool list never changes mid-run. Neither acts on the workspace. Each
  call is journaled (`hypothesis_commit`, `hypothesis_observation`) with its fields, whether it came after the nudge,
  the workspace revision, and for an observation the tool calls made since the commitment it answers.
- **The grader-free instrument** ([`score_commitments.py`](score_commitments.py)): per run, the prediction status
  (none, unchecked, matched, mismatched) against acceptance, and offline (from the task file's mutation fields,
  never shown to a run) whether the last commitment named the mutated file and function and how far its line was.
  Does a failed or absent prediction predict rejection? This is descriptive at this sample size.

### Tasks

The five hard tasks (card 007's evolution set, the only tasks the incumbent fails) with 3 rollouts per arm, and card
020's three easy tasks (025, 034, 040; 12 of 12 accepted in card 020) with 1 rollout per arm as a harm check.
Scripted gold and noop controls under the treatment arm on 001 run first (after verifier generation, because a
treatment run needs its task's manifest entry).

Why no tasks from the 56 unused sqlparse mutations: 15 of card 007's 20 randomly chosen tasks were solved twice, so an
unused task is probably easy, and knowing which ones are hard needs a screening pass (about 56 incumbent runs, roughly
$15-20) that this budget cannot carry next to the comparison. Five tasks is the card's largest limit (task-level
effects, 5 verifier draws). A screening card to build a larger hard pool is the natural next step if card 021 shows
anything.

### Rollouts, power, and what the card can show

Hard block: 5 tasks x 3 rollouts x 2 arms = 30 runs (15 per arm), seeded arm order per unit (seed 21),
rollout-major. Power by simulation (one-sided Fisher exact at 0.05, runs treated as independent, which task
clustering makes optimistic), incumbent at 0.20:

| Treatment rate | 15 v 15 (this card) | 25 v 15 (with card 020's incumbent runs) | 20 v 20 |
|---|---|---|---|
| 0.35 | 0.13 | 0.19 | 0.17 |
| 0.50 | 0.39 | 0.52 | 0.54 |
| 0.60 | 0.61 | 0.76 | 0.76 |
| 0.70 | 0.80 | 0.91 | 0.90 |

Stated honestly: **no affordable design has power for a plausible gain** (+10 to +20 points). This card has an even
chance only for a large one (0.2 to 0.6), which card 020's oracle, a strictly stronger verifier, did not show (3/10 to
4/10). What it can show: a large gain; harm on the easy block; verifier validity per task (deterministic, no sampling
noise); the realistic verdict's agreement with acceptance on real candidate trees; and the mechanism counts, which
occur in most hard runs (budget exhaustion is 16 of 24 incumbent rejections; a drop from 0.53 to 0.2 has about 0.44
power at 15 v 15, 0.59 with card 020's runs). What it cannot show: a modest gain, which half of the bundle caused a
gain, or anything beyond sqlparse.

### Budgets and cost

Per run as card 020: 20 responses, 24 attempts, 1200 active seconds, 80,000 context bytes, 4096 max tokens, pytest
timeout 600 s. Campaign: 36 runs, at most 1000 model attempts.

| Item | Estimate (CLI list price) | Guard |
|---|---|---|
| 30 hard runs | ~$36 (card 020: ~$1.2 per hard run by token share; up to ~$1.8) | campaign spend guard $54 |
| 6 easy runs | ~$1.5 | (same) |
| Verifier generation, 8 tasks, 1-3 calls each | ~$2-4 | $0.60 per call (CLI `--max-budget-usd`), $6 in total |
| This session's live smoke | measured below | ~$1 |

Expected total about $40-42; worst case within $60.

### Stop rules

Card 020's, plus: never regenerate, edit or drop a frozen test after generation (whatever its validity); an
unavailable verifier stays unavailable; a generation attempt with an isolation, login, model-pin or out-of-workspace
problem stops generation; trajectory review reports reads of the verifier directory.

### Decision rule

Primary: hard-block acceptance, verifier-commit against incumbent, 15 paired runs each; one-sided Fisher exact at
0.05, with Wilson intervals and per-task outcomes. Mechanism, reported per arm: runs ending at the budget; wrong
finishes; checks used and what followed a failing count; validity per task and acceptance split by valid and invalid
verifier; the realistic verdict's agreement with acceptance on final trees; the commitment record against acceptance.
Easy block: any treatment-arm rejection is reported as possible harm. Reading:

- a hard-block gain, valid verifiers, commitments that name the mutated function: the bundle works; card 022 splits
  it (verifier-only, commit-only);
- no gain and mostly invalid verifiers: the realistic verifier is the bottleneck, not the model;
- no gain, valid verifiers, fewer budget exhaustions: the model now commits, but to wrong fixes (a diagnosis limit);
- no change in budget exhaustion: the prompt does not produce commitment.

The arm is never promoted to incumbent on this card alone.

## Implementation (all opt-in; every existing card plans byte-identically)

| Piece | Where | Hashed as |
|---|---|---|
| `check()` over a frozen test | [`reticle/tools/repro_verifier.py`](../../reticle/tools/repro_verifier.py) (`ReproTestVerifier`, on `HiddenTestOracle`'s scratch-copy path, now with a `_counts` hook), [`run_repro_test.py`](../p6_pilot/run_repro_test.py) | `treatments.verifier`: name, `repro-test-verifier-v1`, max_calls, the runner's and the manifest's LF sha256 |
| Test generation, validity, agreement | [`experiments/p6_pilot/repro_verifiers.py`](../p6_pilot/repro_verifiers.py) (`generate`, `score`, `agree`) | the manifest records the generator (version, model, CLI, prompt hashes, limits) |
| Commitment nudge | `CommitmentNudge` in [`reticle/runtime/nudges.py`](../../reticle/runtime/nudges.py) | `treatments.nudge`: name `commit`, `commit-nudge-v1`, fraction, template, text, tools |
| Commitment tools | [`reticle/tools/commitment.py`](../../reticle/tools/commitment.py) | their schemas, in the offered tools |
| Runner flags | `--verifier repro-test[:K]`, `--verifier-manifest`, `--nudge commit` in [`run_pilot.py`](../p6_pilot/run_pilot.py) | off: nothing changes; `--verifier` with `--oracle` is refused |
| Offline instrument | [`score_commitments.py`](score_commitments.py) | analysis only |

Offline validation (no model): [`tests/test_card021_verifier_commit.py`](../../tests/test_card021_verifier_commit.py):
a scripted reproduction test through the `check()` path fails on the mutated tree (1 failing, 1 passing) and passes on
the gold tree (0, 2); a fix turns the count; the cap holds; a gaming conftest cannot change counts; an unavailable
verifier runs nothing; generation against a stub `claude` sends a blind test back with its counts and freezes the
failing one, refuses isolation and out-of-workspace problems, leaves a task unavailable after the attempts run out,
and scores a valid and an invalid test correctly; `agree` builds the confusion matrix without touching evidence; the
commitment nudge fires once at half budget even after an edit and the model's commitments are journaled; the runner
records, hashes and offers exactly what `model_tool_schemas` lists; an end-to-end gold run with both treatments.

## Live smoke (this session, host, CLI 2.1.284, `claude-sonnet-5`)

*Filled below after the smoke.*

## Reporting

`experiments/session_harness/E4-verifier-commit-021-report.md`; evidence, the verifier manifest, `validity.json` and
`agreement.json` on a `cloud-results-021` branch.
