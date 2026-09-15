# Falsification Extraction Evaluation (Exercism multi-turn repair)

- Model: `mistralai/mistral-small-3.2-24b-instruct` (temperature 0, via OpenRouter)
- Tasks: 23 Exercism Python practice exercises rated difficulty 5-9 (paasio excluded: missing test helper)
- Arms: last_failure | up to 1 turn(s) per task | prompt hash `e829dc56f1`
- Model-written code ran locally in a temporary directory with a 10s test timeout
- Report generated: 2026-09-15 02:12 UTC from `results.jsonl`
- Decision rule (fixed before running): On pass rate within the turn budget, an arm is called better than another only if the exact McNemar test on paired task outcomes gives p < 0.05. Repeat rates and token use are descriptive.

## Per-arm results

| Arm | Completed | Errors | Missing | Passed | Cumulative passes by turn | Mean turns (passed) | Repeated code, turns 2+ | Same failure as previous turn, turns 2+ | Missing APPROACH line | Mean prompt tokens per call by turn |
| :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |
| last_failure | 23 | 0 | 0 | 3/23 | 3 | 1.00 | n/a | n/a | 0/23 | 629 |

## Per-task results

| Task | last_failure |
| :-- | :-- |
| binary-search-tree | fail (5/10 failing) |
| bowling | fail (10/31 failing) |
| camicia | fail (28/28 failing) |
| custom-set | PASS turn 1 |
| dot-dsl | fail (12/12 failing) |
| forth | fail (54/54 failing) |
| knapsack | PASS turn 1 |
| rational-numbers | PASS turn 1 |
| relative-distance | fail (9/9 failing) |
| zebra-puzzle | fail (2/2 failing) |
| affine-cipher | fail (10/16 failing) |
| alphametics | fail (7/10 failing) |
| bank-account | fail (10/16 failing) |
| react | fail (9/14 failing) |
| two-bucket | fail (tests could not run) |
| word-search | fail (24/24 failing) |
| zipper | fail (12/14 failing) |
| book-store | fail (19/20 failing) |
| dominoes | fail (13/13 failing) |
| satellite | fail (9/9 failing) |
| sgf-parsing | fail (23/23 failing) |
| rest-api | fail (9/9 failing) |
| pov | fail (14/15 failing) |
