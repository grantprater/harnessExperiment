# E3 run 4: `sqlparse-865`, Qwen3-Coder-Next @ Parasail, revised interface

Date: 2026-09-15  
Card: [E3-repair-control-004](E3-repair-control-004.md) (approved "Yes"); gate [U1 run 1](U1-qwen-parasail-1.md) passed; smoke passed  
Status: response budget reached (`model_call_limit`); not accepted  
Raw evidence: `experiments/p6_pilot/runs/e3-smoke-qwen-parasail-v2/`, `experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-4/`  
Protocol `4d1c4f5d945d`; runner v6; policy `pressure-recent-v2`; toolset `reticle-tools-v2`

## Trajectory

All 20 HTTP attempts returned 200 from Parasail. "Left" is the remaining-responses figure shown in that request.

| # | Left | Tool call (raw arguments, truncated) | Result |
|---:|---:|---|---|
| 1 | 20 | `list_files {"path": "."}` | 88 files |
| 2 | 19 | `read_file sqlparse/sql.py` | lines 1-661 |
| 3 | 18 | `search {"pattern": "get_real_name", "path": "tests"}` | **rejected**: missing `query`; search finds literal text; `pattern` only selects files; example given |
| 4 | 17 | `search {"query": "get_real_name", "path": "tests"}` | 19 matches |
| 5-7 | 16-14 | `read_file` tests (test_parse 460-480, test_regressions 100-130, 455-480) | success |
| 8 | 13 | `read_file sqlparse/engine/grouping.py 1-100` | success |
| 9 | 12 | `search {"query": "def group_.*identifier"}` | 0 matches, "matched as literal text, not a regex" |
| 10 | 11 | `search {"query": "def group_"}` | 24 matches |
| 11-12 | 10-9 | `read_file grouping.py 248-290, 164-195` | success |
| 13 | 8 | `search {"query": "^def _group\\("}` | 0 matches, literal-text note |
| 14 | 7 | `search {"query": "def _group"}` | 2 matches |
| 15 | 6 | `read_file grouping.py 473-520` | success |
| 16 | 5 | `write_file test_issue.py` (77-line reproduction script) | created |
| 17 | 4 | `run {"command": "cd /testbed && python test_issue.py"}` | **rejected**: shell operators are not supported; example given |
| 18 | 3 | same call | **rejected** (same message) |
| 19 | 2 | same call ("Let me try a different approach") | **rejected** (same message) |
| 20 | 1 | `run {"command": "python test_issue.py"}` | exit 0; script prints the parse results |

At response 3 the model again located `NameAliasMixin` (lines 16-37) and `TokenList` (377-388) in `sql.py`; the
upstream fix is in `NameAliasMixin.get_real_name`. No transcript unit was omitted (peak request 64,459 bytes).

## Outcome

- Stop: `model_call_limit` (20 responses). Acceptance: rejected; fail-to-pass failed, pass-to-pass passed, 88 tests observed.
- Final workspace: new `test_issue.py`; no library source change.
- Ledger: 20 responses, 20 attempts, 20 tool actions, 59.2 active seconds, $0.0359782 (reported = charged); nothing pending.

## Friction compared with run 3 (`interface_friction.py`)

| Run | Rejected (rate) | Recovery turns | Failed lookups | First command (resp / s) | First edit of an existing file | First edit (any) |
|---|---|---|---:|---|---|---|
| 3 (v1 policy, unversioned tools) | 4 (0.20) | 1, 1, 1, never | 1 | none | none | none |
| 4 (v2 policy, toolset v2) | 4 (0.20) | 1, 3, 2, 1 | 2 | 20 / 57.0 | none | 16 / 47.7 |

## Observed usability issues (kept with E3)

- **Search:** one `pattern` misuse remained (response 3), with recovery on the next call. Both regex-style
  queries were followed by a working literal search on the next call.
- **Run rejection (new):** `cd /testbed && python test_issue.py` was rejected three times with the same message. The
  message says shell operators are unsupported but not that commands already run in the workspace root (so `cd` is
  unnecessary), and it does not show the corrected command. `/testbed` does not exist in this environment.
- **Repeated rejected calls:** the repeat stop counts identical observation calls only, so three identical rejected
  `run` calls did not trigger it.
- **Countdown:** accurate in every request (20 down to 1). The reproduction script started at "5 left"; no library
  edit or `finish` followed.

## Spend against card 004

Approved: at most 43 attempts, $0.2561 worst case. Used: 29 attempts (U1 8, smoke 1, run 20), $0.0393 reported
(U1 $0.0030, smoke $0.0003, run $0.0360).

## Next decision (not taken)

1. Make the `run` rejection recoverable: say commands already run in the workspace root and show the command with
   the leading `cd <dir> &&` removed. Optionally count identical rejected calls toward the repeat stop. (Toolset v3;
   no-API controls rerun.)
2. Raise the response budget (for example to 40), with the interface fixed.
3. Add an instruction to reproduce and edit early. This is a prompt change; the hypothesis needs stating.
4. Change the task (a different development bug), to separate task difficulty from this model's exploration pattern.
