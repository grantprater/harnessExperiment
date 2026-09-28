# E3 native arm 018: Claude Code's own agent loop on card 007's mutation bank

Date: 2026-09-28  
Status: **approved (owner in session 2026-09-28: 'we should move that up')**. Built and checked offline on
`wt/native-bank`: native arm v2, campaign driver, paired comparison, unit tests with a stub CLI, and the no-model
controls (gold accepted, noop rejected; [below](#no-model-controls-done)). **No live run yet**: the campaign waits for the
live-run lock (card 013 holds it) ([commands](#commands)). CLI permission settings (read block, deny list) were added
after review; the optional `--sandbox` layer is off (not installed on this machine).  
Stage: S6 reference line. Card 006 compared the two harnesses on one easy upstream task (both accepted); card 007
measured the Reticle interface on 20 mutation tasks (32/40). This card runs the same 20 tasks through the stock harness.

## Hypothesis

At matched budgets (20 model turns or responses, 1,200 s, the same model, materializer and evaluator), does the stock
Claude Code harness **match, beat or trail** the Reticle interface on card 007's bank?

| Result (per task, paired with card 007) | Reading | Next |
|---|---|---|
| Acceptance within noise of card 007 and efficiency differences inside the 2-sigma line | The Reticle interface costs a capable model nothing measurable at this budget | Keep S6 on the Reticle harness; this card is the reference line for later treatments |
| Native accepts clearly more (for example on 032, 057 or 061, which card 007 never solved) | Capability is lost in the Reticle path (stateless context, no shell, prompt, or tools) | Pair the trajectories on those tasks and mine what the native loop did differently before any S6 treatment |
| Native accepts clearly fewer | The Reticle harness adds something (fixed context policy, structured tools, the `finish` step) | Name it from the paired trajectories; it is a candidate to keep, not to tune away |
| Same acceptance, native cheaper in responses or seconds beyond the 2-sigma line | The interface costs time or turns, not outcomes | Weigh against the harness's other properties; an efficiency treatment, not a capability one |

Power: 20 tasks x 2 rollouts cannot resolve an acceptance difference below roughly 15-20 points (S6 noise budget).
For efficiency, with card 007's within-task noise (1.8 responses and 55 s per run), about 15 tasks solved twice by both
arms put the 2-sigma line on the mean paired difference near 2 x 1.8 x sqrt(15 x 1) / 15 = 0.93 responses and 28 s
(`compare_native_c007.py` computes it from the runs that actually exist).

## Arms

| | Reticle (card 007, recorded, not rerun) | Native (this card) |
|---|---|---|
| Driver | `run_pilot.py` runner v8 via `run_card007.py` | [`native_control.py`](native_control.py) v2 via [`run_native_bank.py`](run_native_bank.py) |
| Model | `sonnet` (`claude-sonnet-5`), CLI 2.1.283, default effort | `sonnet`, the CLI version at run time (recorded per run); default effort |
| Loop | Reticle controller; each response is a fresh `claude -p` process (`--max-turns 1`) seeing what `pressure-recent-v3` renders (80,000 bytes) | one `claude -p` process, continuous conversation, the CLI's own compaction |
| Tools | the 15 `reticle-tools-v3` tools; `run` executes without a shell; `finish` ends the run | `Bash, PowerShell, Read, Edit, Write, Glob, Grep`; the init event is checked and any other tool (WebFetch, WebSearch, Agent) kills the run |
| Opening request | Reticle system contract and adapter prompt, then `run_pilot.INSTRUCTIONS` with the statement, then remaining-resource lines | `run_pilot.INSTRUCTIONS` with the statement, with "with the run tool)" -> "with Bash)" and "Call finish when you are done." -> "Stop when you are done." and nothing else changed, as the whole user message; Claude Code's own system prompt |
| Where commands run | isolated OCI image `8b74015e5079`, workspace mount only, no network | Windows host (Git Bash or PowerShell), `bypassPermissions`, network on; task interpreter (`.runtime/bugs-venv`, Python 3.13) first on PATH, PYTHONPATH = workspace |
| Budget | 20 responses, 24 CLI attempts, 1,200 active s checked before each dispatch | `--max-turns 20`; 1,200 s wall, hard kill of the CLI process tree |
| Stop | `finish`, or a budget | a text-only turn (`end_turn`), `--max-turns`, or the wall cap |
| Command timeout | `run`: 120 s default, 600 s max | the Bash tool's own: 120 s default, 600 s max |
| Workspace | `materialize_workspace`, `mutation-workspace-v2` | the same function, called from `native_control.py` (mutation applied, `tests/` removed, commit-time timestamps) |
| Evaluator | `build_evaluator` + `acceptance_plan` + `AcceptanceRunner`, OCI | the same, OCI (`--backend oci`), bundle built only after the CLI exits |
| Flags | adapter: `--safe-mode --setting-sources "" --strict-mcp-config --disable-slash-commands --no-session-persistence --tools ""` | v1's flags: `-p --model sonnet --max-turns 20 --permission-mode bypassPermissions --output-format stream-json --verbose --setting-sources "" --no-session-persistence --safe-mode --strict-mcp-config --disable-slash-commands --tools Bash,PowerShell,Read,Edit,Write,Glob,Grep` |

Both child environments drop `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `CLAUDE_CODE_*` and `ANTHROPIC_*`; no API key
(`apiKeySource: none` is required by the native init check). The prompt text and its sha256 are in each run's
`config.json`. The native instructions template (before the statement is filled in) has sha256
`8e3c6786d5e9d8c44a6b3062d89441fb82944efd9b93c076a121ba6c8f02a70c` (`run_pilot.INSTRUCTIONS`: `d6194fb95e18...`); the
full prompt for `sqlparse-mut-001` has `ee3e905181cb7821105080a2766876537c2a2124aeb128d2c87817b9adaadf25` (the Reticle
opening request for the same task: `c8379db5af58...`).

## Tasks

Card 007's 20 tasks ([`E3-calibration-007-tasks.json`](E3-calibration-007-tasks.json), seed 7) from
`experiments/mutation_tasks/tasks.mutations.json` (LF sha256 `fa185723735d...`). Run names `c018-<task>-r<k>`,
rollout 1 over all tasks in task-id order, then rollout 2. 40 runs, strictly sequential.

## Budgets and stop rules

- Per run: `--max-turns 20`, 1,200 s wall (hard kill), model `sonnet`, OCI evaluator (600 s pytest timeout). The driver
  kills a run's whole process tree after 3,600 s.
- Campaign: 40 runs, one at a time under `.runtime/locks/live-run.lock` of the main checkout (refused if held), idle
  priority, single-threaded BLAS. At card 007's mean of 229 s per run, about 2.5 hours. No monetary cost (subscription
  login); the CLI's list-price estimate is recorded as `cost_estimate_usd`, billing as unknown.
- Before the start: both controls recorded as expected (gold accepted, noop rejected), or `--execute` refuses.
- Stop at once (integrity): a leak-check refusal (native_control exit 3), an init-check abort (a tool outside the set,
  an MCP server, an API key, another permission mode), or two crashes of one run (evidence loss). A single crash is
  rerun once under the same name; the crashed record is kept as `<name>.interrupted-<time>`.
- Stop (checkpoint): three consecutive CLI failures (no result event, or an error result that is not the turn cap).
- A run whose audit is not clean (`audit_clean` false: a network command, a path outside the workspace, a parent-directory
  or home/temp reference, or a harness marker in a tool input or result) is reviewed by hand before it counts. Any
  sign that the agent read hidden material (the task file, run records, an evaluator bundle, the task clones, or the
  upstream code over the network) stops the campaign and marks the arm contaminated.
- Evidence (`native_runs/c018-*`, [`c018-campaign.jsonl`](c018-campaign.jsonl)) committed after every 10 finished runs
  and at the end.

## Known mismatches (all stand; none is corrected by this card)

1. **Host with network vs container without.** Native commands run on the Windows host with network and host file
   access, narrowed only by the CLI's permission settings (the file tools cannot read outside the workspace; common
   network and read commands on hidden paths are denied by pattern; see below). Reticle commands ran in a Linux
   container with only the workspace mounted and no network. The evaluator is the same (OCI) for both. The optional
   `--sandbox` layer (no network for commands, OS-level read denial) would close most of this gap, but it needs
   `claude sandbox install`, which this machine does not have (`claude sandbox status`: installed false, "The Windows
   sandbox is not enabled on this build"), so card 018 runs without it.
2. **Continuous conversation vs stateless per response.** The native model keeps its whole conversation (the CLI's
   window and compaction); each Reticle response saw only what `pressure-recent-v3` rendered within 80,000 bytes.
3. **Shell vs no shell.** Native has Bash and PowerShell (pipes, `sed -i`, heredocs) plus Claude Code's file tools;
   Reticle had 15 structured tools and a `run` that takes no shell syntax. The native deny list also refuses a few
   harmless commands Reticle allowed (`pip list`, `ls`/`cat` of the task interpreter's files under the repository),
   and the read block keeps Read/Grep/Glob inside the workspace, as Reticle's file tools were.
4. **"Turns" vs "responses".** The native budget is the CLI's `--max-turns`; the Reticle budget is 20 model responses
   in the durable ledger (plus 24 attempts). The comparison counts native responses as distinct assistant messages
   (API responses) and shows the CLI's `num_turns` beside them; Reticle responses are `agent.model_calls`.
5. **Seconds.** Reticle: active seconds, checked before each dispatch (a response under way can run past 1,200 s);
   native: wall seconds of the CLI process with a hard kill at 1,200 s, CLI start-up included. Evaluation time is
   excluded from both.
6. **Prompt and completion.** Two phrases differ (above). Native sees Claude Code's system prompt and environment note
   (working directory, platform, date, model name) and no remaining-resource lines; Reticle saw its contract and a
   resource line in every request. Reticle ends with a `finish` call; native with a text-only turn.
7. **First edit.** Reticle's `first_edit_response` (labels_c007_rules.jsonl) sees edits by any tool through workspace
   revisions; native `first_base_file_edit` sees Edit/Write calls only, so an edit made through Bash (`sed -i`, a Python
   one-liner) is not counted.
8. **Time and versions.** Card 007 ran 2026-09-28 00:07-02:40 UTC with CLI 2.1.283; this card runs later. The model
   behind `sonnet` and the CLI can change in between; each run records the CLI version and the init event's model.
9. **Guards and retries.** Reticle's repeat guard was off in card 007 (flags only); native has none. Reticle retried a
   failed CLI attempt at most twice per response; native retries happen inside the CLI and are not visible.
10. **Arm order.** Not interleaved: all Reticle runs are recorded; all native runs come after.

## Hidden material and what confines the native arm

The CLI runs on the host with `bypassPermissions`, network and host file access. What confines it:

- **Leak checks before every run** (`native_control.py` refuses to start, exit 3): the scratch base
  (`%TEMP%\reticle-native-control`) is outside every checkout of this repository and the task clones; it is on a local
  fixed drive (not UNC, network, removable, or OneDrive), so no network location can hold the evaluator bundle; it
  holds nothing but this run's directory (every run deletes its workspace, pristine copy, evaluator bundle and session
  store after scoring, so rollout 2 cannot see rollout 1's fix or bundle); the materialized workspace has no hidden
  test root, no `.git`, no evaluator file; the task interpreter, outside the workspace and without PYTHONPATH, cannot
  import an installed `sqlparse`.
- **The evaluator bundle** (the fix commit's test roots) is built only after the CLI has exited, in the scratch
  directory, and deleted with it.
- **Tools**: WebFetch, WebSearch and Agent are not in `--tools`; the init check kills a run that has them.
- **CLI permission settings** (`--settings <scratch>\cli-settings.json`, written beside the workspace, recorded verbatim
  with its sha256 in `config.json` under `confinement`; the rules are defined once, in `native_control.py`):
  - *read block*, enforced by the CLI: `permissions.blockReadsOutsideWorkingDirectories: true`, so Read, Grep and Glob
    refuse any path outside the workspace;
  - *deny list*, enforced by the CLI, pattern-matched and best-effort: for Bash and PowerShell, `curl`, `wget`,
    `git clone/fetch/pull`, `pip`, `pip3`, `python -m pip`, `py -m pip`, `uv pip`, `Invoke-WebRequest`,
    `Invoke-RestMethod`, `iwr`, `irm`; and `cat`, `type`, `head`, `tail`, `less`, `more`, `ls`, `dir`, `find`, `grep`,
    `rg`, `Get-Content`, `gc`, `Get-ChildItem`, `gci`, `Select-String` on every spelling (`C:\`, `C:/`, `/c/`) of the
    repository root (which covers its worktrees, `.runtime\bug-mining` and the run records) and of the run's scratch
    entries other than the workspace (session store, pristine copy, evaluator bundle, the settings file). The scratch
    base itself is not denied, because the workspace is inside it; leak check 3 keeps other runs out of it;
  - *sandbox*, only with `--sandbox` (off; needs `claude sandbox install`, and refuses to start unless
    `claude sandbox status` reports it installed and available): commands get no network domain and an OS-level
    `denyRead` over the repository's top-level entries except `.runtime` (the task interpreter lives there),
    `.runtime\bug-mining`, and the scratch entries above.
  Which layers were on is recorded per run (`config.json` and `result.json`, `confinement.layers`). Whether they are
  live is not observable before something is denied: the init event does not list permissions, and no live smoke was
  run. A denial shows as an errored tool result or in the result event's `permission_denials`; `result.json` counts
  them (`confinement.denials`, `observed_active`). That deny rules still apply under `bypassPermissions` is the
  expected CLI behaviour (deny takes precedence over the permission mode), not something this card has observed.
- **Context**: `--setting-sources ""` and `--safe-mode` load no CLAUDE.md, memory, skills or MCP servers; the prompt
  names only the upstream repository and the statement.

What does **not** confine it (recorded in `config.json` under `authority`; the audit flags the common forms, and the
audit decides `audit_clean` whatever the CLI enforced):

- **The network.** The upstream repository (`repo_url` is in the prompt) and PyPI hold the healthy code at or near
  commit `f66d12c`, from which every bank task is cut, and its test suite. The deny list refuses the direct commands,
  but `python -c "import urllib.request; ..."`, a script file, `git -C x fetch`, `Start-BitsTransfer`, or a command
  built from variables still reaches them. The audit flags network command words and any URL.
- **Host files through commands.** The read block covers the file tools only. Through Bash or PowerShell this
  repository is still readable by any command the deny list does not name (`python -c "print(open(...).read())"`,
  `sed -n p`, `awk`, `cp`, `Copy-Item`, a path reached through `cd` or a variable):
  `experiments/mutation_tasks/tasks.mutations.json` holds every task's
  `mutation_patch` and `gold_patch`; `experiments/p6_pilot/runs/*/sessions/*/evaluator` (git-ignored, present in the
  main checkout) holds evaluator bundles with the hidden tests; `.runtime/bug-mining/repos/sqlparse` is a full clone.
  The repository path is discoverable from inside the run: the task interpreter on PATH lives in
  `<repo>\.runtime\bugs-venv`. The audit flags absolute paths outside the workspace and the task interpreter's
  environment, `..` steps, home and temp references, checkout paths and harness words in tool inputs and results.
  An audit that finds none of these does not prove nothing was read (a command can build a path the patterns miss).
- **The v1 scratch leftover** (`%TEMP%\reticle-native-control\pc-native-sonnet-1`, card 006, which held the test roots of
  `f66d12c`) was removed by the orchestrator on 2026-09-28; leak check 3 would refuse any run while such a directory
  exists.

## What counts

Primary: accepted runs per task (n/2) against card 007's n/2, counting runs whose audit is clean or reviewed clean.
Secondary, on tasks both arms solved at least once: responses and seconds to accept, and the first-edit index; paired
differences (native - Reticle) with mean, SD, n, and the 2-sigma line from the within-task noise (1.8 responses, 55 s),
from [`compare_native_c007.py`](compare_native_c007.py), which runs on partial data. The report adds the paired
trajectories of any task where the arms differ by 2 accepted runs. This card sets a reference; it promotes nothing.

## Commands

From the main checkout's root, with the test interpreter (`.\.runtime\test-venv\Scripts\python.exe`):

```
# 0. prerequisites: card 013 finished (the lock is free); %TEMP%\reticle-native-control empty (leak check 3)
# 1. plan: 40 invocations, lock state, controls, scratch base
python experiments/session_harness/run_native_bank.py --plan
# 2. controls (recorded on wt/native-bank; rerun only if native_control.py changes; no model, no lock)
python experiments/session_harness/run_native_bank.py --controls
# 3. campaign (restartable: finished runs are skipped)
python experiments/session_harness/run_native_bank.py --execute
# 4. comparison, at any point
python experiments/session_harness/compare_native_c007.py
```

## No-model controls (done)

2026-09-28, `run_native_bank.py --controls --scratch-root <session scratchpad>` from `wt/native-bank` at `213c084`, the
final code of this card (the records say `tracked_changes: true`: the staged removal of the first control records, not
code; earlier passes at `5bf5860` and `f21aee6`, before the audit fixes and the CLI settings, gave the same outcomes and counts). Each control
went through the driver's `run_one` into `native_control.py --scripted <kind>`: leak checks, `materialize_workspace`,
the scripted agent in place of the CLI, the pristine copy and `git diff`, the evaluator bundle built afterwards,
`AcceptanceRunner` in OCI image `8b74015e5079`, scratch removal. No CLI and no model.

| Run | Agent step | Diff | Decision | fail-to-pass | pass-to-pass | Tests observed |
|---|---|---|---|---|---|---:|
| [`c018-control-gold`](native_runs/c018-control-gold/) | the task's `gold_patch` applied with `git apply` | `sqlparse/filters/others.py` +1 -1 (`!=` back to `==`) | **accepted** | 1/1 pass | 490/490 pass | 493 |
| [`c018-control-noop`](native_runs/c018-control-noop/) | nothing | none | **rejected** | 0/1 (1 failing) | 490/490 pass | 493 |

Both used evaluator `sqlparse-mut-001:inputs-6c22ee52ed71258a:evaluator-6d3921fc4b729ce3` and observed 493 tests, as
both card 007 runs of this task did; both removed their scratch directory (`scratch_removal_error: null`). The prompt
recorded in their `config.json` has the sha256 given above.

Leak check 3 on this machine as it is now: `native_control.py --scripted gold` with the default scratch base refused
before materializing anything (exit 3): "`...\Temp\reticle-native-control` holds other runs' directories
(pc-native-sonnet-1)". That was the v1 leftover named above, since removed.

Offline tests: 382 before, 413 after (31 new: native arm 19, driver 8 including one stub-CLI run end to end through the
real `native_control.py` path, comparison 4). The 4 `test_run_card` failures present before (cards 013-015 status
and `note_stop`) were fixed on this branch by `299d861`; the suite is now all green (4 OCI skips).
