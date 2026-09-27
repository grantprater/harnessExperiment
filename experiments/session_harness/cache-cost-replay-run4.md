# Cache-cost replay of E3 run 4 (`e3-sqlparse-qwen-parasail-4`)

Date: 2026-09-27  
Status: mechanism check done (replay, no model calls)  
Plan: [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md) section 3.2, "Measure prompt-cache and retransmission effects instead of assuming shorter context is always cheaper overall."  
Tool: [`cache_replay.py`](cache_replay.py); test `tests/test_cache_replay.py`  
Evidence: `experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-4/` (run 4, [report](E3-sqlparse-qwen-parasail-4.md)). Its `sessions/` directory is gitignored and exists only in the main checkout; it was read there, and rebuilds used a temporary copy (the source journal's checksum was unchanged afterwards).

## Question

Run 4 used `pressure-recent-v2`, which puts a resource-status line ("model responses, including this one: N of 20; ...") right after the task, so it changes every request. Under provider prefix caching, does that layout cost more than an append-only rendering of the same transcript, and where exactly does each request stop matching the one before it?

## Method

- **Requests.** `calls.jsonl` holds every request body as sent, so run 4 needed no reconstruction. The replay also rebuilds each request from the session journal with the package's own policy class, which enables other layouts and budgets.
- **Order.** Requests are compared in provider render order: the tool schemas first, then the messages. Anthropic renders tools, then system, then messages, and chat templates also put the schemas ahead of the conversation. The byte length equals the canonical `{"messages","tools"}` JSON that the context manifests record.
- **Per turn.** The table gives the longest common byte prefix (LCP) with the previous request and the cacheable prefix, which is the LCP rounded down to a unit boundary (the tool block counts as one unit, each message as one). It also gives the leading messages that are unchanged, the first differing message with the byte offset inside it, and every previous message that does not reappear byte-for-byte anywhere in this request.
- **Price.** Tokens are bytes/4, and uncached input costs 1.0 per token. The cached cost is 0.10 x cacheable tokens (a read) + 1.25 x the rest (a 5-minute write, because each request is cached for the next). The first request is all write. Every cost below is in these token units.
- **Idealised.** A breakpoint is assumed to sit at the read boundary. That takes at most two explicit `cache_control` breakpoints in either layout, against a limit of 4. No cache entry expires: calls were 2 to 15 s apart. The model also charges the trailing status of the append-only layout (327 bytes, about 82 tokens) as a write, whereas a breakpoint placed before it would bill it at 1.0. That is under 1% of the append-only total, and it counts against append-only.

## Does the rebuild match the recorded requests?

Yes, exactly. Script output for the two main runs:

```
recorded:   calls.jsonl: 20 attempts, 20 calls; request_sha256 recomputed from the recorded body matches 20/20
            session manifests: 20; recorded body -> manifest hash 20/20, manifest request_bytes 20/20,
            journal chain manifest->call_index->request_sha256 20/20
rebuilt v2: status lines re-rendered identically after parsing: 20/20
            rebuilt vs session manifests: hash 20/20, request_bytes 20/20; messages identical to the recorded request 20/20
```

The rebuild takes each turn's resource status from the recorded request of the same call. It parses the status back into the controller's mapping and re-renders it, and all 20 lines round-trip byte-for-byte. Everything else is rebuilt from the journal: the transcript as of each manifest's sequence number, the task contract, and the tool schemas. The status is controller state that a journal replay cannot recompute, which is why it comes from the recorded request.

## Table 1: requests as sent (`pressure-recent-v2`, 80,000-byte budget)

In the last column, "provider cached" is the `prompt_tokens_details.cached_tokens` value that Parasail reported for the real call. It is an independent witness.

| # | bytes | LCP | cacheable | same lead msgs | first break (msg, byte in msg) | previous msgs not reused | cost no cache | cost cached | cached % | provider cached / prompt tok |
|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| 1 | 7,524 | 0 | 0 | 0 | (first request) | - | 1,881 | 2,351 | 0.0 | 0 / 2599 |
| 2 | 10,106 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 2,526 | 1,090 | 71.2 | 0 / 3236 |
| 3 | 37,135 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 9,284 | 9,536 | 19.4 | 2176 / 12076 |
| 4 | 37,981 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 9,495 | 9,801 | 18.9 | 0 / 12262 |
| 5 | 39,629 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 9,907 | 10,316 | 18.2 | 2176 / 12754 |
| 6 | 40,834 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 10,208 | 10,692 | 17.6 | 2176 / 13189 |
| 7 | 42,988 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 10,747 | 11,365 | 16.7 | 2176 / 13795 |
| 8 | 44,745 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 11,186 | 11,915 | 16.1 | 2176 / 14345 |
| 9 | 49,140 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 12,285 | 13,288 | 14.6 | 2176 / 15700 |
| 10 | 49,655 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 12,414 | 13,449 | 14.5 | 0 / 15798 |
| 11 | 51,469 | 7,330 | 7,194 | 2 | m2 status +135 | m2 status | 12,867 | 14,016 | 14.0 | 0 / 16282 |
| 12 | 53,565 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 13,391 | 14,671 | 13.4 | 2176 / 17017 |
| 13 | 55,366 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 13,842 | 15,234 | 13.0 | 2176 / 17606 |
| 14 | 55,883 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 13,971 | 15,395 | 12.9 | 0 / 17711 |
| 15 | 56,396 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 14,099 | 15,555 | 12.8 | 2176 / 17826 |
| 16 | 58,840 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 14,710 | 16,319 | 12.2 | 2176 / 18612 |
| 17 | 62,862 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 15,716 | 17,576 | 11.4 | 2176 / 19597 |
| 18 | 63,383 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 15,846 | 17,739 | 11.4 | 2176 / 19694 |
| 19 | 63,904 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 15,976 | 17,902 | 11.3 | 2176 / 19791 |
| 20 | 64,459 | 7,329 | 7,194 | 2 | m2 status +134 | m2 status | 16,115 | 18,075 | 11.2 | 2176 / 19895 |

## Table 2: append-only rendering of the same transcript

Same opening and the same full rendering of every unit. Nothing is reduced, omitted or reordered, and the status line (the same text) is the last message.

| # | bytes | LCP | cacheable | same lead msgs | first break (msg, byte in msg) | previous msgs not reused | cost no cache | cost cached | cached % |
|---:|---:|---:|---:|---:|---|---|---:|---:|---:|
| 1 | 7,524 | 0 | 0 | 0 | (first request) | - | 1,881 | 2,351 | 0.0 |
| 2 | 10,106 | 7,207 | 7,194 | 2 | m2 status->assistant(list_files) +12 | m2 status | 2,526 | 1,090 | 71.2 |
| 3 | 37,135 | 9,789 | 9,776 | 4 | m4 status->assistant(read_file) +12 | m4 status | 9,284 | 8,794 | 26.3 |
| 4 | 37,981 | 36,818 | 36,805 | 6 | m6 status->assistant(search) +12 | m6 status | 9,495 | 1,288 | 96.9 |
| 5 | 39,629 | 37,663 | 37,651 | 8 | m8 status->assistant(search) +11 | m8 status | 9,907 | 1,559 | 95.0 |
| 6 | 40,834 | 39,312 | 39,299 | 10 | m10 status->assistant(read_file) +12 | m10 status | 10,208 | 1,462 | 96.2 |
| 7 | 42,988 | 40,517 | 40,504 | 12 | m12 status->assistant(read_file) +12 | m12 status | 10,747 | 1,789 | 94.2 |
| 8 | 44,745 | 42,671 | 42,658 | 14 | m14 status->assistant(read_file) +12 | m14 status | 11,186 | 1,719 | 95.3 |
| 9 | 49,140 | 44,428 | 44,415 | 16 | m16 status->assistant(read_file) +12 | m16 status | 12,285 | 2,587 | 90.4 |
| 10 | 49,655 | 48,823 | 48,810 | 18 | m18 status->assistant(search) +12 | m18 status | 12,414 | 1,484 | 98.3 |
| 11 | 51,469 | 49,337 | 49,325 | 20 | m20 status->assistant(search) +11 | m20 status | 12,867 | 1,903 | 95.8 |
| 12 | 53,565 | 51,152 | 51,139 | 22 | m22 status->assistant(read_file) +12 | m22 status | 13,391 | 2,037 | 95.5 |
| 13 | 55,366 | 53,249 | 53,236 | 24 | m24 status->assistant(read_file) +12 | m24 status | 13,842 | 1,997 | 96.2 |
| 14 | 55,883 | 55,050 | 55,037 | 26 | m26 status->assistant(search) +12 | m26 status | 13,971 | 1,640 | 98.5 |
| 15 | 56,396 | 55,566 | 55,554 | 28 | m28 status->assistant(search) +11 | m28 status | 14,099 | 1,652 | 98.5 |
| 16 | 58,840 | 56,079 | 56,067 | 30 | m30 status->assistant(read_file) +11 | m30 status | 14,710 | 2,268 | 95.3 |
| 17 | 62,862 | 58,525 | 58,512 | 32 | m32 status->assistant(write_file) +12 | m32 status | 15,716 | 2,822 | 93.1 |
| 18 | 63,383 | 62,546 | 62,534 | 34 | m34 status->assistant(run) +11 | m34 status | 15,846 | 1,829 | 98.7 |
| 19 | 63,904 | 63,067 | 63,055 | 36 | m36 status->assistant(run) +11 | m36 status | 15,976 | 1,842 | 98.7 |
| 20 | 64,459 | 63,589 | 63,576 | 38 | m38 status->assistant(run) +12 | m38 status | 16,115 | 1,865 | 98.6 |

## Totals

| Layout | Budget (bytes) | Requests over budget | Bytes sent | Cost, no cache | Cost, cached | Cached / no cache | Cacheable bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| pressure-recent-v2 as sent (run 4) | 80,000 | 0 | 945,864 | 236,466 | **256,285** | **1.084** | 14.5% |
| append-only | none | 0 at 80,000 | 945,864 | 236,466 | **43,978** | **0.186** | 92.5% |
| pressure-recent-v3 (rebuilt) | 80,000 | 0 | 947,364 | 236,841 | 256,754 | 1.084 | 14.4% |
| v2, status moved last (rebuilt) | 80,000 | 0 | 945,864 | 236,466 | 43,978 | 0.186 | 92.5% |
| *Hypothetical: tighter budget, same transcript* | | | | | | | |
| v2 | 40,000 | 0 | 532,433 | 133,108 | 127,088 | 0.955 | 25.7% |
| v2, status moved last | 40,000 | 0 | 532,433 | 133,108 | 43,264 | 0.325 | 80.4% |
| append-only | 40,000 | 15 of 20 | 945,864 | 236,466 | 43,978 | 0.186 | 92.5% |
| v2 | 20,000 | 0 | 323,980 | 80,995 | 61,947 | 0.765 | 42.2% |
| v2, status moved last | 20,000 | 0 | 323,980 | 80,995 | 42,411 | 0.524 | 63.2% |
| append-only | 20,000 | 18 of 20 | 945,864 | 236,466 | 43,978 | 0.186 | 92.5% |

The budget rows are hypothetical: the model would have acted differently under a tighter budget. They replay run 4's transcript through the policy only to show which omissions break the prefix.

## Findings

1. **The status line breaks every v2 request at message 2.** The tool block, the contract and the task end at byte 7,194 of the render-order request, and those bytes are the same on all 20 requests. The status message starts at byte 7,195. The first changed byte is 134 or 135 bytes into it (absolute byte 7,329 or 7,330), at the remaining-responses count: "20 of 20" became "19 of 20", and so on. The other four counts (attempts, tool actions, active seconds, cost) change later in the same line. Every transcript message after the status gets rewritten on every turn, so the cacheable share falls from 71% at turn 2 to 11% at turn 20. With a 1.25x write premium, caching under this layout costs **8.4% more than no caching at all** (256,285 against 236,466).
2. **The provider's own counter agrees.** Parasail reported exactly 2,176 cached prompt tokens on 14 of 20 calls, and 0 on calls 1, 2, 4, 10, 11 and 14. Over the same calls the prompt grew from 2,599 to 19,895 tokens. Had any transcript been reused, the cached count would have grown with it. It stayed at a block-aligned amount below the 2,599-token first request, which contains only the opening and the status. That fits the replay: only the tool block, contract and task are reused. The six zero calls are unexplained by layout; they are probably cold or other-replica routing.
3. **Append-only reuses everything except the previous status.** Each turn's prefix ends at the first content byte of the previous request's trailing status message: offset +11 or +12, just after `{"content":`. The only previous message not reused on any turn is that status. At the same bytes, the cached cost is 43,978: **0.186x no cache, and 5.8x cheaper than the v2 layout as sent.** The one expensive later turn is turn 3 (26% cached), which writes the 27 KB `sql.py` read once.
4. **Nothing else in run 4 broke the prefix.** The tool schemas were byte-identical in all 20 requests. No transcript unit was omitted, and none was re-rendered, because the peak request of 64,459 bytes was under the 80,000 budget. v3 behaves exactly like v2: its status wording differs, but the position is the same.
5. **Under pressure, omission is a second breaker, and it is smaller.** In the hypothetical tighter-budget replays, status-last isolates the omission effect. Each time the oldest kept unit changes, the prefix breaks right after the opening: at the inserted omission marker (m2), or at the first kept unit behind the marker (m3). That happened on 2 of 19 turns at 40,000 bytes and 9 of 19 at 20,000 bytes (turns 3, 4, 10-13, 16, 17, 19).
   - Even so, v2 with the status last is the cheapest layout that stays inside the budget, at 43,264 and 42,411.
   - At 40,000 bytes, append-only sends 1.78x the bytes of v2 and still costs 2.9x less in dollars (43,978 against 127,088). The plan's "longer in tokens, cheaper in dollars" holds, but 15 of its 20 requests exceed the budget. The status position, not the omission, carries almost all the difference.
6. **Pricing matters for the size, not the direction.** From run 4's `cost_details`, Parasail charged $0.12/M uncached and $0.07/M cached (0.58x), with no write charge. Under that pricing caching cannot lose money. By arithmetic, and assuming every call hits the cache (6 of 20 did not), v2's layout would cost about 0.94x no-cache and append-only about 0.61x. The net loss in finding 1 comes from Anthropic's write premium.

## Recommendation

- **Move to the end.** Put the per-turn resource status after the last transcript message, and anything else that changes per turn with it: counters, diagnostics, timestamps. On Anthropic this is either a trailing system message (on models that allow mid-conversation system messages) or a text block after the final `tool_result` blocks. Place the cache breakpoint on the last transcript block before the status.
- **Keep byte-stable.** The tool schemas and their order, the contract text, the task, and every transcript message once sent. Never re-render an older unit's view, prefix or handle text. Note that the baseline fallback appends "Context diagnostics" into the contract message; that fallback is read from code, not measured.
- **Under pressure, drop in pages.** Omit older material in large pages (for example down to about half the budget) rather than one unit per turn, so the post-opening break happens once per page and not on most turns.

For run 4 this layout alone turns caching from an 8% loss into an 81% saving, at unchanged bytes. The policies were not modified. Moving the status is a prompt change, so its effect on model behaviour needs its own check before adoption.

## Not done, and doubts

- **No model or API calls.** The costs are Anthropic-style list multipliers applied to bytes/4. They are not a bill. Real Qwen tokenisation was 2.9-3.1 bytes per token (for example 7,524 bytes against 2,599 prompt tokens). The ratios are unaffected, but absolute token counts here are about 25% low.
- **Idealised breakpoints.** The model does not simulate Anthropic's 20-block lookback, minimum cacheable length, or TTL expiry. None should bind for append-only: turns add 2-3 blocks, and calls are seconds apart. The v2 opening prefix (7,194 bytes, about 1,800 tokens by bytes/4 and at least 2,176 real tokens) might fall below the 4,096-token minimum of Opus 4.6/4.5 and Haiku 4.5, in which case v2 would cache nothing.
- **Retries** would be priced once per call. Run 4 had none (20 attempts, 20 calls).
- **The rebuild's status lines come from the recorded requests**, not from replaying the resource ledger. For v3, the "unknown billing" count comes from `calls.jsonl` responses that lack a cost (0 in run 4).
- **The tighter-budget rows are counterfactual renderings** of a transcript produced at 80,000 bytes, not runs.
- **Not built:** a paging policy, or a status-last policy in the package. Recommendation only.
- **Scope:** one run and one task. Only the policy used in run 4 (v2) was checked against recorded hashes. v3 and append-only are renderings that have no recorded counterpart.

## Reproduce

```
python experiments/session_harness/cache_replay.py <run_dir>                                  # as sent
python experiments/session_harness/cache_replay.py <run_dir> --policy pressure-recent-v2      # rebuild, hash check
python experiments/session_harness/cache_replay.py <run_dir> --policy append-only
python experiments/session_harness/cache_replay.py <run_dir> --policy pressure-recent-v3
python experiments/session_harness/cache_replay.py <run_dir> --policy pressure-recent-v2 --status-last [--budget 40000]
```

`<run_dir>` must contain `sessions/` for anything other than the as-sent replay (for run 4, use the main checkout's run directory).

Provenance: analysis and text by a subagent (Claude Opus 5.5) in this repository's worktree on 2026-09-27; the orchestrating session reran the script for the three main layouts and reproduced every total above before committing this file.
