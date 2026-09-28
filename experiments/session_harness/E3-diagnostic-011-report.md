# E3 diagnostic 011 report: budget or diagnosis?

Date: 2026-09-28 (campaign 03:09 to 04:37 UTC)  
Card: [E3-diagnostic-011](E3-diagnostic-011.md) / `cards/011.json`; executed with `run_card.py --execute --resume`
under the owner's permission rule. Controls: `c011-control-gold` accepted 2/2, `c011-control-noop` rejected 2/2, both under
the 40-response budget. Evidence: `experiments/p6_pilot/runs/c011-*`, `runs/card-E3-diagnostic-011/campaign.jsonl`.

## Result

| Run | Stop | Accepted | Seconds |
|---|---|---|---:|
| 032-r1 | budget (40) | no | 1360 |
| 032-r2 | finish | no | 996 |
| 057-r1 | finish | no | 292 |
| 057-r2 | finish | no | 1046 |
| 061-r1 | finish | no | 1026 |
| 061-r2 | finish | no | 359 |

**0 of 6 accepted at 40 responses**, against 0 of 6 at 20 responses in card 007. Doubling the budget rescued none of
the three negative tasks. Five of the six runs used the extra budget to commit to a fix and call `finish`; the
evaluator rejected each. Only 032-r1 exhausted the budget.

## Decision

By the card's rule these are diagnosis failures, not pacing failures: pacing treatments (the midpoint nudge, card 014)
cannot help on these three tasks, and the mechanism is "finishing on a self-chosen check" (mechanism A in
[weakness-mining-c007.md](weakness-mining-c007.md)) in 5 of 6 runs. Treatments that change what a check must cover
(finish guard, card 013) or that give a bounded signal about the hidden tests (check oracle, card 015) are the ones
with a mechanism on these tasks. The three tasks stay in the evolution set as negatives.

## Not done

No trajectory labelling of these 6 runs yet (S6b input); no journal mining beyond the stop and acceptance facts.
