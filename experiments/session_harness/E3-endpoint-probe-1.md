# Endpoint probe 1: results

Date: 2026-09-15  
Card: [E3-endpoint-probe-001](E3-endpoint-probe-001.md) (approved "Yes, approved")  
Raw evidence: `endpoint_probes/probe-1/` (`card.json`, `calls.jsonl`, `summary.json`)  
Sent: 48 of 48 planned requests (cap 48). Reported cost $0.013515; worst case approved $0.1504.  
Window: 16:46:15-16:51:28 UTC, same day as E3 run 1's 429s (16:31-16:32 UTC).

## Per route (generated summary)

| Route | Valid tool calls | Outcomes | Served by | Latency median / p90 / max s | Tokens per request (prompt / completion) | Reported cost | Eligible |
|---|---|---|---|---|---|---|---|
| gemma-4-26b @ DeepInfra | 8/8 | 8 valid | DeepInfra 8 | 1.94 / 4.28 / 4.31 | 1,699 / 13-15 | $0.000988 | yes |
| gemma-4-26b @ Cloudflare | 8/8 | 8 valid | Cloudflare 8 | 0.80 / 0.99 / 1.56 | 1,698-1,699 / 13 | $0.001390 | yes |
| gemma-4-26b @ DekaLLM | 8/8 | 8 valid | DekaLLM 8 | 1.00 / 1.17 / 1.36 | 1,699 / 13-15 | $0.000851 | yes |
| DeepSeek V4 Flash @ Novita | 8/8 | 8 valid | Novita 8 | 3.24 / 3.94 / 4.56 | 2,031 / 88-275 (44-231 reasoning) | $0.001915 | yes |
| Qwen3-Coder-Next @ Parasail | 8/8 | 8 valid | Parasail 8 | 0.98 / 1.47 / 2.28 | 2,421 / 39-52 | $0.002073 | yes |
| Devstral 2 @ Mistral | 8/8 | 8 valid | Mistral 8 | 1.11 / 1.45 / 1.54 | 1,883 / 17 | $0.006298 | yes |

No HTTP errors, error bodies, missing tool calls, or dropped routes occurred.

## Audit notes (from `calls.jsonl`)

- First tool calls: gemma routes `list_files` with `{"path": "."}` (Cloudflare sent `{}` in 7 of 8);
  Qwen3-Coder-Next `list_files {"path": "."}`; Devstral `list_files {"path": ".", "pattern": "*.py"}`;
  DeepSeek `list_files {"path": "."}` in 7 of 8 and three `search` calls (first query `get_real_name`) once.
- The probe checks tool names and JSON-object arguments, not each tool's argument schema. Checked by
  hand: `path` and `pattern` (Devstral) are both `list_files` schema properties; `search` takes `query`.
- Prompt token counts differ by model tokenizer for the same 7,466-byte request (1,698-2,421).
- Per-request reported cost at this first-turn size: gemma DekaLLM $0.00011, DeepInfra $0.00012,
  Cloudflare $0.00017, DeepSeek $0.00021-0.00031, Qwen $0.00021-0.00033, Devstral $0.00079.

## What this does and does not show

- Under the preset rule, all six routes are eligible. The probe did not separate them on reliability.
- The E3 run 1 route (gemma @ DeepInfra) returned 8/8 about 15 minutes after its 429s, which is
  consistent with a transient upstream limit; one clean window does not predict later capacity.
- Not measured: behavior under longer, growing contexts or sustained agent loops, and repair competence.

## Next decision (not taken)

Choosing the route for the next E3 run is a user decision and needs its own card and approval.
Relevant data for that choice: all routes are eligible here; latency p90 is lowest on the gemma
Cloudflare/DekaLLM and Qwen routes; Devstral is 4-8 times the per-request cost of the others; switching
to gemma on another provider changes one variable relative to run 1, while a different model changes
the model as well.
