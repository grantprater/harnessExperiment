# E3 run 3: `sqlparse-865`, Qwen3-Coder-Next pinned to Parasail (chunked)

Date: 2026-09-15  
Card: [E3-repair-control-003](E3-repair-control-003.md) (approved "Approved")  
Status: response budget reached (`model_call_limit`); not accepted  
Raw evidence: `experiments/p6_pilot/runs/e3-smoke-qwen-parasail/` and
`experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-3/` (`config.json`, `calls.jsonl`, `results.jsonl`;
session journal and workspace git-ignored, kept locally)  
Protocol `3a06264aaf6c`, runner v5; source hashes in `E3-source-manifest.sha256`

## Smoke (passed)

1 HTTP attempt, HTTP 200 from Parasail, 1.01 s, `list_files` (valid), $0.0003232.

## Run 3: every model response

All 20 HTTP attempts returned 200 from Parasail; no retries, no provider stop, no resume. Every response
carried one short narration sentence plus one tool call.

| # | Prompt / completion tok | Request bytes | Tool call (raw arguments, truncated) | Result status |
|---:|---|---:|---|---|
| 1 | 2,422 / 39 | 6,919 | `list_files {"path": "."}` | success, 88 files |
| 2 | 3,057 / 43 | 9,491 | `read_file {"path": "sqlparse/sql.py"}` | success, lines 1-661 |
| 3 | 11,895 / 134 | 36,509 | `search {"pattern": "get_real_name\|get_parent_name\|get_name", "path": "tests"}` | **rejected**: missing required argument 'query' |
| 4 | 12,061 / 31 | 37,267 | `search {"query": "get_real_name", "path": "tests"}` | success, 19 matches |
| 5 | 12,553 / 61 | 38,915 | `read_file tests/test_parse.py 460-480` | success |
| 6 | 12,988 / 57 | 40,120 | `read_file tests/test_regressions.py 100-130` | success |
| 7 | 13,581 / 66 | 42,226 | `read_file tests/test_regressions.py 450-480` | success |
| 8 | 14,209 / 66 | 44,216 | `read_file tests/test_grouping.py 310-340` | success |
| 9 | 14,809 / 58 | 45,940 | `read_file tests/test_grouping.py 620-670` | success |
| 10 | 15,663 / 64 | 48,258 | `read_file sqlparse/engine/grouping.py 1-100` | success |
| 11 | 17,019 / 50 | 52,654 | `search {"pattern": "def group_.*identifier", "path": ".../grouping.py"}` | **rejected**: missing 'query' |
| 12 | 17,102 / 35 | 53,114 | `search {"query": "def group", ...}` | success, 25 matches |
| 13 | 17,600 / 66 | 54,977 | `read_file grouping.py 164-270` | success |
| 14 | 19,282 / 55 | 59,631 | `search {"pattern": "def _group\\(", ...}` | **rejected**: missing 'query' |
| 15 | 19,370 / 37 | 60,109 | `search {"query": "^def _group", ...}` | success, 0 matches (search is literal) |
| 16 | 19,445 / 37 | 60,499 | `search {"pattern": "^_group", ...}` | **rejected**: missing 'query' |
| 17 | 19,515 / 49 | 60,884 | `read_file grouping.py 50-165` | success |
| 18 | 21,091 / 61 | 65,600 | `read_file grouping.py 300-450` | success |
| 19 | 23,374 / 67 | 71,982 | `read_file grouping.py 480-520` | success |
| 20 | 24,093 / 64 | 74,249 | `read_file grouping.py 450-485` | success |

Narration at response 3: "I can see that `NameAliasMixin` (lines 16-38) implements `get_real_name()` and
`get_alias()`. Let me also check the `get_name()` and `get_parent_name()` methods in `TokenList` (lines 368-388)."

## Audit

- Context: no transcript unit was omitted and every result was rendered in full (peak request 74,249 of 80,000 bytes).
- Repeats: no identical observation call; the repeat stop did not trigger.
- Tool schema: `search` requires `query` ("Find lines containing a literal string") and also accepts `pattern`,
  a glob on file paths. Four of 20 calls passed a regex-like `pattern` without `query` and were rejected;
  the model used `query` on its next search each time. One literal query (`^def _group`) returned 0 matches.
