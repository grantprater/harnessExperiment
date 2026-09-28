# E1 cache layout 008, gates 1 and 2: `pressure-recent-v4` offline checks

Date: 2026-09-27  
Card: [E1-cache-layout-008.md](E1-cache-layout-008.md)  
Result: **gate 1 passed, gate 2 passed on run 4.** No model or API calls. Gate 3, the live behaviour check, was not run.  
Code: `PressureRecentContextPolicyV4` in `reticle/context/baseline.py`; arm `pressure-recent-v4` in `experiments/p6_pilot/run_pilot.py`; `--policy pressure-recent-v4` in [`cache_replay.py`](cache_replay.py)  
Tests: `tests/test_pressure_context_v4.py` (11 tests), plus 2 new tests in `tests/test_cache_replay.py`

## What v4 changes

The policy is v3 with two changes.

1. **The status goes last.** The resource status line keeps v3's wording, but it is now the final message of the request instead of the one after the task.
2. **Omission works in pages.** When a request would exceed the budget, v4 omits the oldest units until the request is at most half the budget. That boundary then stays fixed until the budget is exceeded again. v3 re-fits the boundary on every request, so under pressure the first transcript message after the opening changes on most turns.

The page boundary needs no stored state. v4 replays the page rule over the requests the transcript implies (one before each assistant message, then the current one). It counts every unit at full size, adds the current status size, and adds the marker once anything is omitted. A rebuilt, compared or resumed session therefore pages exactly as the live one did; a test rebuilds every request with a fresh policy instance to check this.

Everything else follows v3:
- the required tail (the latest exchange and everything after it) and its reduced view;
- contiguous retained history, still fitted to the actual request after the page plan;
- the omission marker, byte-identical to v3's text and included when it fits;
- pins, fitted after the transcript;
- every size check counts the status.

**Change to the page rule.** If the opening plus the latest exchange at full size already exceed half the budget, a page omits all older history. The request then goes down to that minimum, not to half. This happened on turn 17 of the 20,000-byte replay (11,866 bytes).

## Gate 1: E1 fixtures (passed)

The fixtures are those of `tests/test_pressure_context.py`. Each budget is that file's budget plus the 398 bytes that the fixture status line adds.

| Requirement | Test | Result |
|---|---|---|
| Ample budget: nothing omitted; only the status moves | `test_ample_budget_moves_only_the_status` (all 10 fixtures at 200,000 bytes) | v4 messages equal v3 messages with the status moved last; request bytes are equal. `message_order` ends with `resource-status`; `policy_version` is `pressure-recent-v4` |
| Forced pressure: latest outcome kept, older exchange omitted, and the omission discoverable | `test_forced_pressure_omits_older_history_behind_the_marker` | Latest `status=error` result present. Unit 0 omitted with reason `context_pressure_page`. The marker is m2, byte-identical to v3's and naming `search_history` and `read_output/search_output or read_artifact`. The contract still says "Use search_history to discover omitted actions" |
| Omitted history is actually recoverable | `test_omitted_history_is_recoverable_with_the_marker_instructions` | With real tools, the evicted `OLD-NEEDLE` read is found by `search_history` and recovered by `read_artifact`, as the marker instructs |
| Oversized latest exchange | `test_oversized_latest_exchange_gets_a_retrievable_view` | Within budget, with the `read_output(id="out_1"...)` view; identical to v3 apart from the status position |
| Latest exchange always present, no over-budget request, overflow flagged where v3 flags it | `test_every_budget_keeps_the_latest_exchange_and_flags_overflow_where_v3_does` (10 fixtures x 16 budgets, 1,000 to 40,000) | The latest exchange and every later unit are present on every build. `over_budget` equals v3's on every build, and is true exactly when the request exceeds the budget. v4 never keeps a unit that v3 omits. When v3 has the marker, v4 has it too |
| `context_budget_exhausted` raised exactly where v3 raises it | `test_context_budget_exhausted_is_raised_at_the_same_budget_as_v3` | Huge-arguments fixture: v3's smallest fitting budget is 10,948 bytes, and v4 flips at the same byte. Through `AgentController` at 100 and 10,947 bytes, both policies stop with `context_budget_exhausted` and 0 model calls. At 10,948 bytes both dispatch the same way |
| Pages on a growing transcript (18 turns, 7,000-byte budget) | `V4PageTests` (3 tests) | Pages fall on turns 8, 12 and 16, each dropping the request to 3,500 bytes or less. The prefix breaks fall on exactly the page turns. v3 moves the boundary on 11 turns and breaks on every turn from 3 onward |
| v1-v3 byte-for-byte unchanged | `test_v1_v2_v3_render_the_existing_fixtures_byte_for_byte_as_before` | 60 digests: 10 fixtures x 2 budgets x v1/v2/v3, covering request bytes, message order, omissions and the over-budget flag. They were generated from commit ef524a2 before v4 existed, and all match. The v1-v3 source is untouched: the `baseline.py` diff adds lines after the v3 class and changes none |

