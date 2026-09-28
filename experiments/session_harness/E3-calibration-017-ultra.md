# E3 calibration 017: mutation-task bank with Nemotron 3 Ultra (free)

Date: 2026-09-28  
Status: approved (owner, in session 2026-09-28: "get ultra running"); machine-readable card `cards/017.json`  
Stage: S6a follow-up to cards 007 (Sonnet, 0.80) and 012 (Nemotron 3 Super, stopped at 1/12). Same 20 tasks, policy,
toolset, backend and per-run budgets; client `openrouter`, model `nvidia/nemotron-3-ultra-550b-a55b:free`; one rollout.

Question: does the largest free model land in the 30-70% zone on the bank? Pass if acceptance is between 30% and 70%
after 20 runs; then a second rollout under a new card. Results go in `E3-calibration-017-ultra-report.md`.
