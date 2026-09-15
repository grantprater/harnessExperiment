# E3-repair-control-001: first live repair calibration

Date: 2026-09-15  
Status: approved 2026-09-15. Smoke passed; run 1 stopped on provider HTTP 429 (infrastructure class). See [E3-sqlparse-gemma-deepinfra-1.md](E3-sqlparse-gemma-deepinfra-1.md).  
Plan: IMPLEMENTATION_PLAN.md S3 "Competent live repair control", steps 2-3  
Runner: `experiments/p6_pilot/run_pilot.py` runner v4 (hashes in `E3-source-manifest.sha256`)

## Question

Can one pinned model/provider repair a real development bug through the repaired runner?
The runner now has durable resource accounting, `pressure-recent-v1`, history tools, and the
isolated OCI candidate/evaluator path. This calibrates a control; it does not compare treatments.

## Fixed before running

| Item | Value |
|---|---|
| Task | `sqlparse-865`: `get_real_name()` wrong for names with more than two dotted parts; gold fix changes 5+/2- lines in `sqlparse/sql.py`; hidden tests: 1 fail-to-pass, 87 pass-to-pass |
| Why this task | Its full candidate-visible suite runs cleanly in the image (489 passed in 6.1 s, S2b tester control). Reference point, not a comparison: in pilot 2, gemma on this task under `bounded-transcript-v2`, trusted-local, without history tools, stopped at 25 calls, rejected, with no library edit. |
| Excluded tasks for this calibration | `markdown-it-py-416` (needs missing linkify-it-py); `more-itertools-1270/1279` (full suite 297.6 s in OCI, above the 120 s default `run` timeout) |
| Also not chosen first (candidate-visible collection errors in both environments) | `tomlkit-549/551`, `pyparsing-639`, `packaging-1330`, `click-3805`, `humanize-329` (15 setup errors) |
| Model / provider | `google/gemma-4-26b-a4b-it` pinned to DeepInfra (fp8), no fallbacks; temperature 0; `max_tokens` 4096 |
| Why this endpoint | 79 logged calls (pilot 2 + E2): 0 errors or empty replies; latency median 1.8 s, p90 5.7 s, max 56.3 s; median $0.00042/response |
| Pricing at plan time | $0.070/M input, $0.340/M output (endpoint catalog, 2026-09-15) |
| Context policy | `pressure-recent-v1`, 80,000 bytes (fixed; operational choice, not a finding) |
| Environment | isolated OCI image `8b74015e5079…`, Podman `--userns keep-id`, workspace-only mount, no network |
| Tools | full runner tool set (file, `run`, output paging, `history`, `search_history`, `read_artifact`, notes, `finish`) |
| Command timeout | `run` default 120 s, model may request up to 600 s |
| Evaluator | fixed hidden upstream tests, OCI, pytest timeout 600 s |

## Limits (per run, enforced by the durable task ledger unless noted)

| Limit | Value | Basis |
|---|---|---|
| model responses | 20 | plan E3 allocation |
| HTTP attempts | 24 | 20 responses plus 4 retries |
| retries per request | at most 2 | plan section 5.3 (runner `MAX_ATTEMPTS = 3`) |
| tool actions | 40 | up to two tool calls per response |
| active seconds | 480 | pilot 2 gemma sqlparse took 142.9 s for 25 calls trusted-local; allow OCI `run` calls (about 6-12 s each) and one 56 s latency outlier |
| cost | $0.10, reserving $0.00326 per attempt before dispatch | reservation = (80,000 bytes / 3 tokens x $0.07/M) + (4,096 x $0.34/M) |
| repeat stop | three identical observation calls without a workspace change end the run (`diagnostic_termination`) | plan section 5.3 |
| campaign cap (runner, not ledger) | `--max-total-calls` 30 for the E3 invocation, 3 for the smoke | hard HTTP-attempt cap |

## Requested approval: at most 33 HTTP attempts, at most $0.108 worst case

