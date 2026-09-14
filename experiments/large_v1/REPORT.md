# Larger-repository Luna observation experiment

Generated DispatchDesk: 95 Python files, 8,067 package source lines. Ran 18 fresh GPT-5.6 Luna agents (low reasoning effort): three tasks, three observation modes, two repetitions each.

| Metric | Full files | Foveated | Adaptive choice |
|---|---:|---:|---:|
| Public-suite passes | 6/6 | 6/6 | 6/6 |
| Held-out-suite passes | 6/6 | 6/6 | 6/6 |
| Observation characters | 87,581 | 60,462 | 56,821 |
| Source-view characters | 56,814 | 29,197 | 24,159 |
| Actions (excluding start, including finish) | 54 | 71 | 56 |
| Rejected edits | 0 | 1 | 2 |
| Unavailable observation attempts | 3 | 6 | 0 |
| Mean elapsed seconds | 109.8 | 117.9 | 115.3 |
| API tokens/cost | Unavailable | Unavailable | Unavailable |

Observation characters include tree, search, outlines, regions, and full reads. Source-view characters include only outlines, regions, and full reads. These are returned text, not cumulative context tokens or billed usage. Rejected observation attempts consume actions but reveal no forbidden source.

## Paired task results

| Task | Mode | Held-out passes | Observation characters | Actions |
|---|---|---:|---:|---:|
| quote | full | 2/2 | 40,148 | 17 |
| quote | foveated | 2/2 | 21,137 | 21 |
| quote | adaptive | 2/2 | 14,600 | 14 |
| cache | full | 2/2 | 13,756 | 16 |
| cache | foveated | 2/2 | 14,216 | 20 |
| cache | adaptive | 2/2 | 18,418 | 20 |
| feed | full | 2/2 | 33,677 | 21 |
| feed | foveated | 2/2 | 25,109 | 30 |
| feed | adaptive | 2/2 | 23,803 | 22 |

## What the model chose

| Successful observation | Full files | Foveated | Adaptive choice |
|---|---:|---:|---:|
| tree | 6 | 6 | 6 |
| search | 5 | 7 | 6 |
| file | 16 | 0 | 11 |
| outline | 0 | 9 | 2 |
| region | 0 | 17 | 5 |

| Adaptive trial | Observation | File | File length | Requested region |
|---|---|---|---:|---|
| cache_1_adaptive | file | dispatchdesk/cache/service.py | 21 | — |
| cache_1_adaptive | file | dispatchdesk/cache/keys.py | 11 | — |
| cache_1_adaptive | file | dispatchdesk/cache/storage.py | 29 | — |
| cache_1_adaptive | file | test_contract.py | 72 | — |
| cache_1_adaptive | region | dispatchdesk/cache/storage.py | 29 | 7-13 |
| cache_2_adaptive | file | dispatchdesk/cache/keys.py | 11 | — |
| cache_2_adaptive | file | dispatchdesk/cache/service.py | 21 | — |
| cache_2_adaptive | file | dispatchdesk/cache/storage.py | 29 | — |
| feed_1_adaptive | file | dispatchdesk/events/service.py | 6 | — |
| feed_1_adaptive | outline | dispatchdesk/events/query.py | 282 | — |
| feed_1_adaptive | region | dispatchdesk/events/query.py | 282 | 1-8 |
| feed_1_adaptive | region | dispatchdesk/events/query.py | 282 | 180-195 |
| feed_2_adaptive | file | dispatchdesk/events/service.py | 6 | — |
| feed_2_adaptive | outline | dispatchdesk/events/query.py | 282 | — |
| feed_2_adaptive | region | dispatchdesk/events/query.py | 282 | 185-195 |
| quote_1_adaptive | file | dispatchdesk/billing/service.py | 12 | — |
| quote_1_adaptive | region | dispatchdesk/billing/pricing.py | 352 | 185-205 |
| quote_2_adaptive | file | dispatchdesk/billing/service.py | 12 | — |

## Interpretation and limits

