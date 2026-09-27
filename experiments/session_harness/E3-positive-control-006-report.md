# E3 positive control 006: Claude Sonnet 5 on `sqlparse-865`, Reticle interface vs Claude Code

Date: 2026-09-27  
Card: [E3-positive-control-006](E3-positive-control-006.md) (approved by the owner; amended before the Arm R rerun)  
Status: **both arms accepted.** Arm R's first run stopped on an adapter failure before any response; the adapter was
fixed and Arm R was rerun once, as the card allows.  
Raw evidence: `experiments/p6_pilot/runs/pc-reticle-sonnet-1/` (Arm R run 1), `experiments/p6_pilot/runs/pc-reticle-sonnet-2/`
(Arm R run 2), `experiments/session_harness/native_runs/pc-native-sonnet-1/` (Arm N); controls and smokes under
`experiments/p6_pilot/runs/pc-*`.  
Arm R: runner v8, `--client claude-cli`, policy `pressure-recent-v3`, toolset `reticle-tools-v3`, OCI image
`8b74015e5079...`; run 1 protocol `7d91aad4cc99` (adapter v1), run 2 protocol `6f1061c028c8` (adapter v2).
Arm N: `native_control.py` v1, Claude Code 2.1.283. Model in both: `sonnet` = `claude-sonnet-5`.
Evaluator for both: `sqlparse-865:inputs-6c22ee52ed71258a:evaluator-6d3921fc4b729ce3` in the same OCI image.

## Outcome

| | Arm R: Reticle interface (run 2) | Arm N: Claude Code's own loop |
|---|---|---|
| Acceptance | **accepted**: fail-to-pass 1/1 pass, pass-to-pass 87/87 pass, 88 tests observed, pytest exit 0 | **accepted**: fail-to-pass 1/1 pass, pass-to-pass 87/87 pass, 88 tests observed, pytest exit 0 |
| Stop | `finish_requested` | CLI completed (`end_turn`), not the turn cap |
| Responses used / budget | 9 / 20 | 11 turns / 20 |
| Tool actions | 15 (up to 4 per response) | 10 (one per turn) |
| First edit of a base file (response / s) | 6 / 54.9 | 8 / 31.5 |
| First command (response / s) | 7 / 59.8 | 9 / 34.4 |
| Checks run | the statement's examples (`python -c`), then `pytest tests/ -q`: 489 passed, 2 xfailed, 1 xpassed | the same two checks, same pytest result |
| Final diff (`git diff --stat` vs the base commit) | `sqlparse/sql.py` +7 -1 | `sqlparse/sql.py` +7 -1 |
| Time | 90.5 active s (95.6 s including evaluation); 75.3 s in 9 CLI processes, 65.1 s of it API time | 45.4 s wall; 37.3 s API time |
| Tokens (as the CLI reports them) | 75,491 input (46,934 cache writes, 28,539 cache reads, 18 uncached), 5,203 output (2,936 thinking) | 233,933 input (224,014 cache reads, 9,897 cache writes, 22 uncached), 3,492 output (1,151 thinking) |
| Attempts | 9 CLI processes, no retry, no timeout | 1 CLI process |
| Billing | unknown (subscription login, `apiKeySource: none`); CLI list-price estimate $0.2455, not billed | unknown; list-price estimate $0.1194, not billed |
| Rejected calls / tool errors | 0 / 0 | 0 / 0 |
| Audit | tools confined to the workspace, OCI without network | no network command, no path outside the workspace, only the 7 allowed tools used |

Both arms made the same change to `NameAliasMixin.get_real_name`: start at the first dot as before, then follow
`token_next_by` to the last dot, and pass that index to `_get_first_name`. Only the comment differs
(`# a.b.c.d -> d, a.b -> b` in R, `# a.b.c.d -> d` in N). The upstream fix (`f66d12c`, dated 2026-07-19) scans
`self.tokens` for the last dot instead; all three give the same results on the hidden tests.

## Arm R trajectory (run 2, `pc-reticle-sonnet-2`)

All 9 CLI attempts succeeded on the first try. "Left" is the remaining-responses figure shown in that request.
"Reply" is how the adapter took the calls from the model's first message: `direct` (the model called the harness
tools directly) or `structured` (a `StructuredOutput` call).

| # | Left | Reply | Tool call(s) (raw arguments, truncated) | Result | Latency |
|---:|---:|---|---|---|---:|
| 1 | 20 | direct | `search_text` x3: `def get_real_name`, `def get_parent_name`, `def _get_first_name` | 2, 1, 1 matches (`sql.py` 19 and 377, 381, 390) | 3.3 s |
| 2 | 19 | direct | `read_file sqlparse/sql.py 360-430` | lines 360-430 of 661 | 4.3 s |
| 3 | 18 | direct | `read_file sql.py 1-40`; `read_file sql.py 300-360` | success | 5.0 s |
| 4 | 17 | direct | `search_text` x4: `def token_next_by`, `def token_matching`, `class Identifier`, `class Function` | 1, 1, 3, 1 matches | 12.3 s |
| 5 | 16 | direct | `read_file sql.py 240-300` | success | 5.1 s |
| 6 | 15 | direct | `replace_text sqlparse/sql.py` (`get_real_name`: walk to the last dot) | replaced 1 occurrence; lines 17-31 shown | 19.8 s |
| 7 | 14 | direct | `run python -c "..."` with the statement's five examples | exit 0: `col`, `col`, `db`, `b`, `z w`, `func` | 4.4 s |
| 8 | 13 | direct | `run python -m pytest tests/ -q` | exit 0: 489 passed, 2 xfailed, 1 xpassed (6.1 s) | 13.1 s |
| 9 | 12 | structured | `finish` ("... returns the name after the LAST dot ...") | finish recorded | 8.0 s |

