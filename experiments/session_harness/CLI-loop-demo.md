# Minimal harness optimization loop

Hypothesis: streaming file bytes into the existing digest can reduce peak Python
allocations while preserving every revision value and stale-write check.

One Reticle task edits an isolated copy of `reticle/runtime/workspace.py`, runs
the supplied measurement before and after the edit, and requests finish. The
orchestrator then measures the candidate with the original benchmark in a fresh
process. No candidate change is promoted automatically.

- Connection: existing Reticle Harness OpenAI subscription login, `gpt-6.1-sol`.
- Context: `pressure-recent-v4`; file/edit/run tools; trusted-local execution.
- Budget: eight model responses, eight provider attempts, eighty tool actions.
- Fixture: 16 MiB file plus empty, text, Unicode-path-independent text, and binary files.
- Metric: maximum `tracemalloc` peak across three revision calls.
- Acceptance: all seven checks pass, peak below 4 MiB and below 25% of baseline,
  only the target module changes, and the supplied benchmark remains unchanged.
- Timing is recorded descriptively; this is one demonstration, not comparative
  evidence for general harness optimization ability. Python allocations differ
  from total process RSS. The copied workspace is not a security sandbox.

```powershell
.runtime\test-venv\Scripts\python.exe experiments/session_harness/cli_loop_demo.py --prepare
.runtime\test-venv\Scripts\python.exe experiments/session_harness/cli_loop_demo.py --execute
```

Default artifacts: `.runtime/cli-loop-demo-openai/`. `baseline.json`, `after.json`,
`result.json`, `report.md`, and `candidate.patch` contain the measurements and
reviewable result; `session/` contains the durable Reticle transcript. A runner
failure writes `failure.json`. Choose a new `--out` for another trial.
