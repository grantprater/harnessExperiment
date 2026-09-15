# E3 run 1: `sqlparse-865`, gemma-4-26b pinned to DeepInfra

Date: 2026-09-15  
Card: [E3-repair-control-001](E3-repair-control-001.md) (approved "Yes, run it")  
Status: stopped by provider rate limiting (the card's infrastructure class); not accepted  
Raw evidence: `experiments/p6_pilot/runs/e3-smoke-gemma-deepinfra/` and
`experiments/p6_pilot/runs/e3-sqlparse-gemma-deepinfra-1/` (`config.json`, `calls.jsonl`,
`results.jsonl`; session journals and workspaces are git-ignored, kept locally under `sessions/`)  
Protocol `47260c3bca2d`, runner v4; source hashes in `E3-source-manifest.sha256`

## Smoke (passed)

1 HTTP attempt, HTTP 200, 1.27 s. Tool call `list_files {"path": "."}` (a known tool with a JSON-object argument).
1,697 prompt / 15 completion tokens, $0.00012389 reported.

## Run 1: every HTTP attempt

| Row | Request | Try | HTTP | Latency s | Prompt / completion tok | Reported cost | Model output |
|---:|---:|---:|---|---:|---|---:|---|
| 1 | 1 | 1 | 200 | 6.49 | 1,699 / 13 | $0.000123 | `list_files {"path": "."}` |
| 2 | 2 | 1 | 200 | 139.62 | 2,487 / 802 | $0.000447 | `write_file` `reproduce_issue.py` (2,278 bytes) |
| 3 | 3 | 1 | 200 | 5.18 | 3,329 / 22 | $0.000241 | `run {"command": "python reproduce_issue.py"}` |
| 4 | 4 | 1 | 429 | 0.24 | - | - | - |
| 5 | 4 | 2 | 200 | 18.87 | 3,571 / 24 | $0.000258 | `read_file {"path": "reproduce_issue.py"}` |
| 6 | 5 | 1 | 429 | 0.23 | - | - | - |
| 7 | 5 | 2 | 429 | 0.19 | - | - | - |
| 8 | 5 | 3 | 429 | 0.25 | - | - | - |

- Every 429 body: `provider_name` DeepInfra, `provider_error_code` `engine_overloaded`,
  `limit_source` `upstream_provider_shared_pool`, "temporarily rate-limited upstream".
- Retry timing from `calls.jsonl` timestamps: second tries came 5.5 s and 5.4 s after the failed
  attempt, the third 10.2 s after the second (configured backoff 5 s, then 10 s).
- Request sizes from the context manifests: 6,918; 9,388; 12,305; 13,196; 16,392 bytes (limit 80,000).

## Tool results

| Call | Result |
|---|---|
| `list_files` | 88 files |
| `write_file` | created `reproduce_issue.py` (66 lines) |
| `run` (isolated OCI) | status success, exit 0, 1,222 ms. Printed `get_name()`/`get_real_name()` = `schema` for `db.schema.tbl.col`, `get_real_name()` = `y` for `x.y.z AS w`, and `sch` for `mydb.sch.func(1)`. The script caught its own assertion failures. |
| `read_file` | `reproduce_issue.py`, lines 1-66 |

## Outcome

- Controller stop: `model_error`, "failed after 3 attempts: HTTP 429 ...". The repeat stop did not trigger.
- Acceptance: rejected. fail-to-pass failed (`tests.test_parse::test_get_real_name_multi_part_dotted`),
  pass-to-pass passed, 88 tests observed.
- Final workspace: one new file, `reproduce_issue.py`; no library source change.
- Durable ledger: 4 responses, 8 HTTP attempts, 4 tool actions, 195.3 active seconds; nothing pending.
  Cost charged $0.01411: $0.00106876 reported, plus 4 x $0.00326 conservative charges for 429 attempts
  that reported no cost. The campaign cap was not reached (8 of 30). Wall time 200.5 s.
- Card class: **infrastructure** (provider errors). It is not counted as model inability.

## Spend against the approval

Approved: at most 33 HTTP attempts, $0.108 worst case. Used: 9 attempts (smoke 1, run 8).
Reported $0.00119; ledger-charged $0.01424.

## Audit notes

- Row 2 latency, 139.6 s for 802 completion tokens, exceeds the 56.3 s maximum logged for this
  endpoint in pilot 2.
- The four 429 attempts keep conservative charges. If the provider bill for them is confirmed
  zero, a supervisor adjustment could replace them; that has not been done.
- Before the stop, the model listed files, wrote a reproduction script, ran it in the container,
  and read it back. It had not yet read any library file.

## Next decision (not taken)

The card requires review before another live run. Options:

1. Rerun the identical configuration at a later time under the same card, using at most 24 of the
   unused approved attempts. The configuration stays frozen; the shared-pool limit may recur.
2. Pin gemma-4-26b to a different provider under a new card with its own smoke. This changes one
   variable (the provider).
3. Lengthen the backoff or allow more retries. This is a protocol change against the plan's
   section 5.3 defaults and needs a stated reason.
4. Add a provider key to OpenRouter (the remedy the 429 body suggests). This is an account change.
