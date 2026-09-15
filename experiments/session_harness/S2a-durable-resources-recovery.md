# S2a delivery 1: durable resources, ownership, and crash transitions

Date: 2026-09-15  
Status: S2a complete offline (delivery 1 and delivery 2); S2b not started
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

## Delivery 2: provider attempts, pause/deadline, billing adjustment (S2a complete)

- **Provider attempts.** A client that sets `reports_provider_attempts = True` receives a
  `ProviderAttemptRecorder` (`reticle/runtime/budgets.py`). Every underlying network attempt,
  including retries, calls `begin()`, which reserves one `model_attempts` unit plus the per-attempt
  cost reservation and journals `provider_attempt_started`. A retry that would exceed a limit
  raises `TaskBudgetExhausted`; the controller records `model_call_failed` as a terminal event, so
  resume sees no ambiguous request. The successful attempt is reconciled with the response's
  reported cost; failed or unfinished attempts keep their conservative cost charge. A crash inside
  an attempt leaves its reservation pending and the request stops as `needs_reconciliation`. Clients
  that do not opt in are still charged one attempt per request, unchanged.
- **Pause and deadline.** A task is paused whenever no controller owns the session. `active_seconds`
  accrues only while a controller runs and is now charged at every model/tool dispatch boundary
  rather than once at exit, so a crash no longer renews it. The optional `deadline_utc` budget
  (ISO 8601 with offset) is wall-clock, keeps running while paused, and stops the run as
  `task_deadline_reached` before dispatch. Pausing releases no reservation.
- **Billing adjustment.** `TaskBudgetLedger.adjust(operation_id, actual, source=, reason=)` replaces
  the charge of an already reconciled operation, journals `task_resource_adjusted` with the previous
  charge, and is reflected in `snapshot().adjusted`. It rejects pending or unknown operations. It is
  supervisor-only: the controller never calls it and the event kind is not model-visible.
- `AgentRunResult` gains `provider_attempts`; `model_calls` still counts requests. The cost-reservation
  precondition is now checked before any reservation, so a missing reservation writes no reservation events.

Validation (delivery 2):

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest tests.test_s2_resources -v
# 18 passed (6 new)

.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests -q
# 185 passed; 3 OCI integration tests skipped
```

Limitations: time spent inside an in-flight provider call or tool is lost if the process crashes
before the next boundary. `adjust` can lower a charge, so it must stay behind the supervisor.
Neither `experiments/p6_pilot/run_pilot.py` nor `experiments/session_harness/run_e2.py` has adopted
the attempt-reporting protocol; their retries remain invisible to the task ledger until a runner opts in.
The live OCI and evaluator boundaries belong to S2b and remain unrun. Delivery 2 made no
provider/network call and had no spend.

This S2a slice made no provider/network call, installed-wheel check, or spend of its own. E2
did run separately in the same working session: fixture `changed-file`, one approved attempt with
`google/gemma-4-26b-a4b-it` pinned to DeepInfra under `pressure-recent-v1`, accepted in 4 model
calls for $0.00092 reported cost. It used the S1 runtime through `run_e2.py`, not the S2a
resource ledger. See [E2-changed-file.md](E2-changed-file.md).
The source manifest records the exact S2 file contents at this handoff; subsequent shared-window
edits should update it rather than treating the dirty-tree base commit as a complete identifier.