The materialized Reticle requests grew from 8,666 to 27,522 bytes; every context manifest shows no omitted item and
every item rendered in full under the 80,000-byte policy. The model passed `start_line`/`end_line` and
`timeout_seconds` as strings in responses 2, 3, 5, and 8; the tools accepted them.

**Run 1 (`pc-reticle-sonnet-1`, adapter v1): no response.** All three attempts at the opening request ended in the
CLI's `error_max_turns` (7.0 s, 8.7 s, 7.6 s) because the model called the harness tools as native functions, which
the CLI rejected. The request stopped with `failed after 3 attempts`; the run ended as `model_error` after 38.6 active
seconds (3 attempts, 0 responses, 0 tool actions), and the untouched workspace was scored rejected (fail-to-pass
fail, pass-to-pass pass). This is a mechanism failure, not an outcome; see [below](#what-broke-and-how-it-was-fixed).

## Friction (`interface_friction.py`)

| Run | Stop | Acceptance | Tool calls | Rejected (rate) | Recovery turns | Failed lookups | First command (resp / s) | First base-file edit | First edit (any) |
|---|---|---|---:|---|---|---:|---|---|---|
| E3 run 3 (Qwen3-Coder-Next, toolset v1) | `model_call_limit` | rejected | 20 | 4 (0.20) | 1, 1, 1, never | 1 | none | none | none |
| E3 run 4 (Qwen3-Coder-Next, toolset v2) | `model_call_limit` | rejected | 20 | 4 (0.20) | 1, 3, 2, 1 | 2 | 20 / 57.0 | none | 16 / 47.7 |
| `pc-reticle-sonnet-1` (Sonnet 5, adapter v1) | `model_error` | rejected | 0 | 0 | - | 0 | - | - | - |
| `pc-reticle-sonnet-2` (Sonnet 5, toolset v3) | `finish_requested` | accepted | 15 | 0 (0.0) | - | 0 | 7 / 59.8 | 6 / 54.9 | 6 / 54.9 |

Rows 3-4 are copied from the [run-4 report](E3-sqlparse-qwen-parasail-4.md). Toolset v3 changed between run 4 and
this run, so the friction difference is not attributable to the model alone.

## Arm N (`pc-native-sonnet-1`)

Turns used: 11 of 20 (`num_turns` 11; 11 distinct model messages). Wall: 45.4 s, not timed out, exit 0. Init event:
tools `Bash, Edit, Glob, Grep, PowerShell, Read, Write`, no MCP servers, `apiKeySource: none`, `bypassPermissions`,
no skills or slash commands; CLAUDE.md and memory not loaded (`--safe-mode --setting-sources ""`).

| # | s | Tool | Input (truncated) | Result |
|---:|---:|---|---|---|
| 1 | 3.1 | Grep | `def get_real_name\|def get_parent_name\|def _get_first_name` over the workspace | 4 lines (`sql.py` 19, 377, 381, 390) |
| 2 | 5.2 | Read | `sql.py` from line 360, 50 lines | success |
| 3 | 7.8 | Grep | `class Identifier" -A 40` (grep flags typed into the pattern) | "No matches found" |
| 4 | 9.6 | Grep | `class Identifier`, `-A 40` | `sql.py:448` and following lines |
| 5 | 12.6 | Read | `sql.py` lines 1-45 | success |
| 6 | 18.1 | Grep | `def token_next_by\|def token_next\b\|def token_prev\b\|def _token_matching`, `-A 15` | matches with context |
| 7 | 27.7 | Grep | `class Function`, `-A 10` | `sql.py:623` |
| 8 | 31.5 | Edit | `sql.py` `get_real_name` (walk to the last dot) | updated |
| 9 | 34.4 | Bash | `cd <workspace> && python -c "..."` with the statement's examples | `col col db`, `z w w`, `func`, `b` |
| 10 | 39.5 | Bash | `cd <workspace> && python -m pytest tests/ -q 2>&1 \| tail -30` | 489 passed, 2 xfailed, 1 xpassed |
| 11 | 45.2 | (text) | final summary | - |

`git diff --stat` against a fresh export of the base commit:

```
 sqlparse/sql.py | 8 +++++++-
 1 file changed, 7 insertions(+), 1 deletion(-)
```

No other file changed (cache files excluded; no ignored untracked files). The CLI's network access could not be
disabled; the transcript shows no network command, no web tool (none was available), and no path outside the
workspace, so the accepted result counts as a clean positive under the card's rule. The opening request mentions
"the run tool" and "Call finish", which do not exist in this arm; the model used Bash and ended with a text summary.

## What broke and how it was fixed

**Adapter v1 (Arm R run 1).** The tools were listed as OpenAI function schemas in the system prompt, and the reply
was expected through `--json-schema` (the CLI's `StructuredOutput` call) within three CLI turns. The model instead
called `search_text`, `glob_files`, and `run` directly; the CLI has no such tools and rejected each call, and the
turns ran out. Eight replays of that request (original prompt; "these are not callable functions"; tools as a text
catalog) all called the tools directly first. The three that recovered did so only after seeing the CLI's
rejections, and one reply then said it was "investigating available tools since search_text returned an error":
the CLI's internal errors were leaking into the model's picture of the Reticle tools.

**Adapter v2 (commit `148107e`).** The reply is the model's first message and the CLI stops after it
(`--max-turns 1`), so the model never sees the CLI's rejection. The tool calls come from a `StructuredOutput` call
when the message has one, otherwise from the direct calls in that message. Each attempt records the reply channel
and the CLI-internal events. Checks before the rerun: 258 offline tests (3 new), 2/2 replays of the failing request,
a tool probe (only `StructuredOutput` exposed, no MCP, `apiKeySource: none`), and a one-response smoke under the
arm's exact flags. In run 2, 8 of 9 replies came through the direct channel and 1 (the `finish`) through
`StructuredOutput`.

Nothing else failed: no provider or CLI error, retry, timeout, evaluator error, or budget stop in either accepted run.

## Comparison

- **Acceptance:** equal. Both arms repaired the task well inside the budget (R 9/20 responses, N 11/20 turns;
  neither came near 1,200 s) and made the same code change.
- **Path to the edit:** R batched lookups (3-4 calls per response) and edited at response 6; N issued one call per
  turn and edited at turn 8. Both verified with the same two checks before stopping.
- **Speed:** N was about twice as fast (45.4 s vs 90.5 s active). R starts a fresh CLI process for every response
  (about 10 s of process overhead in total), runs each command in a new container (`podman run --rm`), and thought
  more (2,936 vs 1,151 thinking tokens).
- **Tokens:** R re-sent a selected transcript each time and wrote most of it to the cache anew (46,934 cache-write
  tokens); N re-read its whole conversation, including Claude Code's large system prompt, from the cache every turn
  (224,014 cache-read tokens). The list-price estimates ($0.25 vs $0.12) reflect that difference; neither was billed.
- **Friction:** R had no rejected call and no failed lookup; N had one ineffective Grep (flags typed into the pattern).

Ways the arms were not matched (from the card, all still true): R ran its commands in a Linux container without
network, N on the Windows host with network; R had 15 Reticle tools and no shell, N had shells and Claude Code's file
tools; R was stateless per response under an 80,000-byte policy, N kept one continuous conversation; N received the
opening request without Reticle's contract or resource lines and with Claude Code's system prompt; R counts
responses in the ledger and checks active time before dispatch, N used `--max-turns` and a hard kill; R stopped at
repeated observations, N had no such guard; the arm order was fixed (R, then N); R's reply mechanics changed once
(adapter v1 to v2) before its accepted run. One run per arm on one task: these are development observations, not a
comparison with statistical weight.

## Conclusion

**The Reticle interface does not stop a capable model.** Claude Sonnet 5 repaired `sqlparse-865` through it in 9 of
20 responses with no rejected call, making the same change that Claude Code's own loop made in 11 turns, and the
same evaluator accepted both. Runs 1-4 therefore failed because of the weak models and the friction they met, not
because of the task, the runtime, the OCI path, or the evaluator, all of which now have an accepted live repair
behind them. The task is easy for this model (both arms finished at about half the budget), so it cannot tell
interfaces apart; a harness comparison needs harder tasks.

Public-repository caveat: the fix commit is dated 2026-07-19, after the CLI's stated knowledge cutoff (January
2026), so memorizing this fix is unlikely, but the model knew sqlparse well: in the smoke it reproduced the shape of
`get_real_name` without reading the file.

## Not done

- Card 005 (U2 gate, Qwen run 5) was not run.
- No second run per arm, no randomized arm order, no other task.
- No cost cap: billing is unknown on the subscription; list-price estimates are recorded only as metadata.
- The CLI's internal API retries in Arm N are not visible; Arm N's environment (Windows host, network) was not made
  to match Arm R's container.
- The v7 no-API controls and the v1 smoke are superseded for Arm R run 2 by the v8 controls (unchanged by the adapter
  fix: the fix touches only the claude-cli client) and the v2 smoke.

## Next decision (not taken)

From the card's decision table (accepted, accepted): audit is done above; calibrate the configuration on harder
repairs (the critique's option 3: a private or mutation-generated repair that needs an existing-file edit), where a
capable model does not finish at half the budget, before any memory or interface comparison.
