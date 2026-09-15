# Reticle: durable sessions, replaceable harnesses, fast experiments

Date: 2026-09-15.
Status: current implementation direction; S1 mechanics are delivered and later runtime changes are planned.
Supersedes: [the September 14 plan](IMPLEMENTATION_PLAN_2026-09-14.md), including its
P0-P9 sequence and continuation instructions. That document preserves the implementation
ledger, commit identifiers, wheel checks, and historical experiment decisions.

## 1. Objective and operating rule

Build a dependable session runtime in which different harness policies can be operated
and compared. Find useful improvements through short, discriminating experiments.

The session records what happened. Context is the selected view for one model invocation.
The harness decides how to continue. Execution environments perform work. Separate their
responsibilities and lifetimes, even when they run on one host.

**Fail fast on broken mechanisms; iterate quickly on development tasks; require stronger
evidence before claiming a general improvement.** Do not complete another long substrate
roadmap before observing whether a model can use the interface.

The first research question is narrow: does retaining full recent observations until
context pressure requires reduction improve accepted repairs relative to the current
512/4,000-byte views? This is a hypothesis, not a promised result.

Initial workload: pinned Python repository repairs, plus small behavioral exercises for
history retrieval, context pressure, and interrupted work. Preserve support for human or
incomplete acceptance criteria; passing available tests does not establish every user goal.

Anthropic's April 8 publication separates durable session history from replaceable context
management and execution environments. This plan applies that distinction locally. Its
implementation choices and experiments are proposals, not results established by Anthropic.
[Source: Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents).

### Changes from the prior plan

- Reuse the journal, artifacts, workers, and evidence machinery already implemented.
- Restore useful context and discoverable history before adding cognitive machinery.
- Treat boards, foveation, summaries, and forgetting as replaceable experimental choices.
- Persist task budgets and pending operations across controller replacement.
- Test the actual runner's execution/evaluator boundary, not just isolated components.
- Run model usability experiments alongside implementation as prerequisites become ready.
- Ship one installed session workflow before expanding a program library.
- Search policies only after a competent control and trustworthy evaluator exist.

Non-goals for this sequence: hosted services, distributed scheduling, concurrent controller
swarms, universal memory ontologies, mandatory cognitive phases, automatic cross-session
consolidation, and recreating every historical modality demo.

## 2. Starting evidence

Review baseline: `08871ac3d083bd72b33ac18499d0391c9c9cd20e`; tracked tree was clean before
this documentation change. Review-time offline command:

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests -q
```

Result: 140 tests ran, no failures, three OCI integration tests skipped. This does not
claim fresh validation of OCI boundaries or installed packaging during the review.

Confirmed by review reproductions:

- A 200,000-byte context budget produced a roughly 9,388-byte request for two reads, with
  just 361 bytes of the older result and 3,834 bytes of the newest result visible.
- With 6,000 or 8,000 bytes, the same policy kept the older exchange and omitted the newest
  while reporting `over_budget=false`.
- Two controller invocations on one session with one-call invocation limits persisted two
  model calls; each invocation reported one. No cumulative task limit was enforced.

Other inspected limits:

- `ToolSuite` and `AcceptanceRunner` default to trusted local execution. The P6 runner
  keeps evaluator files beside the workspace without enforcing their inaccessibility.
- `reticle run` uses the legacy harness; its package shim imports root source.
- Workspace revisions scan all files; journal/transcript queries repeatedly read full
  history. Scaling cost is a concern to measure, not a measured performance regression.

The generated larger study reached a success ceiling. Each recent P6 pilot recorded 0/9
accepted with substantial harness/provider interference. Neither demonstrates a clean
harness effect. Existing inspected tasks are development material, not a pristine holdout.

- [Larger-repository experiment](experiments/large_v1/REPORT.md)
- [Pilot 1 audit](experiments/p6_pilot/runs/pilot1-transcript/AUDIT.md)
- [Pilot 2 audit](experiments/p6_pilot/runs/pilot2-transcript/AUDIT.md)

Retain and extend `LocalRuntime`, `EventJournal`, `ArtifactStore`, `TranscriptStore`,
`AgentController`, `ToolSuite`, and `AcceptanceRunner`. Do not rebuild completed work just
to rename it. Old P2-P5 completion is evidence about components, not these new end-to-end gates.

## 3. Architecture and contracts

```text
Task + authority + resource contract
                  |
          replaceable harness
            /           \
   session read API      execution interface
         |                       |
  events + artifacts        task workspace / tools
         |
  context policy -> validated request manifest -> model

