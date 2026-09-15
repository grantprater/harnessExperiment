# E2: history retrieval, fixture `changed-file`

Date: 2026-09-15  
Status: first fixture run once; other E2 fixtures not built  
Runner: `experiments/session_harness/run_e2.py` (runner version 1)  
Raw evidence: `e2_runs/e2-gemma-deepinfra-1/` (`card.json`, `calls.jsonl`, `results.jsonl`; the
session journal and workspace are git-ignored and kept locally)

## Question and decision rule

Can the model discover and use evidence that is no longer in its context? Seeded through the
real tools and journal: `service.cfg` was read (`release_code = K7Q-4821`), rewritten to
`K7Q-9035`, then a 28 KB log was read. Under `pressure-recent-v1` at 12,000 bytes, the original
read is omitted. Task: write the pre-change `release_code` to `answer.txt`.

Fixed before running: accepted iff `answer.txt`, stripped, equals `K7Q-4821`.

## Card (approved)

| Item | Value |
|---|---|
| Model / provider | `google/gemma-4-26b-a4b-it`, pinned to DeepInfra, no fallbacks |
| Protocol hash | `8f245afd698c` |
| Attempts | 1 |
| Limits | 8 model calls; 12 HTTP attempts; 300 s elapsed; $0.25 reported cost; stop after 3 identical observation calls |
| Context | `pressure-recent-v1`, 12,000 bytes; `run` tool removed |
| Worst-case cost at plan time | $0.0201 |

## Preflight and pipeline controls (no API)

Preflight: request within budget, earlier units omitted, original value absent from the first
request, live file holds the changed value.

| Client | Outcome | Answer | Retrieval calls |
|---|---|---|---|
| gold (search_history, writes value only if surfaced) | accepted | K7Q-4821 | 1 |
| live-file (reads current file) | answered_changed_value | K7Q-9035 | 0 |
| noop | no_answer | none | 0 |

## Live run

| Call | Tool call (raw arguments) | Prompt / completion tokens | Cost | Request contains original value |
|---|---|---|---|---|
| 1 | `search_history {"query": "service.cfg"}` | 4,818 / 21 | $0.000344 | no (11,948 bytes) |
| 2 | `read_output {"id": "out_1"}` | 2,491 / 21 | $0.000182 | yes (8,751 bytes) |
| 3 | `write_file {"content": "K7Q-4821", "path": "answer.txt"}` | 2,604 / 34 | $0.000194 | yes (9,233 bytes) |
| 4 | `finish {"summary": "Wrote the previous release_code (K7Q-4821) to answer.txt."}` | 2,672 / 38 | $0.000200 | yes (9,602 bytes) |

- Outcome: accepted; answer `K7Q-4821`; stop `finish_requested`.
- 4 model calls, 4 HTTP attempts (no retries), all served by DeepInfra; reported cost $0.00092;
  16.2 s elapsed.
- Tool results containing the original value: `search_history` (call 1) and `read_output`
  of `out_1` (call 2), which is the handle of the omitted seeded read.

## Audit

Checked against `calls.jsonl` and `results.jsonl`. The first request did not contain the
original value; it first appears in the `search_history` result. The written value matches
the raw `write_file` arguments. No empty replies, truncated outputs, rejected calls, or
diagnostic stops occurred.

## Not established

- One run of one fixture with one model; no repetition or variance estimate.
- The task text states that the file was read earlier and has changed.
- The other planned E2 fixtures (an old failure whose output ID is no longer visible; a
  revised user constraint across context pressure) are not built or run.
