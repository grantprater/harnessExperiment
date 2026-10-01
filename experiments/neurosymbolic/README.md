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
| `--reasoning injected` | Same as symbolic, plus a bounded advisory summary appended to edit/run results (follow-up arm; see below) |

The treatments enter config, results and protocol hashing. Hash inputs include
ontology/tool source digests, SHACL shapes, schemas and installed dependency versions.
Other treatments compose with this option; the first experiment should isolate it.
The optional dependencies are imported only when reasoning is enabled.

Example configuration inspection without model calls:

```powershell
.runtime/test-venv/Scripts/python.exe experiments/p6_pilot/run_pilot.py --client gold --reasoning symbolic --tasks experiments/mutation_tasks/tasks.mutations.json sqlparse-mut-001 --run-name ontology-config --dry-run
```

With `--reasoning injected` the same command prints
`treatments (in the protocol hash): reasoning evidence-ontology evidence-ontology-v1 mode=injected`.

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

Four executable fixtures run in all three modes (memory, symbolic, injected): stale evidence,
misleading reproduction, competing diagnoses and interrupted investigation. They use actual file
edits and commands on a small zero-boundary defect, and a fresh runtime for recovery. In injected
mode they also check that the stale-evidence edit result and the misleading-reproduction run
result carry the expected finding, and that no citable observation contains injected text. The
checked-in report records all twelve passing with zero model calls (2026-09-30). These engineered
controls establish mechanism behavior, not agent effectiveness.

Validation of the injected arm on 2026-09-30: 25 focused ontology tests pass (8 new injected-arm
tests). These suites also pass: finish-guard (22 tests), check-oracle (10), output-paging (6),
pressure-context (12) and pressure-context-v4 (11). The full suite was not rerun. No model calls
were made.

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

### Proposed amendments (2026-09-30, owner-approved for drafting; `injected` implemented offline but not run; `notes` deferred and not implemented)

**Owner decision (2026-09-30).** "2. Let's do 3 arms" (extended to 4 arms on 2026-10-01; see below). The first live run uses the original
3 arms: incumbent, `--reasoning memory` and `--reasoning symbolic`. The `notes` and `injected`
arms are deferred; `injected` becomes the planned follow-up if the memory/symbolic arms show
low tool use. The task set comes from the card 010 bank's eval split once calibrated. The
spend estimate for 3 arms is $45-55 list price (~780 calls) at c013's 8 tasks x 2 rollouts;
it must be re-estimated for the card 010 task count and confirmed with the owner at launch.
The model/provider is not yet chosen.

