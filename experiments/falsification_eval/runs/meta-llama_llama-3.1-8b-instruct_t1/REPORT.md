# Falsification Extraction Evaluation (Exercism multi-turn repair)

- Model: `meta-llama/llama-3.1-8b-instruct` (temperature 0, via OpenRouter)
- Tasks: 23 Exercism Python practice exercises rated difficulty 5-9 (paasio excluded: missing test helper)
- Arms: last_failure | up to 1 turn(s) per task | prompt hash `e829dc56f1`
- Model-written code ran locally in a temporary directory with a 10s test timeout
- Report generated: 2026-09-15 02:04 UTC from `results.jsonl`
- Decision rule (fixed before running): On pass rate within the turn budget, an arm is called better than another only if the exact McNemar test on paired task outcomes gives p < 0.05. Repeat rates and token use are descriptive.

## Per-arm results

| Arm | Completed | Errors | Missing | Passed | Cumulative passes by turn | Mean turns (passed) | Repeated code, turns 2+ | Same failure as previous turn, turns 2+ | Missing APPROACH line | Mean prompt tokens per call by turn |
| :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |
| last_failure | 23 | 0 | 0 | 1/23 | 1 | 1.00 | n/a | n/a | 0/23 | 627 |

## Per-task results

| Task | last_failure |
| :-- | :-- |
| binary-search-tree | fail (5/10 failing) |
| bowling | fail (26/31 failing) |
| camicia | fail (28/28 failing) |
| custom-set | fail (tests could not run) |
| dot-dsl | fail (12/12 failing) |
| forth | fail (tests could not run) |
| knapsack | PASS turn 1 |
| rational-numbers | fail (13/43 failing) |
| relative-distance | fail (7/9 failing) |
| zebra-puzzle | fail (tests could not run) |
| affine-cipher | fail (12/16 failing) |
| alphametics | fail (7/10 failing) |
| bank-account | fail (10/16 failing) |
| react | fail (11/14 failing) |
| two-bucket | fail (tests could not run) |
| word-search | fail (tests could not run) |
| zipper | fail (13/14 failing) |
| book-store | fail (19/20 failing) |
| dominoes | fail (4/13 failing) |
| satellite | fail (9/9 failing) |
| sgf-parsing | fail (22/23 failing) |
| rest-api | fail (9/9 failing) |
| pov | fail (tests could not run) |
