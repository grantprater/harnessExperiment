# Design critique: `IMPLEMENTATION_PLAN.md`

Date: 2026-09-15  
Scope: Review of Reticle's current implementation plan as a foundation for durable, experimentally validated, and eventually self-improving agent harnesses.

## Overall assessment

The current plan is unusually strong. It incorporates most of the architecture required for bounded recursive harness improvement: durable evidence, replaceable policies, explicit authority, independent evaluation, resource accounting, candidate isolation, held-out confirmation, and rollback-friendly versioning.

Its most important design principle is the governing test:

> Can a better model or policy improve task outcomes here without losing history, escaping authority, renewing its budget, or changing the meaning of success?

That is the correct standard. Reticle's principal innovation is not yet a particular memory, context, or symbolic-reasoning technique. It is the construction of an experimental environment in which those techniques can be tested without allowing a candidate system to redefine success.

The plan is therefore best described as a credible substrate for self-improvement, not yet a self-improving cognitive harness. Its operational foundations are substantially ahead of its demonstrated agent capability.

## What the plan gets right

### Clear separation of responsibilities

The distinction among session, context policy, controller, execution backend, evaluator, and experiment runner is excellent:

- The session preserves what happened; context is only a selected view.
- The controller manages continuation but does not own the sole copy of essential state.
- The execution backend enforces resource and authority boundaries.
- The evaluator, rather than the model, determines acceptance.
- The experiment runner versions assignments and prevents undocumented arm changes.

This separation permits policies and harnesses to be replaced without silently changing the task, evidence, budget, or definition of success.

### Strong evidence and recovery model

Stable event identities, immutable artifacts, high-water cursors, explicit omissions, request manifests, durable operation IDs, and conservative crash recovery are exactly the right substrate for long-horizon work. The plan correctly refuses to infer exactly-once behavior for ambiguous external effects.

Persisting budgets across controller replacement is particularly important: replacing or restarting an agent must not renew its resources. Keeping stop reason, acceptance, and resource status separate also avoids conflating normal termination with successful work.

### Sound experimental discipline

The E0-E5 ladder separates:

1. mechanical correctness;
2. model usability;
3. competent task execution;
4. comparative development screening; and
5. held-out confirmation.

The plan also correctly requires paired conditions, frozen protocols, recorded provider failures, explicit costs, negative-result retention, and final tasks kept away from the proposal generator. Counts of memories, summaries, or procedures are not treated as task success.

### Appropriate retreat from premature cognitive commitments

The superseded architecture treated boards, foveation, predictive pruning, sleep consolidation, and three-use skill crystallization as structural commitments. The current plan properly treats these as replaceable hypotheses. Symbolic reasoning and autonomous consolidation are deferred until a competent control and trustworthy evaluator exist.

This makes Reticle more scientifically credible than frameworks that commit to a cognitive metaphor before demonstrating task-level benefit.

## Immediate empirical blocker

Reticle has not yet established a competent live repair control. Four E3 runs produced no library edit. The latest run spent twenty responses exploring and constructing a reproduction before exhausting its response budget.

Tool friction explains part of this result, and toolset v3 directly addresses observed interface failures. The proposed U2 gate and run 5 are therefore reasonable. They should, however, be the final interface-patching iteration before changing the diagnosis.

If run 5 still produces no accepted repair, stop refining individual error messages and run a hard positive-control comparison:

1. Use a demonstrably capable coding model with the same Reticle interface and task.
2. Run the same model and task through a conventional coding harness under a matched budget.
3. Give Reticle an easier private or mutation-generated repair that definitely requires an existing-file edit.
4. Compare first meaningful command, first source edit, diagnosis quality, tests executed, cost, and final acceptance.

This separates four possible causes: an insufficient base model, poorly calibrated task difficulty, an inhibiting Reticle protocol, or a broken execution/evaluation path. Another weak-model failure on the same task would provide little additional information.

S4 and S5 task-utility comparisons should remain blocked until this positive control exists.

## Largest architectural gap: durable cognition

Reticle now has excellent durable operational state: contracts, events, artifacts, budgets, pending operations, and workspace identity. It does not yet have durable semantic task state. A controller must still reconstruct most of the following from transcript history and retrieval:

- active goals and subgoals;
- competing hypotheses;
- supporting and contradicting evidence;
- decisions and their rationale;
- invalidated assumptions;
- unresolved blockers;
- predicted and observed effects;
- intended next actions.

