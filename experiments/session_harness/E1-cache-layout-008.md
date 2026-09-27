# E1 cache layout 008: `pressure-recent-v4` with status last and page-wise omission

Date: 2026-09-27  
Status: gates 1-2 passed, gate 3 not run ([gates 1-2 report](E1-cache-layout-008-gates12.md); mechanism evidence: [cache-cost replay of run 4](cache-cost-replay-run4.md))  
Stage: independent of S6; context-management module candidate.

## Hypothesis

Moving the per-turn resource status to the end of the request and omitting older material in pages rather
than one unit per turn keeps the request prefix byte-stable, so provider prefix caching reads most of each
request instead of rewriting it. Replay of run 4 predicts cached cost falling from 1.084x to 0.186x of
no-cache at unchanged bytes. The model-behaviour question is separate: does moving the status line change
how often the model notices its remaining budget?

## Change

`PressureRecentContextPolicyV4`: identical selection to v3; status rendered as the final message; under
pressure, omit the oldest units down to half the budget in one step, with the omission marker inserted once
per page. v3 unchanged. Toolset unchanged. Runner records policy version in the protocol hash as before.

## Gates

1. E1 fixtures (no model calls): ample budget, forced pressure, oversized latest exchange. Required: latest
   exchange always present, omitted history discoverable, no over-budget request, `context_budget_exhausted`
   raised where v3 raises it.
   **Passed (2026-09-27).** 11 tests in `tests/test_pressure_context_v4.py`, including 60 golden digests showing v1-v3 unchanged.
2. Replay (no model calls): `cache_replay.py` on run 4 and on the card-007 trajectories rebuilt under v4.
   Required: cacheable fraction above 85% at the 80,000-byte budget; per-page break count equals the number
   of pages, not turns, at 40,000 and 20,000.
   **Passed on run 4 (2026-09-27).** 92.4% cacheable at 80,000 bytes. Breaks equal pages: 1 = 1 at 40,000 and 4 = 4 at
   20,000; v3 breaks on 18 of 19 turns. The card-007 trajectories were not replayed, because none exist yet.
3. Behaviour check (model calls): 3 task pairs from the card-007 evolution set, incumbent v3 versus v4,
   Sonnet via CLI, 1 rollout each, arm order randomised. Measured: acceptance, responses used, whether the
   final response references remaining budget, first edit response. This is a mechanism screen, not a
   utility claim; 3 pairs cannot show a small effect.

## Budgets

Gate 3: 6 runs x 20 responses, serialised under the live-run lock. No monetary cost.

## Decision rule

Adopt v4 as the incumbent context policy for S6 if gates 1 and 2 pass and gate 3 shows no acceptance
regression (candidate wins or ties on 3 of 3 pairs). Otherwise keep v3 and record the result. Either way,
report the replay numbers on the calibration trajectories.

## Reporting

`experiments/session_harness/E1-cache-layout-008-report.md`; register row "Cache-stable request layout"
moves to "screened" or "shelved".
