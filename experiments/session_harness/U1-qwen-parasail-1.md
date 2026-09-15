# U1 run 1: usability fixture, Qwen3-Coder-Next @ Parasail (gate for E3 run 4)

Date: 2026-09-15  
Card: [E3-repair-control-004](E3-repair-control-004.md), step 1 (approved "Yes")  
Raw evidence: `u1_runs/u1-qwen-parasail-1/` (`card.json`, `calls.jsonl`, `results.jsonl`; session git-ignored)  
Runner `run_u1.py` version 1; policy `pressure-recent-v2`; toolset `reticle-tools-v2`

## Gate decision (preset rule): pass

| Condition | Result |
|---|---|
| Hidden check passes | yes (`hidden-check-passed`) |
| Every rejected call followed by a non-rejected call of the same tool | yes (0 rejected calls) |
| Remaining-resources line in every request | yes (8 of 8) |

Stop: `model_call_limit` (8 of 8 responses). 8 HTTP attempts, all 200 from Parasail; $0.00301208 reported; 18.2 s.

## Trajectory

| # | Status line (responses left, incl. this) | Tool call | Result |
|---:|---|---|---|
| 1 | 8 of 8 | `list_files {"path": "."}` | 4 files |
| 2 | 7 of 8 | `read_file names/core.py` | success |
| 3 | 6 of 8 | `read_file tests/test_names.py` (narration: "Found the bug! ... returns `parts[1]` ... instead of `parts[-1]`") | success |
| 4 | 5 of 8 | `replace_text names/core.py` (three-line `old_text`) | **error**: old_text was not found; re-read and copy exact text |
| 5 | 4 of 8 | `read_file names/core.py 12-14` | success |
| 6 | 3 of 8 | `replace_text` one line: `return parts[1] if ...` -> `return parts[-1] if ...` | success |
| 7 | 2 of 8 | `run pytest tests -q` | exit 0, 4 passed |
| 8 | 1 of 8 | `read_file names/core.py` (narration: "Let me verify the fix") | success; no `finish` |

Friction: 8 tool calls, 0 rejected, 1 error, 0 failed lookups, first edit of an existing file at response 6
(11.8 s), first command at response 7 (13.5 s).

## Audit notes

- **Fixture defect found:** runner version 1 wrote the fixture files in text mode, which produced CRLF line endings
  on Windows (18 CRLF, 0 bare LF in `names/core.py`), while the fixture source uses LF. The three-line `old_text` at
  response 4 used LF newlines, so it could not match, and the tool reported the miss. The model recovered with a
  one-line edit. Runner version 2 writes exact LF bytes. P6 repair workspaces come from `git archive` with
  `core.autocrlf=false` and are unaffected: `sqlparse/sql.py` in E3 runs 1-3 has 661 LF and 0 CRLF line endings.
- The remaining-response count was accurate in every request (8 down to 1). At "1 of 8" the model re-read the file
  instead of calling `finish`, so the run ended at the response limit. The hidden check was unaffected.
- The function was located by reading `names/core.py` directly (4 files listed), not by `search`, so this run
  did not exercise the `file_glob` naming or search error messages.

## What this does and does not show

It shows the revised interface worked end to end on a trivial repair: an accurate countdown in every request, no
rejected calls, recovery from a failed edit, a test run, and a correct fix. It does not show that the model uses the
countdown to finish in time, that the search changes help, or anything about the sqlparse repair (E3 run 4).
