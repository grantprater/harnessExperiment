# Project state: 2026-10-03

## Objective and organizing model

Build an agent that improves how it acquires evidence, updates beliefs and chooses
actions, with demonstrated transfer to future tasks. Recursive self-improvement
is a longer-term objective; current experiments do not demonstrate it.

The organizing unit is a **versioned observation procedure with applicability
conditions and evidence**. The task loop observes, revises beliefs, acts and checks.
The refinement loop identifies a weakness, proposes a candidate, compares it with
the incumbent and retains, restricts or rejects its scope.

Representation depends on substrate, goal and progress. For code repair, a useful
sequence may be repository map, AST outline, relevant source, edit, automatic
checks and failure diagnostics. A delta is one representation within that strategy.
The framework is not primarily a universal context-compaction algorithm.

Derive and verify mechanical invariants; empirically test conditional policies;
evaluate transfer for semantic judgments. More task examples alone do not establish
generality. Vary the proposed conditions and retain counterexamples.

## Where the components fit

| Component | Current role and implementation |
|---|---|
| Journal/artifacts | Authoritative exact history and evidence, `reticle/runtime/session.py` and storage |
| Ontology | Explicit model assertions, provenance and advisory rules, `runtime/reasoning.py` |
| Knowledge | Immutable cross-session snapshots and dependency rechecking, `runtime/knowledge.py` |
| Tools/representations | AST, exact source, search, patches, output retrieval, `tools/primitives.py` |
| Checks | Blender geometry, raster/CSS measurements and the experimental post-edit unittest hook |
| Self-modification | Generated extension staging plus supervised between-turn runtime activation |
| Comparison | Frozen fixtures/protocols, provider usage and independent acceptance |

Execution success, evidence support, task acceptance and candidate activation are
different events. Tests cover their declared contract; they do not establish every
user goal. Refinement candidates must not redefine their own acceptance criteria.

## Latest evidence

| Experiment | Observation | Interpretation and limit |
|---|---|---|
| [Original full/delta smoke probe](../experiments/observation_probe/runs/live-001/summary.json) | Four correct decisions; 33.9% less combined input | Retained-baseline exact deltas can help; predefined simple decisions, one sample per cell |
| [Conditional delta probe](../experiments/observation_probe/runs/refinement-live-001/REPORT.md) | 12/12 correct; sparse cells saved 9% input; whole probe saved 1.9% total tokens | Full fallback worked for dense changes and absent baselines; small records, retained history and metadata dilute savings |
| [Post-edit check probe](../experiments/check_hook_probe/runs/live-001/REPORT.md) | 18/18 accepted; automatic full saved 19.1% total tokens, selective saved 21.1%, relative to manual | Most saving came from fewer verification decisions; selective reporting added 2.4% over automatic full; three small saturated tasks |
| [Autumn context-policy comparison](../experiments/policy_bench/runs/autumn-10k-20261003-134451/REPORT.md) | Three usable asset pairs at 175k–217k total tokens; six attempts had provider errors | No policy winner; 10k target not reached; repeated retrieval/weak continuity suggest a problem, not proof of its cause |
| [Earlier reading-interface pilot](../experiments/pilot/REPORT.md) | Both modes 6/6; bounded views returned 51.3% less source text with 32% more actions | Smaller observations need not reduce total decision cost; API tokens unavailable |

Post-edit probe totals: manual 95,751 tokens/35 model calls; automatic full
77,439/28; automatic selective 75,555/28. Each condition accepted 6/6 attempts.
All usage was reported, cached input was zero, and no provider errors occurred.
Automatic arms ran ten checks each versus six in manual; each automatic arm had
four failed intermediate checks and six passing checks. No output retrievals.
Acceptance used fresh snapshots and original public tests, not hidden coverage.

Reasoning horizon results remain in `.runtime/reasoning-horizon-002/`: memory and
symbolic modes each accepted all six stages and used 80 responses. Stale-evidence
warnings appeared; no overall correctness/response-count benefit was demonstrated.
The earlier knowledge-transfer pilot is confounded; see the preserved
[October 2 handoff](history/HANDOFF_2026-10-02.md) for detail.

## What is implemented versus integrated

**CLI/runtime:** multi-turn sessions, intermediate output, token reports and optional
model usage feedback; patches, regex/context search, execution cwd/sequences;
runtime snapshots/rollback and generated extensions. Default context policy is
`minimal` with 32,000 bytes including schemas. `decision` is experimental opt-in;
`pressure-v4` is the cache-oriented comparator. No new policy was promoted.

