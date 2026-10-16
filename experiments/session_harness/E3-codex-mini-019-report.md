# P019 exploratory pilot results

Status: completed; transcript audit pending.

Evidence class: exploratory pilot; separate from the controlled experiment cards.
Do not pool these results with existing cards or use them as equivalent evidence.
Other campaigns may run concurrently; timing and cache behavior are descriptive.

Reticle: Sonnet / pressure-recent-v4. Codex: gpt-6.1-sol / medium.

| Task | Arm | Accepted | Seconds | Responses | Tool actions | Cache usage |
|---|---|---|---|---|---|---|
| sqlparse-mut-032 | reticle | accepted | 78.9 | 11 | 14 | 35.1% reads |
| sqlparse-mut-032 | codex | rejected | 81.4 | 3 | 7 | [{"input_tokens": 125458, "cached_input_tokens": 89984, "cache_write_input_tokens": 0, "output_tokens": 1413, "reasoning_output_tokens": 85}] |
| sqlparse-mut-061 | codex | accepted | 92.5 | 3 | 7 | [{"input_tokens": 115084, "cached_input_tokens": 97792, "cache_write_input_tokens": 0, "output_tokens": 1766, "reasoning_output_tokens": 56}] |
| sqlparse-mut-061 | reticle | accepted | 56.6 | 10 | 10 | 53.5% reads |

Provider failures and leaks require separate review. Response counters differ by product.
Final diffs and independent acceptance results are saved per run. No statistical superiority claim.
