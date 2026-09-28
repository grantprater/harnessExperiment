# E3 native arm 018 report: stock Claude Code vs the Reticle interface on the mutation bank

Date: 2026-09-28. Card: [E3-native-arm-018](E3-native-arm-018.md). 40 valid runs (20 tasks x 2), Sonnet 5, matched
turn/response budget (20), same materializer, evaluator and OCI image. Four runs voided and rerun (3 usage-limit
API errors, 1 straddled machine sleep), kept under `native_runs/*.void-*`.

## Headline

| | Reticle (card 007) | Native Claude Code (card 018) |
|---|---|---|
| Accepted | 32/40 | 29/40 |
| Per task | Reticle better on 4, native better on 1, equal on 15 | |
| Responses/turns to accept (15 shared solved tasks) | | +0.9, not significant |
| Tool actions per solve (same 15 tasks) | | about 21 fewer (SD 8.3), significant |
| Seconds to accept (same 15 tasks) | | 117 s faster (SD 102), significant |

## Reading

- Acceptance: statistically indistinguishable (3 runs apart on 40); the interface neither helps nor hurts solving on
  this bank at matched budgets.
- Work per solve: the same number of model turns, but the native arm takes far fewer tool actions. The Reticle model
  batches several tool calls per response (stateless per-response context, so it re-reads and fans out), while Claude
  Code keeps a continuous conversation.
- Time: the seconds gap is infrastructure, not harness design: 83% of Reticle wall time is model-call latency (fresh
  CLI process per response, whole context flattened into one prompt so nothing caches). An API client with the
  status-last layout (card 008) is the fix to test before reading anything into seconds.
- Confinement: the native arm attempted `pip download sqlparse` (the route to the upstream fix); the deny rule refused
  it. Read-block and deny rules verified live under bypassPermissions.

## Full comparison output

# Native arm (card 018) vs Reticle incumbent (card 007)

Tasks with native runs: 20 of 20 (40 native runs; accepted but audit not clean: 3).

| Task | Reticle acc | Native acc | R resp | N resp (turns) | d resp | R s | N s | d s | R 1st edit | N 1st edit |
|---|:-:|:-:|--:|--:|--:|--:|--:|--:|--:|--:|
| sqlparse-mut-001 | 1/2 | 0/2 | 19.0 | - (-) | - | 717 | - | - | 15.0 | - |
| sqlparse-mut-002 | 2/2 | 2/2 | 14.5 | 15.0 (15.0) | 0.5 | 143 | 44 | -98 | 10.5 | 6.0 |
| sqlparse-mut-022 | 1/2 | 0/2 | 17.0 | - (-) | - | 313 | - | - | 15.0 | - |
| sqlparse-mut-023 | 2/2 | 2/2 | 15.5 | 18.0 (18.5) | 2.5 | 179 | 46 | -133 | 13.5 | 12.0 |
| sqlparse-mut-024 | 2/2 | 2/2 | 15.0 | 14.0 (15.0) | -1.0 | 204 | 45 | -159 | 10.0 | 13.5 |
| sqlparse-mut-025 | 2/2 | 2/2 | 7.0 | 13.5 (13.5) | 6.5 | 52 | 39 | -13 | 4.5 | 7.0 |
| sqlparse-mut-032 | 0/2 | 0/2 | - | - (-) | - | - | - | - | - | - |
| sqlparse-mut-033 | 2/2 | 1/2 | 16.0 | 20.0 (20.0) | 4.0 | 207 | 71 | -136 | 11.5 | 17.0 |
| sqlparse-mut-034 | 2/2 | 2/2 | 6.0 | 12.0 (12.0) | 6.0 | 51 | 27 | -25 | 3.5 | 3.5 |
| sqlparse-mut-040 | 2/2 | 2/2 | 10.0 | 8.5 (8.5) | -1.5 | 69 | 19 | -51 | 3.5 | 2.5 |
| sqlparse-mut-042 | 2/2 | 2/2 | 14.0 | 14.0 (15.5) | 0.0 | 387 | 36 | -351 | 9.0 | 11.0 |
| sqlparse-mut-043 | 2/2 | 2/2 | 13.0 | 16.0 (17.0) | 3.0 | 211 | 62 | -149 | 8.5 | 15.5 |
| sqlparse-mut-044 | 2/2 | 2/2 | 8.0 | 8.0 (9.0) | 0.0 | 62 | 20 | -42 | 5.0 | 4.0 |
| sqlparse-mut-046 | 2/2 | 2/2 | 10.5 | 11.5 (12.0) | 1.0 | 76 | 30 | -46 | 4.5 | 6.0 |
| sqlparse-mut-057 | 0/2 | 0/2 | - | - (-) | - | - | - | - | 13.0 | 6.0 |
| sqlparse-mut-060 | 2/2 | 1/2 | 15.0 | 6.0 (7.0) | -9.0 | 340 | 20 | -319 | 6.5 | 3.0 |
| sqlparse-mut-061 | 0/2 | 1/2 | - | 3.0 (4.0) | - | - | 9 | - | 16.0 | 2.0 |
| sqlparse-mut-073 | 2/2 | 2/2 | 8.5 | 11.0 (12.0) | 2.5 | 67 | 27 | -40 | 4.0 | 5.0 |
| sqlparse-mut-075 | 2/2 | 2/2 | 9.5 | 12.5 (14.0) | 3.0 | 81 | 33 | -48 | 5.5 | 5.5 |
| sqlparse-mut-076 | 2/2 | 2/2 | 13.5 | 9.0 (9.5) | -4.5 | 162 | 21 | -140 | 8.5 | 3.0 |

Accepted on the tasks with native runs: Reticle 32/40, native 29/40.

| Paired difference (native - Reticle) | n tasks | mean | SD | 2-sigma line (mean) | observed 2 SE | detectable |
|---|--:|--:|--:|--:|--:|:-:|
| acceptance rate | 20 | -0.075 | 0.245 | - | - | native better on 1, Reticle on 4, equal 15 |
| responses to accept | 15 | 0.87 | 3.96 | 0.96 | 2.04 | no |
| seconds to accept | 15 | -116.6 | 101.7 | 29.3 | 52.5 | yes |
| first-edit index | 17 | -0.88 | 5.02 | - | - | - |

Within-task noise used: sigma_w = 1.8 responses and 55 s per run (card 007 efficiency baseline). Pooled within-task SD of accepted runs, from the data: Reticle 1.95 responses, 54 s; native 6.24 responses, 22 s.
Responses: Reticle counts model responses; native counts distinct assistant messages (the CLI's num_turns in parentheses). Seconds: Reticle active seconds; native CLI wall seconds.
