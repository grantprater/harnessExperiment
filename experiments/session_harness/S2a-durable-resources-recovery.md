# S2a delivery 1: durable resources, ownership, and crash transitions

Date: 2026-09-15  
Status: first offline slice completed; S2a remains in progress
Source base: `08871ac3d083bd72b33ac18499d0391c9c9cd20e` plus the shared dirty S0-S2 working tree.  
Source manifest: `S2a-source-manifest.sha256`

## Delivered behavior

- The full task contract and normalized resource limits persist in the session journal.
  Resuming with a conflicting task or budget contract fails visibly.
- Model attempts, successful responses, tool actions, active elapsed time, and reported or
  conservatively reserved cost use durable reservation/reconciliation events. Starting a new
  controller does not renew a task limit.
- A hard monetary cap requires a positive per-attempt reservation before provider dispatch.
  Missing billing retains the conservative charge. An exhausted resumed task makes zero
  provider calls.
- One OS-backed writer lock covers a controller run. A second owner is rejected; after release,
  a replacement owner can acquire the session.
- Native workspace reads/edits and supervised command execution share the same in-process
  read/write boundary.
- Crash state distinguishes known-not-started actions, dispatched work with an unknown external
  outcome, and known-complete outcomes missing transcript publication. Ambiguous mutations and
  provider calls stop with `needs_reconciliation`.
- Persisted tool outcomes are republished without rerunning their mutation. Persisted model
  responses are linked by attempt ID and resume their first unfinished tool call without another
  provider call.

## Validation

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest tests.test_s2_resources -v
# 12 passed

.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests -q
# 179 passed; 3 OCI integration tests skipped
```

## Remaining S2a work

The current model-client contract exposes one `complete` call after any internal retry policy;
it cannot yet journal every underlying failed HTTP attempt. Deadline pause semantics and a
supervisor-visible adjustment path for later billing reconciliation also remain to be defined.
The live OCI and evaluator boundaries belong to S2b and remain unrun.

This S2a slice made no provider/network call, installed-wheel check, or spend of its own. E2
did run separately in the same working session: fixture `changed-file`, one approved attempt with
`google/gemma-4-26b-a4b-it` pinned to DeepInfra under `pressure-recent-v1`, accepted in 4 model
calls for $0.00092 reported cost. It used the S1 runtime through `run_e2.py`, not the S2a
resource ledger. See [E2-changed-file.md](E2-changed-file.md).
The source manifest records the exact S2 file contents at this handoff; subsequent shared-window
edits should update it rather than treating the dirty-tree base commit as a complete identifier.