## Gate 2: replay of run 4 (passed)

Setup:
- Run 4 is `e3-sqlparse-qwen-parasail-4`, rebuilt from its journal with `cache_replay.py`.
- Each turn's status comes from the recorded request, as the v2 rebuild takes it. The unknown-billing count is computed the same way as for v3.
- The source journal's SHA-256 was the same before and after all rebuilds.
- The v3 row at 80,000 bytes and the three v2-status-last rows reproduce [the earlier replay report](cache-cost-replay-run4.md) exactly. That report has no v3 rows at 40,000 or 20,000 bytes. All six v3 and v2-status-last totals are the same under `cache_replay.py` before and after this change.
- All nine rows were produced twice, before and after the code commit, with byte-identical output.

Definitions:
- A **prefix break** is a turn whose cacheable prefix ends before the previous request's final message. On such a turn more than a trailing status is rewritten.
- A **page** is a turn on which the set of omitted units changed.
- By this definition, v3's turn 2 is not a break, because on turn 1 the status is also the last message.

| Layout | Budget | Bytes sent | Cost, no cache | Cost, cached | Cached / no cache | Cacheable fraction | Prefix breaks (of 19 turns) | Omission changed on |
|---|---:|---:|---:|---:|---:|---:|---|---|
| pressure-recent-v3 | 80,000 | 947,364 | 236,841 | 256,754 | 1.084 | 14.4% | 18 (turns 3-20) | 0 turns |
| v2, status moved last | 80,000 | 945,864 | 236,466 | 43,978 | 0.186 | 92.5% | 0 | 0 turns |
| **pressure-recent-v4** | 80,000 | 947,364 | 236,841 | **44,446** | **0.188** | **92.4%** | **0** | 0 turns |
| pressure-recent-v3 | 40,000 | 533,933 | 133,483 | 127,557 | 0.956 | 25.6% | 18 (turns 3-20) | 2 turns (6, 7) |
| v2, status moved last | 40,000 | 532,433 | 133,108 | 43,264 | 0.325 | 80.4% | 2 (turns 6, 7) | 2 turns (6, 7) |
| **pressure-recent-v4** | 40,000 | 506,904 | 126,726 | **34,223** | **0.270** | 85.2% | **1 (turn 6)** | **1 page (turn 6)** |
| pressure-recent-v3 | 20,000 | 325,396 | 81,349 | 62,389 | 0.767 | 42.0% | 18 (turns 3-20) | 9 turns (3, 4, 10-13, 16, 17, 19) |
| v2, status moved last | 20,000 | 323,980 | 80,995 | 42,411 | 0.524 | 63.2% | 9 (the same 9 turns) | 9 turns |
| **pressure-recent-v4** | 20,000 | 260,091 | 65,023 | **23,127** | **0.356** | 77.8% | **4 (turns 3, 4, 10, 17)** | **4 pages (turns 3, 4, 10, 17)** |

For reference, v3 with its status moved last gives these results:

| Budget | Cached cost | Cached / no cache | Cacheable fraction | Breaks |
|---:|---:|---:|---:|---|
| 80,000 | 44,446 | 0.188 | 92.4% | 0; per turn identical to v4 |
| 40,000 | 43,733 | 0.328 | 80.2% | 2 |
| 20,000 | 42,853 | 0.527 | 62.9% | 9 |

The status move alone produces the 80,000-byte result. Paging alone produces the extra saving under pressure.

**Against the card:**
- **Cacheable fraction at 80,000 bytes: 92.4%.** The requirement is above 85%.
- **Breaks versus pages:**
  - At 40,000 bytes there was 1 break and 1 page.
  - At 20,000 bytes there were 4 breaks and 4 pages.
  - v3 breaks on 18 of 19 turns at every budget.

