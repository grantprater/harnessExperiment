# Audit of pilot1-transcript (raw logs checked against REPORT.md)

Every statement below was checked against `calls.jsonl` (raw requests and responses) and the
per-run session journals (git-ignored, kept locally under `sessions/`).

## Outcome counts

- 9/9 runs recorded; 0 accepted, 9 rejected. In every run `fail-to-pass` failed and
  `pass-to-pass` passed, i.e. the final workspace matched the pre-fix library behavior.
- In all 9 runs the upstream fix's source file (`gold_source_files`) was unchanged from the
  base commit. No run called `finish`.

## Harness defect: tool results cut to 512 bytes with no retrieval tool

- `BaselineContextPolicy` was used with its default `tool_preview_bytes=512`. Every tool result
  longer than 512 bytes, including the most recent one, was sent as a 512-byte preview plus
  `[truncated: N bytes omitted; exact observation: art_...]`.
- The tool suite has no tool that reads an artifact ID, so omitted content was unrecoverable
  by the model, contrary to the context contract ("Retrieve omitted exact evidence by artifact ID").
- Examples: in the last request of `sqlparse-865__qwen_qwen3.5-9b`, 22 of 24 tool results were
  truncated, including the newest (`sqlparse/sql.py` lines 390-420, 845 bytes omitted). In the
  last request of `tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free`, 13 of 24 were truncated,
  including the newest.
- Repeated identical reads: `sqlparse-865__qwen` read `sqlparse/sql.py` 390-420 10 times;
  `tomlkit-549__qwen` read `tomlkit/container.py` 1147-1261 11 times; `humanize-329__qwen` read
  `src/humanize/filesize.py` lines 1-22 4 times. Nemotron runs made 21-25 observation calls with
  at most one repeat per run.
- Consequence for interpretation: these runs do not measure the models' ability to repair the
  bugs under a usable bounded-transcript arm.

## Provider and infrastructure events

- gemma-4-26b-a4b-it:free: 14 HTTP attempts, 13 were HTTP 429 "temporarily rate-limited
  upstream"; all three runs stopped with `model_error` after 4 attempts. One successful response
  (humanize-329) called `list_files` with the malformed path `.} help:list_files(path='.')`.
  These runs are infrastructure failures, not model results.
- nemotron-3-super-120b-a12b:free: 96 attempts, 21 returned HTTP 200 bodies containing
  `Upstream error from Nvidia: Service temporarily overloaded` (retried; counted toward the call
  cap, not toward model calls). All 75 model responses contained tool calls. Usage cost is absent
  for those 21 error bodies only.
- qwen3.5-9b: 76 attempts across five providers (SiliconFlow 27, Venice 19, Darkbloom 15,
  DeepInfra 9, Together 5), one HTTP 502. SiliconFlow returned 3 empty `stop` replies with the
  tool call left inside `reasoning` (see `runs/diag-qwen-empty-reply`).
- Reported cost: $0.0432 (qwen only; free models report $0).

## Not verified

- Whether any model would have repaired a bug with complete tool results; this needs a rerun
  after the defect is fixed.