The historical mandatory epistemic board should not be restored. Instead, Reticle should add a generic, provenance-linked state-projection interface. Projections should be derived and rebuildable; the event journal remains authoritative. Policies may then test different schemas without embedding one cognitive theory in the runtime.

A minimal projection could contain:

```text
kind: hypothesis | goal | decision | blocker | prediction
status: active | supported | contradicted | resolved
sources: event/artifact references
created_as_of: journal sequence
supersedes: optional projection ID
confidence: optional and policy-defined
```

This would permit a controlled comparison between transcript reconstruction and explicit semantic state.

## Requirements for genuine harness self-improvement

The deferred loop—inspect failure, predict an effect, propose a candidate, contract-test it, screen it, and confirm or reject it—is directionally correct. Three additional contracts should be explicit before describing it as recursive harness improvement.

### Define the trusted computing base

The immutable supervisor surface should include:

- authority enforcement;
- budgets and accounting;
- event and artifact integrity;
- hidden evaluation inputs and acceptance logic;
- candidate promotion and rollback;
- credential and filesystem boundaries.

Candidate-modifiable surfaces may include context selection, retrieval and ranking, planning policy, tool descriptions, procedures, skills, and other explicitly declared harness components.

### Use descendant candidates, not in-place mutation

A candidate should create a versioned descendant of the incumbent in an isolated workspace or child session. It must not rewrite the currently running supervisor. Promotion should be a supervisor-owned operation based on recorded evidence, with the incumbent preserved for rollback.

### Harden evaluator isolation

The plan acknowledges that candidate code may currently share a process with grader code and can potentially tamper with in-container grading artifacts. This is tolerable for development calibration but blocks trustworthy self-modification. Before policy or harness-code search, hidden evaluation and promotion logic must be inaccessible to the candidate, not merely path-confined by convention.

The same concern applies to native host file tools. A self-modifying candidate should receive capability-scoped filesystem access to its candidate workspace, never general access to the incumbent, supervisor, evidence store, evaluator, or credentials.

## Secondary concerns

### The plan itself is becoming a context-management problem

At more than 900 lines, the current plan mixes stable architecture, active sequencing, status, historical delivery records, and experiment results. This raises the chance that a human or agent will follow stale context.

Prefer four linked artifacts:

- a short stable architecture and decision document;
- a machine-readable current-stage and next-action record;
- the experiment register;
- append-only delivery reports and evidence bundles.

The current plan should describe active contracts and gates. Historical evidence should remain discoverable without occupying the main operational document.

### Workload breadth will eventually matter

Code repair is a strong first domain because evaluation is relatively objective. D1 adds active inference, but neither alone supports broad claims about harness intelligence. The later evaluation portfolio should include:

- private or mutation-generated repairs with hidden tests;
- delayed-constraint tasks requiring durable user corrections;
- repeated task families where procedure transfer can amortize learning cost;
- stateful environments in which earlier actions change later observations.

Public repair dates do not reliably exclude model contamination, so generated or private tasks will be important for final claims.

## Recommended sequence

1. Complete toolset-v3's U2 gate and one final E3 run.
2. If it fails, freeze interface work and perform the positive-control comparison.
3. Establish at least one competent, accepted repair configuration.
4. Add replaceable provenance-linked semantic state projections.
5. Run the bounded semantic-retrieval and learned-procedure experiments.
6. Before any self-modifying policy search, formalize the trusted computing base and harden evaluator/filesystem isolation.
7. Introduce versioned descendant candidates, supervisor-owned promotion, and rollback.
8. Evaluate harness changes on sealed, diverse tasks with total adaptation cost included.

## Conclusion

Reticle is closer to the necessary architecture than most public agent frameworks because it understands that self-improvement is primarily an evaluation-and-governance problem, not a code-generation problem. Its evidence retention, authority boundaries, experimental ladder, and refusal to promote attractive but unvalidated cognitive ideas are substantial strengths.

The central risk is spending too long perfecting the laboratory before demonstrating that a capable agent can work effectively inside it. The next decisive result is not semantic memory or symbolic reasoning; it is a trustworthy positive control. Once that exists, Reticle will have a credible path toward accumulating software-level cognition while keeping evidence, evaluation, authority, and rollback outside the part that learns.
