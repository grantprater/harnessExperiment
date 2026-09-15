# E3-repair-control-002: repair calibration on gemma-4-26b @ Cloudflare, chunked (proposed)

Date: 2026-09-15  
Status: approved and run 2026-09-15. Smoke passed; run 2 ended in a diagnostic termination after 18 responses with no library edit, not accepted. See [E3-sqlparse-gemma-cloudflare-2.md](E3-sqlparse-gemma-cloudflare-2.md).  
Runner: `experiments/p6_pilot/run_pilot.py` runner v5 (hashes in `E3-source-manifest.sha256`)  
Supersedes for the next run: [E3-repair-control-001](E3-repair-control-001.md). Its run 1 stopped on DeepInfra
429s ([report](E3-sqlparse-gemma-deepinfra-1.md)); the [endpoint probe](E3-endpoint-probe-1.md) found all six
routes valid 48/48; the user chose Cloudflare.

## Changes from card 001 (everything else is identical)

| Item | Card 001 | This card |
|---|---|---|
| Provider | DeepInfra (`deepinfra/fp8`) | Cloudflare (`cloudflare`, quantization not listed), no fallbacks |
| Pricing at plan time | $0.07/M in, $0.34/M out | $0.10/M in, $0.30/M out |
| Per-attempt cost reservation | $0.00326 | $0.003896 |
| Provider stops | end the run | **chunked:** after a request exhausts its 2 retries on provider errors (429/5xx/network/error body), wait 300 s (paused, not charged to active time) and resume the same session; at most 2 resumes |
| Runner | v4 | v5 (adds only the resume option) |

Unchanged: task `sqlparse-865` (with the same exclusions), `pressure-recent-v1` at 80,000 bytes, the isolated OCI image
`8b74015e5079…`, full tool set, `run` timeout 120 s (600 s max), temperature 0, `max_tokens` 4096, repeat stop,
and per-run task budgets: 20 responses, 24 HTTP attempts, 40 tool actions, 480 active seconds, $0.10.
The campaign cap is 30 HTTP attempts. Resumes do not add budget: every resumed request draws on the same durable ledger.

## Why chunking, and what it does not do

Run 1's 429s were upstream shared capacity (`engine_overloaded`, 4 within 40 s). The probe 15 minutes
later saw none. Our own request rate was low (one request per 5-20 s), so pacing our requests is unlikely
to prevent an upstream burst. Chunking changes what happens when one occurs: the run keeps its trajectory
and resumes after the burst, instead of ending as an infrastructure stop. Wall time can grow by up to 600 s of waits.

## No-API controls under this exact configuration (done)

| Run | Outcome |
|---|---|
| `e3v5-control-gold-sqlparse` | accepted |
| `e3v5-control-noop-sqlparse` | rejected (fail-to-pass fail, pass-to-pass pass) |

Offline runner tests: 21 passed (5 cover chunked resume). Full offline suite: 216 passed, 4 OCI skipped.

## Requested approval: at most 33 HTTP attempts, at most $0.1286 worst case

1. **Smoke** (Cloudflare, same configuration): 1 response, at most 3 attempts. Passes if HTTP 200 with a valid
   runner tool call. If it fails, stop.
2. **E3 run 2:** 1 run, at most 20 responses and 30 attempts (campaign cap), up to 2 resumes.

Worst case: 33 x $0.003896 = $0.1286. Expected from the probe (about $0.00017 per first-turn request, rising
with context): roughly $0.01.

```powershell
# 1. smoke
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models google/gemma-4-26b-a4b-it --provider google/gemma-4-26b-a4b-it=cloudflare `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --max-calls-per-run 1 --max-attempts-per-run 3 --max-tool-actions-per-run 2 `
  --elapsed-cap-seconds 120 --cost-ceiling-usd 0.012 --max-total-calls 3 --max-tokens 4096 `
  --run-name e3-smoke-gemma-cloudflare
# 2. E3 run 2 (only after the smoke passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models google/gemma-4-26b-a4b-it --provider google/gemma-4-26b-a4b-it=cloudflare `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --resume-after-provider-stop 2 --resume-wait-seconds 300 `
  --max-calls-per-run 20 --max-attempts-per-run 24 --max-tool-actions-per-run 40 `
  --elapsed-cap-seconds 480 --cost-ceiling-usd 0.10 --max-total-calls 30 --max-tokens 4096 `
  --run-name e3-sqlparse-gemma-cloudflare-2
```

Dry run of step 2 (catalog read only): protocol `4c97104f37a2`; worst case $0.0039/call and $0.1169 under
the 30-attempt cap.

## Outcome classes, decision rule, and audit

As in card 001, with one addition: a run that resumed is classified by its final stop, and the report lists
every invocation and wait. There is no second live run before the trajectory review.