- Upstream fix location: `NameAliasMixin.get_real_name` in `sqlparse/sql.py` (take the component after the
  last dot, 5+/2- lines). The model named that method and its line range at response 3, then read tests
  (responses 4-9) and `sqlparse/engine/grouping.py` (responses 10-20). It ran no command and edited no file.

## Outcome

- Stop: `model_call_limit` (20 responses); 1 invocation.
- Acceptance: rejected; fail-to-pass failed (`tests.test_parse::test_get_real_name_multi_part_dotted`),
  pass-to-pass passed, 88 tests observed. Final workspace unchanged from the base commit.
- Ledger: 20 responses, 20 attempts, 20 tool actions (4 rejected), 38.2 active seconds, $0.02704108
  (reported = charged); nothing pending. Wall time 43.2 s.
- Card class: **resource stop** (response budget), no library edit.

## Spend against the approval

Approved: at most 33 attempts, $0.2137 worst case. Used: 21 attempts (smoke 1, run 20), $0.0274 reported.

## Across E3 runs (sqlparse-865)

| Run | Model @ provider | Responses | Stop | Library edit | Commands run | Cost |
|---|---|---:|---|---|---:|---:|
| 1 | gemma-4-26b @ DeepInfra | 4 | provider 429 | no | 1 | $0.0011 |
| 2 | gemma-4-26b @ Cloudflare | 18 | repeat stop | no | 2 | $0.0306 |
| 3 | Qwen3-Coder-Next @ Parasail | 20 | response budget | no | 0 | $0.0270 |

## Observed usability issues (kept with E3)

These are observed interface issues, not a separate research campaign. The revised interface
(toolset `reticle-tools-v2`, context policy `pressure-recent-v2`, runner v6) addresses them. Accepted
repairs remain the check on whether the revision helps.

| Principle | Observed in E3 | Revision |
|---|---|---|
| Names should match expectations | `search.pattern` was used as a text pattern: 4 of 20 calls passed a regex-like `pattern` without `query` | renamed to `file_glob` in `search` and `list_files`; the old name is still applied, with an explicit note |
| Errors should support immediate recovery | the rejection said only "missing required argument 'query'" | rejections say what the tool does, list the accepted arguments, and give an example call; ignored unknown arguments and literal-only matching are stated |
| Constraints should be observable | only the static budget limits were visible; the run ended at 20 responses while still exploring | every request states remaining responses, HTTP attempts, tool actions, active seconds, and cost |

Friction baseline (`interface_friction.py`, from saved logs only). "Recovery turns" counts responses until the
same tool next ran without a rejection; "never" means no later call of that tool.

| Run | Tool calls | Rejected (rate) | Recovery turns | Failed lookups | First command (response / s) | First edit of an existing file | First edit (any) |
|---|---:|---|---|---:|---|---|---|
| E3 run 1, gemma @ DeepInfra | 4 | 0 (0.00) | - | 0 | 3 / 152.2 | none | 2 / 146.5 (new script) |
| E3 run 2, gemma @ Cloudflare | 18 | 0 (0.00) | - | 0 | 5 / 13.5 | none | 4 / 11.9 (new script) |
| E3 run 3, Qwen3-Coder-Next @ Parasail | 20 | 4 (0.20) | 1, 1, 1, never | 1 | none | none | none |

## Next decision (not taken)

The card rules out an automatic cap increase and a further live run before review. Options (one change each):

1. Raise the per-run response budget (for example to 40) with everything else fixed. Run 3 was not
   repeating and was still exploring when the budget ended; at this run's rate, 40 responses would cost
   about $0.06-0.08.
2. Fix the `search` argument ambiguity (4 of 20 calls rejected), for example by stating that `pattern` is a
   path glob and that `query` is literal and required. This changes the tool schema, so the no-API controls
   rerun.
3. Add instructions to reproduce and edit early. This changes the prompt, and the hypothesis would need stating.
4. Run Devstral 2 @ Mistral as a separately labeled diagnostic (about 4 times the per-request cost).
