# Observational and belief refinement in Reticle

The objective is an agent that improves how it acquires evidence, revises beliefs,
and chooses actions, with measured transfer to future tasks. The organizing unit
is a versioned procedure with stated applicability conditions and evidence.

The task loop observes, updates beliefs, acts, and checks outcomes. The refinement
loop identifies a recurring weakness, proposes an implementation, compares it
against the incumbent, and retains, restricts, or rejects its proposed scope.

## Existing components

| Component | Responsibility |
|---|---|
| Journal and artifact store | Exact provenance and immutable records |
| Evidence ontology | Explicit hypotheses, checks, dependency and contradiction assertions |
| Knowledge library | Evidence-linked cross-session claims and dependency invalidation |
| Extensions and runtime supervisor | Candidate implementation, smoke checks, activation and rollback |
| Experiment cards, drivers and telemetry | Frozen comparisons, resource accounting and recorded failures |
| Independent evaluation | Acceptance of resulting work, separate from tool execution |

Mechanical properties may be verified directly. Conditional policies require
experiments varying their proposed causal conditions. Semantic judgments require
experience and transfer evaluation; exact representation fidelity does not prove
decision quality. More successful examples alone do not establish generality.

## Implemented first connection

`reticle/runtime/refinements.py` stores proposal and conclusion revisions in the
existing runtime journal and artifact store. Records state the weakness,
hypothesis, implementation fingerprint, conditions, verified properties,
limitations and status. Comparative evidence is an immutable parent artifact;
the original proposal remains available. Scoped support requires accepted,
usage-reported paired trials and lower total tokens in the adaptive arm. The
record describes support on those fixtures, not broad reliability or permission
to activate an implementation. The evidence producer remains responsible for
its experiment design and independent scoring; this is not a security boundary.

No parallel memory database is introduced. Direct record loading is implemented;
automatic retrieval into model context, ontology publication and cross-session
knowledge import are not wired yet. Those should retain evidence provenance and
explicit scope rather than turn experiment conclusions into unconditional rules.

`reticle/runtime/observation_delta.py` implements an opt-in reusable selector:

1. Require observer-declared stable record IDs.
2. Require the baseline fingerprint in the caller's retained-prefix inventory.
3. Require changed identities to be at most 25% of the union of record IDs.
4. Require the serialized delta to be smaller than a complete snapshot.
5. Otherwise return a full snapshot.

Deltas replace or remove exact records and carry baseline/current fingerprints.
Reconstruction verifies the baseline and resulting snapshot. Null values,
additions, removals and JSON type changes are supported. The selector knows
nothing about semantic relevance. The 25% threshold is an initial explicit
parameter, not a derived optimum. Baseline retention is a caller contract:
availability on disk is insufficient. No default CLI tool output changes.

## Initial small comparison

Driver: `run_refinement_probe.py`. Protocol: `conditional-observation-probe-v1`.
Twelve one-decision calls: full versus adaptive, on six frozen fixtures:
checks and UI measurements, each with sparse changes, dense changes, or an absent
baseline. Each retained prefix contains an initial observation and a revised
observation; the final observation changes again. Both arms have identical
prefixes. A persistent failure omitted by a sparse delta must still be reported,
while historical resolved failures must not be reported.

Checks are the development domain; UI is a predeclared transfer domain. The same
selector and threshold apply to both. Dense and missing-baseline conditions must
produce requests identical to the full control. All fixtures, protocol and
proposal are saved before the first call. Order uses seed 41. No retries; stop on
the first provider error. Provider usage remains unknown when unreported.

The independent scorer checks exact current failed IDs and the next action.
Scoped support requires all twelve answers to pass and lower combined input plus
output tokens for adaptive observations. Otherwise the conclusion is inconclusive
or rejected for an observed adaptive decision failure. This is a smoke result,
not a statistical comparison; fallback cells intentionally measure no saving.
It is not an interactive generation task, visual style review, demonstration of
agent-discovered conditions, or end-to-end self-improvement.

```powershell
& ./.venv/Scripts/python.exe -m unittest tests.test_observation_refinements
& ./.venv/Scripts/python.exe experiments/observation_probe/run_refinement_probe.py --offline --run-dir experiments/observation_probe/runs/NEW-OFFLINE
& ./.venv/Scripts/python.exe experiments/observation_probe/run_refinement_probe.py --run-dir experiments/observation_probe/runs/NEW-LIVE
```

The output includes requests, provider call logs, fixtures, protocol, summary,
evaluation, a readable refinement record, and the journal/artifact store holding
immutable proposal/evidence/conclusion ancestry.

## Next increments

Updated 2026-10-03: both delta probes completed; results and active sequencing are
in [project state](../../docs/PROJECT_STATE.md). The subsequent
[post-edit check probe](../check_hook_probe/runs/live-001/REPORT.md) tested a workflow
transition and found that automatic execution accounted for most token savings.
Representation depends on substrate, goal and progress; deltas are one choice,
alongside AST, source, receipts and failure diagnostics.

The recommended next probe challenges failure diagnosis and one applicability
condition. Connecting the delta selector to a real observer remains possible
work, not a queued task. Model-proposed conditions and implementations should
follow stronger evidence about these narrow transitions. Candidate activation
and demonstrated improvement remain separate. The candidate does not define
its own acceptance criteria; evaluator improvements need a separate comparison.

Historical experiments remain evidence with their original limitations. The
first delta probe is supportive preliminary evidence; the autumn context-policy
comparison is evidence of costly recovery/continuity problems and provider
failures, not a ranking of general context policies.