**Owner decision (2026-09-30), model.** "Yeah we can pin sonnet 5 for now, though I think we pivot after this initial test run that we've gotten the comparison for to harder tasks and see if they extend/generalize". The pilot's model is pinned by
full ID, `claude-sonnet-5` via the Claude CLI, after the alias `sonnet` drifted to `claude-sonnet-5-5` with CLI
2.1.286 (card 010's alias drift note).

**Owner decision (2026-10-01), fourth arm.** Asked whether to add card 021's verifier-commit
treatment as a 4th arm (about +60 runs), replace `memory` with it, or keep 3 arms, the owner
answered "4. Yes", i.e. add it as a 4th arm. The pilot is now incumbent, `--reasoning memory`,
`--reasoning symbolic` and verifier-commit. Verifier-commit needs one frozen reproduction test per
task (card 021's `repro_verifiers.py generate`, 1-3 headless calls per task); those calls and the
final pilot size and spend are confirmed with the owner at launch. The arm's code comes from the
integration branch (cloud-card branches merged with this one; same decision message, "3. Yes").

**Owner decision (2026-10-01), after the cloud integrity audit.** Card 021's verifier-commit result was contaminated (two accepted runs read the answer outside the workspace; hard block 2/13 vs 0/15, p = 0.21 after exclusion; `experiments/cloud/INTEGRITY_AUDIT_019-021.md`). Asked whether to keep verifier-commit as the 4th arm, the owner answered "2. Yes keep it". The pilot runs on the OCI backend (no network, workspace-only mount, private /tmp), so it is the first clean test of the arm. Card 021 was set to invalidated ("1. stop it").

**Planned next step.** After the pilot on the card 010 bank (Sonnet 5), move to harder tasks to test whether
the comparison extends and generalizes. Not yet designed.

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

**Arm `injected`** (`--reasoning injected`). Implemented 2026-09-30 per the owner's option A;
not part of the first 3-arm run; no live runs. Same ontology, schema, rules and model tools
as `symbolic` (`reasoning_state`, `reasoning_update` and `assess_check` stay available).
The earlier draft of injecting *before* edits and at `finish` was replaced by the owner's
decision above. As built:

- Trigger: after every `replace_text`, `write_file` and `run` action (the harness's edit and
  command tools), whatever the action's status. Never after `finish` or any other tool. The action
  always executes; nothing is rejected, retried or blocked.
- Placement: `ReasoningTools.dispatch` appends the block to that action's result as the model sees
  it, after the raw result has been recorded as the tool output. Recorded observations, and so
  citable evidence, never contain injected text. The mixin is outermost, so finish-guard and oracle
  see the raw result.
- Block (`reasoning-injection-v1`): a header labelling it an advisory, runtime-generated summary
  conditional on model assertions; one line with the high-water sequence and counts of active
  hypotheses, checks and findings; then one line per active finding: rule, entity IDs, message.
  It has no instruction or acceptance wording.
- Cap: `INJECTION_MAX_CHARS = 1200` characters for the appended text, separator included, and
  `INJECTION_MAX_LINE_CHARS = 300` per finding line (cut lines end with `...`). Findings are kept in
  state order until the next one would not fit. The rest are replaced by
  `[truncated: K of N findings omitted; reasoning_state lists all]`.
- No-change behaviour: if there are no active findings and the digest (active hypothesis/check
  IDs and findings, excluding the ever-advancing sequence) equals that of the last injected block,
  nothing is appended. Active findings are repeated after every edit/run, even when unchanged. The
  first edit/run always injects, even with an empty graph.
- Provenance: each decision is a controller-only `reasoning_injection` journal event (not a
  model-visible history kind). It holds the text, character count, token estimate
  (UTF-8 bytes / 4, rounded up, as the context policy estimates) and truncation. Citing it in
  `reasoning_update` is rejected like any controller/evaluator event.
- Budgets: injected text is part of the tool result, so it counts against the existing context and
  response budgets. No new budget is added.
- Views: the block is exempt from view truncation on the newest result. The outcome carries
  `advisory_chars`, and the controller copies it into the message's private output metadata. When
  a context policy must cut that result (`bounded-transcript-v2`'s 4 KB newest view, or
  `pressure-recent-*` shrinking the newest exchange under pressure), the view is taken over the
  recorded output alone, with budget reduced by the block size. Its line counts therefore match
  `read_output`. The whole block follows the view. On older, cut results the block is dropped
  rather than shown as an unlabelled fragment. Older results kept whole (pressure policies) keep
  it. Before this fix, the tightest `pressure-recent-v3` budgets cut the header or the whole block
  from the newest `run` result, and older baseline previews showed a finding line without its
  header. `test_newest_long_run_result_always_shows_the_whole_block` renders ~25 KB failing-test
  output through the controller under both policies. Because the block is kept whole, the newest
  exchange at the very tightest budgets can exceed the context limit sooner. The controller then
  stops over budget, as it does for any oversize result.
- Tool text: the `reasoning_state` and `assess_check` descriptions now say findings are returned
  "in symbolic and injected modes". This changes the tool text the model sees in every reasoning
  arm, including memory and symbolic, and therefore their protocol hashes.
- Hashing: `reasoning_contract("injected")` adds the mode, template version, caps, trigger tools,
  placement and no-change rule, so the arm has its own protocol hash.
- Recording: the per-run reasoning record gains `tool_reads` (`reasoning_state`, `assess_check`
  calls) and `tool_writes` (`reasoning_update` calls) in every mode. Injected mode adds
  `injections`, `injections_skipped_no_change`, `injected_chars`, `injected_tokens_estimate`
  and `injections_truncated`.

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
