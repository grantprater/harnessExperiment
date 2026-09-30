# Evidence ontology experiment

Implemented 2026-09-29, at the owner's request. This is an optional treatment
over the existing session journal, tools, context policy and independent evaluator.
No live repair campaign has been run.

## Arms and installation

Install the optional dependencies into the environment running the harness:

```powershell
uv pip install --python .runtime/test-venv/Scripts/python.exe '.[reasoning]'
```

| Runner option | Behavior |
|---|---|
| Omit `--reasoning` | Existing incumbent |
| `--reasoning memory` | Durable evidence ontology and model tools |
| `--reasoning symbolic` | Same ontology/tools, plus advisory inference |

The treatments enter config, results and protocol hashing. Hash inputs include
ontology/tool source digests, SHACL shapes, schemas and installed dependency versions.
Other treatments compose with this option; the first experiment should isolate it.
The optional dependencies are imported only when reasoning is enabled.

Example configuration inspection without model calls:

```powershell
.runtime/test-venv/Scripts/python.exe experiments/p6_pilot/run_pilot.py --client gold --reasoning symbolic --tasks experiments/mutation_tasks/tasks.mutations.json sqlparse-mut-001 --run-name ontology-config --dry-run
```

## Interface and provenance

`reasoning_state(offset=0, limit=50, focus=..., as_of_sequence=...)` returns runtime observations,
model assertions, semantic relations and, in symbolic mode, findings. It pages
entities, relations and findings at the same offset and reports separate totals
and a next offset. Carry the returned high-water sequence as `as_of_sequence` when
paging to keep graph membership fixed. Staleness always uses the current workspace.
Source output handles allow reading text truncated in the view.

`reasoning_update(entities=[...], relations=[...])` records up to 20 records in one
atomic journal event after validating the whole batch. Entities require immutable
IDs, a kind, text and authorized tool-output or task-description event IDs. `supersedes` revises a
previous assertion while retaining its provenance; cycles are rejected.

`assess_check(id=...)` retrieves the state around a recorded check. It executes
no code. All tools follow the existing tool action/result protocol and budgets.
There are no extra extraction model calls: the agent must explicitly use the tools.

Example update after a `run` observation appears in `reasoning_state`:

```json
{
  "entities": [
    {"id": "h-boundary", "kind": "hypothesis", "text": "The zero boundary is wrong", "evidence": ["evt_FROM_STATE"]},
    {"id": "check-negative", "kind": "check", "text": "Check the negative branch", "evidence": ["evt_FROM_STATE"], "observation": "obs:evt_FROM_STATE", "cases": ["negative"], "predictions": {"h-boundary": "passes"}}
  ],
  "relations": [{"source": "check-negative", "relation": "tests", "target": "h-boundary"}]
}
```

Entity types are requirement, hypothesis, check, change, code entity and runtime
observation. Relations include supports, contradicts, tests, depends_on, addresses
and supersedes. Entity kind/text/origin/provenance are validated through RDFLib and
SHACL; references, endpoint types, field constraints and cycles have explicit
application validation. The RDF projection includes semantic relations.

The authorized task description is projected as a runtime-owned requirement; hidden
criteria are excluded. Model assertions cannot supersede this source requirement.
Observations are reconstructed from the authorized history projection and recorded
action outcomes; the model cannot create or overwrite them. Controller/evaluator
events and evaluator-labeled observations cannot be cited as source evidence.
Assertions and findings never gain instruction authority or acceptance authority.

## Advisory rules and limits

| Rule | Condition |
|---|---|
| stale_observation | A check refers to a successful exit-zero command on an earlier workspace revision |
| narrow_coverage | A check addressing a requirement omits declared requirement cases |
| non_discriminating_check | Two active hypotheses predict the same outcome for a check |
| contradicted_hypothesis | A model-declared contradiction links an observation to an active hypothesis |

Findings cite evidence and are explicitly conditional on model assertions. Unknown
cases or predictions remain unknown. A successful command is not a passing test or
an accepted repair. Coverage compares exact case labels; it cannot prove semantic
coverage. Identical prediction strings are treated as identical outcomes.

Staleness conservatively uses the existing whole-workspace source revision. An
unrelated edit can therefore warn; dependency-specific invalidation is future work.
Superseded assertions remain in memory but are excluded from active-rule reasoning.
The journal is authoritative and the graph is rebuildable after restart. Model
entities are capped at 200 and relations at 500 per session. History projection is
currently a full journal scan, suitable for the short development experiments.

