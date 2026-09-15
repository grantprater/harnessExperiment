# E3 run 2: `sqlparse-865`, gemma-4-26b pinned to Cloudflare (chunked)

Date: 2026-09-15  
Card: [E3-repair-control-002](E3-repair-control-002.md) (approved "Yes, run it")  
Status: diagnostic termination (repeat stop); not accepted  
Raw evidence: `experiments/p6_pilot/runs/e3-smoke-gemma-cloudflare/` and
`experiments/p6_pilot/runs/e3-sqlparse-gemma-cloudflare-2/` (`config.json`, `calls.jsonl`, `results.jsonl`;
session journal and workspace git-ignored, kept locally)  
Protocol `4c97104f37a2`, runner v5; source hashes in `E3-source-manifest.sha256`

## Smoke (passed)

1 HTTP attempt, HTTP 200 from Cloudflare, 1.03 s, `list_files` (valid), 1,698 / 13 tokens, $0.0001737.

## Run 2: every model response

All 18 HTTP attempts returned 200 from Cloudflare; no retries, no provider stop, no resume.

| # | Latency s | Prompt / completion tok | Request bytes | Tool call (raw arguments, truncated) | Result |
|---:|---:|---|---:|---|---|
| 1 | 0.85 | 1,699 / 13 | 6,919 | `list_files {}` | 88 files |
| 2 | 0.79 | 2,481 / 22 | 9,372 | `search {"query": "def get_real_name"}` | 2 matches |
| 3 | 1.23 | 2,579 / 30 | 9,807 | `read_file {"path": "sqlparse/sql.py", "start_line": 1}` | lines 1-661 (25,578 chars) |
| 4 | 7.42 | 11,941 / 509 | 36,764 | `write_file reproduce_issue.py` | created, 38 lines |
| 5 | 1.06 | 12,491 / 22 | 38,732 | `run python reproduce_issue.py` | exit 0; `get_real_name: schema` for `db.schema.tbl.col` |
| 6 | 9.62 | 12,839 / 626 | 39,718 | `write_file reproduce_issue_v2.py` | created, 49 lines |
| 7 | 2.43 | 13,509 / 21 | 42,148 | `run python reproduce_issue_v2.py` | exit 0; prints the wrong names; "TEST FAILED" |
| 8 | 1.57 | 13,629 / 39 | 42,683 | `read_file sql.py 16-410` | 16,047 chars |
| 9 | 1.57 | 19,448 / 42 | 59,663 | `read_file sql.py 16-410` (repeat 2) | 16,047 chars |
| 10 | 2.39 | 25,275 / 38 | 76,745 | `read_file sql.py 16-45` | |
| 11 | 1.78 | 25,800 / 40 | 78,444 | `read_file sql.py 380-390` | |
| 12 | 1.47 | 26,070 / 38 | 79,339 | `read_file sql.py 16-41` | |
| 13 | 3.02 | 25,797 / 38 | 78,627 | `read_file sql.py 16-37` | |
| 14 | 2.92 | 26,131 / 40 | 79,580 | `read_file sql.py 380-410` | |
| 15 | 1.89 | 17,313 / 40 | 54,349 | `read_file sql.py 400-661` | |
| 16 | 1.36 | 20,927 / 43 | 64,637 | `read_file sql.py 16-37` (repeat 2) | |
| 17 | 1.15 | 21,358 / 40 | 66,044 | `read_file sql.py 380-410` (repeat 2) | |
| 18 | 1.93 | 21,904 / 39 | 67,770 | `read_file sql.py 16-410` (repeat 3) | repeat stop set |

Request 19 (79,369 bytes) was not sent: the runner stopped before dispatch with
`diagnostic_termination: three identical read_file calls without a workspace change`.

## What was visible at each repeat (from the context manifests)

- Every selected transcript item in requests 9-19 was rendered in full; no bounded views were used.
- Omissions began at request 13 (earliest exchange) and reached 6 units at request 19: `list_files`,
  `search`, the full-file read (lines 1-661, omitted from request 15), and the two scripts with their first run.
- At every repeated read, the identical earlier result was present in full in that request:
  request 9 contained out_8 (lines 16-410, the immediately preceding result); request 16 contained out_13
  (16-37); request 17 contained out_14 (380-410); request 18 contained out_8 and out_9 (16-410).
- Request 19's contract names `search_history`, `history`, and `read_artifact` and carries the omission
  notice. The model called none of the history or output-paging tools.

## Outcome

- Stop: `diagnostic_termination` (controller `model_error`); 1 invocation, no resumes.
- Acceptance: rejected; fail-to-pass failed (`tests.test_parse::test_get_real_name_multi_part_dotted`),
  pass-to-pass passed, 88 tests observed.
- Final workspace: `reproduce_issue.py` and `reproduce_issue_v2.py` added; no library source change.
- Ledger: 18 responses, 18 attempts, 18 tool actions, 58.5 active seconds, $0.0306231 (reported = charged);
  nothing pending. Wall time 63.5 s.
- Card class: **diagnostic termination** (with no library edit).

## Spend against the approval

Approved: at most 33 attempts, $0.1286 worst case. Used: 19 attempts (smoke 1, run 18), $0.0308 reported.

## Observations for review (not conclusions)

- Provider reliability: 19/19 attempts succeeded on Cloudflare, median latency about 1.6 s.
- Across E3 runs 1-2 and pilot 2, gemma-4-26b made no library edit on this task (4, 18, and 25 responses).
- In run 2 the repeated reads were of content already visible in full. Context omission and missing
  retrieval therefore do not explain these repeats.
- Requests reached 76-80 KB (of 80 KB) by request 10, driven by the full-file read and two 16 KB range reads.

## Next decision (not taken)

The card requires review before another live run. Options:

1. Change the model to one of the probe-eligible coding models (Qwen3-Coder-Next @ Parasail, or
   Devstral 2 @ Mistral) under a new card and smoke. This changes the model and provider, and keeps the
   task, tools, context policy, environment, and budgets.
2. Keep gemma and change the interface (for example instructions about editing, or a different context
   budget). The run does not show an interface defect behind the repeats, so the hypothesis would need stating.
3. Move to a different development task with the same model, to separate task difficulty from model behavior.
