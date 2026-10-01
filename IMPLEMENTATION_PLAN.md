# Reticle: durable sessions, replaceable harnesses, fast experiments

Date: 2026-09-15.
Status: S1/S2 mechanics delivered; one E2 live fixture accepted. E3 (one session): runner
accounting and no-API controls passed. Run 1 stopped on provider HTTP 429; an endpoint probe returned
48/48 valid; run 2 (gemma @ Cloudflare) ended in a repeat stop, and run 3 (Qwen3-Coder-Next @ Parasail)
reached its 20-response budget; neither edited the library. After an interface revision, run 4 (Qwen, pressure-recent-v2,
toolset v2) again reached its budget without a library edit (section 7). Semantic retrieval and learned-procedure transfer remain unrun. 2026-09-27: positive control passed (Sonnet via CLI accepted through the Reticle interface and through Claude Code, card 006); S6 added; cards 007-009 proposed.
Supersedes: [the September 14 plan](archive/docs/IMPLEMENTATION_PLAN_2026-09-14.md), including its
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

The next research questions are whether semantic retrieval helps agents recover relevant
experience, and whether procedures learned from earlier tasks improve later repairs enough
to repay retrieval and learning costs. These are hypotheses, not promised results. Establish
a competent repair control first. Keep observation retention fixed during these studies;
the 512/4,000-byte versus pressure-based retention comparison is deferred.

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
- Establish a live repair control before testing cross-task memory and learned procedures.
- Defer installed-workflow polish and the retention comparison as experiment prerequisites.
- Search policies only after a competent control and trustworthy evaluator exist.

Non-goals for this sequence: hosted services, distributed scheduling, concurrent controller
swarms, universal memory ontologies, mandatory cognitive phases, an autonomous consolidation
daemon, and recreating every historical modality demo. Bounded procedure learning is in scope;
general symbolic reasoning is a separate deferred experiment (the bounded evidence-ontology experiment is active; the general solver/proof tool remains deferred).

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

### S3 - Competent live repair control

Depends on S1/S2 mechanics and the actual execution/evaluator gates. Reuse the existing
runner; an installed CLI is not a prerequisite.

1. Have `experiments/p6_pilot/run_pilot.py`'s provider client adopt the attempt-reporting
   protocol so every HTTP retry reserves and reconciles durable task resources. Verify retry
   exhaustion and resume without provider calls before live execution.
2. Select one development repair compatible with the current pinned OCI image. Initially
   exclude tasks needing missing linkify-it-py or suites exceeding the selected command
   timeout. Record exclusions and timeout in the card before assignment. If changing the
   image, rerun affected boundary and pipeline controls.
3. Run the provider/tool-schema smoke and E3: one task, at most three before trajectory
   review, with explicit attempt, tool, elapsed, token/cost, and campaign limits.
4. Fix demonstrated interface problems and freeze one usable model/provider, context policy,
   tool set, environment, evaluator, and budget configuration for the memory comparisons.

Use `pressure-recent-v1` as the initial fixed context policy; this is an operational choice,
not a claim that it beat the legacy retention policy. Add a stronger model only as a separately
labeled and budgeted diagnostic. Do not vary model, tools, and policy simultaneously.

Exit: valid live runs produce meaningful accepted repairs with trustworthy accounting and
evidence. If everything fails or passes, diagnose infrastructure/usability and adjust development
difficulty before comparing treatments. E2's one accepted changed-file fixture establishes
limited retrieval usability, not this repair gate. Remaining E2 fixtures are targeted diagnostics,
not a requirement to finish every fixture before E3.

### Coding-tool interface contract

Use familiar capabilities with explicit semantics; there is no universal coding-tool naming
standard. The interface is part of the versioned harness, not neutral plumbing. Keep the
canonical design here rather than adding another specification document.

| Target tool | Contract |
|---|---|
| `glob_files(glob, path=".")` | Recursively return matching workspace-relative file paths in stable order. `glob` matches filenames/paths, never file contents. Document the exact glob dialect and directory rules. |
| `search_text(query, path=".", file_glob="*", regex=false)` | Search file contents and return path, 1-based line number, and matching text. Literal matching is the default; regex is explicit, never inferred from punctuation. File selection is separate from content matching. |
| `read_file(path, start_line?, end_line?)` | 1-based inclusive line ranges; omitted bounds mean beginning/end. Report actual range and truncation, with an exact retrieval reference for omitted output. |
| `replace_text(path, old_text, new_text, replace_all=false)` | Exact text replacement; missing or ambiguous matches fail without mutation unless all matches were explicitly requested. Report replacement count. |
| `write_file(path, content)` | Create or overwrite the named workspace file. Explicitly document overwrite and parent-directory creation behavior. |
| `run(command, timeout_seconds?)` | Execute without shell interpretation, preserving the current backend contract. No implicit pipes, redirection, or variable expansion. Show command, exit code, timeout status, stdout/stderr, and output retrieval references. |

Keep authorized history, output paging, notes, and completion tools as supporting capabilities.
Do not expose duplicate synonymous tools in the same model-facing schema. Preserve existing
path confinement, resource accounting, immutable evidence, and independent acceptance.

Errors name the rejected argument, explain its meaning, and give one valid example. A missing
content query with `pattern`/`file_glob` supplied must explain that file selection is not a text
query; do not guess the user's intended expression. Unknown or conflicting arguments must be
reported rather than silently changing meaning. Empty results explicitly state the matching
mode and searched scope. Truncation is not an empty result. Process success is not task acceptance.

Remaining responses (including the current response), HTTP attempts, tool actions, active
time, and monetary resources appear automatically in every request from authoritative ledger
state, respecting tighter invocation limits. Original limits are labeled separately. This
information must survive context pressure; the agent should not need a status-tool call to
discover that its next response is its last. Missing billing remains explicitly unknown.

