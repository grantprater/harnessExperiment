# E3-repair-control-005: toolset v3 (coding-tool interface contract), U2 gate, then Qwen run 5 (proposed)

Date: 2026-09-15  
Status: proposed, awaiting approval. No model call has been made for this card.  
Why: E3 run 4 ([report](E3-sqlparse-qwen-parasail-4.md)) still made no library edit; 3 of its 20 responses went to
a rejected `cd /testbed && ...` command whose error did not show a recovery. IMPLEMENTATION_PLAN.md's
"Coding-tool interface contract" proposes a more typical interface. This card tests that interface.  
Source hashes: `E3-source-manifest.sha256`

## What changed (versioned; card 004's configuration is unchanged and not described as testing these names)

| Component | Card 004 | This card |
|---|---|---|
| Toolset | `reticle-tools-v2` | `reticle-tools-v3` |
| File discovery | `list_files(path, file_glob)` | `glob_files(glob, path=".")`: sorted relative paths; glob matches relative path or file name with Python fnmatch rules, **case-sensitive**; never matches contents; cache/VCS directories skipped (documented in the schema) |
| Content search | `search(query, path, file_glob)` | `search_text(query, path=".", file_glob="*")`: exact text, case-sensitive; results and empty results state mode, path, file_glob, and files searched. **No `regex` argument** (not implemented; `regex` is rejected with an explanation) |
| Unknown arguments | ignored with a note | rejected with a specific hint (e.g. `pattern` on `search_text`) plus accepted arguments and an example |
| `run` rejections | "shell operators are not supported" | names the operators; for `cd <dir> && cmd` says commands already run in the workspace root and shows `Run instead: {"command": "cmd"}`; a bare `cd` is explained |
| Tool descriptions | - | state inclusive line ranges, overwrite and parent-directory creation, no shell/`cd`/expansion, paging ids, and that process success is not acceptance |
| Legacy names | - | `list_files`/`search` are not in the schema; dispatch keeps their v2 behavior with an explicit legacy-name note, for recordings |
| Context policy | `pressure-recent-v2` ("X of Y") | `pressure-recent-v3`: "X remaining (limit Y)", and attempts whose billing is unknown are stated |
| Runner | v6 | v7 (`pressure-recent-v3` arm; new tool names in repeat detection) |

Offline validation: `tests/test_toolset_v3.py` 16 passed (glob rules and ordering, case sensitivity, cache skipping,
literal punctuation, file selection vs content, empty-result scope, binary skipping, missing/unknown/regex arguments,
inclusive line ranges, edit ambiguity without mutation, replacement counts, parent-directory creation, `cd`/pipe
guidance, run status/exit/timeout, labeled limits with unknown billing). Full offline suite 244 passed, 4 OCI skipped.
No-API controls under the exact configuration: `e3v7-control-gold-sqlparse` accepted, `e3v7-control-noop-sqlparse`
rejected; `u2-control-gold` passed (3/3 requests with status), `u2-control-noop` failed the hidden check.

These changes are bundled: a result cannot attribute benefit to any single rename or message.

## Step 1: U2 usability fixture (gate)

`run_u1.py --fixture u2`. The `inventory` package applies percentage discounts ten times too strongly, in two
functions whose defective line is identical, so a single exact replacement is ambiguous. `docs/discounts.md` states
the intended rule and a report module uses the pricing code. Visible tests cover only `apply_discount`; the hidden
check also covers `apply_coupon`, the report, and unchanged totals. `pressure-recent-v3`, toolset v3, repeat stop on.

| Limit | Value |
|---|---|
| responses / HTTP attempts / tool actions | 12 / 14 / 24 |
| active seconds / cost | 240 / $0.05 (reserves $0.004557 per attempt) |
| context / `max_tokens` / temperature | 32,000 bytes / 4096 / 0 |

**Pass rule (fixed):** the hidden check passes, **and** every rejected call is followed by a non-rejected call of the
same tool, **and** every request contains the remaining-resources line. Friction is reported alongside.
**If U2 does not pass:** stop and review; steps 2-3 are not run.

## Steps 2-3: smoke and E3 run 5 (only if U2 passes)

Identical to card 004's run (Qwen3-Coder-Next @ Parasail, sqlparse-865, OCI image, 20 responses, 24 attempts, 40 tool
actions, 480 active seconds, $0.10, repeat stop, up to 2 resumes) except `--arm pressure-recent-v3` with runner v7 and
toolset v3. Dry run: protocol `9138935e846d`.

## Requested approval: at most 47 HTTP attempts, at most $0.2775 worst case

| Step | Attempts (max) | Worst case |
|---|---:|---:|
| 1. U2 fixture | 14 | $0.0638 |
| 2. Smoke | 3 | $0.0194 |
| 3. E3 run 5 | 30 | $0.1943 |
| Total | 47 | $0.2775 |

Expected: U1 cost $0.003 and run 4 $0.036; about $0.045 in total.

```powershell
# 1. U2 gate
.\.runtime\test-venv\Scripts\python.exe experiments/session_harness/run_u1.py --fixture u2 --client openrouter `
  --model qwen/qwen3-coder-next --provider parasail --max-total-calls 14 --run-name u2-qwen-parasail-1
# 2. smoke (only if U2 passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v3 --stop-on-repeats `
  --max-calls-per-run 1 --max-attempts-per-run 3 --max-tool-actions-per-run 2 `
  --elapsed-cap-seconds 120 --cost-ceiling-usd 0.02 --max-total-calls 3 --max-tokens 4096 `
  --run-name e3-smoke-qwen-parasail-v3
# 3. E3 run 5 (only if the smoke passes)
.\.runtime\test-venv\Scripts\python.exe experiments/p6_pilot/run_pilot.py --client openrouter `
  --models qwen/qwen3-coder-next --provider qwen/qwen3-coder-next=parasail `
  --tasks sqlparse-865 --backend oci --arm pressure-recent-v3 --stop-on-repeats `
  --resume-after-provider-stop 2 --resume-wait-seconds 300 `
  --max-calls-per-run 20 --max-attempts-per-run 24 --max-tool-actions-per-run 40 `
  --elapsed-cap-seconds 480 --cost-ceiling-usd 0.10 --max-total-calls 30 --max-tokens 4096 `
  --run-name e3-sqlparse-qwen-parasail-5
```

## Outcome classes, decision rule, and audit

As in cards 001-004. The primary endpoint is an accepted repair; friction (rejected calls, recovery turns, failed
lookups, first command and first edit) is reported beside it and compared with runs 3-4. There is no further live run
before the trajectory review.