**Delta selector:** [`runtime/observation_delta.py`](../reticle/runtime/observation_delta.py)
requires declared stable IDs, a baseline in the caller's retained-prefix inventory,
at most 25% changed record identities, and a smaller serialized result. Otherwise
it returns a full snapshot. Exact reconstruction is verified. It is reusable and
opt-in; it is not connected to default CLI observer outputs. The threshold is an
explicit initial parameter, not a derived optimum.

**Refinement records:** [`runtime/refinements.py`](../reticle/runtime/refinements.py)
uses the existing journal/artifact store for immutable proposal/evidence/conclusion
ancestry. The conditional delta probe exercised it. Its current support validator
specifically expects paired `full`/`adaptive` trials and lower total tokens; it is
not yet a general evaluator for every policy comparison. Direct loading works;
automatic ontology publication, knowledge-library import and model retrieval are
not wired. Model-discovered conditions and candidate generation are untested.

**Check hooks:** [`runtime/check_hooks.py`](../reticle/runtime/check_hooks.py) and
[`tools/check_hooks.py`](../reticle/tools/check_hooks.py) are opt-in experiment
components. They run fixed tests after each successful byte-changing source edit,
retain full evidence and provide full or selective observations. Manual verification
remains available. Empty/all-skipped, timeout, error and stale results are explicit.
They are not a configurable production CLI hook. Test choice, dependency-specific
triggers, coalescing multiple edits and selective successful-result silence remain
untested. The probe uses trusted-local execution and no generic command tool.

**Visual work:** Blender audits detect concrete topology/coplanar-overlap defects;
style tools measure raster palette and CSS tokens. Neither proves aesthetic quality,
composition consistency or subjective taste. Historical furniture scores were not
rewritten: all five saved assets showed overlap findings in the newer read-only audit.
Details and usage are in the [runtime guide](RUNTIME_GUIDE.md).

## Recommended next step, not an automatic task

Challenge one observation-strategy transition before extending the architecture:
repeat the post-edit comparison on a small task where a failed check genuinely
requires investigation. Add one applicability contrast such as verbose/concise
results or local/cross-file repair. Keep checks, schemas, model, representation
access and acceptance fixed. Measure accepted completion, all-attempt token use,
recovery reads and extra check execution cost. Current tasks saturate correctness.

Only after that evidence, consider a configurable real hook and explicit observer
selection conditions. Preserve full evidence on demand. Evaluate difficult check
selection and missing coverage separately from cheap established-check execution.
Do not build a general context-manager model or launch a broad task sweep merely
to continue this handoff. Earlier capability-boundary work remains a possible
task-supply direction, not the current automatic next action.

## Resume and workspace notes

Start with [NEXT_SESSION.md](../NEXT_SESSION.md), this state and the latest report.
Use [RUNTIME_GUIDE.md](RUNTIME_GUIDE.md) only for the features needed next.
The [refinement design](../experiments/observation_probe/REFINEMENT_DESIGN.md) explains
the record/selector mechanism; the [check probe](../experiments/check_hook_probe/README.md)
contains the reproducible protocol and commands. The older
[implementation ledger](../IMPLEMENTATION_PLAN.md) and
[experiment register](../experiments/REGISTER.md) retain earlier evidence.

No experiment is pending. The latest live comparison completed all 18 runs.
No new experiments or commits were requested by the wrap-up instruction.
The checkout has extensive pre-existing modified/untracked code and result files;
preserve them. Artifacts include prompts/generated code; do not blanket-publish
session directories or protected login files. Use the existing Reticle subscription
and exact model `gpt-6.1-sol` for authorized future experiments.

Latest focused code validation: 20 tests passed across `tests.test_check_hooks`,
`tests.test_observation_refinements` and `tests.test_toolset_v4`; all 27 offline
check-probe control attempts behaved as expected. Code tests were not rerun for
this documentation-only wrap-up. Local links in the rewritten entry points and
reference guide were checked, and all three live check-probe implementation hashes
still match the frozen protocol.

A local source/documentation checkpoint is saved under
`.runtime/checkpoints/wrapup-2026-10-03.zip`, with a hash manifest beside it.
It excludes credentials, environments and raw model sessions/results; those
results remain at the linked workspace paths. It is a local recovery snapshot,
not a commit, complete workspace backup or publication bundle.

The runtime guide preserves
feature details previously embedded in the README. The October 2 handoff was copied
unchanged before replacement. Historical reports and raw data remain unchanged.