Independent evaluator <- final candidate snapshot
```

| Component | Owns | Does not own |
|---|---|---|
| Session | Task, authorized updates, events, artifact references, usage, pending work | A mandatory attention strategy |
| Context policy | Selection, ordering, rendering, optional summaries | Authoritative deletion, authority, evaluator access |
| Harness/controller | Model/tool protocol, dispatch, lifecycle transitions | Essential state available only in process memory |
| Execution backend | Resources, enforced authority, supervision | Provider secrets, journal authority, hidden acceptance inputs |
| Evaluator | Fixed criteria, measurements, final-artifact decisions | Trust in the model's success claim |
| Experiment runner | Assignment, protocol versions, budgets, reporting | Undocumented arm changes or exclusions |

These are logical boundaries. Keep one host and one active controller per session. No
network services or generic plugin framework are required. Extend interfaces for real callers.

### 3.1 Durable, interrogable sessions

Proposed operations, implemented incrementally through the existing package:

```text
open_session(id) -> contract, status, event cursor, usage, pending operations
append_event(expected_sequence, operation_id?, kind, payload_refs) -> event
get_events(after_sequence?, before_sequence?, kinds?, limit, as_of_sequence?) -> page
search_events(query, kinds?, source?, cursor?, limit, as_of_sequence?) -> matches
read_artifact(id, byte_range?) -> bytes or explicit unavailable status
checkpoint() -> reconstruction cursor and workspace identity
```

- Preserve stable IDs, sequence order, source references, and exact observations. Pages
  include a next cursor and explicit truncation. Use a fixed high-water mark across search
  pages so retrieval events do not create an endlessly expanding search.
- Start with positional slices and literal search over authorized action/observation text.
  Return tool, path/source, sequence, status, and snippet; the model must be able to find
  an old action without remembering its output ID. Report search scope and coverage.
- Expose `history`, `search_history`, and session-scoped `read_artifact` tools. Keep current
  `read_output`/`search_output` as compatibility conveniences. Avoid duplicate abstractions.
- Model-visible history excludes credentials, hidden evaluator inputs, and controller-only
  records. Session membership is not universal read permission. Test this authorization.
- Summaries and notes are derived, labeled artifacts citing source versions. They never
  replace source evidence or acquire system-instruction authority merely through pinning.
- Persist later authorized task corrections; they must survive compaction and restart.
- Keep a single event authority. Indexes/checkpoints are rebuildable. Add a cross-process
  writer lock before promising safe controller replacement; reject concurrent owners.
- Retain evidence through evaluation/review. Set explicit storage quotas and report missing,
  redacted, or expired artifacts honestly. Stop before executing work whose evidence cannot
  be recorded. No garbage collection controlled by a context policy.

### 3.2 Pressure-based context control

Add `pressure-recent-v1` as a separate policy. Preserve old policy version semantics.

1. Include task/current authorized instructions, authority, remaining task resources, and
   concise history-retrieval instructions.
2. Reserve a valid representation of the latest assistant/tool exchange, including every
   result's status and retrieval reference. Older exchanges cannot substitute for it.
3. Retain recent observations in full while space permits. No automatic age-based shrink
   to 512 bytes with unused space available for the original material.
4. Under actual pressure, reduce older material first with declared views/omissions. If an
   entire exchange leaves context, retain an indication of omitted history and how to find it.
5. Bound an oversized newest exchange with useful line/byte views. Requested retrieval pages
   receive newest-result priority. Record loops where a retrieved page is immediately hidden.
6. Fit optional pins/summaries after required material. Report overflow; pins cannot displace
   the latest exchange or authoritative contract.

Validate the final materialized request in the controller. If the contract and minimum
protocol-valid latest exchange cannot fit, checkpoint and stop with an explicit
`context_budget_exhausted` reason. Do not send an over-budget request or silently lose feedback.

Each manifest records selected/omitted event ranges, artifact versions, views, message order,
tool schemas, policy version, request hash, and size accounting. Provider adaptation records
the actual submitted request, including reasoning-field transformations.

Keep the deterministic byte limit, clearly named as bytes. Also respect provider context
limits using supported token counting or a documented conservative bound plus output reserve.
Actual usage is separate; bytes/4 is not billed usage. Measure prompt-cache and retransmission
effects instead of assuming shorter context is always cheaper overall.

### 3.3 Durable resources and recovery

Separate task budgets from invocation limits. Persist model attempts, successful responses,
tool work, active elapsed time, deadline semantics, and monetary usage. Define whether paused
time counts toward each deadline. Reserve final evaluation resources separately.

- Admit work against a reservation before dispatch; reconcile usage afterward. Record failed
  HTTP attempts separately from model turns. Retries do not consume another run's allocation.
- Unknown billing remains unknown. Keep conservative reservations for ambiguous attempts
  until reconciled when enforcing a hard monetary cap.
- Resume cumulative consumption with monotonic invocation/attempt/action IDs. Starting a
  new controller never silently renews a task budget.
- Persist model request intent and returned responses before executing actions. A recorded
  response resumes at its first uncompleted action, rather than being regenerated.
- Repair a crash between action-outcome persistence and transcript publication without
  repeating a completed mutation. Deduplicate bookkeeping by operation ID.
- Classify pending work as known complete, known not started, or unknown external outcome.
  Reconcile observable state; replay only with justified idempotency. Otherwise stop with
  `needs_reconciliation` and actionable evidence. Never infer exactly-once external effects.
- Acquire/release one session writer lock across controller lifetimes. Preserve torn-journal
  evidence when repairing a tail. Use existing conservative recovery mechanisms where possible.

Keep controller stop reason, acceptance outcome, and resource status separate: an interrupted
run may leave an accepted artifact, and a normal finish may leave a rejected artifact.

### 3.4 Actual execution and evaluator boundaries

Use existing OCI execution for candidate commands in benchmark runs. Provision a pinned
task-compatible image/environment and map guest paths/interpreters. Do not pass host Windows
interpreter paths to the guest. A candidate sees only its workspace and declared resources,
not the journal, secrets, fix repositories, evaluator inputs, or other runs. Disable task
networking for the first repair study. Trusted-local remains explicit for trusted work;
an unavailable isolated backend never silently falls back.

Evaluate a candidate snapshot in a separate invocation with fixed inputs. Candidate code
remains untrusted during test execution and may share a process with grader code. Use read-only
fixed inputs, supervisor-owned reporting where practical, expected coverage checks, and
targeted tampering probes. Host isolation alone does not establish grader integrity.

Retain golden/noop/breaker/gamer controls through this real path. State the residual threat
model; do not claim arbitrary adversarial grader resistance from a conftest regression test.

Define source revision scope separately from full execution snapshot identity. Cache files
must not masquerade as relevant source changes. Final acceptance still covers all declared
deliverables and is invalidated by applicable subsequent mutations.

## 4. Delivery: small slices with early experiments

Stage IDs below replace P0-P9. Engineering and empirical gates are separate. Model smokes
can run before every production feature is complete if their actual prerequisites hold.
An unmet unrelated stage is not a reason to delay a safe, discriminating experiment.

### S0 - One current plan (this documentation change)

Preserve the old ledger; label the older architecture/board/README claims historical; publish
this plan and experiment protocol. No runtime implementation is claimed by this stage.
Exit: links resolve and old continuation instructions no longer direct new work.

### S1 - Useful context and history discovery

Files: `reticle/context/baseline.py`, `reticle/runtime/events.py`,
`reticle/runtime/observations.py`, `reticle/tools/primitives.py`, controller validation,
and focused context/controller/paging tests. Add a session query module if needed.

Deliver in independent slices:

- **S1a:** Reproduce the review failures; add the pressure policy and latest-exchange
  protection while retaining the named legacy renderer. Run experiment E1 immediately.
- **S1b:** Add history/search/authorized artifact tools. Prove discovery after full exchange
  eviction and restart without a remembered handle. Run E2 as soon as its fixture is isolated.
- **S1c:** Add checkpoint-based context comparison output: exact visible/omitted material,
  request size, policy identity, and retrieval entry points. This is diagnostic replay only.

Tests cover large-budget full retention, small-budget latest continuity/explicit stop,
multi-tool pairing, huge arguments/results, UTF-8 long lines, pin overflow, later user
corrections, cursor stability, missing artifacts, and denied controller-only history reads.

Exit: mechanical gates pass; actual model usability is separately recorded as passed,
failed, or unrun. A scripted model cannot satisfy the behavioral gate.

### S2 - Reliable continuation and isolated experiment path

Depends on S1 mechanics; boundary work may overlap S1. Files: runtime controller/session/
contracts/events, execution controller/backends, acceptance, and P6 runner. Add a small
`runtime/budgets.py` ledger; reuse existing stores and supervised execution.

- **S2a:** Persist task/resources, writer ownership, and crash transitions. Coordinate native
  file edits and command mutations under the same workspace mutation boundary. Run E0 recovery probes.
- **S2b:** Wire pinned OCI environments into actual candidate/evaluator runs. Run no-API
  pipeline controls and boundary probes before any capability comparison.

Gates: exhausted-task resume makes no extra provider call; crash points before/after dispatch,
outcome persistence, and transcript publication produce no duplicate known mutation; ambiguous
effects stop visibly; a second controller is rejected and a replacement can take ownership;
candidate cannot access sibling paths, harmless credential sentinels, or network; golden
accepted and noop/breaker/known gamer rejected; caches do not falsely report source edits.

Skipped OCI tests do not satisfy the boundary gate. A cheap fixture smoke may use the existing
isolated backend before full repository provisioning is ready, with that limited scope recorded.

### S3 - Installed vertical slice and competent control

Depends on S1/S2 for production readiness. Development behavioral work need not wait for CLI polish.

Proposed commands: `reticle session start`, `resume`, `inspect`, and `evaluate`. Use the same
controller/tools/evaluator as experiments. Make policy/backend/provider/task budgets explicit.
Keep `reticle run` visibly legacy until migration; move authoritative legacy implementations
behind package imports before advertising their installed support.

Test an installed wheel outside the checkout with a scripted client: start, interrupt,
inspect, resume, retrieve history, and evaluate. Resolve the advertised Python >=3.9 range
against actual imports/dependencies. Document supported environments and clear errors.
Replace stale README/architecture/board content with implemented contracts and linked historical
reports; do not wait for S5 to make public documentation accurate.

Calibrate one pinned, reliable model/provider on development repairs (E3). Add a stronger model
only as a separately labeled and budgeted interface diagnostic if needed. Do not vary model,
provider, tools, and policy simultaneously while diagnosing a failure.

Exit: installed workflow passes and valid model runs produce meaningful accepted artifacts.
This establishes a usable control, not superiority. If everything fails or passes, investigate
infrastructure/usability and change development difficulty before a comparative study.

### S4 - First controlled comparison

Requires usable control plus actual evaluator/authority/resource gates; it need not wait for
unrelated CLI documentation polish. Deliver versioned protocol, paired assignments, artifacts,
results, failure audit, and a decision. Run E4 screening, then E5 only if justified.

| Arm | Observation retention |
|---|---|
| A | Current 512/4,000-byte views on the repaired shared substrate |
| B | pressure-recent-v1, full recent observations until pressure requires reduction |

Both arms get identical history tools, latest-exchange protocol protection, task budgets,
model/provider, authority, prompts, evaluator, and fixtures. Assign a new composite arm version
to A: this is an ablation on repaired infrastructure, not a rerun of the historical broken pilot.
Do not add a board, summaries, or new tools only to B.

Known arm-version difference: B prefixes every handled tool result with
`[tool result status=...; output=...]`, including full results; A shows handles only in
partial views and never shows status. Report it as part of B's version, or equalize it in a
new A version before assignment. A turn whose manifest `policy_version` differs from its
assigned arm (the `ContextBuilder` fallback) invalidates that run for the comparison; count
and report such runs rather than pooling them. B's contract message also names
`search_history`, `history`, and `read_artifact` and B emits an omission marker; A's contract
does not mention the history tools, although both arms receive the same tool schemas.

Exit: report improvement, regression, or uncertainty. A negative result completes the experiment.
Default promotion follows section 5; passing engineering gates does not establish policy superiority.

### S5 - Bounded policy search

Conditional on S4 and a trustworthy control. Keep a frozen incumbent and candidate archive.
Start with manual/model-assisted offline proposals, not an autonomous recursive framework.
Execute model-authored policies in isolation with an authorized read-only session view.

Candidate record: source/prompt hash, parent, hypothesis, intended change, task/model scope,
development/selection results, costs, and disposition. Candidates cannot change the evaluator,
budgets, authority, or held-out data. Use E4/E5 gates for selection and promotion.

Loop: inspect failure -> predict effect -> propose -> contract-test -> screen -> select ->
confirm or reject. Allocate further trials by a declared rule. Preserve negative results.
Stop when candidate search fails to produce worthwhile gains within its budget.

Later work is conditional: semantic retrieval, learned context allocation, reusable programs,
cross-task transfer, more models/domains, and multiple workers. Each needs a hypothesis and
cost account. Provisional program use is allowed; promotion never relies on a three-use rule.

## 5. Experiment protocol: fail fast without fooling ourselves

### 5.1 Two speeds

**Development discovery:** small, sequential, heavily inspected experiments. Stop early when
an observable failure invalidates the mechanism. Change one variable and retry on development
tasks. Findings are provisional and may overfit these tasks; no significance claim is needed
to fix a reproducible defect or reject an obviously unusable interface.

**Confirmation:** freeze candidates/protocol, predeclare endpoints, sample size and stopping
rule, and run on unseen tasks. No tuning on this set. A mid-study fix creates a new protocol;
old outcomes remain visible and are not pooled as if the treatment were unchanged.

Do not use confirmatory machinery to slow routine diagnosis. Do not use rapid diagnosis
results as if they were confirmed general gains.

### 5.2 Experiment ladder and default allocation

These are initial screening caps, not statistical sample sizes or spending authorization.
Each run card can lower them. Raise a cap only with a recorded reason and available authority.

| ID | Question | Initial allocation | Stop / next action |
|---|---|---|---|
| E0 | Are mechanics, recovery, and boundaries correct? | Focused offline reproductions plus golden/noop/breaker/gamer; no model calls | Any contract failure blocks dependent model runs; fix smallest cause |
| E1 | Does context rendering preserve the required evidence? | Three fixtures: ample budget, forced pressure, oversized latest exchange; no model calls | Missing latest outcome, unreachable history, or overflow ends trial immediately |
| E2 | Can the model discover and use omitted history? | One fixture first, up to 8 model turns; at most 3 fixtures before review | Audit first failure immediately; distinguish retrieval, tool schema, or provider failure |
| E3 | Can the control repair real code? | One development bug first, up to 20 model turns and a declared wall/cost cap; at most 3 tasks before review | Do not launch a batch behind a broken first trajectory; calibrate difficulty/provider |
| E4 | Does one policy change look promising? | Three matched development task pairs, one run/arm/task before review | Stop on integrity failure; drop a clearly dominated candidate or allocate a second small block |
| E5 | Does the apparent gain generalize? | Unseen tasks; size chosen from practical effect and pilot variability | Predeclared fixed-sample or valid sequential rule; report uncertainty and negative results |

E2 fixtures should include: an earlier file observation after the live file changes; an old
failure whose output ID is no longer visible; and a revised user constraint across context
pressure. Grade correct use of recovered evidence, not just calling a retrieval tool.
Choose one fixture for the suspected mechanism before using the others as transfer checks.

Each live experiment has explicit attempt, token/cost, tool, and elapsed-time limits. A turn
cap alone is not a monetary limit. E2's fixture execution is isolated; E3-E5 require actual
repository/evaluator boundary gates. No dependencies are waived to obtain a quick green result.

### 5.3 Fast-stop rules

- Stop a run/campaign immediately on evaluator leakage, false acceptance, evidence loss,
  authority escape, budget violation, or corrupted protocol. Keep the artifacts and repair.
- Before a live batch, perform one provider/tool-schema smoke and one no-API pipeline control.
  Reuse a valid control only while its exact runtime/environment/evaluator inputs are unchanged.
- Initially allow at most two retries after the first provider attempt, with recorded
  backoff. After three consecutive failed attempts, checkpoint and stop that provider block.
  Do not burn the whole campaign cap on an unavailable free endpoint. Revise these defaults
  only as an explicit protocol change supported by provider behavior.
- Three identical observation calls without a relevant source change or new visible evidence
  trigger an immediate diagnostic flag and trajectory review. In E2/E3 discovery runs, stop
  at that point by default; label it diagnostic termination, not natural task failure.
  In E4/E5 use an identical predeclared rule across arms or only flag it without termination.
- Review every E2/E3 trajectory and every initial E4 pair before expanding. No unattended
  larger matrix until its first block produces interpretable outcomes.
- If a small E4 block is uniformly no better in acceptance and worse in both cost and latency,
  provisionally shelve the candidate. This is resource triage, not proof of statistical inferiority.
- If the study hits a ceiling/floor, stop expanding the same task set. Diagnose infrastructure
  first, then change development difficulty under a new protocol.

### 5.4 One experiment card per hypothesis

Store cards and reports under `experiments/session_harness/`; reuse the current runner where
possible instead of creating a second agent loop. Version runner/protocol changes explicitly.

```yaml
id: E4-retention-001
status: proposed  # running | completed | invalidated | inconclusive
hypothesis: Full prior observations reduce rereads and increase accepted repairs within budget.
mechanism: Relevant previously read source remains visible for the next decision.
one_change: observation retention policy
control: legacy-views-on-repaired-substrate
candidate: pressure-recent-v1
tasks_partition: development
task_ids: []  # pin before execution
runtime_tools_evaluator_environment_hashes: {}  # required before execution
model_provider_sampling: {}  # required before execution
budgets_per_run: {}  # attempts, turns, tokens/cost, tools, elapsed, final evaluation reserve
campaign_cap: {}  # explicit, independently enforced
assignment_seed: null  # record before randomization
primary_endpoint: accepted final artifact within the declared resource contract
diagnostics: [identical_rereads, history_retrieval_success, context_bytes, cost, elapsed]
failure_prediction: Old evidence remains inaccessible, or added input cost erases the benefit.
stop_rule: first three pairs, then review; integrity failures stop immediately
decision_rule: advance, revise, provisionally reject, or inconclusive with stated evidence
evidence_bundle: null  # required at completion, including failed/aborted trials
next_action: null  # required at completion
```

The card must be concrete before live execution: no empty tasks, environment, budgets, or
provider configuration. Record source content hashes for dirty work; a dirty boolean is
insufficient. Preserve exact model requests/responses, tool outcomes, manifests, initial/final
source, evaluator inputs/results, failure classifications, and all attempts. Raw bundles may
live outside git but need a retained location, hash manifest, and retention policy.

### 5.5 Pairing, infrastructure, and outcomes

- Match task, provider/model, environment, resources, tools, evaluator, and instructions.
  Interleave randomized arm order within task blocks. Avoid model-major scheduling that lets
  early provider failures consume later participants' opportunities.
- Allocate resources per run. Keep a campaign safety cap, but launch a pair only when both
  allocations fit. Mark an interrupted/incomplete pair explicitly rather than dropping it.
- Record 429s, HTTP-200 error bodies, empty responses, malformed calls, timeouts, retries,
  and unknown billing. Provider compatibility is a measured prerequisite, not an assumption.
- Primary endpoint: fraction of accepted final artifacts within the per-run contract. Also
  report controller stop reason, criterion coverage, operational success including outages,
  and separately labeled results under predeclared infrastructure-valid conditions.
- Do not decide exclusions after seeing which arm won. Retain diagnostic terminations and
  evaluator failures as such; do not relabel every unsuccessful run as model inability.
- Secondary measures: all provider tokens/cache usage, money, latency, tool compute, context
  construction cost, rereads, retrieval success, false finishes, recovery failures, and storage.
  Token compression, notes saved, and programs generated are not task success metrics.

### 5.6 Confirmation and default promotion

Split development, selection, and sealed final tasks by repository/family where feasible.
The already inspected P6 tasks may inform development; use unseen tasks for final claims.
Public fix dates do not by themselves prove lack of model contamination.

Before E5, declare a minimum useful effect, any quality noninferiority margin, study size,
and analysis/stopping rule. Use pilot variability to allocate enough independent tasks.
Report paired effects and uncertainty, accounting for repository/family clustering; repeated
attempts on one bug are not independent tasks. Do not select the best-looking subset afterward.

Promote a candidate only if it meets engineering gates and either demonstrates the predeclared
meaningful acceptance gain under matched limits, or meets quality noninferiority while
delivering a meaningful cost/latency benefit. Otherwise keep it experimental, retain the
incumbent, or state that the result is inconclusive. Correctness fixes need no statistical gate.

Repeated candidate screening spends selection data. Keep the final set sealed from the
proposal generator, evaluate only finalists, and record each exposure. Further tuning requires
new final tasks. Avoid optional stopping unless the chosen sequential method supports it.

### 5.7 Cost of search and practical optimality

Charge proposal generation, evaluation, discarded candidates, retries, retrieval, and
maintenance to adaptation. Report marginal deployment cost separately from total search cost.
Recorded-session comparisons diagnose selection but do not prove task utility: changed
contexts cause different actions and later histories. Require live continuations/rollouts.

Later program/memory studies compare reset/no-memory, frozen-library, retrieval-only, and
adaptive conditions on unseen later tasks. Show amortized benefit before calling accumulation
learning. The target is a measured quality/cost frontier for a specified workload/model/budget,
not a universally optimal harness. Recalibrate when the model or workload changes.

Exact model choices, new spend, and confirmatory sample sizes belong in the run card. Prior
P6 authorizations cover named historical runs, not a new campaign. Complete offline work and
prepare a concrete priced protocol before any required spending approval. Reuse standing
authorization within its actual scope; do not interrupt every iteration to reapprove it.

## 6. Validation and implementation discipline

Keep separate gates for mechanics, actual model usability, and task utility. Scripted models
test mechanics. E2/E3 test usability. E4/E5 test comparative utility. Report skipped/unrun gates.

Run focused tests per slice and the offline suite at integrated milestones. Run installed
wheel checks for packaging changes and live OCI gates for boundary changes. Do not encode
arbitrary preview sizes as requirements of the new control; test continuity, discoverability,
protocol validity, resource limits, and recovery. Preserve explicit old-arm tests separately.

Measure query/context latency and storage growth on short/long synthetic sessions, and
workspace tracking on representative repositories. Profile before selecting SQLite, persistent
indexes, or incremental hashing. Remove repeated full scans only without weakening final
artifact identity. Performance work requires an observed bottleneck or a failing scale probe.

Each implementation slice should answer one question and produce reviewable evidence. If it
needs several unrelated changes to make progress, split the slice or revise the hypothesis.
Automate report generation from raw logs; concise reports must include failures and a next
decision, not only successful trajectories. Avoid building a research dashboard before these
records and decisions exist.

## 7. Work ledger and next action

| Stage | Status | Next evidence |
|---|---|---|
| S0 | Complete | Replacement plan, preserved historical ledger, current-direction notices; documentation only |
| S1 | Complete (mechanics) | S1a-S1c offline gates pass; E1 passes; E2 `changed-file` run once (gemma-4-26b/DeepInfra, accepted); other E2 fixtures unrun |
| S2 | In progress | S2a delivery 1 passes offline; finish attempt/deadline accounting, then run S2b isolation controls |
| S3 | Not started | Installed session workflow plus usable control |
| S4 | Not started | Small paired retention screen; confirmation only if justified |
| S5 | Deferred | Bounded policy search after trustworthy comparison |

**Next implementation:** finish S2a by exposing individual provider attempts to the durable
ledger, defining paused/deadline semantics, and adding a supervisor adjustment for reconciled
billing. Then run S2b no-API isolation/evaluator controls. E2 `changed-file` ran once
(see `experiments/session_harness/E2-changed-file.md`); the next empirical action is the
second E2 fixture (old failure whose output ID is no longer visible) under a new approved card,
at most three fixtures before review. Do not start a new consolidation engine, board
policy, or broad model matrix.

Per delivery record: exact source identifier, changed contracts/files, validation commands
and results, empirical gates run/unrun, failed hypotheses, remaining limitations, and next
slice. Update this table; do not restart at historical P0. Revise decisions when evidence
contradicts them and preserve the negative result.

The governing test: can a better model or policy improve task outcomes here without losing
history, escaping authority, renewing its budget, or changing the meaning of success?

### Delivery record: S1a pressure and continuity mechanics

- Source base: `08871ac3d083bd72b33ac18499d0391c9c9cd20e`, with the S0 documentation
  changes already present in the working tree.
- Added `pressure-recent-v1` while retaining `bounded-recent-v2` unchanged as the named
  legacy arm. The new policy reserves the latest paired assistant/tool exchange, retains
  full recent observations while the serialized request fits, and creates exact output
  views only under pressure.
- Context manifests now record exact request bytes and omitted transcript units. Tool views
  carry outcome status and output handles. The controller verifies the materialized request,
  manifest hash/size, and byte limit before provider dispatch; impossible requests stop as
  `context_budget_exhausted` with zero model calls.
- E1 offline fixtures: ample budget retained two complete 3 KB observations; forced pressure
  omitted the older observation and retained the latest error result; an oversized latest
  observation fit through an exact `read_output` view. The named legacy preview limits also
  remain covered.
- Review fixes: the required context is now the latest exchange plus every later unit (a
  text-only reply, the no-tool-call prompt, a user correction); previously these could be
  omitted, re-sending the prior turn unchanged. Older history is retained as a contiguous run
  back from that tail; previously a newer unit could be skipped to admit an older one.
  Regressions cover the trailing prompt, a later correction, and contiguity.
- Controller semantics change for every policy, including `bounded-recent-v2`: an over-budget
  request now stops the run instead of dispatching with `context_over_budget: true` (that
  request field is now always false). No pilot 1/2 or pipeline log recorded a true value, so
  historical runs are unaffected.
- Validation: focused context/controller tests, 25 passed; full offline suite, 149 passed
  with three OCI integration tests skipped. After the review fixes: focused 28 passed; full
  offline suite 161 passed, three skipped (this count includes the S1b tests, so it supersedes
  the S1b record's 158). No model usability run was attempted; E2 remains
  gated on S1b discoverable history. Live OCI boundaries remain unrun for this slice.

### Delivery record: S1b history discovery and S1c comparison replay

- Added a model-visible session query boundary with allowlisted event kinds, bounded history
  pages, literal search, stable high-water cursors, structured credential redaction, and
  explicit scope/coverage metadata. Retrieval operations exclude their own records.
- Added `history`, `search_history`, and session-scoped `read_artifact` tools. Search results
  include sequence, kind, tool/source, path when available, outcome status, snippet, output
  handle, and authorized artifact references. Raw controller/evaluator context and raw
  transcript artifacts are denied through this view.
- The restart fixture reads an old file observation, changes the live file, forces that
  exchange completely out of context, opens a new runtime, discovers it without a remembered
  output handle, and recovers the immutable old bytes. Tests also cover cursor stability,
  later user corrections, missing blobs, denied controller records, and bounded large pages.
- Added diagnostic-only checkpoint comparison. Multiple policies render the transcript as of
  one fixed event sequence; the persisted comparison identifies each exact request artifact,
  policy version, byte count, visible/omitted records, and recovery calls. It does not invoke
  a model or dispatch tools. Scratch pins are honestly labeled as current at replay time until
  S2 persists full task state at checkpoints.
- Review fixes (details in the S1 report): call metadata is indexed up to the high-water mark
  so paging and explicit windows cannot drop path/status or return retrieval records; each
  call is one search record with linked artifacts; JSON tool-call argument strings are
  redacted; legacy manifests record omitted units for comparison; history tool results are
  indented for line paging.
- Validation: focused S1 tests, 21 passed; full offline suite, 161 passed with three OCI
  integration tests skipped. After review fixes: focused S1 files 27 passed; full offline
  suite 175 passed, three skipped (includes concurrent work). E2 actual model usability is unrun. No provider/network calls
  or new spend occurred.

### Delivery record: S2a durable resources and crash transitions, slice 1

- Persisted the full task contract plus journal-authoritative reservations and reconciliation
  for model attempts/responses, tool actions, active time, and monetary usage. Task limits do
  not renew when a controller is replaced; unknown billing retains its conservative charge.
- Added an OS-backed single-writer lease for controller lifetimes and a shared workspace
  mutation boundary for native file tools and command execution.
- Added durable model-request intent and response linkage. Recovery distinguishes known not
  started, known complete but unpublished, and unknown external outcomes. It republishes
  completed results without repeating mutations, resumes recorded unfinished tool calls without
  regenerating the response, and stops ambiguous effects as `needs_reconciliation`.
- Evidence, exact source hashes, remaining limitations, and validation commands are recorded in
  [the S2a delivery report](experiments/session_harness/S2a-durable-resources-recovery.md).
- Validation at handoff: 12 focused S2a tests passed; the full offline suite passed 179 tests
  with three OCI integration tests skipped. E2, live OCI boundaries, installed-wheel checks,
  and S2b evaluator controls were not run. No provider/network calls or new spend occurred.
