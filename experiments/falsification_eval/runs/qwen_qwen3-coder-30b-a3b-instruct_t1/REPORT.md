# Falsification Extraction Evaluation (Exercism multi-turn repair)

- Model: `qwen/qwen3-coder-30b-a3b-instruct` (temperature 0, via OpenRouter)
- Tasks: 23 Exercism Python practice exercises rated difficulty 5-9 (paasio excluded: missing test helper)
- Arms: last_failure | up to 1 turn(s) per task | prompt hash `e829dc56f1`
- Model-written code ran locally in a temporary directory with a 10s test timeout
- Report generated: 2026-09-15 02:18 UTC from `results.jsonl`
- Decision rule (fixed before running): On pass rate within the turn budget, an arm is called better than another only if the exact McNemar test on paired task outcomes gives p < 0.05. Repeat rates and token use are descriptive.

## Per-arm results

| Arm | Completed | Errors | Missing | Passed | Cumulative passes by turn | Mean turns (passed) | Repeated code, turns 2+ | Same failure as previous turn, turns 2+ | Missing APPROACH line | Mean prompt tokens per call by turn |
| :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |
| last_failure | 23 | 0 | 0 | 7/23 | 7 | 1.00 | n/a | n/a | 5/23 | 627 |

## Per-task results

| Task | last_failure |
| :-- | :-- |
| binary-search-tree | PASS turn 1 |
| bowling | fail (14/31 failing) |
| camicia | fail (28/28 failing) |
| custom-set | fail (tests could not run) |
| dot-dsl | fail (6/12 failing) |
| forth | fail (46/54 failing) |
| knapsack | fail (tests could not run) |
| rational-numbers | PASS turn 1 |
| relative-distance | fail (7/9 failing) |
| zebra-puzzle | fail (tests could not run) |
| affine-cipher | PASS turn 1 |
| alphametics | PASS turn 1 |
| bank-account | PASS turn 1 |
| react | fail (9/14 failing) |
| two-bucket | PASS turn 1 |
| word-search | PASS turn 1 |
| zipper | fail (2/14 failing) |
| book-store | fail (tests could not run) |
| dominoes | fail (6/13 failing) |
| satellite | fail (tests could not run) |
| sgf-parsing | fail (22/23 failing) |
| rest-api | fail (9/9 failing) |
| pov | fail (14/15 failing) |