1. **Provider/tool-schema smoke:** 1 model response, at most 3 HTTP attempts, same configuration.
   Passes if the reply is HTTP 200 and contains a tool call with a known tool name and JSON
   arguments. If it fails, stop and do not run step 2.
2. **E3 run:** 1 run, at most 20 model responses, at most 30 HTTP attempts (campaign cap).

Worst case: 33 attempts x $0.00326 = $0.108. Expected, from logged medians: about $0.01.

```powershell
# 1. smoke
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models google/gemma-4-26b-a4b-it --provider google/gemma-4-26b-a4b-it=deepinfra `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --max-calls-per-run 1 --max-attempts-per-run 3 --max-tool-actions-per-run 2 `
  --elapsed-cap-seconds 120 --cost-ceiling-usd 0.01 --max-total-calls 3 --max-tokens 4096 `
  --run-name e3-smoke-gemma-deepinfra
# 2. E3 run (only after the smoke passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models google/gemma-4-26b-a4b-it --provider google/gemma-4-26b-a4b-it=deepinfra `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v1 --stop-on-repeats `
  --max-calls-per-run 20 --max-attempts-per-run 24 --max-tool-actions-per-run 40 `
  --elapsed-cap-seconds 480 --cost-ceiling-usd 0.10 --max-total-calls 30 --max-tokens 4096 `
  --run-name e3-sqlparse-gemma-deepinfra-1
```

Dry run of step 2 (catalog read only): protocol `47260c3bca2d`; worst case $0.0033/call and $0.0978
under the 30-attempt cap.

## No-API controls under this configuration (done)

Same runner v4, arm, guards, image, and budgets. The protocol hash differs from the live run only
through provider routing, which is keyed by client name.

| Run | Outcome | Checks |
|---|---|---|
| `e3-control-gold-sqlparse` | accepted | 88 tests observed, pytest exit 0; 2 responses / 2 tool actions / 0 HTTP attempts; nothing pending |
| `e3-control-noop-sqlparse` | rejected (fail-to-pass fail, pass-to-pass pass) | revision unchanged; 1 response / 1 tool action / 0 HTTP attempts; nothing pending |

## Outcome classes and decision rule (fixed before running)

Primary endpoint: hidden fail-to-pass and pass-to-pass both pass within the limits above.

| Class | Definition | Next action |
|---|---|---|
| accepted | acceptance `accepted` | audit the trajectory; then propose `boltons-474` and `cachetools-408` under the same frozen configuration on a new card (at most 3 tasks before review) |
| rejected, library edited | final revision differs in library source and acceptance is rejected | audit the diff and failing tests; decide difficulty or interface before another run |
| rejected, no library edit | no library source change | audit tool use (reads, repeats, paging, history); treat as an interface/usability problem until shown otherwise |
| diagnostic termination | repeat stop | audit the repeated calls and what was visible in context |
| resource stop | `task_budget_exhausted` (name the resource) or `model_call_limit` | audit whether the limit or the trajectory is at fault; no automatic cap increase |
| infrastructure | provider errors, attempt cap, evaluator `runtime_error` | diagnose provider/runtime; not counted as model inability |

There is no second live run before the trajectory review. Integrity failures (evaluator leakage,
false acceptance, evidence loss, authority escape, budget violation) stop the campaign immediately.

## Audit plan

Check `calls.jsonl` (every attempt, raw request and response), `results.jsonl`, the session journal
(provider attempts, reservations, reconciliations, tool outcomes, context manifests), the final
workspace diff, and the evaluator report. Report numbers and per-call rows only; audit the raw reply
behind any counted failure.

## Limitations

- The per-attempt cost reservation assumes at least 3 bytes per input token. Denser text could
  bill more than the reservation for one attempt; the reported total is reconciled afterwards.
- Active time is charged at dispatch boundaries; a crash loses time since the last boundary.
- Candidate code can tamper with in-container grading artifacts (only the conftest gamer is tested).
