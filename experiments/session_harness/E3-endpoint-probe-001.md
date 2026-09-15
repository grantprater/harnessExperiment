# E3-endpoint-probe-001: endpoint reliability probe before the next E3 run (proposed)

Date: 2026-09-15  
Status: approved and run 2026-09-15: 48/48 requests valid, all six routes eligible, $0.0135 reported. See [E3-endpoint-probe-1.md](E3-endpoint-probe-1.md).  
Why: E3 run 1 ([report](E3-sqlparse-gemma-deepinfra-1.md)) stopped on four HTTP 429s from DeepInfra
(`engine_overloaded`, `upstream_provider_shared_pool`). The user asked for a more reliable endpoint;
a different model or provider is allowed.  
Script: `experiments/session_harness/probe_endpoints.py` (offline tests: `tests/test_probe_endpoints.py`, 4 passed)

## What the catalog can and cannot tell us

- OpenRouter's rate-limit docs: paid model variants have no platform-level request cap; upstream 429s
  are handled by "add fallback models or relax provider routing preferences". This key is paid tier
  ($0.19 used, no credit limit).
- Endpoint uptime does not show this failure: DeepInfra reported 99.4% uptime (last 30 minutes) at a
  time when it was returning 429s to us. Only live requests at agent cadence can measure it.
- Logged history: gemma/DeepInfra 88 attempts, 4 x 429 (all in E3 run 1); qwen3.5-9b/Venice 65 x 429 in
  120 attempts; nemotron free, 35 error bodies. No logs exist for the candidate routes below.

## Design (fixed before running)

- The same recorded request for every route: the first request of E3 run 1 (task instructions,
  full runner tool schemas, temperature 0, max_tokens 4096; 7,466 bytes). Only `model` and the
  pinned provider change. `allow_fallbacks: false`, `require_parameters: true`.
- 8 rounds; each round sends one request to every route, in seeded shuffled order (seed 20260915),
  5 s between requests. One HTTP attempt per request, no retries.
- A route is dropped after 3 consecutive failures (plan section 5.3).
- Every request is appended to `endpoint_probes/<run>/calls.jsonl` as it completes; the summary is
  generated from that file only.

| Route | Endpoint(s) | Why included | Price $/M in / out | Worst case per request |
|---|---|---|---|---|
| gemma-4-26b @ DeepInfra | `deepinfra/fp8` | reference: the E3 run 1 route (is the limit still present?) | 0.07 / 0.34 | $0.00157 |
| gemma-4-26b @ Cloudflare | `cloudflare` | same model, provider-only change | 0.10 / 0.30 | $0.00148 |
| gemma-4-26b @ DekaLLM | `dekallm/bf16` | same model, provider-only change | 0.06 / 0.33 | $0.00150 |
| DeepSeek V4 Flash @ Novita | `novita/fp8` | different model, low price | 0.14 / 0.28 | $0.00150 |
| Qwen3-Coder-Next @ Parasail | `parasail/bf16` | coding-agent model | 0.12 / 0.80 | $0.00358 |
| Devstral 2 @ Mistral | `mistral/eu` | agentic-coding model, first-party host | 0.40 / 2.00 | $0.00919 |

Excluded after checking endpoint metadata: GPT-5.6 Luna (its OpenAI endpoints do not accept
`temperature`, which the runner sends), and Gemini 3.1 Flash Lite @ Google Vertex (the `google-vertex`
route matches five variants, including one that is down and a higher-priced priority tier, so the served
endpoint would not be controlled).

## Requested approval: 48 requests, at most $0.1504

Worst case assumes 3 bytes per input token and all 4,096 output tokens on every request. Expected
from E3 run 1's first response (1,699 prompt, 13 completion tokens): under $0.02 in total.

```powershell
.\.runtime\test-venv\Scripts\python.exe experiments/session_harness/probe_endpoints.py --run-name probe-1 --rounds 8 `
  --endpoint google/gemma-4-26b-a4b-it=deepinfra --endpoint google/gemma-4-26b-a4b-it=cloudflare `
  --endpoint google/gemma-4-26b-a4b-it=dekallm --endpoint deepseek/deepseek-v4-flash=novita `
  --endpoint qwen/qwen3-coder-next=parasail --endpoint mistralai/devstral-2512=mistral --max-requests 48
```

## Decision rule (fixed before running)

A route is eligible iff all 8 of its requests returned HTTP 200 with a tool call to a runner tool with
JSON-object arguments. The summary reports, per route: outcomes, served provider, latency median/p90/max,
and reported cost.

The probe does not pick a model. It reports the eligible routes for review. The next E3 run on any chosen
route needs its own card (with that route's pricing and a smoke) and approval.

## Limitations

- A snapshot: provider capacity varies with time of day, so an eligible route can still rate-limit later.
- One request type (the first turn). Longer contexts later in a repair are not exercised.
- A valid first tool call says nothing about repair competence; that is what E3 measures.
