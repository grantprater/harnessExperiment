# D1: active identification of a hidden Boolean rule

Status: design only, 2026-09-15. No simulator implemented or model runs authorized by this
document. Next workload after E3 calibration; use the existing runtime and evidence stores.
This is a bounded system-identification task, not a test of general scientific ability.

## Question and sequence

Can an agent choose informative experiments and predict a hidden system's behavior within
a probe budget? First establish a no-memory baseline. Only then use this workload for S4/S5
retrieval and procedure-transfer experiments. Do not combine a new environment with a new
memory treatment in its first run.

Design and offline controls can proceed during E3. Schedule the first live D1 smoke after
the E3 review and a reliable provider/tool configuration. An accepted E3 repair remains the
repair-comparison gate; if repairs remain blocked for task-specific reasons, explicitly record
a D1-only baseline decision rather than claiming S3 complete. D1 still needs its own usability gate.

## Minimal world: five switches, one binary response

Each episode is a deterministic black-box device. An experiment sets five binary inputs
`[a,b,c,d,e]` and observes one binary output. Experiments are independent: no hidden temporal
state, noise, reset action, or natural-language clues about the particular device.

The public hypothesis family is:

`y = bias XOR term_1 XOR ... XOR term_k`, where `k` is 0 through 3.

Each distinct term is either one input or the AND of two different inputs. There are five
single-input terms and ten pair terms. Bias is 0 or 1. Thus there are
`2 * (1 + 15 + 105 + 455) = 1,152` candidate devices over 32 possible input settings.
Publish this family and explain XOR/AND with an unrelated worked example to every arm.
The hidden device's chosen terms and bias are never shown. This tests experimental design
within a known family, not discovery of an unrestricted law or an underlying causal graph.

Example development device (never a sealed evaluation device):
`y = b XOR (a AND d)`. Varying `a` has an effect only when `d=1`; single-switch probes from
all-zero inputs can therefore miss interactions. Exact explanation wording is not graded.

Advantages: exhaustive external scoring, cheap probes, interactions that reward targeted
experiments, and no dependency installation. Limitation: a solver can enumerate the family;
this is intentional for exact-solver diagnostics, not evidence of broad scientific reasoning.

## Agent interface and contract

Use a small ToolSuite-compatible adapter under the existing AgentController:

- `probe(inputs: five bits)` -> observation ID, exact inputs/output, remaining probe budget.
- `submit(bias: bit, terms: list of terms)` -> stores an immutable structured rule and ends
  the episode. For example, `{"bias": 0, "terms": [["b"], ["a", "d"]]}`. The supervisor
  expands it to all 32 predictions; no accuracy feedback until stopped.
- Retain authorized history retrieval and notes. No shell, arbitrary file access, or code
  execution in v1. Publish the rule schema and an example; no truth-table transcription required.

Accept zero through three distinct terms, each containing one known input or two different
known inputs. Canonicalize input and term order; reject duplicate terms, unknown names, and
out-of-family rules with schema-only errors. Never execute submitted text as code. A valid
but observation-inconsistent rule is accepted as a submission and scored after stopping;
validation must not provide an extra prediction or consistency-feedback channel.

Reject invalid inputs explicitly; they consume a tool action but not a physical probe.
Every valid probe, including a repeated input, consumes one probe. Journal intent/outcome
and deduplicate replay of the same operation ID so recovery cannot spend twice or return a
new observation. A new call ID to the same input is a new charged experiment.
Store submission before stopping; malformed submissions can be corrected within remaining
tool/model limits. Permit only one valid final submission. No feedback-driven resubmissions.

Select probe budget B from offline difficulty curves below, not an assumed ten-probe limit.
Initial non-probe limits: B+6 model responses, B+10 HTTP attempts, 2B+4 tool actions,
80,000 context bytes, 480 active seconds; at most two retries per request. Freeze these,
monetary limits, and output-token caps in the live card, checking that infrastructure limits
allow B probes and submission. Enforce probes durably as
an additional task resource. Stop at limits and retain the final state; reserve submission
capacity in the interface instructions. Missing valid submission counts as unsuccessful.

