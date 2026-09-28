# E4 finish guard 013 report

Date: 2026-09-28 (campaign 05:06 to 08:14 UTC)  
Card: `cards/013.json` (approved by the owner in session 2026-09-28); runner v8, `--completion finish-guard` (finish-guard-v2,
fail-then-pass criterion), Sonnet via CLI, OCI. Controls under the guard: gold accepted, noop rejected.
Evidence: `experiments/p6_pilot/runs/c013-*`, `runs/card-E4-finish-guard-013/campaign.jsonl`.

## Result

| | Incumbent | Finish guard |
|---|---|---|
| Accepted, evolution block (5 tasks x 2) | 2/10 (022-r1, 001-r2) | 1/10 (022-r1) |
| Accepted, efficiency block (3 tasks x 2) | 6/6 | 6/6 |
| Accepted, all | 8/16 | 7/16 |
| Pairs | 15 ties, 1 incumbent win (001-r2), 0 guard wins | |

On the 7 pairs both arms solved, guard minus incumbent: **responses +4.3 (SD 2.6; 2-sigma threshold at n=7 is 2.0)**,
seconds +21 (SD 38; not significant).

Per pair (accepted / responses / seconds):

| Task | Rollout | Incumbent | Finish guard |
|---|---|---|---|
| 001 | 1 | rejected / 20 / 555 | rejected / 20 / 764 |
| 001 | 2 | **accepted** / 20 / 686 | rejected / 17 / 1009 |
| 022 | 1 | accepted / 17 / 291 | accepted / 16 / 249 |
| 022 | 2 | rejected / 8 / 350 | rejected / 9 / 284 |
| 032 | 1 | rejected / 20 / 607 | rejected / 17 / 494 |
| 032 | 2 | rejected / 20 / 429 | rejected / 20 / 475 |
| 057 | 1 | rejected / 20 / 634 | rejected / 20 / 346 |
| 057 | 2 | rejected / 15 / 198 | rejected / 20 / 695 |
| 061 | 1 | rejected / 20 / 331 | rejected / 18 / 468 |
| 061 | 2 | rejected / 18 / 529 | rejected / 20 / 639 |
| 025 | 1 | accepted / 13 / 163 | accepted / 19 / 135 |
| 025 | 2 | accepted / 9 / 79 | accepted / 15 / 116 |
| 034 | 1 | accepted / 9 / 76 | accepted / 12 / 110 |
| 034 | 2 | accepted / 10 / 100 | accepted / 16 / 170 |
| 040 | 1 | accepted / 10 / 63 | accepted / 13 / 91 |
| 040 | 2 | accepted / 8 / 49 | accepted / 15 / 99 |

## Reading

- **Rejected.** The guard rescued no evolution-set task and cost about a third more responses on the tasks the incumbent
  already solves. This matches the offline replay in the treatment's own docstring: the fail-then-pass pair was absent on
  30 of 32 accepted card-007 runs too, so demanding it mostly taxes successful runs.
- The mechanism it targeted (finishing on a self-chosen check) is real, but forcing a reproduction does not fix the
  diagnosis behind it: on 057 and 061 the guard fired and the model reproduced its own wrong theory.
- Incumbent noise, again: 001 accepted in rollout 2 and not rollout 1; 022 the reverse; 025's incumbent times 163 s and
  79 s on the same task. The paired design absorbed this; an unpaired comparison would have read the 8/16 vs 7/16 as noise
  and missed the response cost.
- Decision per S6: not promoted. Recorded as a negative result; the candidate stays in the register as rejected with
  evidence.

## Not done

Trajectory labelling of the 32 runs; card 014 (midpoint nudge) and 015 (check oracle) not yet run.
