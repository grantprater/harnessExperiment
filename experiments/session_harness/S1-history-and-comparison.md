# S1b/S1c: history discovery and checkpoint comparison

Date: 2026-09-15  
Status: offline mechanics completed; E2 model usability unrun  
Source base: `08871ac3d083bd72b33ac18499d0391c9c9cd20e` plus working-tree S0/S1 changes.

## S1b result

An observation was recorded from `state.txt`, the live file was replaced, and the original
exchange was forced entirely out of a 2,000-byte pressure-policy request. After reopening the
runtime, `search_history` found the old text without an output ID and returned its original
path, success status, output handle, and authorized artifact. `read_artifact` recovered the
immutable old bytes while the workspace retained the new content.

Additional offline checks cover stable search cursors while new events are appended, bounded
history snippets, scope/coverage reporting, revised user constraints after restart, structured
secret redaction, missing artifact blobs, and denial of context manifests/raw transcript blobs.

## S1c result

A checkpoint replay rendered `bounded-recent-v2` and `pressure-recent-v1` from the same event
cursor. Events appended after the checkpoint appeared in neither request. The comparison
artifact records each policy/version, exact request artifact/hash/bytes, visible and omitted
items, and retrieval calls for omitted output handles. Replay made no model or tool call.

## Validation

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest tests.test_context_comparison tests.test_session_history tests.test_pressure_context -v
# 21 passed before the review fixes below; 27 passed after them

.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests -q
# 161 passed before review fixes; 175 passed after (includes concurrent work); 3 OCI tests skipped
```

## Review fixes

A review probe found these defects; each now has a regression test.

- Call metadata depended on the query window: paging with `limit=1` lost path/status and
  labeled outcomes `unknown`, and an explicit `after_sequence` returned a `search_history`
  outcome and its result message. Call links are now indexed up to the high-water mark.
- One `read_file` produced five search hits. When `tool_output` is in the requested kinds,
  each call is one record with its outcome and observation artifacts linked; explicitly
  requested derived kinds are still returned.
- Credentials inside JSON tool-call argument strings were searchable through the assistant
  transcript record. Parsed argument strings are now redacted; unparseable strings are not.
- `bounded-recent-v2` manifests recorded no omissions, so the comparison showed legacy
  dropping nothing while its request kept one of three results. Legacy now records skipped
  units (rendering unchanged) and receives retrieval entry points.
- History tool results were single-line JSON, so bounded views could show only a byte
  prefix. They are now indented for line paging.

Remaining limits: authorization reads every visible artifact on each `read_artifact`, artifact
denial is a label blocklist, and replay appends context manifests to the live journal.

E2 remains unrun. A live run requires a new concrete card with current provider routing and
pricing, per-attempt/turn/token/tool/elapsed caps, a monetary ceiling, and retained raw evidence.
