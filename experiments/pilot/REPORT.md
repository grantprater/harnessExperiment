# Luna reading-interface pilot

Twelve fresh GPT-5.6 Luna agents (low reasoning effort), three tasks, two repetitions per reading mode. No conversation history was forked into participants.

Both modes passed 6/6 and 6/6 trials respectively. Foveation returned 51.3% less source-view text in aggregate, while requiring 32.0% more interface actions. This pilot measures a reading-efficiency tradeoff; it does not demonstrate a correctness advantage.

| Measurement | Full file | Outline + bounded regions |
|---|---:|---:|
| Public-suite successes | 6/6 | 6/6 |
| Source-view characters, total | 35,298 | 17,200 |
| All tool-returned characters, total | 38,270 | 20,576 |
| Interface actions, total | 50 | 66 |
| Mean actions per trial | 8.3 | 11.0 |
| Rejected edits | 1 | 5 |
| Mean elapsed seconds | 37.6 | 59.7 |
| API token usage | Unavailable | Unavailable |

## Per-trial results

| Task | Repeat | Mode | Passed | Actions | View characters | Rejected edits | Seconds |
|---|---:|---|---|---:|---:|---:|---:|
| billing | 1 | foveated | True | 8 | 3,100 | 0 | 26.6 |
| billing | 1 | full | True | 7 | 8,579 | 0 | 27.8 |
| billing | 2 | foveated | True | 8 | 3,094 | 0 | 29.6 |
| billing | 2 | full | True | 7 | 10,986 | 0 | 26.4 |
| kv | 1 | foveated | True | 21 | 5,110 | 4 | 157.4 |
| kv | 1 | full | True | 12 | 5,373 | 0 | 58.7 |
| kv | 2 | foveated | True | 9 | 2,442 | 1 | 53.4 |
| kv | 2 | full | True | 7 | 4,610 | 0 | 33.9 |
| pagination | 1 | foveated | True | 10 | 1,736 | 0 | 49.4 |
| pagination | 1 | full | True | 9 | 2,875 | 1 | 45.4 |
| pagination | 2 | foveated | True | 10 | 1,718 | 0 | 41.5 |
| pagination | 2 | full | True | 8 | 2,875 | 0 | 33.3 |

## Interpretation

The billing task has enough irrelevant source that an outline can help select a smaller region. The KV task requires implementing most methods in a small file, so reading much of that file is useful. One foveated KV trial incurred four rejected edits involving stale or incorrect line ranges; it recovered and passed. A full-file pagination trial also incurred a rejected edit. These outcomes motivate testing stable edit anchors separately from reading mode.

All tasks were solvable with both interfaces under the shared budget. A useful next test would increase repository size and irrelevant code while retaining a small required change. Include a third adaptive mode that permits full reads of small files. Use a direct API runner when credentials are available to measure actual input, output, and reasoning tokens; character reductions alone cannot establish lower cost.

## Validation

Original source files preserved: True. Initial and final snapshot hashes match for every audited trial: True.

Independent public-suite rechecks passed for 12/12 candidates. Supplementary contract checks passed for 12/12 candidates. These extra checks cover billing combinations, KV expiration and import boundaries, and generated pagination combinations. They were added during the pilot, not preregistered as the primary endpoint.

Five driver tests passed, covering bounded reads, atomic rejection of invalid syntax, protected tests and paths, failing final verification, and genuinely passing final verification.

## Scope and access

The configured OpenRouter connection rejected Luna with HTTP 402 and its free Liquid model with a daily-quota HTTP 429. Benchmark work therefore used the native agent runner with the requested `gpt-5.6-luna` alias, rather than the original HTTP harness. The exact model snapshot and API token counts are not exposed.

The controlled CLI equalizes file operations, tests, and action budgets. Native-agent system context and generic shell-tool access remain present; interface-only access is instructed rather than secured by OS isolation. Agents were not given task solutions or parent findings. Up to three independent trials shared the runner, so elapsed time is descriptive, not a clean latency comparison. Time starts at the first interface action and ends at final verification, excluding startup and final prose.

Two repeats on three small tasks are a pilot, not a statistically persuasive estimate of general capability. Source-view characters count each returned view once; they are not cumulative context usage. The experiment omits editorial refactoring, prediction pruning, and memory consolidation.

Protocol: [README](../README.md). Measurements: [summary.json](summary.json). Validation: [audit.json](audit.json). Each `runs/<run_id>/` directory contains complete interface action/result logs, the final source snapshot, and a candidate diff.