Migration status: toolset v2 and `pressure-recent-v2` already implement `file_glob`, improved
errors, and resource visibility; see the S3 delivery record. Pending card 004 retains its
existing `search`/`list_files` names and literal-only matching. Do not mutate that frozen card
or imply it tests the target names above. A subsequent toolset version can rename them to
`search_text`/`glob_files`; retain legacy dispatch for old recordings, with explicit alias
semantics. Regex support is an additional capability, not a rename: before exposing it,
specify dialect, case sensitivity, invalid-pattern errors, and bounded execution. Never
advertise `regex=true` until implemented and verified. Current literal mode remains valid
while this capability is pending.

For each implementation version, check a small usability fixture covering file discovery,
literal punctuation, file filtering, line boundaries, edit ambiguity, actionable error
recovery, and remaining-resource visibility. Add regex cases only for a regex-capable version.
Record schema/runner/policy versions and update affected controls before the next live card.
Measure rejected calls, recovery turns, failed lookups, first meaningful action, and accepted
repairs within budget. This is baseline usability work; bundled changes do not establish the
causal benefit of each individual rename or capability.

### D1 - Scientific-discovery simulator baseline (next workload after E3)

Use [D1's bounded design](experiments/session_harness/D1-discovery-simulator.md): identify a
hidden five-switch response rule through limited probes, then submit independently scored
predictions. Design/offline controls can overlap E3; live calibration follows its review and
a reliable inference configuration. Establish a no-memory simulator baseline before applying
S4/S5 treatments to this workload. D1 is a workload calibration, not another harness feature
or a substitute for the accepted-repair gate. One smoke and at most three development devices
before review; exact live budgets and devices belong in the run card.

### S4 - Semantic history retrieval pilot

Offline implementation can overlap S3; repair-utility comparisons require the S3 control.
Reuse the authorized history view and artifact store. Add a rebuildable semantic index with
stable session/event/artifact references. Index only authorized, redacted observations;
exclude credentials, controller records, hidden evaluator data, and retrieval-generated echoes.
Recheck authorization on reads. Record embedding model/version, chunking, corpus snapshot,
ranking parameters, query, returned IDs, latency, and indexing/retrieval cost.

Start with one bounded same-session fixture: the question paraphrases relevant old evidence,
the live source has changed, and plausible distractors exist. Compare literal versus semantic
retrieval over identical frozen history. Keep the tool contract, result rendering, context,
and budgets matched; declare any unavoidable interface differences. Results must link to
original evidence, and unavailable sources must remain explicitly unavailable.

Gate: source/authorization/rebuild checks pass; a live model recovers and correctly uses the
evidence. Retrieval calls or ranking scores alone are not success. Use E2-sized discovery
limits, then E4 paired screening and E5 confirmation only if justified.

Next, test cross-task retrieval on S3-compatible repair families. Export only an explicitly
authorized training-history corpus, with origin and outcome metadata, through the same read
boundary; session membership alone never grants cross-session access. Give both retrieval
arms the same corpus. Freeze it before later-task evaluation and prevent evaluation sessions
from entering another run's memory. Compare literal and semantic search; include a reset/no-prior-
memory reference when measuring the benefit of having prior experience at all.

Exit: report improvement, regression, or uncertainty, with accepted artifacts, cost, latency,
retrieval failures, and misleading-memory cases. A negative result completes the experiment.

### S5 - Persistent learned-procedure transfer pilot

Requires the S3 control and a usable S4 retrieval path, not a statistically significant S4 win.
Learn a small versioned library from completed training tasks. Start with textual procedures;
add executable skills only when the hypothesis requires them. Reuse `ProgramRegistry` and
supervised execution for executable variants rather than building a new runtime.

Each procedure records source episodes/artifacts, derivation prompt/model, version, intended
scope, preconditions, known failures, validation outcomes, and creation cost. It is derived
data, never a higher-priority instruction. Keep candidates distinct from validated procedures;
successful registration or three uses is not a promotion rule. Support rejection/retirement
without deleting source evidence. No autonomous consolidation daemon is required.

Compare retrieval-only against the same retrieval plus learned procedures on unseen task
variations. Match training exposure, task order, base tools, context policy, model, and task
budgets; procedure access is the declared treatment. Separate training, selection, and sealed
evaluation tasks by family/repository where feasible. Freeze corpus and library before
evaluation; reset each run to those snapshots. Charge learning, validation, rejected candidates,
and retrieval costs as well as later task execution. Evaluate whether later gains amortize them.

Use E4 discovery first and E5 only for a promising frozen candidate. Audit inappropriate reuse,
stale assumptions, and negative transfer. Any later adaptive-library arm needs its own protocol
with predeclared task order and update rules; do not pool it with frozen-library results.

Exit: measured transfer benefit, regression, or uncertainty. Broad capability or learning
claims require held-out gains, not counts of memories saved or procedures generated.

#### Lesson-store protocol amendments (2026-09-30)

Owner-approved for drafting; nothing below has been run. Motivation, not evidence: HyperSkill
(arXiv 2608.16114) built its skill memory on the test tasks, scored skills by gold-answer success,
and lost its advantage under a self-judge; several of its memory baselines scored below no memory.
"Memory in the Loop" (arXiv 2607.05690) traced misses to duplicate saves crowding a bounded read.
These rules apply to S4 memories, S5 procedures, and any later lesson store.

1. **Disjoint learning tasks.** Lessons are learned only on tasks disjoint from evaluation tasks.
   Record the training/selection/evaluation split (task IDs, family/repository, date) in the
   card before learning starts, and hash it into the protocol.
2. **Deployment-available signals only.** Writing, scoring, and pruning lessons use only what the
   agent could see in deployment: its own tool outputs, task description, and runtime observations.
   No gold answers, hidden evaluator inputs, or evaluator verdicts, consistent with model-visible
   history excluding hidden evaluator inputs (section 3.1) and with evaluator/acceptance logic being
   outside any candidate's scope (S6). Mutation tests and the independent evaluator are held-out
   verification of a frozen store, never a lesson-writing signal.
3. **Mandatory no-lessons arm.** Every lesson evaluation includes a matched no-lessons arm
   (same tasks, budgets, model, context policy). Memory can underperform no memory.
4. **Exposure bookkeeping.** Store per lesson, with provenance: times retrieved, and pass rate of
   runs it was retrieved into (by deployment-available signals during learning; by the held-out
   evaluator only after freezing). A pass rate below a preregistered threshold after >=3
   retrievals *queues* a held-out A/B retraction test for that lesson. It is never a promotion
   gate, because it is confounded by task difficulty.
5. **Dedup on write.** Before storing, compare against active lessons by normalized-string or
   static-embedding similarity. Preregister the threshold from development logs; record merges.
6. **Retrieval budget as an arm.** k in {0, 2, all}, preregistered; k = 0 is the no-lessons arm.
   Do not tune k on evaluation tasks.

### S6 - Bounded harness self-improvement loop (Self-Harness and ModularRSI, adapted)

Added 2026-09-27 after the positive control ([card 006](experiments/session_harness/E3-positive-control-006.md),
[report](experiments/session_harness/E3-positive-control-006-report.md)): Claude Sonnet 5 repaired `sqlparse-865`
through the Reticle interface (9 of 20 responses, 0 rejected calls) and through Claude Code's own loop (11 turns),
both accepted by the same evaluator. The interface does not stop a capable model; E3 runs 1-4 failed on the models.
The task is too easy for a capable model to separate harnesses, so S6 starts by building a task distribution
where the incumbent harness succeeds sometimes and fails sometimes. Nothing in this stage runs a paid provider;
the capable model is Claude via the local CLI (`--client claude-cli`, adapter v2), and cheap arms use free
OpenRouter models under the owner's daily request cap.

Sources adapted: [Self-Harness](https://arxiv.org/abs/2606.09498) (weakness mining by failure signature,
K minimal proposals, held-in/held-out acceptance) and [ModularRSI](https://arxiv.org/abs/2609.14857) (five
module scopes evolved one at a time, benchmark-disjoint evolution tasks, contrastive rollouts, validation
gates with rollback, integration stage). Not adopted from either: LLM-written harness code as the editable
surface (Reticle edits declared configuration first), and unbounded rounds.

**Governing test for this stage:** a candidate edit is promoted only when a supervisor outside the candidate
records paired evidence on sealed tasks, and the incumbent is preserved for rollback. The plan's governing test
(section 7) still applies.

#### What is editable and what is frozen

| Module (ModularRSI scope) | Reticle surface that may change | Frozen (trusted base) |
|---|---|---|
| Agent loop | Opening instructions; continuation and stagnation rules exposed as policy parameters | Controller lifecycle, journal, budgets, attempt accounting |
| Tool use | Tool descriptions, argument hints, rejection messages (toolset version bump) | Tool implementations, path confinement, no-shell contract |
| Observation management | `render_output_view` parameters (view size, tail-heavy rule), paging note text | Artifact store, exact output retrieval |
| Context management | Context policy version and parameters (budget, status position, page-wise omission) | Manifest recording, request validation, `context_budget_exhausted` stop |
| Task completion detection | `finish` instructions and pre-finish verification rule | Evaluator, acceptance logic, hidden inputs, promotion |

A **harness bundle** is the set of those surfaces at fixed versions; its hash enters the protocol hash. A
candidate is a descendant bundle in its own worktree. Promotion rewrites a pointer, never the incumbent.

#### The loop, one round

1. **Evidence.** Run the incumbent bundle on the evolution set with K=2 rollouts per task. Classify tasks as
   positive (2/2), contrastive (1/2), negative (0/2) as ModularRSI does. Contrastive tasks are the richest
   evidence: the same task, one accepted and one rejected trajectory.
2. **Weakness mining.** Compute a failure signature per rejected trajectory from the journal: verifier cause
   (fail-to-pass failed, pass-to-pass regression, no edit, budget, timeout), causal status (rejected calls,
   repeat stop, edit outside gold files, no verification before finish), and mechanism (phase labels from
   S6b). Cluster on exact signature; rank clusters by distinct-task support, then actionability. Each cluster
   becomes an evidence bundle: size, representative tasks, symptoms, contrastive pair if any, prior attempts.
3. **Proposal.** The proposer (Claude via CLI, separate invocation, no evaluator access) returns K=3 mutually
   distinct, minimal edits, each naming one cluster, one module, the expected effect and the regression risk.
   With probability 0.2 the target cluster is drawn at random from all clusters rather than the top-ranked one;
   with probability 0.1 the parent is a non-incumbent archive bundle. A no-change arm runs every round to
   measure evaluation noise.
4. **Validation gates, in order.** (a) Program check: bundle validates, E1 fixtures pass, no-API gold/noop
   controls pass. (b) Diff review: a second invocation, shown the edit and the evolution-set task list but not
   the held-out list, answers whether the edit encodes a task-specific solution; a yes rejects. (c) Paired
   execution: held-in D_in (the tasks that produced the evidence) and held-out D_oh (never shown to the
   proposer), 2 rollouts each, incumbent and candidate on identical tasks with arm order randomised.
5. **Acceptance.** Promote only if delta_in >= 0 and delta_oh >= 0 and max(delta_in, delta_oh) > 0 with the
   no-change arm's spread subtracted. Compatible accepted candidates from one round are merged; rejected ones
   are logged with their evidence. Every promoted bundle joins the archive with its lineage.
6. **Integration.** After each module has had one round, one integration round repairs cross-module
   conflicts only (retire redundancy, merge overlaps, in-place repair); no new capability.

Noise budget, stated up front: with 20 tasks at p ~ 0.5 and 2 rollouts, a per-arm acceptance rate has a
standard error near 8 points, so a single round can only see effects of roughly 15 points or more. Smaller
true effects will look like noise and be rejected. Mitigations, in order: pair on identical tasks, grow the
evolution set (the generator is parameterised for other repositories), and pool evidence across rounds before
claiming a general gain (section 5.6). A rejected small effect is a negative result, not a verdict.

#### Slices and gates

| Slice | Deliverable | Gate to pass | Depends on |
|---|---|---|---|
| S6a Task supply wiring and calibration | `materialize_workspace` applies `mutation_patch` and removes `hidden_paths`; `--tasks` selects the mutation file; [card 007](experiments/session_harness/E3-calibration-007.md) runs 20 distinct-failing-set tasks with Sonnet via CLI | Acceptance per task recorded; evolution set = tasks in the 30-70% zone (or a stratified sample if none); tasks at 2/2 leave the set | positive control (done) |
| S6b Trajectory labels and weakness mining | Phase-label schema (explore, reproduce, diagnose, edit, verify, stuck, repeat); 20-30 trajectories labelled by hand or by Claude with spot checks; `weakness_mining.py` producing signatures and clusters from the journal; classifier agreement measured per criterion if a cheap classifier (for example Jev) is adopted | Signatures reproduce from the journal alone; labelled set kept as the classifier's held-out set | S6a trajectories |
| S6c Harness bundle and one manual round | Bundle declaration with version hash in the protocol; [card 009](experiments/session_harness/E4-diagnostic-commitment-009.md): the first proposal is written by hand from run-4 and card-007 evidence | One paired round completes end to end with the acceptance rule applied; result may be reject | S6a, S6b signatures |
| S6d Executable run cards | A card is machine-readable (arms, tasks, budgets, rollouts, stop rules) and a runner executes it unattended, locally or on the cloud VM with the CLI, writing the report skeleton | The same card replays to identical protocol hashes; one card runs unattended end to end | S6a |
| S6e Automated rounds | Proposer, diff review, paired evaluation, supervisor promotion, archive; 2-3 rounds on one module (agent loop first), then integration | Each round produces a logged decision; at least one promoted or a documented null; no gate skipped | S6c shows a manual round works; S6d |

Parallel and independent of the loop: [card 008](experiments/session_harness/E1-cache-layout-008.md)
(cache-stable request layout, `pressure-recent-v4`: status last, page-wise omission) and the forecasting
workload ([FutureEval bot](https://www.metaculus.com/futureeval/); separate repository), which supplies sealed
weekly tasks with an external evaluator but is not part of S6's task set.

#### Parallel tracks and ownership

| Track | Worktree | Runs model calls | First output |
|---|---|---|---|
| S6a wiring + card 007 | `wt/s6a-calibration` | Yes: 20 tasks x 20 responses, Sonnet via CLI, serialised | acceptance table, evolution set |
| S6b labels + mining | `wt/s6b-mining` | Labelling only (Claude via CLI or classifier) | label schema, `weakness_mining.py`, cluster table for runs 1-4 and 006 |
| Card 008 cache layout | `wt/cache-layout-v4` | E1 fixtures (none); 3-pair check (Sonnet via CLI) | v4 policy, replay numbers, pair results |
| S6d card runner | `wt/s6d-cards` | None until a card is executed | card schema, runner, replay-hash check |
| Forecasting bot | `~/metac-bot` | Free OpenRouter models | testing-area runs; live only on owner go-ahead |

One live model run at a time on this machine; agents queue on a lock file under `.runtime/locks/`. Editing
worktrees run in parallel. S6c and S6e wait for S6a's acceptance table.

#### Out of scope for S6

LLM-written harness code as the editable surface; a general consolidation daemon; symbolic reasoning; paid
provider runs; claims of general improvement from a single round; running the loop on tasks outside the
calibrated zone.

### Deferred track - Installed vertical slice

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

Exit: installed workflow passes. This remains a delivery requirement before advertising the
installed session workflow, but does not gate S3-S5 experiments through the existing runner.

### Deferred experiment - Observation-retention comparison

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

### Deferred track - Bounded policy search and symbolic reasoning

2026-09-29 owner-directed update: the bounded evidence ontology experiment is now
implemented as optional `--reasoning memory` and `--reasoning symbolic` treatments.
Four executable fixtures pass in both modes; the live repair comparison is pending.
See [the protocol and limitations](experiments/neurosymbolic/README.md). This activates
one advisory evidence experiment; the general solver/proof tool remains deferred.

Revisit after the memory/procedure pilots and a trustworthy control. It is not a prerequisite
for them. Keep a frozen incumbent and candidate archive.
Start with manual/model-assisted offline proposals, not an autonomous recursive framework.
Execute model-authored policies in isolation with an authorized read-only session view.

Candidate record: source/prompt hash, parent, hypothesis, intended change, task/model scope,
development/selection results, costs, and disposition. Candidates cannot change the evaluator,
budgets, authority, or held-out data. Use E4/E5 gates for selection and promotion.

Loop: inspect failure -> predict effect -> propose -> contract-test -> screen -> select ->
confirm or reject. Allocate further trials by a declared rule. Preserve negative results.
Stop when candidate search fails to produce worthwhile gains within its budget.

Later work is conditional: learned context allocation, broader executable libraries, more
models/domains, and multiple workers. Symbolic reasoning is a separate tool-ablation study on
tasks with checkable constraints, not part of the memory treatments. Each needs a hypothesis
and cost account. Provisional program use is allowed; promotion never relies on a three-use rule.

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

### Experiment selection and documentation

Keep one competent baseline and at most one active challenger initially. Choose a recurring
failure from observed trajectories, state a falsifiable hypothesis, and change one mechanism.
Pair tasks and match model, environment, evaluator, and budgets; randomize arm order. Move
from mechanism check to development screen to confirmation on unseen tasks. Examine combinations
only when there is a specific interaction hypothesis: one feature could change another's benefit.
A shelved or negative result is useful evidence, not a reason to expand the feature matrix.

[The experiment register](experiments/REGISTER.md) holds one row per candidate, its smallest
comparison, status, and evidence link. Ideas need no separate proposal documents. This plan
owns sequencing and gates; the register is a backlog, not an implementation commitment.
Only an active experiment needs the concrete run card required below. Reuse existing report
and artifact locations; reports answer what changed, what happened, and what happens next.
Link results from the register rather than duplicating them. Keep historical delivery records
in place for now; do not create a separate methodology document.

### 5.2 Experiment ladder and default allocation

These are initial screening caps, not statistical sample sizes or spending authorization.
Each run card can lower them. Raise a cap only with a recorded reason and available authority.

| ID | Question | Initial allocation | Stop / next action |
|---|---|---|---|
| E0 | Are mechanics, recovery, and boundaries correct? | Focused offline reproductions plus golden/noop/breaker/gamer; no model calls | Any contract failure blocks dependent model runs; fix smallest cause |
| E1 | Does context rendering preserve the required evidence? | Three fixtures: ample budget, forced pressure, oversized latest exchange; no model calls | Missing latest outcome, unreachable history, or overflow ends trial immediately |
| E2 | Can the model discover and use omitted history? | One fixture first, up to 8 model turns; at most 3 fixtures before review | Audit first failure immediately; distinguish retrieval, tool schema, or provider failure |
| E3 | Can the control repair real code? | One development bug first, up to 20 model turns and a declared wall/cost cap; at most 3 tasks before review | Do not launch a batch behind a broken first trajectory; calibrate difficulty/provider |
| E4 | Does one retrieval/procedure treatment (or later policy change) look promising? | Three matched development task pairs, one run/arm/task before review | Stop on integrity failure; drop a clearly dominated candidate or allocate a second small block |
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
id: E4-semantic-001
status: proposed  # running | completed | invalidated | inconclusive
hypothesis: Semantic search recovers relevant paraphrased evidence and improves repairs within budget.
mechanism: Relevant old observations can be found without matching their original wording.
one_change: history retrieval ranking
control: literal-history-search
candidate: semantic-history-search
context_policy: pressure-recent-v1  # fixed across arms
memory_corpus_hash: null  # same authorized frozen corpus in both arms
library_hash: null  # no procedure library in this retrieval-only study
tasks_partition: development
task_ids: []  # pin before execution
runtime_tools_evaluator_environment_hashes: {}  # required before execution
model_provider_sampling: {}  # required before execution
budgets_per_run: {}  # attempts, turns, tokens/cost, tools, elapsed, final evaluation reserve
campaign_cap: {}  # explicit, independently enforced
assignment_seed: null  # record before randomization
primary_endpoint: accepted final artifact within the declared resource contract
diagnostics: [identical_rereads, history_retrieval_success, context_bytes, cost, elapsed]
failure_prediction: Irrelevant memories displace useful evidence, or retrieval cost erases the benefit.
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
| S2 | Complete (mechanics, no-API gates) | S2a offline gates; S2b E0 probes 24/24 and OCI controls 70/70 on 14 tasks; Docker, installed wheel, and live runs unrun |
| S3 | In progress (E3 session) | Smoke passed; E3 run 1 stopped on DeepInfra HTTP 429 after 4 responses (infrastructure class, no library edit, not accepted); [report](experiments/session_harness/E3-sqlparse-gemma-deepinfra-1.md). Endpoint probe: 6 routes, 48/48 valid ([results](experiments/session_harness/E3-endpoint-probe-1.md)). Run 2 @ Cloudflare: 18 responses, 0 provider errors, repeat stop, no library edit ([report](experiments/session_harness/E3-sqlparse-gemma-cloudflare-2.md)). Run 3 Qwen3-Coder-Next @ Parasail: 20 responses, response budget reached, 4 rejected `search` calls, no edit ([report](experiments/session_harness/E3-sqlparse-qwen-parasail-3.md)). Interface revised (pressure-recent-v2, toolset v2, runner v6; offline gates pass); [card 004](experiments/session_harness/E3-repair-control-004.md): U1 passed, run 4 reached 20 responses with no library edit and 3 rejected `cd /testbed && ...` commands ([report](experiments/session_harness/E3-sqlparse-qwen-parasail-4.md)). Toolset v3 (interface contract) passes offline and no-API gates; [card 005](experiments/session_harness/E3-repair-control-005.md) (U2 gate, then run 5) awaited approval; superseded 2026-09-30 by the positive control below, which passed, and by cards 007 and 018 (see "Current execution"); run 5 is not scheduled. Positive control ([card 006](experiments/session_harness/E3-positive-control-006.md), [report](experiments/session_harness/E3-positive-control-006-report.md)): Claude Sonnet 5 through the local Claude Code CLI repaired `sqlparse-865` through the Reticle interface (accepted in 9 of 20 responses, after one adapter fix and its single rerun) and in Claude Code's own loop (accepted in 11 of 20 turns, same code change), so runs 1-4 were limited by the model, not by the interface, task, runtime, or evaluator |
| S4 | Not started | Semantic index and paraphrase fixture; paired retrieval screen, then cross-task utility |
| D1 | Designed; not implemented | After E3 review: offline simulator controls, then no-memory discovery calibration; [design](experiments/session_harness/D1-discovery-simulator.md) |
| S5 | Not started | Versioned learned procedures; frozen-library transfer versus retrieval-only |
| S6 | Proposed 2026-09-27 | Bounded self-improvement loop (section 4, S6): S6a wiring + [card 007](experiments/session_harness/E3-calibration-007.md) calibration; S6b labels/mining; S6c [card 009](experiments/session_harness/E4-diagnostic-commitment-009.md) manual round; S6d executable cards; S6e automated rounds. Independent: [card 008](experiments/session_harness/E1-cache-layout-008.md) cache-stable layout. S6a (2026-09-27, `wt/s6a-calibration`): runner wiring done (`--tasks FILE.json`; `mutation_patch` applied, `hidden_paths` removed, workspace timestamps normalised); gold/noop controls on 2 mutation tasks pass in OCI; 20 tasks selected (seed 7); one-response CLI smoke passed; card 007 ready to run, awaiting approval (no calibration run yet) Card 007 complete 2026-09-28: 40/40 runs, acceptance 0.80 (0.68-0.92), 2 contrastive + 3 negative; below the 5-contrastive pass rule; [report](experiments/session_harness/E3-calibration-007-report.md); card 010 (difficulty) proposed. S6b on card 007 (2026-09-28, `wt/mining-c007`): 5 minable clusters (at most 2 tasks each), 5 evidence bundles, 533 responses labelled by rules and Jev (488/533 agree), diagnose development set (7 clear, 22 borderline), two rule fixes (context-omission refetch, look-only test discovery); [mining](experiments/session_harness/weakness-mining-c007.md) Treatments 2026-09-28 (`wt/treatments`, offline): three arm-selectable runner flags, each off by default with the incumbent's hash unchanged (`b0fda8c921ad` for `sqlparse-mut-001`) and hashed under `treatments` when on: `--completion finish-guard`, `--nudge midpoint`, `--oracle hidden-tests:3`; cards [013](experiments/session_harness/E4-finish-guard-013.md), [014](experiments/session_harness/E4-midpoint-nudge-014.md), [015](experiments/session_harness/E4-check-oracle-015.md) proposed (blocked only on approval) Card 018 (native harness reference, 2026-09-28, `wt/native-bank`, offline): `native_control.py` v2 runs any bank task through Claude Code's own loop with the runner's materializer and OCI evaluator and five leak checks; driver `run_native_bank.py` (40 runs, lock, resume) and `compare_native_c007.py` (paired, 2-sigma line); no-model controls gold accepted, noop rejected; complete 2026-09-28: native Claude Code 29/40 accepted vs Reticle 32/40, statistically indistinguishable at matched budgets; [card](experiments/session_harness/E3-native-arm-018.md), [report](experiments/session_harness/E3-native-arm-018-report.md) |
| S6d | Runner and schema built 2026-09-27 (offline; no model runs) | [Card schema](experiments/session_harness/cards/SCHEMA.md) ([JSON schema](experiments/session_harness/cards/card.schema.json)) and [`run_card.py`](experiments/session_harness/run_card.py): `--plan` expands a card into ordered `run_pilot.py` invocations (task x rollout x arm, seeded arm order per unit) with their expected protocol hashes and every blocker; `--execute` takes `.runtime/locks/live-run.lock`, checks each live arm's hash with the runner's `--dry-run`, runs the invocations one at a time with the section 5.3 retry and checkpoint rules, and writes the report skeleton; `--resume` skips completed runs. Cards [007](experiments/session_harness/cards/007.json) (S6a's seed-7 selection: the 2 recorded v2 controls + 40 runs named `c007-<task>-r<n>`, one protocol hash per task contract; blocked only on approval), [008](experiments/session_harness/cards/008.json) (gate 3) and [009](experiments/session_harness/cards/009.json) are restated. Replay: a card restating positive-control Arm R plans `6f1061c028c8`, identical to `pc-reticle-sonnet-2` in all 16 recorded config fields; card 007 plans the recorded v2 controls' `f825e41bc259` and `58dfdf928e0b` (18 fields each), and its 20 task hashes equal `run_pilot.py --dry-run`. The hash includes `evaluate_task.py`'s bytes as checked out (CRLF here; an LF checkout gives `0523064ac970`), so a Linux VM needs its own pinned hash. The gate's second half, one card run unattended end to end, is unrun |
| Installed workflow | Deferred | Wheel/CLI delivery checks; not an experiment prerequisite |
| Retention comparison | Deferred | Matched legacy versus pressure-policy study if still useful |
| Policy search / general solver | Deferred | Separate hypotheses after memory/procedure pilots; excludes the active evidence-ontology experiment |

**Current execution (2026-09-27):** the positive control is done (card 006: both arms accepted; the interface does not stop a capable model; `sqlparse-865` is too easy to separate harnesses). Next live action is card 007 (S6a) once the mutation-task wiring lands; cards 008 and 009 follow their stated gates. Four tracks run in parallel worktrees (S6 "Parallel tracks"); live model runs are serialised under `.runtime/locks/live-run.lock`. Card 005 (Qwen run 5) is superseded by the positive control and is not scheduled.

**Current execution (2026-09-30):** card 007 and card 018 are complete. The owner chose to design card 010 (harder mutation bank) first; it is being designed on branch `card/010-difficulty-calibration`. The evidence-ontology live run ([protocol](experiments/neurosymbolic/README.md)) follows on the card 010 bank.

**Owner decisions (2026-10-01):** "1. $144. 2. Yes. 3. Yes. 4. Yes", answering: (1) cloud credit balance is $144 (expires 2026-11-05); (2) launch card 023 (boltons calibration, $40 nested cap) in the cloud (launched 2026-10-01 as one-shot routine `trig_015orL1bg5GH8rm6TpZuaZz7` with the prompt in `experiments/cloud/RUN_IN_CLOUD-023.md`, results to branch `cloud-results-023`); (3) build an integration branch merging the cloud-card branches with the 2026-09-30 branches (not master); (4) add card 021's verifier-commit as a 4th arm of the evidence-ontology pilot (`experiments/neurosymbolic/README.md`).

**Owner decisions (2026-10-01, later):** "We can wait for card 10 to build the pooled registry. We can keep it as the transfer test." (1) A pooled task registry across cards 007, 023 and 010 (per-task outcomes, role tag: iterate / held-out / near-transfer test / pilot eval) is built offline after card 010's calibration finishes; it is the S6 loop's evidence store. (2) The boltons bank stays the near-transfer test as card 023 planned: its evolution set (015, 023, 056) is not used for iteration. Also approved the same day ("Yes you can run that"): an offline integrity audit of cloud cards 019-021 for the trusted-local `run` authority escape found in card 023. After the audit: "1. stop it 2. Yes keep it. 3. We can try to fix it now": card 021 invalidated; verifier-commit stays the pilot's 4th arm; the trusted-local `run` confinement fix is being built on `fix/cloud-run-confinement`, and cloud cards are paused until its probe passes on the VM. That fix is built: card field `"sandbox": "unshare-confined"`, a fail-closed new-root namespace sandbox with its own protocol hash, plus a report-only post-run scan (`run_integrity.py`). It passed the probe in a host container; the VM probe (`experiments/cloud/RUN_IN_CLOUD-confinement-probe.md`) first failed check 6 only: the marker was the `.gitignore` that `uv venv` writes into the task venv, not a repository or task source (the check matched the text `/.git`). Check 6 now matches path components, exempts only `.gitignore`/`.gitattributes`/`.gitkeep`, and also flags any sqlparse/boltons copy outside the workspace (e8150cd). The VM rerun passed: `SUMMARY 40 passed, 0 failed`, `CONFINEMENT: PASS` (branch `cloud-probe-confinement-2`, 939870d; copy in `experiments/cloud/probe-confinement-result.txt`). The fix is merged into this branch. Cloud cards may resume only with `"sandbox": "unshare-confined"` (a new protocol hash: new runs, no replay); no card uses the mode yet, and any cloud launch still needs the owner's approval of calls and cost.

**Implementation choices before any E3 model run in OCI** (from
`experiments/session_harness/S2b-oci-boundaries-controls.md`):

1. Done offline: the OpenRouter client in `run_pilot.py` (runner v4) reports every HTTP attempt to
   the task ledger; evidence is in the S3 step 1 delivery record. Live retry behavior is not yet observed.
2. Record a command timeout and initially select tasks whose suites fit it. Exclude the slow
   more-itertools suite from this first calibration (297.6 s OCI versus 13.7 s trusted-local).
3. Keep the current image initially; exclude tasks requiring missing linkify-it-py. If later
   adding that dependency, pin the new image and rerun the 70 controls and E0 probes.

Choices 2-3 are settled in `experiments/session_harness/E3-repair-control-001.md`: default `run`
timeout 120 s (600 s maximum), task `sqlparse-865`, current image, with markdown-it-py and
more-itertools excluded.

Resolve these routine choices in the run card. Model/provider selection and new spend remain
subject to the explicit campaign scope in section 5; this plan revision launches no paid runs.

Known S2b limitations carried forward: candidate code can tamper with in-container grading
artifacts (only the conftest gamer is tested); native file tools run on the host (path-confined);
Docker, installed-wheel, and live model runs are unrun. E2 `changed-file` ran once
(see `experiments/session_harness/E2-changed-file.md`); the next empirical action is E3 repair
calibration after runner accounting is connected. Other E2 fixtures remain available for
targeted diagnosis. Keep symbolic reasoning, boards, a consolidation daemon, and a broad model
matrix out of this first memory/procedure sequence.

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

### Delivery record: S2a durable resources, slice 2 (S2a complete)

- Source base: `70b6a9f` plus working-tree changes to `reticle/runtime/budgets.py`,
  `controller.py`, `__init__.py`, and `tests/test_s2_resources.py`.
- Opt-in `ProviderAttemptRecorder` journals and reserves every underlying provider attempt,
  including retries, with per-attempt cost reservation; the attempt budget stops retries
  without leaving an ambiguous request. Non-reporting clients keep one charge per request.
- Pause/deadline: `active_seconds` accrues only while a controller owns the session and is
  charged at each dispatch boundary; `deadline_utc` is wall-clock, runs while paused, and
  stops as `task_deadline_reached`.
- Supervisor-only `TaskBudgetLedger.adjust` replaces a reconciled charge with a journaled
  `task_resource_adjusted` audit event.
- Validation: focused S2 resource tests 18 passed; full offline suite 185 passed, three OCI
  skipped. Limitations, and runners not yet adopting the protocol, are in the
  [S2a report](experiments/session_harness/S2a-durable-resources-recovery.md). No provider
  calls or spend.

### Delivery record: S2b pinned OCI path, boundary probes, and pipeline controls

- Source base: `70b6a9f` plus the dirty tree; exact hashes in
  `experiments/session_harness/S2b-source-manifest.sha256`. Image ID `8b74015e5079…` (Podman 5.8.6).
- Runner v3 selects `trusted-local` or `oci` for both candidate commands and evaluation with guest
  interpreter and paths, pinned by image ID, recorded in the protocol hash; no fallback.
  `writable_mount` lets the evaluator write inside its private copy. Tool cache directories are
  outside source revision scope and evaluator snapshots.
- Failed hypothesis preserved: guest `--user 65534:65534` was sufficient for candidate work. Round 1
  controls all passed, but the tester control exposed `chmod` EPERM on the bind mount, which breaks
  pytest's cache in candidate runs. The fix is Podman `--userns keep-id`; every probe and control was rerun.
- Validation: full suite 191 passed with live OCI tests enabled (0 skipped); E0 probes 22/22 and 24/24;
  controls 70/70 matching expectation in both rounds. Report:
  [S2b](experiments/session_harness/S2b-oci-boundaries-controls.md).
- Limitations: in-container grader/candidate tampering remains a residual threat; native file tools
  run on the host (path-confined); Docker, installed wheel, and live model runs unrun; the full
  more-itertools suite is about 22 times slower in OCI; linkify-it-py is absent from both environments. No provider calls or spend.

### Delivery record: S3 step 1, runner v4 durable attempt accounting

- Source base: `70b6a9f` plus the dirty tree; hashes in `experiments/session_harness/E3-source-manifest.sha256`.
- `run_pilot.py` runner v4: the OpenRouter client is attempt-reporting. Each HTTP attempt checks
  the campaign cap, reserves task resources, is dispatched, and is reconciled, and is linked to its
  `calls.jsonl` row by `provider_attempt_id`. There are at most two retries per request. Per-run
  `model_responses`, `model_attempts`, `tool_actions`, `active_seconds`, and `cost_usd` (with a
  worst-case per-attempt reservation) are durable task budgets. The campaign cap and the opt-in
  repeat stop end a run as a recorded model error, never an aborted controller. `pressure-recent-v1`
  is available as an arm.
- Offline verification with a local HTTP stub (no provider calls): retries are reserved, reconciled,
  and logged; retry exhaustion stops, and resume then makes zero provider calls; a non-retryable
  status is charged once; the campaign cap leaves no phantom attempt; cost is reserved before
  dispatch. `tests/test_run_pilot_guards.py`: 10 passed. Full offline suite: 201 passed, 4 OCI skipped.
- No-API controls under the E3 configuration (OCI, `pressure-recent-v1`, repeat stop, E3 budgets):
  gold accepted, noop rejected on `sqlparse-865`.
- Python range check for the deferred installed track: `experiments/session_harness/python-range-check-2026-09-15.md`
  (3.9 fails in experiment code, 3.10 fails the output-flood test; 3.11, 3.13, and 3.14 pass).
- Next: approval of `experiments/session_harness/E3-repair-control-001.md` (a smoke of at most 3 attempts,
  then one E3 run of at most 30 attempts; at most $0.108 worst case). No provider calls or spend so far.

### Delivery record: S3 interface revision after E3 runs 1-3

- Observed usability issues, kept with E3 ([run 3 report](experiments/session_harness/E3-sqlparse-qwen-parasail-3.md)):
  the `search.pattern` name was read as a text pattern (4 of 20 calls rejected); rejections gave no recovery
  guidance; only static budget limits were visible, and run 3 ended at the response limit while exploring.
- `pressure-recent-v2` (new version; `pressure-recent-v1` unchanged): each request states remaining model
  responses, HTTP attempts, tool actions, active seconds, and cost, from the ledger and invocation limit at build
  time. The context builder's legacy fallback never receives the status.
- Toolset `reticle-tools-v2`: `file_glob` replaces `pattern` in `search`/`list_files` (the old name still works,
  with a note); rejections list accepted arguments and an example; ignored unknown arguments are reported; empty
  searches state literal matching. Matching semantics unchanged. Runner v6 records the toolset version in the protocol hash.
- Friction metrics from saved logs (`experiments/session_harness/interface_friction.py`): rejected rate, recovery
  turns, failed lookups, first command, first edit. Baseline for runs 1-3 is in the run 3 report.
- U1 usability fixture (`experiments/session_harness/run_u1.py`) with a fixed pass rule; no-API gold passed, noop failed.
- Validation: `tests/test_s3_interface.py` 12 passed; full offline suite 228 passed, 4 OCI skipped; no-API v6
  controls on `sqlparse-865`: gold accepted, noop rejected. No provider calls.
- Next: approval of [E3-repair-control-004](experiments/session_harness/E3-repair-control-004.md).

### Delivery record: toolset v3, implementing the coding-tool interface contract

- Source: hashes in `experiments/session_harness/E3-source-manifest.sha256`.
- `reticle-tools-v3`: `glob_files(glob, path)` and `search_text(query, path, file_glob)` replace `list_files`/`search`
  in the model-facing schema; the legacy names are dispatch-only, keep v2 behavior, and carry an explicit note.
  Globs use documented fnmatch rules and are case-sensitive on every platform (v2 was case-insensitive on Windows).
  Search results state mode and scope (path, file_glob, files searched, binary files skipped). Unknown arguments to
  schema tools are rejected with specific hints; `regex` is rejected as unavailable and not advertised. `run` explains
  shell operators and `cd`, and shows the command to run instead. Tool descriptions state line-range, overwrite,
  parent-directory, no-shell, paging, and acceptance semantics.
- `pressure-recent-v3`: labels original limits separately ("X remaining (limit Y)") and states attempts whose billing
  is unknown (`TaskBudgetLedger.unknown_billing_count`); `pressure-recent-v2` output unchanged. Runner v7.
- U2 usability fixture (`run_u1.py --fixture u2`) covers file discovery, literal punctuation, file selection, line
  boundaries, edit ambiguity (identical defective lines), error recovery, and resource visibility. No-API: gold
  passed, noop failed. Regex cases are omitted because no regex capability exists.
- Validation: `tests/test_toolset_v3.py` 16 passed; legacy behavior covered in `tests/test_s3_interface.py`; one
  controller test updated to the new shell-operator wording; full offline suite 244 passed, 4 OCI skipped. No-API
  controls on `sqlparse-865` under runner v7 and `pressure-recent-v3`: gold accepted, noop rejected. No provider calls.
- Limitation: these interface changes are bundled; outcomes cannot attribute benefit to an individual change.
- Next: approval of [E3-repair-control-005](experiments/session_harness/E3-repair-control-005.md).
