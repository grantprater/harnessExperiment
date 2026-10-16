# P019 exploratory Codex mini pilot

Date: 2026-10-01
Status: approved by owner 2026-10-01 ("Yes, let's run it"); parallel execution authorized explicitly by owner afterward.

Evidence class: **exploratory pilot, separate from the controlled cards**. Owner authorized running alongside card 010 and stated this pilot must not be merged as equivalent evidence. The driver uses its own duplicate-run lock; it neither acquires nor removes the shared calibration lock. Within this pilot the four trials remain serial. Concurrent workloads may affect latency, provider availability and cache behavior. Do not pool its results with existing cards, use it to satisfy their gates, or treat it as an equivalent controlled comparison. Its historical `c019` filenames are identifiers only.

Compare the current Reticle harness, using its implemented cache-stable context policy, with stock Codex on two empirically difficult repair tasks. Start with one fresh run per task and arm (four runs). A second repeat, if wanted, brings the total to eight. This is a diagnostic comparison of the two configured systems, not an estimate of a general success rate or an isolated harness effect when models differ.

## Tasks

Use the unchanged bank `experiments/mutation_tasks/tasks.mutations.json`.

| Task | Challenge | Previous Reticle / native Claude acceptance | Final acceptance tests |
|---|---|---|---|
| `sqlparse-mut-032` | Diagnose a formatting failure involving an invalid WHERE clause; reported exception `ValueError: None is not in list` | 0/2 / 0/2 | 1 fail-to-pass, 490 pass-to-pass |
| `sqlparse-mut-061` | Restore identifier-list indentation across wrapping and comment cases without breaking working formatting | 0/2 / 1/2 | 15 fail-to-pass, 476 pass-to-pass |

Selection evidence: [card 018 report](E3-native-arm-018-report.md) and [card 007 weakness review](weakness-mining-c007.md). These are deliberately selected known failures, not held-out tasks. They are small mutations with difficult diagnosis or verification under this protocol; they do not measure large-project engineering. In particular, 032 has a sparse problem statement, which can itself account for difficulty. Do not expose mutation location, gold patches, evaluator files, or previous trajectories to either participant.

## Arms

- **Reticle:** existing `run_pilot.py`, `--arm pressure-recent-v4`, toolset v3; Claude CLI 2.1.286, model alias `sonnet`, resolved identity retained in raw calls. Completion, nudge, oracle and reasoning treatments off.
- **Codex:** CLI 0.159.3, `gpt-6.1-sol`, medium reasoning effort. Fresh ephemeral sessions with user config, rules, AGENTS, memories, plugins, web search and delegation disabled. Same starting workspace and independent evaluator as Reticle.

The Codex executable was found at `C:/Users/grant/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe`. [run_codex_mini.py](run_codex_mini.py) drives this first block and uses the existing materializer, timeout/process-tree runner, diff builder, pinned OCI image and evaluator. The executable card schema is unchanged. Official [non-interactive execution documentation](https://learn.chatgpt.com/docs/non-interactive-mode) describes the CLI's JSONL event route.

Preflight: both gold controls accepted; both noop controls rejected. Native Windows sandbox probe passed workspace write, blocked sibling hidden-canary read, and blocked outbound connection checks. Windows requires root read, so targeted denies cover the task bank, pristine upstream clone and scratch siblings; unrelated host files remain readable. The task protocol forbids outside-workspace inspection, and transcripts require a leakage audit before final conclusions. Evaluator and pristine comparison trees are built only after Codex exits. The initial broad read-deny probe timed out and affected the parent sandbox; its two workspace-root deny ACEs were removed and root access verified restored before this launch.

Only the first four-run block is authorized by this launch; no automatic second repeat. Both clients use existing subscription logins, with no API key or separate paid API route configured.

## Context/cache configuration

`pressure-recent-v4` is already implemented in `reticle/context/baseline.py` and wired into the pilot runner. It puts changing resource status last and omits old history in pages. The policy remains explicitly selected for this card rather than changing the global incumbent.

Preparation checks: `tests.test_pressure_context_v4` and `tests.test_cache_replay`: **20 tests passed** on 2026-10-01. The existing [offline report](E1-cache-layout-008-gates12.md) measured 92.4% cacheable content on the run-4 replay at 80,000 bytes. This is replay evidence, not a live hit rate. Card 008's live v3/v4 behavior gate remains unrun; this Codex comparison does not replace it.

For Claude CLI, raw provider usage is preserved in model-response metadata as `cli_usage`, including `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens` when reported. Retain raw call records. Report aggregate cache-read share as:

`sum(cache_read_input_tokens) / sum(input_tokens + cache_creation_input_tokens + cache_read_input_tokens)`

Missing fields or unavailable usage must be reported as unknown, not zero. Record per-call cache reads/writes, prompt bytes and elapsed time as well. Keep replay cacheability separate from provider-reported hits. The CLI adapter flattens the conversation into one prompt and starts a process per response; live observations determine whether the stable layout translates into provider reuse. Do not claim billing savings from subscription list-price estimates.

For Codex, retain whatever raw usage the selected execution route exposes, including cached input when available. Do not assume the two products expose identical counters or count model turns identically. Do not deliberately prewarm tasks; record run order and any possible cross-run cache reuse.

## Run block and budgets

1. Validate identical starting workspace hashes and hidden evaluator separation. Check gold passes and noop fails for both tasks with the shared evaluator before model runs.
2. Run 032: Reticle then Codex. Run 061: Codex then Reticle. Run serially to keep timing interpretable.
3. If taking the optional second repeat, reset all workspaces and sessions and reverse each task's arm order. Keep settings fixed; no between-run tuning or trajectory hints.

Reticle budget: 20 model responses, 24 provider attempts, 1,200 active seconds, 80,000 context bytes, 4,096 maximum output tokens per response; command timeout 120 s by default / 600 s maximum; evaluator timeout 600 s. No repeat stop and no resumption after provider stop, matching prior calibration.

Codex budget: a 1,200-second solve deadline enforced by its execution route, with the same evaluator timeout after solving. Record responses, actions and tokens rather than assuming its turns equal Reticle responses. Thus the Reticle response cap is an additional asymmetry; state it alongside results. If a comparable enforced response cap becomes available, declare it before starting, not retrospectively.

Provider errors, interrupted machines, leaks of hidden material and failed setup are invalid runs, separately retained. Do not retry an ordinary task failure. Decide any monetary cap after provider/model selection and before a paid launch.

## Score and next decision

Primary: all fail-to-pass and pass-to-pass tests pass within the solve budget. Preserve final diffs and independent evaluator output. Secondary: first source edit, responses, tool actions, solve time, cache usage and stop reason. Compare a failed run with its paired run to identify the specific failure mechanism.

| Task / repeat | Reticle accepted | Codex accepted | Reticle seconds | Codex seconds | Reticle cache-read share | Codex cache usage | Failure / regression |
|---|---|---|---|---|---|---|---|
| 032 / 1 | pending | pending | | | | | |
| 061 / 1 | pending | pending | | | | | |

After four runs, report the paired outcomes and inspect misses. If both systems fail both tasks, consider clearer or fresh tasks before spending on repetitions. If the outcomes differ, a second repeat can check whether that contrast recurs. No promotion or statistical superiority claim from this mini block.