## Mechanism controls

```powershell
.runtime/test-venv/Scripts/python.exe experiments/neurosymbolic/run_fixtures.py --output experiments/neurosymbolic/fixture-report.json
.runtime/test-venv/Scripts/python.exe -m unittest discover -s tests -p test_reasoning.py -v
```

Four executable fixtures run in both modes: stale evidence, misleading reproduction,
competing diagnoses and interrupted investigation. They use actual file edits and
commands on a small zero-boundary defect, and a fresh runtime for recovery. The
checked-in report records all eight passing with zero model calls. These engineered
controls establish mechanism behavior, not agent effectiveness.

Validation on 2026-09-29: 17 focused ontology tests pass; the existing finish-guard
suite passes (22 tests, one skipped) and check-oracle suite passes (10 tests).
The full suite run executed 428 tests with six skipped and two failures in unchanged
areas: native-control's CLI-abort timing test took 60.1 seconds against a 45-second
limit, and a run-card test expects card 013 to be executable although its checked-in
status is completed. The final task-grounding/paging refinements were validated by
the focused suite after that full run. No live model calls were made.

## First live experiment

Develop on the inspected mutation failures; freeze schema, rules and tool descriptions
before evaluating untouched tasks. Randomize the order of incumbent, memory and
symbolic arms within each task/rollout block. Hold the model, context policy,
evaluator, backend and total task budgets fixed; include successful tasks to measure
overhead and harms. Charge reasoning tool actions to the same existing budget.

Primary outcome: accepted repairs within budget. Secondary outcomes: total model
responses/tokens/cost, tool actions, warning frequency, incorrect warnings, and
whether diagnosis changes after contradiction. Record how often the model uses the
tools: unused reasoning tools make this a usability failure rather than evidence
against symbolic inference. Do not tune against hidden evaluation outputs or copy
prior task graphs into confirmation runs. A new live campaign remains pending.

### Proposed amendments (2026-09-30, owner-approved for drafting; `injected` and `notes` deferred; not implemented or run)

**Owner decision (2026-09-30).** "2. Let's do 3 arms". The first live run uses the original
3 arms: incumbent, `--reasoning memory` and `--reasoning symbolic`. The `notes` and `injected`
arms are deferred; `injected` becomes the planned follow-up if the memory/symbolic arms show
low tool use. The task set comes from the card 010 bank's eval split once calibrated. The
spend estimate for 3 arms is $45-55 list price (~780 calls) at c013's 8 tasks x 2 rollouts;
it must be re-estimated for the card 010 task count and confirmed with the owner at launch.
The model/provider is not yet chosen.

**Owner decision (2026-09-30), injection mechanism.** "Yes option A makes sense, do that."
`injected` attaches the bounded summary and active findings to the *result* of the tool
action; the action always executes and nothing is ever rejected, so the arm stays purely
advisory and differs from `symbolic` only in delivery. A result attached to `finish` would
never be read, so there is no finish-time injection. Instead, injection follows edit actions
and command runs, the usual last observation before `finish`. The arm is implemented ahead of
need as the follow-up; it is not part of the first 3-arm run.

Motivation, not evidence: "Memory in the Loop" (arXiv 2607.05690) reports agents writing
to memory up to 17 times but reading once, gains from scaffold-wired checks rather than
model-chosen reads, a prompt-only "restate a NOTES block" arm matching or beating memory
tools, and misses from duplicate saves crowding a bounded read. Its evaluation is weak;
these amendments only add arms and metrics that would separate those explanations here.

**Arm `injected`.** Same ontology, schema and rules as `symbolic`. The scaffold injects the
`reasoning_state` summary plus advisory findings at two fixed points: before each edit
action (`replace_text`, `write_file`) and before `finish`. The model need not call a tool.
Findings stay advisory with no acceptance authority; injected tokens count against the
same budgets. Not implemented. What would change:

- `reticle/runtime/reasoning.py`: a bounded, deterministic `summary(limit=...)` view over
  `state()` (active hypotheses/checks, findings, high-water sequence), with a fixed token cap.
