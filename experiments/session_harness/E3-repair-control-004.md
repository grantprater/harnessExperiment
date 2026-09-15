# E3-repair-control-004: revised interface, usability gate, then Qwen on sqlparse-865 (proposed)

Date: 2026-09-15  
Status: approved and run 2026-09-15. [U1](U1-qwen-parasail-1.md) passed; smoke passed; run 4 reached the 20-response budget with no library edit, not accepted. See [E3-sqlparse-qwen-parasail-4.md](E3-sqlparse-qwen-parasail-4.md).  
Why: E3 runs 1-3 made no library edit. Run 3 (Qwen3-Coder-Next) showed interface friction: 4 of 20 calls
were rejected, and it stopped at the response limit while still exploring
([report, including observed usability issues](E3-sqlparse-qwen-parasail-3.md)). Following the user's plan:
make remaining resources observable, clarify search naming and errors, check the interactions in a tiny
fixture, then rerun Qwen on the same repair under a newly versioned configuration.  
Source hashes: `E3-source-manifest.sha256`

## What changed (versioned)

| Component | Before (card 003) | This card |
|---|---|---|
| Context policy | `pressure-recent-v1` | `pressure-recent-v2`: every request also states remaining model responses (including this one), HTTP attempts, tool actions, active seconds, and cost, read from the durable ledger and invocation limit at build time; `pressure-recent-v1` is byte-identical to before |
| Toolset | unversioned | `reticle-tools-v2`: `search`/`list_files` take `file_glob` (the old name `pattern` still works, with a note); rejections list accepted arguments and give an example call; ignored unknown arguments are reported; empty searches state that matching is literal. Matching semantics unchanged |
| Runner | v5 | v6: `pressure-recent-v2` arm; toolset version in the protocol hash |

Offline validation: `tests/test_s3_interface.py` 12 passed (resource status matches the ledger per request, the
invocation limit is used when lower, v1 is unchanged, the fallback does not pass status, `file_glob` and the alias
note, recoverable errors, literal matching, friction metrics); full offline suite 228 passed, 4 OCI skipped.
No-API controls under the exact v6 configuration: `e3v6-control-gold-sqlparse` accepted,
`e3v6-control-noop-sqlparse` rejected.

## Step 1: U1 usability fixture (gate)

`experiments/session_harness/run_u1.py`: a three-file `names` package with a one-line bug in `last_component`
(returns the second component of a dotted name). The task does not name the function. Visible tests exist; a hidden
check runs afterwards in the same isolated OCI environment. Policy `pressure-recent-v2`, toolset v2, repeat stop on.

| Limit | Value |
|---|---|
| model responses / HTTP attempts / tool actions | 8 / 10 / 16 |
| active seconds / cost | 180 / $0.03 (reserves $0.004237 per attempt) |
| context | 24,000 bytes; `max_tokens` 4096; temperature 0 |
| campaign cap | `--max-total-calls 10` |

**Pass rule (fixed):** the hidden check passes, **and** every rejected tool call is followed by a non-rejected call
of the same tool, **and** every model request contains the remaining-resources line. Also reported: friction
(rejected rate, recovery turns, failed lookups, first command and first edit), stop reason, and cost.
No-API controls: `u1-control-gold` passed (3/3 requests with status), `u1-control-noop` failed the hidden check.

**If U1 does not pass:** stop and review; steps 2-3 are not run.

## Steps 2-3: smoke and E3 run 4 (only if U1 passes)

Identical to card 003 (Qwen3-Coder-Next @ Parasail, sqlparse-865, OCI image, same budgets: 20 responses,
24 attempts, 40 tool actions, 480 active seconds, $0.10; repeat stop; up to 2 chunked resumes), except for
`--arm pressure-recent-v2` and runner v6 / toolset v2. Run 4 dry run: protocol `4d1c4f5d945d`.

## Requested approval: at most 43 HTTP attempts, at most $0.2561 worst case

| Step | Attempts (max) | Worst case |
|---|---:|---:|
| 1. U1 fixture | 10 | $0.0424 |
| 2. Smoke | 3 | $0.0194 |
| 3. E3 run 4 | 30 | $0.1943 |
| Total | 43 | $0.2561 |

Expected: U1 under $0.01; run 3's configuration cost $0.027 for 20 responses.

```powershell
# 1. U1 gate
.\.runtime\test-venv\Scripts\python.exe experiments/session_harness/run_u1.py --client openrouter `
  --model qwen/qwen3-coder-next --provider parasail --max-total-calls 10 --run-name u1-qwen-parasail-1
# 2. smoke (only if U1 passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v2 --stop-on-repeats `
  --max-calls-per-run 1 --max-attempts-per-run 3 --max-tool-actions-per-run 2 `
  --elapsed-cap-seconds 120 --cost-ceiling-usd 0.02 --max-total-calls 3 --max-tokens 4096 `
  --run-name e3-smoke-qwen-parasail-v2
# 3. E3 run 4 (only if the smoke passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v2 --stop-on-repeats `
  --resume-after-provider-stop 2 --resume-wait-seconds 300 `
  --max-calls-per-run 20 --max-attempts-per-run 24 --max-tool-actions-per-run 40 `
  --elapsed-cap-seconds 480 --cost-ceiling-usd 0.10 --max-total-calls 30 --max-tokens 4096 `
  --run-name e3-sqlparse-qwen-parasail-4
```

## Outcome classes, decision rule, and audit

As in cards 001-003. The primary endpoint remains an accepted repair; friction metrics are reported beside it,
compared with run 3's baseline. There is no further live run before the trajectory review.
