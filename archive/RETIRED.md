# Retired: harness self-refactoring loop

`refactoring_meta_loop.py` and `run_refactoring_trial.py` (formerly at the repo root) drove
the harness to refactor its own source code against a complexity metric and are retired here
unchanged. The loop optimized the complexity score of the harness's own code, not task
outcomes, and a metric like that is gameable by restructuring code to score well rather than
by making it work better. Retired 2026-09-27.