- `reticle/tools/reasoning.py`: an `InjectedReasoningTools` mixin (or a flag on
  `ReasoningTools`) that wraps the `replace_text`/`write_file`/`finish` handlers, the way
  `FinishGuardTools` wraps `finish`. The existing controller hook
  (`AgentController._intervene` → `message_after_response`) fires only after a response's
  results, so it cannot run *before* an edit. The first version either prepends the summary
  to that tool's result (the edit still executes) or rejects the first edit/finish once with
  the summary and accepts the retry. Pick one before development and preregister it; the
  first leaves the action sequence unchanged.
- `experiments/p6_pilot/run_pilot.py`: add `injected` to the `--reasoning` choices, compose
  the mixin in `build_tools`, add the injection template/version and cap to
  `reasoning_contract` so it enters the protocol hash, and record injection counts/tokens.
- Tests: injection at both points, cap respected, no authority fields, journal events
  are controller-owned and are not citable as evidence.

**Arm `notes`.** Prompt-only control with no reasoning tools: one fixed instruction to keep
and update a structured notes block (hypotheses, checks, observations, requirements) in
every reply. It separates the instruction effect from the tool effect. Needs a versioned
prompt addendum in the protocol hash; no new tools.

**Interpretation table** (fixed before any run; ">" means the preregistered paired
decision rule is met, "≈" means it is not):

| Pattern | Reading |
|---|---|
| notes ≈ memory ≈ symbolic > incumbent | The instruction to track state helps; the tools add nothing |
| notes > incumbent, memory/symbolic ≈ incumbent with low tool use | Instruction helps; tools unused. Usability, not ontology |
| memory ≈ incumbent with low tool use, injected > incumbent | Ontology content helps when delivered; model-chosen reads are the bottleneck |
| injected > symbolic ≈ memory, notes ≈ incumbent | Scaffold-wired delivery of the graph is the mechanism |
| symbolic > memory, both with high tool use | Advisory inference adds value beyond stored state |
| memory > incumbent, symbolic ≈ memory | Durable state helps; the rules add nothing |
| injected < incumbent, or incorrect-warning rate high | Injected findings mislead or crowd context; check token overhead first |
| All ≈ incumbent | No effect at this sample size; report as uncertain, not negative |

**Extra secondary metrics.** Cumulative prompt tokens per turn (per response, and cache
read/creation where the client reports it); reasoning tool reads (`reasoning_state`,
`assess_check`) versus writes (`reasoning_update`) per run; for `injected`, injection count
and injected tokens.

**Dedup on write (optional, small).** Before recording a hypothesis entity, check for a
near-duplicate active hypothesis by normalized-string or static-embedding similarity. The
threshold is preregistered from development logs. On a match, return the existing ID and
reject the duplicate (the model may `supersedes` it instead). Record dedup hits.

**Call and cost estimate.** Source: campaign c013 (`experiments/p6_pilot/runs/c013-*`,
[report](../session_harness/E4-finish-guard-013-report.md)), the most recent paired
p6_pilot mutation-task comparison. It used Sonnet 5 via the local CLI with 20 responses/run
and 24 attempts max. The per-run list-price cost is the sum of CLI `total_cost_usd` over
`calls.jsonl`: incumbent mean $0.94 (SD 0.64, range 0.15-1.80), 16.2 calls, 25.8k output
tokens; finish-guard arm mean $1.14 (max $2.04), 18.4 calls. The protocol above sets no task
count, so assume c013's shape: T = 8 tasks (5 evolution + 3 efficiency) x K = 2 rollouts, plus
gold/noop controls (no model calls).

Formula: runs = A x T x K; calls ≈ runs x 16.2 (cap runs x 24); cost ≈ runs x c,
with c from $0.94 (incumbent mean) to $1.14 (treatment-like mean); worst case c = $2.04.

| Design | Runs | Calls (expected / cap) | List-price cost (expected / worst) |
|---|---|---|---|
| (a) 3 arms: incumbent, memory, symbolic | 48 | ~780 / 1,152 | $45-55 / $98 |
| (b) 5 arms: + notes, injected | 80 | ~1,300 / 1,920 | $75-91 / $163 |
| Increment for the two arms | +32 | ~+520 / +768 | +$30-36 / +$65 |

Assumptions: treatment arms cost no more than the finish-guard arm; development runs on the
inspected failures are extra; a slower or cheaper model changes c linearly. Via the CLI
subscription, marginal billing is "unknown" and the cost is usage-limit headroom (c018 lost
runs to usage limits); on free OpenRouter models it is the daily request cap. No runs happen
until the owner approves the spend. The model, provider, task set and rollout count are not
yet chosen.