The supervisor owns the device, seed, hypothesis enumeration, and scorer outside the agent's
authorized view. The model receives only public instructions and its actual observations.
Do not put hidden device parameters into model-visible journal events, filenames, IDs, or
errors. Reuse authorization boundaries, but test this new adapter rather than assuming the
repository OCI tests establish its isolation. No OCI process is needed for pure supervisor
evaluation when the model has no code-execution capability.

## Scoring and independent controls

Primary: fraction of episodes whose submitted rule predicts all 32 settings correctly within
budget. Score behavior, not term ordering or explanation wording.
Secondary: accuracy over all 32 settings, accuracy over unprobed settings, probe count,
duplicate probes, model/provider costs, elapsed time, and infrastructure completion rate.
Whole-table accuracy includes already observed settings; report unprobed accuracy separately
so recalling probe outputs cannot masquerade as generalization. Exact table correctness has
the same target for every agent regardless of which probes it chose.

Keep controller stop, prediction correctness, and infrastructure status separate. Missing
submissions count as failures operationally; report infrastructure classifications separately
without removing them silently. Predictions are graded by the supervisor's truth table,
never by an agent-written test or a verbal claim of confidence.

### Budget and device sampling

Ten binary probes have at most 1,024 response paths for 1,152 possible devices. Under uniform
device sampling, exact identification is therefore bounded above by 1,024/1,152 (about 88.9%)
at ten probes, even for an optimal adaptive strategy. Eleven probes are necessary, not proven
sufficient, for guaranteed identification. This uniform-distribution bound must not be reported
as the ceiling of a differently weighted sample.

Measure fixed, random, and greedy strategies at B = 6, 8, 10, 11, 12, and 16 over the full
family before selecting a live budget. Sixteen is a constructive sufficient reference: probe
all-zero, five single-on, and ten pair-on inputs to recover every degree-at-most-two coefficient.
Select and justify a budget using reference identifiability and the gap between adaptive and
fixed/random performance. If using an ambiguity-limited budget, say so explicitly. A greedy
strategy's failure is not proof that the device was impossible to identify within that budget.

Uniform device sampling yields 2 constant, 30 one-term, 210 two-term, and 910 three-term
devices (about 79% three-term). Publish both that full-family result and per-stratum results.
Before model screening, declare sampling counts/weights by term count and interaction
structure (linear-only, disjoint pair interactions, shared-input interactions, and mixed
linear/pair dependencies as applicable). Define disjoint bins or explicit multi-label reporting
in the card. Simple interface fixtures are not the efficacy sample. Do not select only devices
on which the model happens to perform well or inflate aggregates by changing stratum weights.

### Measurement and reference controls

1. Gold control submits the correct rule: accepted. Toggle its bias: rejected (all outputs
   change, and the rule remains valid). Separately test the internal table comparator with
   a one-bit corruption. Noop: no submission, unsuccessful. Constant rules measure trivial
   baseline accuracy; malformed rules test validation, not scientific ability.
2. Exhaustively verify all 1,152 devices have distinct truth tables and generated observations
   match the scorer. Use an independently implemented direct evaluator and table generator.
3. Maintain the exact hypothesis set consistent with probes. The greedy information-gain
   reference chooses an unqueried input splitting that set most evenly (lexicographic tie
   break); it is not an optimal oracle. The random reference samples distinct inputs uniformly
   using recorded seeds. The fixed reference uses a published, output-independent schedule:
   zero, single-on inputs, pair-on inputs, each group lexicographically ordered. All use the
   same B, full public hypothesis family, and final inference rule: choose the first consistent
   candidate under a published canonical ordering. Continue to B for matched-budget curves;
   record the earliest unique identification separately.
