# Audit of pilot2-transcript (raw logs checked against REPORT.md)

Checked against `calls.jsonl` (raw requests and responses), `results.jsonl`, per-run session
journals, and final workspaces (sessions are git-ignored, kept locally under `sessions/`).
Runner v2, arm `bounded-transcript-v2`, protocol `f955736eb747`; providers pinned without
fallbacks: qwen/qwen3.5-9b -> Venice, google/gemma-4-26b-a4b-it -> DeepInfra (fp8),
nvidia/nemotron-3-super-120b-a12b:free -> Nvidia.

## Outcome counts

- 9/9 runs recorded; 0 accepted, 9 rejected. The 250-attempt cap was reached during the last
  run. Reported cost: $0.0314 (qwen) + $0.0292 (gemma) + $0 (nemotron, free) = $0.0606.

## Runs cut short by infrastructure (3 of 9)

- `tomlkit-549__qwen`: stopped after 19 model calls with 4 consecutive HTTP 429 "temporarily
  rate-limited upstream" responses. Across the three qwen runs, 65 of 120 HTTP attempts were 429s.
- `tomlkit-549__nemotron`: stopped after 15 model calls with 4 consecutive HTTP-200 error bodies
  "Upstream error from Nvidia: Service temporarily overloaded".
- `sqlparse-865__nemotron`: 2 model responses, then the pilot-wide 250-attempt cap was reached.

## Runs that edited the fixed source file (2 of 9)

- `humanize-329__qwen` called finish after one edit to `src/humanize/filesize.py`:
  `exp = int(min(log(abs_bytes, base), len(suffix)))` -> `exp = round(...)`. fail-to-pass passed
  (6/6); pass-to-pass failed 15 tests, e.g. `test_naturalsize[test_args13-32.0 MB]`. The evaluator
  result is consistent with the diff (rounding the exponent changes the unit for values such as
  32 MB). This run also had 3 replies that hit the 8,192-token output limit with no tool call;
  one reasoning text ended in a repeated "QB, QB, QB, ..." sequence; 29,091 completion tokens.
- `humanize-329__nemotron` overwrote `src/humanize/filesize.py` with empty content. Raw call 8
  arguments: `{"content":"","path":"src/humanize/filesize.py"}` (finish_reason tool_calls,
  1,914 completion tokens); the tool reported "Overwrote src/humanize/filesize.py (0 bytes,
  0 lines)". The empty module failed to import (collection error), so 6 fail-to-pass and 70
  pass-to-pass tests failed. The empty content came from the model's arguments, not the runner.
- The other 7 runs changed no library source file; gemma wrote only reproduction scripts.

## Repeated identical observation calls

- 47 repeated identical read/search/outline/list calls across 6 runs (qwen sqlparse 16, gemma
  humanize 14, gemma sqlparse 10, nemotron humanize 4, gemma tomlkit 2, qwen tomlkit 1).
- In all 47 cases, the earlier identical call's result was present in the request only as a
  shrunk (<=512-byte) older-exchange view with a read_output note. No repeat occurred while the
  earlier result was shown in full. This is consistent with the 512-byte older-result limit
  prompting re-reads; causation was not tested.

## Paging tools

- Requests whose newest tool result was a partial view: 16 across all runs. The model's next
  tool calls: read_file 7, search 3, run 2, no tool call 3, finish 1; read_output 0.
- Total read_output/search_output calls in the pilot: 2 (gemma humanize 1, gemma sqlparse 1).

## Not verified

- Whether keeping older results larger would reduce re-reads or change outcomes.
- Whether any model would repair these bugs without the infrastructure interruptions.
