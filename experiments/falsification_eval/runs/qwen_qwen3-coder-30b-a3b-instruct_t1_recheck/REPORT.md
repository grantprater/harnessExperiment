# Falsification Extraction Evaluation (Exercism multi-turn repair)

- Model: `qwen/qwen3-coder-30b-a3b-instruct` (temperature 0, via OpenRouter)
- Tasks: 5 Exercism Python practice exercises rated difficulty 5-9 (paasio excluded: missing test helper)
- Arms: last_failure | up to 1 turn(s) per task | prompt hash `e829dc56f1`
- Model-written code ran locally in a temporary directory with a 10s test timeout
- Report generated: 2026-09-15 02:24 UTC from `results.jsonl`
- Decision rule (fixed before running): On pass rate within the turn budget, an arm is called better than another only if the exact McNemar test on paired task outcomes gives p < 0.05. Repeat rates and token use are descriptive.

## Per-arm results

| Arm | Completed | Errors | Missing | Passed | Cumulative passes by turn | Mean turns (passed) | Repeated code, turns 2+ | Same failure as previous turn, turns 2+ | Missing APPROACH line | Mean prompt tokens per call by turn |
| :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |
| last_failure | 5 | 0 | 0 | 2/5 | 2 | 1.00 | n/a | n/a | 0/5 | 430 |

## Per-task results

| Task | last_failure |
| :-- | :-- |
| custom-set | PASS turn 1 |
| knapsack | PASS turn 1 |
| zebra-puzzle | fail (tests could not run) |
| book-store | fail (19/20 failing) |
| satellite | fail (1/9 failing) |