The concrete hypothesis is whether letting the model choose observation scale can preserve correctness while reducing retrieval overhead. The adaptive quote trial in repetition 1 read the small billing service in full, searched for the tax helper, then requested a short region of the large pricing module. That is an observed use of mixed resolution, not an imposed outline-first policy.

Repository size alone is not task difficulty. These defects have localized fixes, named public APIs, regular generated code, and tests exposing concrete failures. Common search lets every mode avoid most unrelated files. Perfect scores therefore indicate a ceiling on this task set, not equivalence on difficult real repositories. Two repetitions per task are insufficient for broad causal or statistical claims.

Adaptive retrieval is not guaranteed to choose economically: extra test reads, redundant searches, or full reads of large modules can erase savings. Inspect the per-task totals and recorded choices before interpreting aggregate results. Character reductions do not establish lower token cost or latency.

The next useful benchmark would be a pinned real repository with a reproducible regression, plus tasks that require following cross-module invariants. Keep search and exact-snippet edits identical across arms. Measure API tokens when direct model access is available. Do not add memory pruning or an editorial pass until observation choice is measured independently.

## Validation and reproducibility

All initial and final snapshots match their recorded hashes: True. Protected tests/docs remained unchanged: True.

The public and held-out tests were fixed before any trial started. Golden code passed both; each seeded fixture failed both. Six interface tests passed, covering mode restrictions, adaptive views, exact edits, atomic failures, protected paths/tests, and independent final verification.

The held-out hash is over UTF-8 text normalized to LF, matching the generator source. An audit-only correction accounted for Windows CRLF storage; held-out content and participant interface behavior were unchanged.

Native agents received fresh contexts and no parent hints, but interface-only access is a protocol constraint, not OS-level isolation. The runner does not expose exact model snapshots, seeds, API token usage, or total system-context overhead. Up to three trials shared the runner, and elapsed time includes scheduling delays.

Shared exact-snippet edits and search differ from the earlier pilot. Do not attribute cross-pilot changes solely to repository size. No original harness or earlier trial files were changed.

Protocol: [LARGE_PROTOCOL.md](../LARGE_PROTOCOL.md). Dataset: [manifest.json](manifest.json). Metrics: [summary.json](summary.json). Observation choices: [observation_choices.json](observation_choices.json). Browse the [generated source](reference/README.md). Each run folder contains its exact prompt, protocol, complete action/result logs, final source snapshot, public/held-out audit, and diff.

## Per-trial metrics

| Trial | Public | Held-out | Actions | Observation characters | Edit errors | Seconds |
|---|---|---|---:|---:|---:|---:|
| cache_1_adaptive | True | True | 12 | 11,516 | 1 | 62.8 |
| cache_1_foveated | True | True | 10 | 7,084 | 0 | 46.2 |
| cache_1_full | True | True | 8 | 6,902 | 0 | 33.7 |
| cache_2_adaptive | True | True | 8 | 6,902 | 0 | 31.8 |
| cache_2_foveated | True | True | 10 | 7,132 | 0 | 45.3 |
| cache_2_full | True | True | 8 | 6,854 | 0 | 32.9 |
| feed_1_adaptive | True | True | 12 | 11,939 | 1 | 65.4 |
| feed_1_foveated | True | True | 15 | 12,718 | 1 | 81.5 |
| feed_1_full | True | True | 9 | 16,442 | 0 | 49.9 |
| feed_2_adaptive | True | True | 10 | 11,864 | 0 | 473.6 |
| feed_2_foveated | True | True | 15 | 12,391 | 0 | 443.4 |
| feed_2_full | True | True | 12 | 17,235 | 0 | 468.8 |
| quote_1_adaptive | True | True | 8 | 6,951 | 0 | 32.5 |
| quote_1_foveated | True | True | 11 | 14,386 | 0 | 44.0 |
| quote_1_full | True | True | 9 | 20,321 | 0 | 41.2 |
| quote_2_adaptive | True | True | 6 | 7,649 | 0 | 25.7 |
| quote_2_foveated | True | True | 10 | 6,751 | 0 | 47.2 |
| quote_2_full | True | True | 8 | 19,827 | 0 | 32.5 |