**Per-turn detail:**
- **Omitted units per turn, 40,000 bytes:** 0, 0, 0, 0, 0, then 2 from turn 6 onward. v3 omits 1 on turn 6 and 2 from turn 7.
- **Omitted units per turn, 20,000 bytes:** 0, 0, 1, 2, 2, 2, 2, 2, 2, 8, 8, 8, 8, 8, 8, 8, 15, 15, 15, 15.
- **Where the 20,000-byte breaks fall:**
  - Turn 3 writes the 27 KB `sql.py` read, reduced to a view. Its page has no marker: the reduced view fills the budget, and v3 drops the marker in the same way.
  - Turn 4 omits that read, and the marker appears.
  - Turns 10 and 17 are ordinary pages. Each breaks at m3, the first kept unit behind the unchanged marker.

**Card-007 trajectories:** these could not be replayed, because card 007 has no runs yet (its status is "proposed"). Gate 2 covers run 4 only.

## Did anything outside the policy have to change?

No manifest field and no request-validation rule had to change.
- **`ContextManifest` is unchanged.** Within the existing fields:
  - `message_order` ends with `resource-status`;
  - `selected_items` lists the `resource_status` item last;
  - page omissions carry a new `omitted_items` reason value, `context_pressure_page`. v3's `context_pressure` and `context_pressure_for_omission_marker` remain for their own cases.
- **The controller's checks do not depend on message order.** They check three things: the materialized request equals the provider request, the manifest hash and bytes match the artifact, and the request is within budget.
- **Clients:**
  - The claude-cli adapter renders messages in order. The status becomes the last `##### [n] system` block before `##### end of conversation`.
  - The OpenRouter client sends messages as they are.
- **Runner:** the arm is registered without a runner-version bump. No existing arm changed, and the arm name is already hashed into the protocol, so v3's protocol hash is unchanged.

## Behaviour differences between v3 and v4 beyond the two intended ones

- **The manifest labels above.** Status last in `selected_items` and `message_order`, and the `context_pressure_page` reason.
- **Less history under pressure, which follows from paging.** Right after a page, v4 shows at most half the budget, where v3 shows up to the full budget. At 20,000 bytes it sent 20% fewer bytes over the run (260,091 against 325,396). If the opening plus the full latest exchange already exceed half the budget, v4 drops all older history. v3 keeps any small unit that still fits beside the reduced latest exchange.
- **Pins get more room.** Pins are fitted after the transcript, so a pin can fit under v4 where it does not under v3. A pin that is admitted or dropped between turns still breaks the prefix at its position, as in v3; run 4 had no pins.
- **The page plan has an edge case.** It assumes that past requests carried a status the size of the current one. If the status length changes by a byte or two, and a past request sat within those bytes of a threshold, the plan can place a page one turn differently. The result is at most one extra break, and never a budget violation, because the actual request is still fitted exactly. This did not happen in run 4 or in the tests.
- **v4 costs more CPU per build.** It renders every transcript unit one extra time to compute the page plan.

## Not done

- **Gate 3 was not run.** No live check, no model or API calls, and no pushes.
- **The card-007 trajectories were not replayed,** because none exist yet.
- **Provider acceptance of a trailing system message after tool results is untested.** Run 4 (Qwen on Parasail) accepted v2's status as a system message in position 2. The claude-cli adapter that gate 3 uses flattens messages into text, so gate 3 will not test the OpenAI-style position either.
- **Gate 3 may not reach pressure.** Run 4 peaked at 64,459 of 80,000 bytes, so a gate-3 run at the same budget may never page. It would then test only the status move.
- **Toolsets, tools, the evaluator and v1-v3 were not changed.** The register row and the ledger were not updated; that is the card's reporting step after gate 3.

## Reproduce

```
python -m unittest tests.test_pressure_context_v4 tests.test_cache_replay
python experiments/session_harness/cache_replay.py <run4_dir> --policy pressure-recent-v4 [--budget 40000|20000]
python experiments/session_harness/cache_replay.py <run4_dir> --policy pressure-recent-v3 [--budget ...]
python experiments/session_harness/cache_replay.py <run4_dir> --policy pressure-recent-v2 --status-last [--budget ...]
```

`<run4_dir>` must contain `sessions/`. Only the main checkout has it: `experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-4`.

Provenance: implementation, replays and text by a subagent (Claude Opus 5.5) in the `wt/cache-layout-v4` worktree on 2026-09-27.