4. Report exact success, earliest unique identification, and remaining-candidate counts by
   stratum. Repeat random schedules across fixed seeds and retain variance. Also report a
   separate per-input majority predictor (ties to 0) for bit accuracy only: its table may not
   represent any device and must not substitute for the exact-identification reference.
   Preserve calibration results and any resulting changes before freezing the live card.
5. Test probe exhaustion/resume, no duplicate dispatch on recovery, submission immutability,
   hidden-data denial, and score independence from agent notes/tool-success statuses.

### Separate experimental design from inference

- Exact solver on agent evidence: after every probe, reconstruct the consistent candidate set.
  Record its size and whether the final submitted rule is consistent. A unique candidate plus
  a wrong rule means the evidence was sufficient but inference/submission failed. Several
  candidates indicate unresolved ambiguity, which may reflect probe selection or budget;
  do not automatically attribute it to either. An empty set indicates an implementation or
  evidence-integrity failure in this noiseless family.
- Agent on sufficient evidence: in separate diagnostic runs, supply the fixed 16-observation
  schedule and allow rule submission with no probes. Use fresh sessions without prior exposure
  to that device, matched public instructions/model, and predeclared inference budgets. This
  tests inference and schema comprehension, not active discovery or matched-probe performance.
  Keep these outcomes out of the main success aggregate and seal their devices from transfer tests.

Hypothesis counts and reference choices are evaluator diagnostics only; never inject them
into active-discovery observations. A correct guess while several candidates remain is a
correct outcome but not demonstrated unique identification. Report that distinction.

## First live block and decision

Prepare a concrete card under this filename's D1 identifier before execution: exact source
hashes, provider/model, device IDs, seeds, budgets, and control results. Reuse provider and
accounting code; add no second agent loop and no general simulation/plugin framework.

Run offline controls and the sufficient-evidence diagnostic before attributing live discovery
failures to experiment choice. Run one development device, inspect the entire trajectory, then at most two additional
devices before review. Include a single-input case and an interaction case across that
block. Use control-measured difficulty; no task changes after seeing a model's result within
the same block. This is calibration, not a significance test or a harness comparison.

Advance when valid probes/submission work and the baseline shows meaningful prediction
ability on an interaction case. If all fail, inspect protocol understanding and probe choices;
if all pass easily, adjust development difficulty before screening treatments. A provider
outage calls for inference diagnosis, not a change to the scientific task or memory policy.

## Later transfer experiment, not part of the first block

Canonicalize devices over all 120 input permutations; use the resulting structural group ID
to split training, selection, and sealed structural-transfer evaluation. Conservatively group
bias complements together too, so changing a constant alone does not become structural novelty.
Verify group disjointness mechanically. Declare two separate endpoints: new instances of
familiar structures (distinct tables, explicit within-structure split) and held-out structures
(entire groups withheld). Do not pool them as one transfer claim. Randomize switch names/order
consistently across task and API; renaming alone is not an unseen law. Reserve the worked
example's group for development. If too few groups support a useful split, report that limit
and redesign before claiming structural transfer.
Freeze authorized training episodes before comparing no-prior-memory, retrieval-only, and
retrieval-plus-learned-procedure conditions in small sequential comparisons, not a full matrix.

Useful procedures should concern experiment choice (for example testing conditional effects),
not answers for a particular device. Include new input dependencies and changed bias/interactions
that invalidate previously successful device-specific conclusions. Make misleading-memory
cases explicit strata selected before running. Freeze libraries during evaluation and count
their creation/validation cost. Held-out data must not enter later agents' memory.

This finite Boolean family can test within-family transfer. Parameter variants are not proof
of general scientific learning. Only after a useful result should a separate family, such as
a small numerical response system, test whether experimental habits transfer across representations.

Deliver one implementation module plus focused tests, a concrete run card, and a concise
report linking raw evidence. Update the register with the decision; do not add another roadmap.
