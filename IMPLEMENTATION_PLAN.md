# Reticle: general adaptive runtime implementation plan

Status: staged delivery plan; P0–P5 engineering stages are complete (see section 14).
Created: 2026-09-14.
Owner: Grant; implementation owners assigned when work is scheduled.

## 1. Purpose and reading guide

Build a general, durable scratchpad and execution environment around an LLM that
expands what the model can accomplish. The runtime should benefit from stronger
models, more available computation, accumulated experience, and better programs.
It should allow strategies to evolve without requiring kernel changes.

This document turns the repository critique into implementation decisions,
migration stages, acceptance criteria, and experiments. It is a design proposal,
not evidence that the proposed architecture improves performance. Subsequent
sessions should update its decision log and work ledger rather than reconstruct
the rationale from conversation history.

Read sections 2–5 for the design, 6–10 for contracts, 11 for implementation order,
and 12–15 for evaluation, risks, and continuation instructions.

Relevant existing sources:

- [Current design](ARCHITECTURE.md) and [README](README.md).
- [Current CLI-backed runtime](stateless_harness.py).
- [Earlier phased runtime](harness.py).
- [Failure evidence implementation](reticle/cognitive/falsification.py).
- [Capability ledger](reticle/cognitive/capability_ledger.py).
- [Larger observation experiment](experiments/large_v1/REPORT.md).
- [Reading pilot](experiments/pilot/REPORT.md).
- [Autotelic limitations](experiments/AUTOTELIC_GROUNDING.md).
- [Sutton's Bitter Lesson](https://www.cs.utexas.edu/~eunsol/courses/data/bitter_lesson.pdf).

The September 14 review was primarily static. Small runtime reproductions could
not run because the available virtual-environment launcher failed with permission
denied. Reproduce suspected defects before claiming they have been fixed. The
working tree already contains unrelated evaluation changes; preserve them.

## 2. Outcomes, boundaries, and non-goals

### Desired outcomes

1. The model can preserve arbitrary useful state and recover exact observations.
2. The model can create, execute, compose, inspect, revise, and reuse programs.
3. Observation and memory strategies can vary by task and model.
4. Execution failures do not destroy the supervising session.
5. Reported completion describes the final artifact and actual evidence.
6. Improvements are measured against a competent general agent baseline.
7. Reusable artifacts improve later held-out tasks after their creation cost is
   included; mere artifact accumulation is not counted as learning.

### Scope

Start with a single-host, single-controller runtime, local file artifacts, and
code/text tasks. Preserve extension points for media and external environments.
Support multiple isolated execution jobs when needed; do not initially build a
distributed scheduler, a swarm framework, or a universal knowledge graph.

The LLM-as-CPU analogy assigns responsibilities: an inference engine uses an
active working set, durable memory, execution facilities, and I/O. It does not
imply deterministic instructions, exact internal state, or reliable CPU-like
execution by a model. Contracts validate proposed operations at the boundary.

### Non-goals for the initial implementation

- Training model weights or implementing reinforcement learning infrastructure.
- Encoding a universal theory of goals, salience, curiosity, or intelligence.
- Requiring every task to have a complete deterministic success oracle.
- Making every task start without useful libraries or existing tools.
- Automatically enabling external effects or unlimited background compute.
- Reproducing every historical modality demo before the core is usable.

## 3. Principles and proposed decisions

These are the proposed defaults. A change should identify which decision it
revises and provide either a correctness argument or relevant experimental data.

| ID | Decision | Rationale and tradeoff |
|---|---|---|
| D01 | Keep the trusted runtime small and operational. | It owns persistence, dispatch, budgets, cancellation, permissions, and event integrity. Cognitive behavior belongs in replaceable policies. |
| D02 | Use files and a small metadata index for durable memory. | Arbitrary formats remain possible; avoid requiring an ontology before useful work. Indexes are rebuildable accelerators. |
| D03 | Preserve raw observation artifacts; derive context views. | Compression can be revised. Disk use grows, so retention must be explicit and metered. |
| D04 | Offer full reads, search, regions, outlines, and media views together. | Observation scale is a choice. Fixed restrictions remain available as experimental arms. |
| D05 | Provide a bounded recent-transcript policy first. | It is a credible baseline and a recovery path. Blank-slate and adaptive policies are optional implementations of the same contract. |
| D06 | Permit arbitrary scratch content. | Plans, prose, tables, code, hypotheses, and incomplete work must not be forced into grounding-pointer fields. |
| D07 | Treat failures as conditional evidence. | Retry decisions depend on state and circumstances. No permanent global prohibition on repeating an action. |
| D08 | Separate execution, measurements, interpretations, and acceptance. | Exit zero, syntax validity, and task success carry different meanings. |
| D09 | Execute generated programs outside the controller. | Ordinary Python module semantics, cancellation, and containment enable more ambitious experimentation. |
| D10 | Store reusable programs as versioned artifacts. | Registry schemas are discovery metadata, not the sole representation of a skill. |
| D11 | Allow immediate provisional reuse. | No arbitrary three-example gate. Broader promotion depends on measured utility, scope, and evaluation risk. |
| D12 | Keep domain priors in adapters and libraries. | Minecraft inventory gains and recipe chains do not define general capability. |
| D13 | Meter all adaptation. | Context construction, retries, policy search, evaluation, and consolidation consume the same accountable resource budget. |
| D14 | Introduce policy adaptation only after an auditable baseline. | Otherwise gains and regressions cannot be attributed or recovered from. |

The Bitter Lesson motivates testing methods that continue to benefit from
computation and learning. It does not establish that minimal tooling, pure model
discretion, or any particular adaptive policy will win. Supplied libraries and
heuristics are useful starting points when they remain replaceable and measured.

## 4. Target architecture

```text
User task + resource/authority contract
                 |
                 v
       Controller / small runtime
        |         |          |
        |         |          +--> accepted final artifact + evidence
        |         +--> versioned event journal / artifact store
        v
 Context policy --> explicit context manifest --> model invocation
        ^                                      |
        |                                      v
        +------- observations <-- action dispatcher
                                      |
                          isolated execution workers
                                      |
                      files / tools / environment adapters
```

### Proposed module ownership

```text
reticle/
  runtime/       controller, contracts, events, budgets, cancellation
  storage/       artifacts, references, atomic writes, retention
  execution/     worker protocol, local backend, isolated backend
  context/       manifests, transcript policy, adaptive policy interface
  tools/         file/search/edit/run/scratch primitives, discovery
  evaluation/    measurements, acceptance policies, result reports
  library/       reusable artifact manifests, retrieval, lifecycle
  adapters/      domain and environment integrations
  cli.py         entry points and configuration
experiments/     fixed policies, benchmarks, adaptation experiments
```

Do not create empty abstractions for every directory immediately. Add modules
when a stage implements their contracts. Package code must be authoritative;
root-level compatibility modules may import from it temporarily, never the reverse.

### Controller sequence

1. Load task, permissions, limits, policy version, and durable session state.
2. Recover any incomplete events/jobs conservatively.
3. Ask the context policy for a manifest within its budget.
4. Validate references and limits; materialize messages and record the manifest.
5. Invoke the model; record provider metadata and actual usage when available.
6. Validate requested actions; dispatch with explicit dependencies.
7. Persist raw results before presenting derived views.
8. Update measurements, workspace revision, and budget consumption.
9. Continue, checkpoint, or evaluate a finish request.
10. Emit a final status referring to a specific artifact/workspace revision.

A model may ask to finish. It cannot make an executable acceptance check pass by
asserting completion. Conversely, tasks with partial or human acceptance criteria
must remain deliverable with an honest "needs review" status.

## 5. Memory and context contracts

### Artifact storage

Start with a session directory containing an append-only JSONL event journal,
immutable content-addressed blobs, and mutable named references written atomically.
Use a single journal writer initially. Introduce SQLite only if measured indexing
or concurrency needs justify it; do not build two authoritative metadata stores.

Minimum artifact envelope:

```text
artifact_id, content_hash, media_type, byte_length, created_at
producer_event_id, parent_artifact_ids, optional labels
```

Artifact payloads are arbitrary bytes. Scratch content has no required semantic
schema. Named references such as `scratch/current-plan` point to immutable
versions; updates carry an expected prior version to detect stale writes.

Workspace files remain ordinary editable files. Observed bytes are snapshotted or
hashed when read. An address into a live file must record its revision/hash and
locator. After mutation, either resolve against the original snapshot or explicitly
revalidate against the new version. Never silently relabel a stale locator verified.

### Initial scratch operations

- `read(ref, range?)`: materialize exact bytes or a declared view.
- `write(name, content, expected_version?)`: create a version and update a name.
- `list(prefix?, labels?)` and `search(query, scope?)`: discover stored work.
- `pin(ref, priority?)` / `unpin(ref)`: express active-context preferences.
- `forget(name)`: remove a working reference, distinct from deleting audit history.

Reuse file operations where practical. Avoid redundant tool schemas that require
the model to learn separate APIs for identical operations.

### Context manifest

Each model call records the exact selected artifact versions, ranges, rendering
methods, message order, selected tool schemas, policy version, and token estimate.
Store hashes/references for the materialized request so the delivered input can be
audited. Provider-hidden prompts and hidden state must be marked unavailable.

Non-evictable contract material includes the user task, current authority and
budget boundaries, protocol essentials, and a way to retrieve omitted evidence.
Model-pinned content competes within the remaining budget. If pins overflow, return
an explicit overflow result and compact under a documented fallback; never imply
all pins were delivered when they were not.

The baseline policy retains bounded recent exchanges plus selected durable notes.
It preserves tool-call/result pairing required by the provider. It may spill large
outputs to artifacts with truthful previews. It does not summarize or remove the
only copy of an observation.

Adaptive policies can choose summaries, retrieval, recent history, raw views, and
tool descriptions. Context construction has its own metered sub-budget. On failure,
use the baseline policy with a visible diagnostic. No unbounded recursive calls to
the same policy/model to decide what to put in context.

### Retention

Default: retain a run's raw observations through its evaluation and review window.
Record disk usage and support configurable quotas. Explicit garbage collection
operates on unreferenced blobs after checkpoints; report missing artifacts as
unavailable, never reconstruct them as if original. Keep secrets out of telemetry
through redaction at ingestion; document any resulting limits on exact replay.

## 6. Execution and sandbox contract

### Tool result envelope

```text
call_id, status(success|error|timeout|cancelled|rejected)
exit_code?, stdout_ref?, stderr_ref?, output_refs[]
preview, preview_truncated, duration_ms, usage
workspace_revision_before, workspace_revision_after
error_kind?, retry_hint?, external_effect_status?
```

Return useful content for observation tools, including outlines and successful
shell commands. Output limits limit the inline view, not silently discard the raw
result. Preserve stdout and stderr separately. Distinguish parser errors, invalid
arguments, tool failures, and evaluator failures.

### Worker model

Generated code is an ordinary module/program loaded inside a worker. Registration
stores source and metadata; it does not execute arbitrary top-level code in the
controller. Validate entry-point existence and signatures in the worker. Helpers,
imports, recursion, module globals, and asynchronous entry points either work
normally or receive an explicit unsupported-feature result.

Each job declares working directory, mounted resources, environment, timeout,
output limit, and available authority. Credentials are passed only when a job
requires the corresponding authorized capability, not inherited wholesale.

Separate two guarantees:

1. **Process supervision:** cancellation, process-tree termination, bounded output,
   and controller survival. This is available in an explicitly trusted local mode.
2. **Host isolation:** enforced filesystem/network/process/resource boundaries.
   This requires an OS-backed backend; changing cwd and launching a subprocess do
   not provide it.

On the current Windows host, implement a backend spike comparing a disposable
container/VM option with available local tooling. Use Windows Job Objects or an
equivalent backend facility for descendant termination. Select one supported
isolated backend first. If isolation is requested but unavailable, fail explicitly;
do not fall back silently to trusted local execution. Avoid importing the entire
host workspace or credential environment into the guest.

### Edits and side effects

- Prefer exact-match or version-checked patches over unguarded line replacement.
- Snapshot before mutation; a conflicting revision produces a recoverable conflict.
- Permit intermediate syntax errors in a task workspace. Optional atomic validated
  edits are conveniences, not the only way to construct a multi-file change.
- Filesystem snapshots do not roll back email, network operations, or game actions.
  Adapters declare irreversible effects and support operation IDs where possible.
- After a crash, an action with unknown external outcome is reconciled or reported
  unknown. Do not automatically replay it as though it never happened.

Concurrent read-only jobs may run independently. Mutating jobs are serialized by
default, or use explicit separate snapshots/branches and a merge step. Do not
promise transactional semantics for arbitrary shell commands.

## 7. Evidence, failure memory, and acceptance

### Evidence distinctions

Store four separate concepts:

1. Observation: what an instrument returned, with source and version.
2. Measurement: a named procedure applied to inputs, with result and scope.
3. Interpretation: a model or user claim linked to evidence.
4. Acceptance decision: application of task criteria to the final artifact.

No default `verified=True` or confidence `1.0` for an unmeasured assertion. Source
quote matching and claim entailment are different checks. Scores have an explicit
scale and meaning; avoid the existing ambiguous 0–1 versus 0–100 convention.

### Failure records

Record attempt/program version, relevant environment revision, action, observations,
stated approach if available, failure category, and applicable conditions. Optional
interpretations include "likely repeat" and "possibly invalidated by environment
change." They never erase evidence or universally forbid an approach.

Failure signatures group similar observations for retrieval. They are not causal
proofs. A test can be marked resolved only when its identity is observed to pass
under the relevant suite/version; absence from a partial test run is insufficient.
Detect regressions and reopen records. Keep timeout, collection failure, and
unknown outcomes distinct from failed assertions.

### Acceptance protocol

Task contracts declare criteria as executable, graded, human-reviewed, or currently
unmeasurable. Preserve their original wording and evaluator versions.

Proposed final states: `accepted`, `rejected`, `needs_review`, `budget_exhausted`,
`cancelled`, `runtime_error`. Also store criterion-level outcomes: pass, fail,
unknown, not_run. This prevents infrastructure failures from being flattened into
task failure or success.

For executable checks, evaluate the final workspace revision after the last
mutation. A mutation invalidates earlier applicable acceptance measurements.
Reserve resources for final evaluation; if it cannot run, report unknown/needs
review or budget exhaustion instead of inheriting an old pass.

Evaluation fixtures and hidden answers live outside agent-writable workspaces.
The harness can run agent-authored tests as useful probes, but those do not replace
the fixed independent acceptance procedure. Isolated evaluators receive a candidate
snapshot. Report semantic limits even when all executable checks pass.

## 8. Reusable programs and adaptive policies

### Artifact lifecycle

Use `candidate`, `evaluated`, `preferred`, and `retired` as operational states,
not universal truth labels. A manifest records entry point, parameters, dependency
lock or environment reference, author/producer, version, examples, observed scope,
trial references, and costs. Programs remain inspectable and editable.

A candidate may be tried immediately in its sandbox. Promotion to preferred use
requires comparison against an alternative on an appropriate validation set.
Thresholds vary with the cost and consequences of misuse; the original three-trial
rule remains a named experimental policy if useful.

Search/index the library and expose a bounded set of relevant descriptions. Do not
inject every registered schema on every model call. Provide an explicit discovery
tool and ordinary `run` access to stored programs. Track retrieval misses, failed
reuse, dependencies, version changes, and retirement decisions.

### Policy adaptation

Policies receive a read-only session view and return a context manifest or proposed
actions. They cannot alter the task contract, audit records, budget accounting, or
evaluation oracle. They run under the same execution boundaries as other generated
programs when model-authored.

Begin with offline candidate generation and paired evaluation, then enable bounded
within-task trials. Version every policy; preserve the baseline for recovery. A new
policy is activated only after protocol validation and an explicit selection event.
Optimization data, validation data, and final held-out evaluation remain separate.

Candidate objectives may include task quality, cost, latency, or later-task utility.
Do not embed a universal weighted score prematurely. Report a quality/cost frontier
and let task configuration specify tradeoffs. Novelty, inventory changes, and number
of tools created are diagnostics, not stand-ins for general competence.

## 9. Budgeting and recovery

Track wall time, model calls, provider-reported input/output/reasoning/cache usage
where available, tool CPU/time, storage, and monetary cost when pricing is known.
Unknown usage remains null with provenance; character counts remain character counts.

Budgets cover foreground work and all policy/consolidation experiments. Reserve
space for final observations and evaluation. Bound tool output, number of concurrent
jobs, and recursive model invocations independently. Reaching a limit produces an
explicit recoverable status and checkpoint.

Journal action intention before dispatch and outcome afterward. On resume, load
the last consistent checkpoint and reconcile incomplete jobs. Use operation IDs to
deduplicate runtime bookkeeping. Exactly-once external side effects are not assumed.
Replay reconstructs recorded state and inputs; stochastic model responses and
changing environments are not promised to reproduce bit-for-bit.

## 10. Migration policy

Maintain historical experiment artifacts and original reports. They establish what
was measured under older protocols. New runs record runtime, prompt, policy, tool,
dataset, evaluator, and source revisions; do not compare incompatible reports as if
they were the same treatment.

The new package implementation becomes authoritative incrementally. Preserve public
imports through small deprecated shims for a stated transition period. Run a wheel
installation test outside the checkout to catch dependencies on root-level modules.

Keep current behavior selectable as `legacy_stateless` for reproductions. The new
CLI accepts explicit policy/backend choices; change the default only at the rollout
gate. Check configuration schema versions on load and provide actionable migration
errors. Preserve legacy ledger imports as provenance-bearing historical records;
do not upgrade old `verified` flags into new measurement evidence.

Update README, ARCHITECTURE, and ACTIVE_EPISTEMIC_BOARD once the corresponding code
lands. Separate implemented behavior, hypotheses, and historical results. Replace
blanket claims of formal verification or general capability with measured scope.
Do not rewrite those documents now as if this proposal were implemented.

## 11. Implementation stages and acceptance gates

Stages are ordered by dependency, not calendar promises. Each should be delivered
as a reviewable change with recorded validation. A failed empirical gate may retain
a useful optional policy while preventing its promotion to default.

### P0 — Establish a reproducible development baseline

Work:

- Inventory active entry points, compatibility imports, tests, and archived code.
- Establish a working interpreter and dependency installation without modifying
  unrelated local evaluation work; record Python and platform versions.
- Run targeted current-runtime tests; classify pre-existing failures separately.
- Record current commit and dirty-tree diff hashes for reproducible local runs.
- Add a baseline runtime inventory and validation commands to the work ledger.

Exit: one documented command runs the selected offline core suite. Existing failures
and unavailable integration backends are listed; no unsupported green-suite claim.

### P1 — Repair the feedback and completion loop

Depends on P0.

Work primarily in `stateless_harness.py`, `harness.py`, and their focused tests:

- Return outline contents and useful stdout/stderr, with explicit truncation.
- Ensure final verification determines completion after every mutation.
- Remove mandatory never-repeat instructions; preserve conditional failure history.
- Default pointers to unvalidated and expose stale addresses honestly.
- Repair module namespace behavior for dynamic tools as an interim compatibility
  fix; clearly label in-process execution until P4 replaces it.
- Disable the mandatory legacy editorial pass by default. If explicitly used,
  validate its final output and restore a filesystem checkpoint on failed local
  edits; report rollback failure separately.

Meaningful regression cases:

- An outline request returns a known symbol; `echo`/search output reaches the model.
- Verify passes, then a later edit breaks tests in the same batch: final state fails.
- A failed test command can be rerun after repair.
- A generated entry point calls its sibling helper/import successfully.
- A locator is stale after an intervening edit.

Exit: these cases pass and existing supported behavior remains reproducible. This
stage fixes correctness without claiming an adaptive architecture exists.

### P2 — Introduce contracts, journal, and artifact storage

Depends on P1.

- Add versioned tool result, artifact, event, task, and final-result envelopes.
- Implement atomic blob/reference writes and a single-writer journal.
- Persist exact observation artifacts and provide honest previews/references.
- Implement workspace revision tracking and version-checked edits.
- Add checkpoint/resume for local operations and explicit incomplete-job states.
- Move authoritative runtime code into the package with compatibility shims.

Exit: a scripted session survives restart, recovers exact prior output, rejects a
stale write, and detects an incomplete action without blindly replaying it. A wheel
installed outside the repository can import and invoke the offline runtime.

### P3 — General scratchpad and bounded baseline context

Depends on P2.

- Implement arbitrary scratch operations and reference discovery.
- Add context manifests, bounded transcript policy, pinning, and overflow behavior.
- Preserve provider tool-message protocol and original user task across compaction.
- Add full/region/outline/search choices through a shared observation interface.
- Remove mandatory two-phase reasoning and prescribed note categories from the new
  baseline. Keep ledgers available as optional renderers.

Exit: a multi-step task can save an unfinished plan, spill a large observation,
resume later, retrieve exact evidence, and finish without relying on a fixed board.
Forced small-context tests exercise recovery and pin overflow, not just rendering.

### P4 — Supervised and isolated execution

Design spike may overlap P2; integration depends on P2 and P3.

- Select one OS-backed isolated backend and document actual guarantees.
- Implement worker lifecycle, ordinary module loading, output artifacts, cancellation,
  descendant termination, and clean environment provisioning.
- Replace controller `exec`; register programs without host-side evaluation.
- Implement trusted-local mode as explicitly different from isolated mode.
- Separate concurrent reads from serialized mutations and candidate snapshots.

Exit: infinite loops, excessive output, worker crashes, and spawned child processes
cannot hang the controller. Boundary tests demonstrate the advertised filesystem
and network restrictions in isolated mode. Backend-unavailable errors fail clearly.

### P5 — Scoped evidence and independent final evaluation

Depends on P2 and P4; selected evidence work may begin earlier.

- Implement observations/measurements/interpretations/acceptance distinctions.
- Migrate failure memory to conditional attempt records and version-aware resolution.
- Add final-revision acceptance, resource reservation, and graded/human criteria.
- Keep fixed evaluator inputs outside the candidate's authority.
- Report test coverage identity and infrastructure failures separately.

Exit: editing candidate tests does not alter independent acceptance; partial suite
execution does not falsely resolve missing tests; a task lacking an executable
oracle produces a useful artifact with an accurate review status.

### P6 — Establish the strong baseline and experimental protocol

Depends on P3–P5.

- Build one shared runner for transcript, legacy fixed, and adaptive-policy arms.
- Pin tasks, tools, source snapshots, prompts, evaluators, and budget rules.
- Capture actual usage and all unsuccessful attempts, including policy overhead.
- Run a small instrumentation pilot and inspect complete trajectories.
- Freeze the comparison protocol before the confirmatory run.

Exit: reports can trace every outcome to final artifacts and evaluator inputs;
paired arms receive equal authority and resource budgets. No architectural advantage
is claimed from the instrumentation pilot alone.

### P7 — Reusable program library and optional adaptive context

Depends on P4 and P6.

- Add versioned manifests, library search, bounded discovery, and lifecycle tracking.
- Implement a model-selectable context policy with baseline fallback.
- Allow optional candidate creation and reuse without fixed repetition thresholds.
- Compare fixed representations with model-selected mixtures under matched budgets.

Exit: the agent can discover, inspect, reuse, revise, and retire a program across
sessions; adaptive context failures recover without losing state. Promotion of an
adaptive policy requires the predefined empirical gate, not a successful demo.

### P8 — Measure adaptation and cross-task transfer

Depends on P7.

- Add bounded policy/program candidate search in isolated child experiments.
- Evaluate later held-out tasks with and without accumulated artifacts.
- Measure discovery, validation, retrieval, failed reuse, and maintenance costs.
- Compare multiple model capability levels and compute budgets.
- Stress domain shifts, stale memories, misleading summaries, and irrelevant tools.

Exit: a report supports a scoped claim of improvement or records a negative result.
If adaptation does not help, keep the substrate and revise the policy; do not add
more mandatory cognitive machinery to rescue the narrative.

### P9 — Default rollout and documentation reconciliation

Depends on engineering gates P0–P7; empirical adaptation claims depend on P8.

- Promote the reliable general runtime after CLI, packaging, recovery, and core
  regression checks pass. Adaptive policy promotion is a separate decision.
- Update architecture, README, examples, and stale active-board instructions.
- Publish backend guarantees, migration commands, supported platforms, and limits.
- Retain an explicit legacy mode and a rollback path through the transition window.

Exit: a new user can install, run, inspect artifacts, resume, and understand results
without root-checkout imports or assumptions from old experiment reports.

## 12. Evaluation design

### Primary questions

1. Does the general runtime preserve baseline task quality while improving reliability
   of execution, recovery, and evidence reporting?
2. Does adaptive context improve quality/cost tradeoffs over bounded transcript and
   fixed Reticle policies?
3. Do accumulated programs/memories improve later-task outcomes after all costs?
4. Do improvements persist as models and compute budgets change?

### Arms and controls

- A: competent model + general tools + bounded transcript + optional plain notes.
- B: same substrate and authority + fixed Reticle context/ledger policies.
- C: same substrate and authority + adaptive context and artifact selection.
- D, later: C with cross-task artifact/policy learning enabled.

Use ablations to separate scratch persistence, observation choice, failure memory,
program reuse, and context adaptation. Keep interface capabilities constant unless
the specific experiment tests the interface itself. Match total budgets rather than
only number of model turns. Account for input caching and actual billed usage.

### Task coverage

Start with pinned real-repository bugs and multi-document synthesis. Include small
files where full reads should win, cross-file invariants, long interruptions,
context overflow, tool failures, changing state, and tasks without perfect oracles.
Add media tasks after the common contracts work; reuse the runtime unchanged.

Use task families and instances split before adaptation. Separate development,
selection, and final evaluation data. Do not allow hidden answers into memory or
artifact training histories. If public benchmark contamination is plausible, include
new private/generated instances and state remaining limitations.

### Metrics and inference

Primary: independently measured task quality/success at a fixed total budget.
Secondary: monetary cost, latency, provider tokens, tool compute, recovery rate,
false-success rate, useful artifact reuse, and cost per successful later task.
Report creation and failed-use costs, including unsuccessful runs.

Choose a minimum practically meaningful effect and, where applicable, a noninferiority
margin before the main run. Use pilot variance to size the study. Use paired
comparisons and uncertainty intervals; account for clustering by task family and
repeated trials. Predeclare primary endpoints and avoid selecting the best-looking
model/task subset afterward. Ceiling scores require harder tasks, not equivalence
claims. Missing provider usage is reported as missing, never inferred from characters.

For adaptation, plot held-out quality against cumulative total compute and task
experience. Include a no-memory/reset condition, a retrieval-only condition, and a
frozen-library condition to identify where any benefit comes from.

### Promotion gates

- Engineering: no known false-success path; required boundary and recovery cases pass.
- Default policy: meets predefined quality floor and provides a meaningful measured
  benefit on the target workload, with uncertainty reported.
- General capability claim: transfer demonstrated beyond construction cases and
  repeated on more than one task family/model setting.

Numerical thresholds remain open until the intended workload and pilot variability
are known. Do not invent confidence from an arbitrary trial count.

## 13. Risks and decisions to revisit

| Risk / question | Initial treatment | Revisit when |
|---|---|---|
| Scratchpad becomes another context dump | Cheap durable storage, bounded manifests, explicit retrieval | Retrieval misses or repeated rereads dominate cost |
| Model cannot manage memory well | Strong baseline, supplied policies, fallback | Paired experiments identify a superior policy |
| Raw traces consume excessive disk | Quotas, references, explicit retention | Real workloads establish retention needs |
| Adaptive policies game metrics | Protected evaluators and held-out tasks | New adaptation objectives or domains are added |
| Library grows without benefit | Retrieval accounting, versions, retirement | Search overhead exceeds reuse benefit |
| Isolation is impractical on local Windows setup | Backend spike; truthful trusted-local mode | Available virtualization/tooling changes |
| Context building costs more than it saves | Shared budget and usage telemetry | Measured break-even differs by model/workload |
| General API becomes lowest common denominator | Arbitrary artifacts and extensible adapters | A modality requires richer streaming or interaction |
| Strong models are constrained by harness defaults | Raw access, replaceable policies, baseline comparisons | Stronger-model evaluations expose regressions |
| Program portability fails | Environment manifests and explicit dependencies | Cross-machine reuse becomes a real requirement |
| Recovery duplicates external effects | Journal + reconciliation; unknown outcome state | An adapter offers stronger idempotency guarantees |

Deferred decisions: exact isolated backend, retention duration, context-token
allocation defaults, library retrieval algorithm, statistical sample sizes, and
legacy support duration. Resolve these through the relevant stage; none blocks P0/P1.

## 14. Work ledger and durable decision process

P0 and P1 were implemented in the working tree on 2026-09-14. No benchmark spend
was authorized or performed.

### 2026-09-14 baseline and P1 implementation record

- Source baseline: commit `d26a4c9e6c2e622cd9633909e159f52c3576ee57`.
  The pre-implementation tracked diff hash was
  `64a07b72b52568aec59b2812e736cb21b8959f8f`; it covered unrelated evaluation
  changes in `experiments/falsification_eval/run_falsification_eval.py`,
  `experiments/hotpotqa_eval/run_eval.py`, and
  `tests/test_falsification_eval.py`. Those changes and the pre-existing untracked
  evaluation artifacts were preserved.
- Active entry points: the installed `reticle` script and `python -m reticle`
  dispatch through `reticle.cli`; `stateless_harness.py` and `harness.py` are
  root-level legacy runtime entry points. `reticle.cognitive.stateless_harness`
  is currently a compatibility import of the root module. Historical runtime and
  modality code under `archive/` is excluded from the active offline suite.
- Interpreter: `.runtime/test-venv/Scripts/python.exe`, CPython 3.13.15 on
  Windows 11 build 26200. The `.venv/Scripts/python.exe` uv trampoline remains
  unusable (`permission denied`), and the bare bundled interpreter lacks project
  dependencies. No dependency installation was needed.
- Selected offline core command:
  `.\\.runtime\\test-venv\\Scripts\\python.exe -m unittest discover -s tests -q`.
  Before P1 it ran 79 tests with one environment-sensitive stateless harness
  failure caused by invoking only the interpreter basename. After P1 it ran 86
  tests successfully. The supplemental root-module command ran 29 tests:
  `.\\.runtime\\test-venv\\Scripts\\python.exe -m unittest test_general_harness test_advanced_harness test_perception test_doc_generator test_calculator -q`.
- Integration status: Blender 5.0 is detected at the installed program path, but
  Blender execution and provider/network integration are outside the offline core
  suite. An OS-backed isolated worker backend does not exist yet and remains P4.
- P1 changed `stateless_harness.py`, `harness.py`, and focused tests. Regression
  evidence covers returned outline/command content and truncation, final-revision
  verification, conditional retry, dynamic module namespace behavior, pointer
  invalidation, the disabled-by-default editorial pass, and successful rollback
  after a failed editorial edit. The tracked P1 diff identifier is
  `c9ae0a54e54d84d9cd717f23f518dcdc1093593e`; the new legacy regression file has
  SHA-256 `1d9f9b427498c450fc9859fc5b0a5870eff105859ea9a40787c9f16866bc3615`.
  `py_compile` and `git diff --check` also passed.
- P2 added the authoritative new-runtime substrate under `reticle.runtime` and
  `reticle.storage`. Versioned task, tool-result, event, artifact, and final-result
  envelopes share schema version 1. The implementation provides immutable
  content-addressed blobs, integrity-checked reads, atomic reference updates,
  append-only single-writer events, operation-ID deduplication, conservative
  incomplete-tail handling, byte-derived workspace revisions, version-checked
  writes, checkpoints, and restart recovery that reports incomplete actions without
  replaying them. The P2 source manifest identifier is
  `931e3f31c909d618e0c82094db3f9d18cf3187ad`.
- P2 validation: the offline suite ran 91 tests successfully. A final wheel built
  offline with
  `uv build --offline --wheel --python .\\.runtime\\test-venv\\Scripts\\python.exe --cache-dir .\\.runtime\\uv-cache`.
  Its 31-file contents excluded the accidentally discovered nested `node_modules`
  tree. The wheel was extracted and invoked from
  `C:\\Users\\grant\\AppData\\Local\\Temp\\reticle-p2-final-7696000969a3416b831a40bfe7d3274d`;
  that installed copy persisted exact output, checkpointed an interrupted action,
  and recovered it as incomplete after restart. The existing setuptools license
  table emits a future deprecation warning; it does not affect this stage's wheel.
- P3 added arbitrary byte/string scratch write, exact/ranged read, reference and
  label listing, scoped search, durable priority pins, unpin, and reference-only
  forget operations. Immutable history remains readable after a name is forgotten.
  The shared observation service supports full, line-region, Python/text outline,
  and search views; every raw/view result is an artifact and bounded previews name
  the exact artifact and omitted byte count.
- P3 added persisted exact transcript messages and the `bounded-recent-v1` context
  policy. It retains the original task and contract, selects recent messages as
  protocol-safe tool-call/result units, spills large tool results to exact artifacts,
  records the actual provider request plus ordered selection provenance, reports
  pin overflow explicitly, and exposes a visible baseline fallback diagnostic when
  another policy fails. Context size is currently a deterministic byte budget with
  a declared approximate token estimate; actual provider token accounting remains
  P6 work. Non-evictable contract material may truthfully set `over_budget` when the
  configured limit cannot contain even the contract.
- P3 acceptance coverage is in `tests/test_context_runtime.py`: an unfinished plan,
  pin state, exact large evidence, and transcript survive restart; a forced 1,900-byte
  context retains both sides of a provider tool exchange; a forced 500-byte context
  exercises explicit pin overflow; observation modes, discovery, forgetting, and
  policy fallback are also covered. The offline suite ran 96 tests successfully and
  the supplemental root suite ran 29. `py_compile` and `git diff --check` passed.
  An offline wheel at `.runtime/wheel-test-p3/reticle-0.2.0-py3-none-any.whl`
  (SHA-256 `10126c31870213f00e223eeef9962a780b0e16298d24745da627da5aaf1580c7`)
  contained the new package directories and passed a restart/context smoke from
  `C:\Users\grant\AppData\Local\Temp\reticle-p3-c74d6b2a4e4f4843b8c8ad806b12df0f`.
  The P3 source manifest identifier is
  `37b2abe93e7cd36de37ff50d81f2dbfc188586bed539f95123349fe8d552d590`;
  it covers the P3 context, scratch, observation, session/export, artifact-store,
  and acceptance-test files. The known setuptools license warning remains
  non-blocking. No provider/network or benchmark run was performed.
- P4 is complete. The backend spike selected a hardened local OCI container as
  the first host-isolated backend and documents its trust boundary in
  `reticle/execution/BACKENDS.md`. `IsolatedOCIBackend` requires Docker or Podman,
  uses only the declared workspace mount, disables networking, makes the container
  root read-only, drops capabilities, enables `no-new-privileges`, runs as an
  unprivileged user, and applies PID, memory, and temporary-filesystem limits. It
  raises `BackendUnavailableError` instead of falling back to local execution.
- P4 implemented a distinct `TrustedLocalBackend`. On Windows it launches a waiting
  bootstrap, assigns that process to a kill-on-close Job Object, and only then
  releases the requested command. Tests show that success, nonzero exits, infinite
  loops, output floods, cancellation, worker crashes, and spawned descendants do
  not hang or escape the controller. Its allowlisted child environment does not
  imply filesystem or network isolation. Read-only executions can overlap while
  mutations use a session-scoped writer gate; concurrent identical artifact writes
  and journal reads were locked after the concurrency tests exposed the races.
- Generated program registration now parses metadata without evaluation. Ordinary
  modules, imports, globals, sibling helpers, and async entry points load in a
  supervised worker, and stdout/stderr are persisted through P2 tool-result
  artifacts. The legacy synthesized-tool path also has no remaining active
  controller-side `exec`. P4 tests are in `tests/test_execution_runtime.py`.
- Final P4 validation uses Podman 5.8.3 with a rootless WSL 2 machine and
  `python:3.13-alpine`. All 105 tests pass with both real-OCI gates enabled; the
  gates prove that the container started before rejecting an undeclared workspace
  write and outbound network connection, and exercise a registered program through
  the isolated worker with persisted stdout. All 29 supplemental tests pass;
  `py_compile` and `git diff --check` pass. The offline wheel
  `.runtime/wheel-test-p4-final/reticle-0.2.0-py3-none-any.whl` (SHA-256
  `35a023f80212df6f0d2b0cc76835030d3b6b2da1de823a72022a88702523a63f`)
  passed an installed isolated-worker/output-artifact smoke from
  `C:\Users\grant\AppData\Local\Temp\reticle-p4-final-c8a71adcdc5b40fca0d4b4351ab4aa76`.
  The final P4 source manifest identifier is
  `c445ea0fd3df13bbff066383a0c656dc903bb02277db70726b49d3a4a7bc195e`;
  it covers the execution package, backend contract, and P4 acceptance test.
- P5 is in progress. Checkpoint 1 adds durable, separately typed observation,
  measurement, and interpretation records in `reticle/evaluation`. Measurements
  carry procedure/scope/revision provenance; numeric values require an explicit
  bounded scale; interpretations must cite evidence. The three focused evidence
  tests in `tests/test_evaluation_runtime.py` pass.
- P5 checkpoint 2 adds independent acceptance over a controller-created candidate
  snapshot. Fixed evaluator inputs must resolve outside candidate authority;
  candidate-authored tests cannot replace them. Criterion coverage identity,
  evaluator infrastructure failures, human/unmeasurable outcomes, review artifacts,
  and reserved final-evaluation budget are reported separately. All nine focused
  P5 tests pass at this checkpoint.
- P5 checkpoint 3 migrates falsification memory to conditional attempt records
  containing program/environment versions, action, observations, failure category,
  and applicable conditions. Resolution requires the cited test identities to be
  observed passing under the same suite version, so partial runs and version drift
  cannot silently clear evidence. Acceptance now validates evaluator versions,
  graded scales/thresholds, final-revision stability, and the live OCI evaluator
  path. The combined P5/falsification checkpoint passes 34 focused tests.
- P5 checkpoint 4 propagates observed test IDs, fixed-suite hashes, program
  fingerprints, and Python environment revisions through the legacy falsification
  evaluation loop. This fixed the only full-suite regression without weakening the
  partial-run rule. All 121 tests pass with the P4 and P5 live OCI gates enabled.
- 2026-09-15 tree cleanup: the working tree was committed as `d711084` (unrelated
  evaluation fixes plus raw falsification run logs), `e51aa33` (P2–P4 substrate),
  `3ea3057` (P1 legacy repairs, which depend on `reticle.execution`), `e725e3e`
  (P5 checkpoints 1–4), and `b260659` (this plan). Each commit's staged snapshot
  was exported with `git checkout-index` and its focused tests passed in isolation;
  the final snapshot ran the full offline suite.
- P5 checkpoint 5 (complete). The installed-wheel gate exposed a real defect:
  `reticle.cognitive.__init__` eagerly imported the root-level `stateless_harness`
  module, so `reticle.cognitive.falsification` could not be imported from a wheel.
  Legacy harness names are now resolved lazily; `InstalledPackageImportTests`
  blocks root checkout modules and fails without the fix. Validation: 122 tests
  pass with `RETICLE_OCI_TEST_IMAGE=python:3.13-alpine`; the 29-test supplemental
  suite, `py_compile`, and `git diff --check` pass. Wheel
  `.runtime/wheel-test-p5/reticle-0.2.0-py3-none-any.whl` (SHA-256
  `a5878a93da2d14db4489d1f56836c34cde78ef1336760481956a11e3e87d2b60`) was extracted
  to `C:\Users\grant\AppData\Local\Temp\reticle-p5-wheel-1789453116` and run with
  `python -P` so the checkout was not importable. That run (smoke script SHA-256
  `d519df83b176f998507142eb75ad224da8afd28c9b27ba77e050ed41a8b66beb`) showed:
  (1) with a candidate-authored always-passing test, the fixed OCI evaluator
  rejected a wrong answer and accepted the correct one; (2) with real `unittest -v`
  output, a partial run of `test_b` left the `test_a` dead end unresolved;
  (3) human/unmeasurable criteria returned `needs_review` with a review artifact
  preserving criterion wording. A first smoke attempt used hand-written unittest
  output without the `====` separator; the parser correctly classified it as a
  collection error, so it was discarded as a script defect, not product evidence.
- Unresolved risk carried to P9: `reticle run` and `reticle.cognitive.stateless_harness`
  still require the root `stateless_harness.py` and `perception.py` modules (the
  latter imports only the standard library). An installed wheel cannot run the
  legacy CLI path until those move into the package behind root shims.

| Stage | Status | Completion evidence | Next action |
|---|---|---|---|
| P0 | Complete | Baseline record above; 86-test offline command passes | Baseline retained for later stages |
| P1 | Complete | Focused regressions plus offline and supplemental suites pass | Define P2 minimal versioned envelopes |
| P2 | Complete | Restart, exact-output, stale-write, incomplete-action, and external wheel gates pass | P3 complete; retain substrate for P4 |
| P3 | Complete | Restart/small-context, exact evidence, paired tools, pin overflow, fallback, and external wheel gates pass | Spike P4 Windows execution backends |
| P4 | Complete | 105 tests pass with real filesystem/network and isolated-worker OCI gates; external wheel smoke passes | Define P5 evidence and final-revision acceptance contracts |
| P5 | Complete | 122 tests pass with live OCI acceptance; supplemental suite passes; installed-wheel smoke passes all three exit gates after fixing the eager root import | Retained for P6 evaluator inputs |
| P6 | Not started | — | Choose the pinned task set, model(s), and budget rules; build the shared offline runner before any paid pilot |
| P7 | Not started | — | Versioned library + optional adaptive policy |
| P8 | Not started | — | Transfer and scaling study |
| P9 | Not started | — | Reconcile CLI/docs and rollout defaults |

For each completed stage, record commit/diff identifier, changed entry points,
validation command and outcome, artifact/report links, deviations, and unresolved
risks. Use `in progress`, `blocked`, `complete`, or `superseded` when appropriate.
Completion means the stage's exit criteria are met, not that its code was drafted.

Decision changes use this template:

```text
Date / decision ID:
Previous decision:
Proposed replacement:
Reason and alternatives considered:
Evidence or experiment needed:
Compatibility / migration impact:
Status: proposed | accepted | superseded
```

Initial decision record: D01–D14 are proposed in this document on 2026-09-14.
No adaptive policy has been selected as the new default.

## 15. Instructions for the next implementation session

1. Read this plan and applicable repository instructions; inspect the current diff.
2. Confirm which stages have evidence of completion. Do not trust stale board claims.
3. Start at P0, then P1. Preserve unrelated evaluation work and historical artifacts.
4. Implement the smallest coherent change satisfying the current stage's gate.
5. Run focused checks covering actual failure modes; broaden only as needed.
6. Update the work ledger with exact evidence and the next actionable step.
7. If findings contradict this proposal, revise the relevant decision explicitly.

The enduring test of the design is simple: can a stronger model or a better learned
program improve how the system works without fighting hard-coded cognitive rules?
The runtime should make that improvement executable, recoverable, and measurable.
