# E3-repair-control-003: repair calibration on Qwen3-Coder-Next @ Parasail (proposed)

Date: 2026-09-15  
Status: approved and run 2026-09-15. Smoke passed; run 3 reached the 20-response budget with no command run and no edit, not accepted. See [E3-sqlparse-qwen-parasail-3.md](E3-sqlparse-qwen-parasail-3.md).  
Runner: `experiments/p6_pilot/run_pilot.py` runner v5 (unchanged since card 002; hashes in `E3-source-manifest.sha256`)  
Why: gemma-4-26b made no library edit on this task in pilot 2, E3 run 1, or E3 run 2
([report](E3-sqlparse-gemma-cloudflare-2.md)). The user chose `qwen/qwen3-coder-next`, which was
probe-eligible ([probe](E3-endpoint-probe-1.md): 8/8 valid, latency median 0.98 s, p90 1.47 s).

## Changes from card 002 (everything else is identical)

| Item | Card 002 | This card |
|---|---|---|
| Model / provider | gemma-4-26b @ Cloudflare | `qwen/qwen3-coder-next` @ Parasail (`parasail/bf16`), no fallbacks |
| Pricing at plan time | $0.10/M in, $0.30/M out | $0.12/M in, $0.80/M out |
| Per-attempt cost reservation | $0.003896 | $0.006477 |
| Smoke cost ceiling | $0.012 | $0.02 (admits its 3 attempts at the new reservation) |

Unchanged: task `sqlparse-865` and its exclusions; `pressure-recent-v1` at 80,000 bytes; the isolated OCI image
`8b74015e5079…`; full tool set; `run` timeout 120 s (600 s max); temperature 0; `max_tokens` 4096; repeat stop;
chunked resumes (at most 2, 300 s paused wait); and per-run task budgets: 20 responses, 24 HTTP attempts,
40 tool actions, 480 active seconds, $0.10. The campaign cap is 30 HTTP attempts.

The endpoint lists `tools`, `tool_choice`, `temperature`, and `max_tokens`, has no reasoning parameters, and
allows up to 235,929 output tokens.

## Controls

No new no-API controls: runner code, image, evaluator, context policy, guards, and budget limits are unchanged
from the v5 controls (`e3v5-control-gold-sqlparse` accepted, `e3v5-control-noop-sqlparse` rejected). Scripted
clients do not use the provider, and the only budget difference is the derived per-attempt reservation.

## Requested approval: at most 33 HTTP attempts, at most $0.2137 worst case

1. **Smoke** (Parasail, same configuration): 1 response, at most 3 attempts. Passes if HTTP 200 with a valid
   runner tool call. If it fails, stop.
2. **E3 run 3:** 1 run, at most 20 responses and 30 attempts (campaign cap), up to 2 resumes.

Worst case: 33 x $0.006477 = $0.2137. The runner also stops the run at the $0.10 per-run task budget.
Expected: in run 2 gemma used $0.0308 for 18 responses at $0.10/M input; Qwen's input price is $0.12/M, so
roughly $0.03-0.05.

```powershell
# 1. smoke
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --max-calls-per-run 1 --max-attempts-per-run 3 --max-tool-actions-per-run 2 `
  --elapsed-cap-seconds 120 --cost-ceiling-usd 0.02 --max-total-calls 3 --max-tokens 4096 `
  --run-name e3-smoke-qwen-parasail
# 2. E3 run 3 (only after the smoke passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --resume-after-provider-stop 2 --resume-wait-seconds 300 `
  --max-calls-per-run 20 --max-attempts-per-run 24 --max-tool-actions-per-run 40 `
  --elapsed-cap-seconds 480 --cost-ceiling-usd 0.10 --max-total-calls 30 --max-tokens 4096 `
  --run-name e3-sqlparse-qwen-parasail-3
```

Dry runs (catalog read only): run protocol `3a06264aaf6c`, worst case $0.0065/call and $0.1943 under the
30-attempt cap; smoke protocol `695932bb9390`, worst case $0.0194.

## Outcome classes, decision rule, and audit

As in cards 001-002. A resumed run is classified by its final stop, and the report lists every invocation.
The audit also checks what was visible in context at any repeated observation. There is no further live run
before the trajectory review.
