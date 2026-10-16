# Evidence-memory versus symbolic reasoning over a task horizon

The treatment is the existing four advisory inference rules, not arbitrary
theorem proving. Memory mode and symbolic mode share the evidence ontology,
reasoning tools, instructions, model, context policy, and resource limits.
Only symbolic mode returns derived staleness, coverage, nondiscrimination and
contradiction findings. Extraction is done by the agent in both arms; no graph
assertions are preseeded. If agents do not record the necessary declarations or
retrieve findings, that is a treatment-uptake result rather than evidence that
inference cannot help.

Two systems each span three tasks in the same durable session:

* Inventory reconciliation: implement event deduplication and accounting; extend
  it with expiring holds; then change deduplication scope, ordering relative to
  time filtering, winner selection, and expiry boundaries.
* Job scheduling: implement eligibility, ordering and capacity allocation;
  extend with dependencies; then change priority direction, deadline boundaries,
  deduplication winners, and whether earlier selections satisfy dependencies.

Each stage has explicit current semantics, visible nontrivial smoke checks, and
33 independent cases including randomized interaction cases and input-mutation
checks. Hidden cases, the reference implementation, and evaluator outcomes remain
outside agent workspaces and session journals. Later stages do not receive earlier
acceptance results. Candidate code and independent results are saved before each
next stage. Requirements and public checks change at task boundaries; the agent
must revalidate prior conclusions rather than continue from a fresh session.

One trajectory per family per arm is a calibration pilot, not a statistical
comparison. Arm order is counterbalanced by family. Gold and noop controls run
for every stage before any model calls. Budgets are 18 responses per stage, 54
per trajectory, and 216 responses overall. Context is bounded at 60,000 bytes.
Model is gpt-6.1-sol through the existing subscription connection. No other
context-board, nudge, finish-guard, knowledge-retrieval or hidden-check treatments
are enabled. Both arms use the corrected newline-aware editing tools.

Agent commands and live independent evaluation use Podman with networking off,
an isolated root, and only their respective workspace mounted. The preinstalled
Python image is resolved to its immutable ID before trials; no image is downloaded.
The host controller still performs workspace reads/edits and subscription calls.
Failure to launch a container ends the study, without local fallback. Source
hashes are frozen before execution and the runner refuses changed sources or
automatic replay. Results remain in `.runtime/reasoning-horizon-002`. The first
preflight exposed a Windows command-line length limit before any model calls;
evaluation now uses files in its private container workspace instead of passing
the full case payload on the command line.

Primary measures are independent correctness and integrity within the response
budget, both per stage and at the final regime-change stage. Secondary measures
are responses, actions, tokens, graph updates and rule exposures. Acceptance also
requires successful finish, unchanged protected files and no extra source files.
Reported correctness remains separate from finish so a budget failure cannot hide
a correct implementation. Symbolic rule exposures are counted when tool results
return findings; whether the model actually used a finding needs transcript review.

If this pilot saturates or has no rule uptake, expand difficulty or improve the
extraction interface in a new development run before freezing another comparison.
The next substantive study should add independent real-repository repair tasks,
more trajectories/seeds, and longer horizons with evidence that becomes irrelevant
or misleading. Do not select only tasks that show a symbolic advantage.

```powershell
.runtime/test-venv/Scripts/python.exe experiments/session_harness/reasoning_horizon.py --prepare
.runtime/test-venv/Scripts/python.exe experiments/session_harness/reasoning_horizon.py --execute
```
