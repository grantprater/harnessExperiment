# E3-positive-control-006: a capable model through the Reticle interface and through a conventional coding harness

Date: 2026-09-27  
Status: approved by the owner; this card was written and committed after the controls and the smoke and **before
either live arm**. Arm R run 1 then stopped on an adapter failure; the [amendment](#amendment-after-arm-r-run-1-mechanism-failure)
below was committed before the single allowed rerun. Completed 2026-09-27: both arms accepted (Arm R run 2 in 9
responses, Arm N in 11 turns); see [E3-positive-control-006-report.md](E3-positive-control-006-report.md).  
Why: E3 runs 1-4 on `sqlparse-865` used weak free models and none produced an accepted repair (run 4:
[report](E3-sqlparse-qwen-parasail-4.md)). [The plan critique](../../IMPLEMENTATION_PLAN_CRITIQUE.md) asks for a
positive control before more interface work: the same task with a demonstrably capable model, once through the
Reticle interface and once through a conventional coding harness under a matched budget. Card 005 (U2 gate, then
Qwen run 5) is unrun; this card neither runs nor replaces it.  
Source: commit `51e1e9d` (runner v8, `experiments/p6_pilot/claude_cli.py`, `experiments/session_harness/native_control.py`),
clean tree for the controls and the smoke. The live arms run from the commit that adds this card.

## Hypotheses

- **H-R (the Reticle path works for a capable model):** Claude Sonnet 5, acting only through the Reticle tools
  under runner v8 / `pressure-recent-v3` / `reticle-tools-v3` in the pinned OCI image, leaves a final workspace that
  the hidden upstream tests accept, within 20 responses and 20 minutes.
- **H-N (reference):** the same model in Claude Code's own agent loop, from the same base commit and the same
  opening request, also leaves an accepted workspace within 20 turns and 20 minutes.

One run per arm on one task: this is a development diagnostic (plan section 5.1), not a comparison with
statistical weight. What each combination would mean:

| Arm R | Arm N | Reading | Next action |
|---|---|---|---|
| accepted | accepted | Runs 1-4 were limited by the model; the Reticle path can deliver an accepted repair | Audit both trajectories; compare cost of reaching the edit (responses, seconds); calibrate on further tasks under this configuration |
| rejected | accepted | The Reticle protocol or interface inhibits a capable model on this task | Trajectory review of R against N before any other harness work |
| accepted | rejected | Unexpected; N's environment (Windows host, prompt naming absent tools) is the first suspect | Audit N |
| rejected | rejected | The task (statement vs hidden test) or the evaluation path is suspect; the gold control shows the evaluator can accept | Re-derive the task statement from the hidden test; consider an easier or mutation-generated repair |

Failure prediction for R: the stateless per-response rendering, the 80,000-byte context policy, or the lack of a
shell slows the model enough that the 20-response or 1,200-second budget ends the run before a verified edit.

## Arms

| | Arm R: Reticle interface | Arm N: conventional coding harness |
|---|---|---|
| Driver | `run_pilot.py --client claude-cli` (runner v8) | `native_control.py` |
| Model | `--model sonnet` (the init event reports `claude-sonnet-5`); CLI default effort and thinking | same |
| Model loop | Reticle controller; each response is a fresh, stateless `claude -p` process; the `pressure-recent-v3` policy alone decides what the model sees | Claude Code's own agent loop: one `claude -p` process, continuous conversation |
| Reply channel | `--json-schema` structured output `{content, tool_calls}`, converted to OpenAI tool calls; the CLI exposes only `StructuredOutput` (checked on every call) | native tool use |
| Tools | the 15 `reticle-tools-v3` tools (no shell; `run` executes without shell interpretation) | `Bash,PowerShell,Read,Edit,Write,Glob,Grep` (the CLI's coding tools; Agent, web, scheduling, worktree, notebook, and skill tools excluded) |
| Prompt | Reticle system contract, then the opening request, then the remaining-resources line | the same opening request, verbatim (`run_pilot.INSTRUCTIONS` with the task statement), as the whole prompt; Claude Code's default system prompt |
| Execution | pinned OCI image `localhost/reticle-p6-task:py313-v1` (`8b74015e5079...`), workspace-only mount, **no network**, unprivileged user | Windows host, `bypassPermissions`, workspace outside this repository (`%TEMP%\reticle-native-control\<run>\workspace`); **network cannot be disabled for the CLI**; the task interpreter (`.runtime/bugs-venv`, Python 3.13.15, pytest 9.1.1) first on `PATH`, `PYTHONPATH` = workspace |
| Responses | 20 (`--max-calls-per-run 20`) | 20 turns (`--max-turns 20`) |
| Wall time | 1,200 active seconds, checked before each model dispatch (a response already under way can finish past it) | 1,200 s hard kill of the CLI process tree |
| Other limits | 24 CLI attempts (retries included; campaign cap `--max-total-calls 24`); context 80,000 bytes; per-attempt CLI timeout 300 s; at most 3 CLI-internal turns per attempt; no tool-action cap; no monetary cap | none |
| Repeat stop | on: three identical observation calls without a workspace change end the run as `diagnostic_termination` | no equivalent guard (flag only, from the transcript) |
| Provider retries | at most two retries per request (5 s, 10 s backoff); no resume after a provider stop | the CLI's own internal API retries (not visible) |
| Priority | both drivers run at Windows idle priority on a shared machine, single-threaded BLAS | same |

Both nested CLIs run with `--safe-mode --setting-sources "" --strict-mcp-config --disable-slash-commands
--no-session-persistence`, and the child environment drops `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT`,
`CLAUDE_CODE_*`, and `ANTHROPIC_*`. `--bare` is not used: it accepts only `ANTHROPIC_API_KEY` or an apiKeyHelper and
reports "Not logged in" on this machine's subscription login (checked). No API key is used; `apiKeySource` is
`none` in every init event. The CLI still adds a short environment note (working directory, platform, shell names,
date, model name, account e-mail). The runner's config records `temperature: 0` and `max_tokens: 4096`; the
claude-cli client applies neither (the CLI has no such flags).

## Accepted repair (both arms)

The final workspace, whatever the stop reason, is scored by the runner's evaluator path: `build_evaluator` (test
roots and root pytest configuration from the fix commit `f66d12c`), `acceptance_plan` with two executable criteria,
and `AcceptanceRunner` in the OCI image above. **Accepted** means decision status `accepted`: fail-to-pass
(`tests.test_parse::test_get_real_name_multi_part_dotted`) passes and all 87 pass-to-pass tests pass, 88 tests
observed, no collection error. Tests the model writes are not used. For Arm N an accepted workspace counts as a
clean positive only if its transcript shows no network fetch of upstream code and no read outside the workspace;
otherwise it is reported as "accepted, contaminated".

Public-repository caveat: sqlparse is public and the fix may be in the model's training data. The smoke reply
reproduced the shape of `get_real_name` without having read the file. An accepted repair shows the pipeline can
carry a capable model to an accepted workspace; it is not evidence of reasoning from scratch. The caveat applies
to both arms equally.

## Controls and smoke (done before this card)

| Step | Run | Result |
|---|---|---|
| No-API controls, unchanged runner v7 | `pc-v7-control-gold-sqlparse` / `pc-v7-control-noop-sqlparse` (protocols `c45686dc23b4` / `996c0aa8e6d0`) | gold accepted (f2p pass, p2p pass); noop rejected (f2p 1 failing, p2p pass); 88 tests observed each |
| No-API controls, runner v8 at `51e1e9d` | `pc-v8-control-gold-sqlparse` / `pc-v8-control-noop-sqlparse` (`2d8f0db9f80c` / `31d95bc3f460`) | gold accepted; noop rejected; 88 tests observed each |
| Offline suite | `python -m unittest discover -s tests` | 255 passed, 4 OCI skipped (244 before; 9 new adapter tests with a stub `claude` on PATH, 2 native-arm tests) |
| Tool probe | `claude_cli.py --probe-tools` (adapter flags, no Reticle tools) | init tools `["StructuredOutput"]`, no MCP servers, `apiKeySource: none`; the model answered "NONE" and reported no CLAUDE.md, memory, skill list, or MCP instructions |
| Smoke | `pc-smoke-claude-cli`: one response on the opening request (protocol `7d91aad4cc99`) | exit 0, JSON parsed, 5 tool calls converted and dispatched; init tools `["StructuredOutput"]`; 191.7 s, 17,754 thinking tokens; billing unknown |

The smoke's single response was told it was the last one; it wrote four blind `replace_text` guesses at
`get_real_name` (none matched the file) and called `finish`. That is expected under a one-response budget and says
nothing about the arms, except that one response can take about three minutes.

## Fast-stop rules (plan section 5.3, as applied here)

- Stop immediately, keep the artifacts, and repair on evaluator leakage, false acceptance, evidence loss, authority
  escape, budget violation, or a corrupted protocol. For Arm N, a network fetch of upstream code or a read outside
  the workspace is recorded as contamination rather than stopping the run (it cannot be prevented in that arm).
- The no-API controls and the provider/tool-schema smoke above precede the live arms; they are valid for the exact
  runtime, environment, and evaluator inputs used by the arms (commit `51e1e9d` plus this card).
- At most two retries after the first attempt of a request, with recorded backoff; after three consecutive failed
  attempts the request stops (`model_error`) and the run ends (no resume configured).
- Arm R stops at three identical observation calls without a workspace change (`diagnostic_termination`, not a
  natural task failure). Arm N has no such guard; repeated calls are only flagged.
- Each trajectory is reviewed before anything is expanded; there is no further live run on this card.
- A mechanism failure (adapter bug, provider or CLI error, evaluator error) is fixed and that arm is rerun **once at
  most**; both runs are reported.

## Known ways the arms are not matched

1. Execution: R's commands run in a Linux container without network; N runs on the Windows host with network.
2. Tools: R has 15 Reticle tools and no shell; N has shells (Bash, PowerShell) and Claude Code's file tools.
3. Context: R is stateless per response and limited to 80,000 bytes by `pressure-recent-v3`; N keeps its own
   continuous conversation (1M-token window, the CLI's own compaction).
4. Prompt: N receives the opening request verbatim, which mentions "the run tool" and "Call finish", neither of which
   exists in N; N does not see Reticle's contract or resource lines, and sees Claude Code's system prompt instead.
5. Budgets: R counts responses in the durable ledger and checks active time before each dispatch; N relies on the
   CLI's `--max-turns` and a hard wall-clock kill.
6. Reply mechanics: each R response is a structured-output reply (two CLI-internal turns per process).
7. Arm order is fixed (R, then N) by the owner's protocol, not randomized.

## Evidence

- Arm R: `experiments/p6_pilot/runs/pc-reticle-sonnet-1/` (`config.json`, `calls.jsonl` with every attempt's
  request, CLI init and result events, `results.jsonl`); the session journal and workspace stay under `sessions/`
  (git-ignored, retained locally).
- Arm N: `experiments/session_harness/native_runs/pc-native-sonnet-1/` (`config.json`, `stream.jsonl` with arrival
  times, `stderr.txt`, `result.json`, `diff.patch`); the workspace and evaluator session stay under
  `%TEMP%\reticle-native-control\pc-native-sonnet-1\`.
- Friction for R: `experiments/session_harness/interface_friction.py`.

## Commands (repo root, Windows; each wrapped to run at idle priority)

```powershell
# Arm R
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client claude-cli --models sonnet `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v3 --stop-on-repeats `
  --max-calls-per-run 20 --max-attempts-per-run 24 --elapsed-cap-seconds 1200 --max-tokens 4096 `
  --max-total-calls 24 --run-name pc-reticle-sonnet-1
# Arm N (after Arm R has finished)
.\.runtime\test-venv\Scripts\python.exe experiments/session_harness/native_control.py --task sqlparse-865 `
  --model sonnet --max-turns 20 --wall-seconds 1200 --backend oci --run-name pc-native-sonnet-1
```

Spend: none billed to an API account. Both arms use the local Claude Code subscription; the CLI's
`total_cost_usd` is a list-price estimate (the smoke's one response: $0.218) and is recorded as metadata only. At the
smoke, the subscription's five-hour window was 28% used and the seven-day window 64%.

## Amendment after Arm R run 1 (mechanism failure)

Committed before the rerun; nothing above is changed except the status line.

**What happened.** `pc-reticle-sonnet-1` (protocol `7d91aad4cc99`, adapter v1) made no model response. All three
attempts at the opening request ended in the CLI's `error_max_turns` (7.0 s, 8.7 s, and the third), the request
stopped with `failed after 3 attempts`, and the run ended as `model_error` after 38.6 active seconds: 3 attempts, 0
responses, 0 tool actions; the untouched workspace was scored rejected (f2p fail, p2p pass, 88 tests). This is an
adapter failure, not a model or task outcome.

**Cause.** The model called the harness tools (`search_text`, `glob_files`, `run`) as native functions. The CLI has
none of them, rejected each call ("No such tool available"), and the three CLI-internal turns ran out before the
model used `StructuredOutput`. Replaying that exact request eight times, with the original prompt and two reworded
ones (explicit "these are not callable functions"; tools as a text catalog), gave the same first move every time; in
the three replays that recovered through `StructuredOutput`, the model had already seen the rejections (one reply
said it was "investigating available tools since search_text returned an error"). A prompt fix alone would leave the
CLI's rejections in the model's view.

**Fix (adapter v2, commit `148107e`).** The reply is the model's first message, and the CLI stops after it
(`--max-turns 1`), so the model never sees the CLI's rejection. The tool calls are taken from a `StructuredOutput`
call when the message has one, otherwise from the direct calls in that message (recorded per attempt as
`reply_channel`, with the CLI-internal events in `cli_turns`). `--json-schema` is still passed. Tools are listed as a
text catalog. The contract now records the adapter version and `--max-turns 1`, so the protocol is `6f1061c028c8`.
What the model sees from Reticle (messages, tools, resource lines) and every budget are unchanged.

| Check (after the fix) | Result |
|---|---|
| Offline suite | 258 passed, 4 OCI skipped (3 new adapter tests: direct calls are the reply and the rejection never reaches the next request; `StructuredOutput` wins over direct calls in the same message; only the first message counts) |
| Replays of run 1's opening request through `ClaudeCliClient` v2 | 2 of 2 returned three `search_text` calls (`direct_tool_use`), 3.1 s and 4.3 s |
| Tool probe v2 (`pc-smoke-claude-cli-v2-toolprobe`) | init tools `["StructuredOutput"]`, no MCP servers, `apiKeySource: none`; answer "NONE", no CLAUDE.md/memory/skills/MCP (it noted that the CLI's environment note mentions Bash, which it cannot call) |
| Smoke v2 (`pc-smoke-claude-cli-v2`): the arm's exact flags with `--max-total-calls 1`, so the one response sees "20 remaining" | one response in 3.4 s, three `search_text` calls dispatched in OCI, all succeeded; the second request stopped at the campaign cap with no phantom attempt (1 attempt consumed, nothing pending) |

**Rerun.** Arm R is rerun once as `pc-reticle-sonnet-2` with the command above (run name changed); Arm N is
unaffected. If the rerun also stops on a mechanism failure, it is reported as such and not run again.
