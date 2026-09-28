# E3 calibration 012: mutation-task bank with a free OpenRouter model

Date: 2026-09-28  
Status: stopped early 2026-09-28 by the owner after 12 runs: 1 accepted (040-r1, at the budget after a correct edit), 11 rejected at the 20-response budget with no source edit. Nemotron 3 Super floors on this bank; its trajectories show real tool use but about 240 reasoning tokens per response and no commitment. Free daily requests conserved for Ultra (card 017).  
Stage: S6a follow-up. Same 20 tasks, policy, toolset, backend and per-run budgets as card 007; the only change is the client and model: `openrouter` / `nvidia/nemotron-3-super-120b-a12b:free`.

Question: where does a free model land on the bank that Sonnet solved at 80%? The card passes if acceptance is between 30% and 70% or at least 5 tasks are contrastive; then the S6 loop runs on this arm, where the harness has the most leverage. Results go in `E3-calibration-012-free-report.md`.
