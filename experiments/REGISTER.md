# Experiment register

Candidate backlog; sequencing and gates live in [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
Keep one working baseline and one active challenger initially. A row is a hypothesis, not a
commitment to build it. Flesh out a run card only when activating a candidate; link its report
here afterward instead of repeating results. Status progresses from idea to mechanism check,
screen, confirmation, and adopted/shelved; negative or inconclusive findings remain linked.

Current prerequisite: E3 repair-control calibration. Controls passed on `sqlparse-865`. The first
live run under [E3-repair-control-001](session_harness/E3-repair-control-001.md) stopped on provider
HTTP 429 after 4 responses ([report](session_harness/E3-sqlparse-gemma-deepinfra-1.md)). Run 2 on Cloudflare
([E3-repair-control-002](session_harness/E3-repair-control-002.md)) had no provider errors but ended in a repeat
stop with no library edit ([report](session_harness/E3-sqlparse-gemma-cloudflare-2.md)). Run 3 with Qwen3-Coder-Next
([E3-repair-control-003](session_harness/E3-repair-control-003.md)) reached its 20-response budget without editing
([report](session_harness/E3-sqlparse-qwen-parasail-3.md)). Observed usability issues are kept with E3, and the revised
interface ran under [E3-repair-control-004](session_harness/E3-repair-control-004.md): the U1 fixture passed, and run 4 reached its budget without a
library edit ([report](session_harness/E3-sqlparse-qwen-parasail-4.md)). Toolset v3, implementing the plan's coding-tool interface
contract, is next under [E3-repair-control-005](session_harness/E3-repair-control-005.md) (U2 gate, then run 5). No accepted live repair from the weak models; the capable-model positive control (row below) was accepted in both arms.

| Candidate | Failure addressed | Smallest comparison | Status / evidence |
|---|---|---|---|
| Positive control (capable model) | Unknown whether E3 failures come from the model, the task, the interface, or the pipeline | Claude Sonnet 5 on `sqlparse-865`: Reticle interface (`--client claude-cli`) versus Claude Code's own loop, 20 responses and 20 minutes each | Done 2026-09-27: both accepted (Reticle 9 responses, 90.5 s, after one adapter fix; Claude Code 11 turns, 45.4 s), same code change; [card](session_harness/E3-positive-control-006.md), [report](session_harness/E3-positive-control-006-report.md) |
| Semantic history retrieval | Relevant experience missed because wording differs | Literal versus semantic search over identical frozen history | Next (S4); [existing literal-retrieval fixture](session_harness/E2-changed-file.md) is supporting evidence only |
| Learned procedures | Useful techniques repeatedly rediscovered | Retrieval alone versus retrieval plus a frozen learned-procedure library on unseen variations | Planned (S5) |
| Memory applicability checks | Stale or irrelevant experience misapplied | Same memories with versus without explicit preconditions/source-version checks | Idea |
| Stagnation response | Same failed action repeated without new evidence | Ordinary continuation versus a triggered different diagnostic probe | Idea |
| Diagnostic commitment | Editing begins before the failure is understood | Ordinary first edit versus prior cause prediction and discriminating test | Next (S6c): [card 009](session_harness/E4-diagnostic-commitment-009.md), blocked on card 007 |
| Verification allocation | Repairs finish without adequate checking | Current allocation versus a verification reserve within the same total budget | Idea |
| Constraint tracking | User constraints lost under context pressure | Fixed context policy with versus without a source-linked constraint record | Idea |
| Adaptive observation detail | Inspection spends context on irrelevant material | Fixed output detail versus agent-selected detail under matched budgets | Idea |
| Independent critique | Agent misses defects in its proposed repair | An extra ordinary continuation versus critique using the same extra compute allowance | Idea |
| Observation retention | Useful recent observations reduced prematurely | Legacy views versus pressure-based retention on the same repaired runtime | Deferred; [mechanical evidence](session_harness/E1-pressure-recent-v1.md), no utility claim |
| Symbolic reasoning tool | Explicit constraints reasoned about incorrectly | Same tasks with versus without a solver/proof-checking tool | Deferred; separate from memory treatments |
| Cache-stable request layout | Per-turn resource status at the head of the request breaks the provider prefix cache every turn, so cached pricing costs more than no caching | Recorded pressure-recent-v2 requests versus the same transcript with the status moved last (byte replay of run 4) | Proposed: [card 008](session_harness/E1-cache-layout-008.md) (v4 policy, E1 + replay + 3-pair check); mechanism check done, [report](session_harness/cache-cost-replay-run4.md) |
| Harness self-improvement loop (S6) | No mechanism turns recorded failures into tested harness edits | One manual round (card 009) before any automated round; per-module, held-in/held-out, supervisor promotion | Proposed 2026-09-27; see IMPLEMENTATION_PLAN.md S6 |
| Trajectory labelling and weakness mining (S6b) | Trajectory review is manual and does not scale to the mutation bank | Rule-based failure signatures from the journal versus signatures plus phase labels (Claude or a cheap classifier), agreement against 20-30 hand-labelled trajectories | Proposed; starts on card-007 trajectories |

Task supply: where the tasks that measure the candidates above come from.

| Candidate | Need addressed | Mechanism | Status / evidence |
|---|---|---|---|
| Mutation-generated repair tasks | Hundreds of sealed repair tasks with hidden tests; public repairs may be contaminated | One semantic mutation of a healthy upstream checkout per task, kept when the suite fails partly; statement from failing-test names and the first failure message | Prototype (76 tasks); calibration proposed as [card 007](session_harness/E3-calibration-007.md) (S6a, runner wiring pending); [report](mutation_tasks/REPORT.md) |

Next workload after E3: [D1 scientific-discovery simulator](session_harness/D1-discovery-simulator.md).
Design complete; implementation and live runs unrun. Calibrate limited-probe prediction of a
hidden Boolean system without memory first, then consider S4/S5 transfer treatments. This is
a workload axis, not another feature to cross with every candidate in the table.

For each activated candidate, declare accepted tasks within budget as the primary measure
unless its card justifies another measure. Record total costs and relevant harms. Decide
whether to advance, revise, or shelve after the first small block. Test combinations only
when a specific interaction hypothesis warrants them; keep evaluation tasks out of tuning
and memory/library updates.
