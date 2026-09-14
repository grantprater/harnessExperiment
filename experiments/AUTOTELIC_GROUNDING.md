# Grounded autotelic runner

The runner accepts a bounded number of cycles against an already connected local
Minecraft bridge. Each cycle records observed pre/post state, the model decision,
the action response, and verification results as JSONL.

```powershell
.\.runtime\test-venv\Scripts\python.exe run_autotelic_cortex.py --cycles 10 --log autotelic_cycles.jsonl
```

The runner also maintains a sidecar capability ledger next to the cycle log
(``<log stem>.capabilities.json``). A ledger entry has one compact observed
condition descriptor, a routine (craft recipes remain distinct), and a
canonical state change such as ``inventory:oak_log:positive``. The first
observed change is discovery evidence; subsequent known trials contribute to
success/failure reliability and median execution cost. Missing snapshots are
unknown evidence and do not affect either denominator. Coverage counts only
entries meeting the configurable evidence threshold (three known repeat
trials and two-thirds reliability by default), while competence is exposed per
entry as reliability and median cost. This is an inspectable evidence proxy,
not a generalization claim across unobserved conditions.

This invokes the configured LLM and changes the live game. Restart the bridge to
load its updated `/state` endpoint before running. No live trial was performed as
part of this implementation.

## Observation and control contract

- `/viewscreen.jpg` remains available for pixel perception and foveation.
- `/state` exposes source-attributed Mineflayer inventory, health, pose and food.
  This is structured instrumentation, not a claim of pixel-derived perception.
- Missing measurements remain unknown. Inventory deltas require both snapshots.
- Raw key and mouse commands remain available. Held inputs expire after two
  seconds without a new press; longer routines must explicitly renew them.
- `release_all` cancels held controls and digging. Python callers also release
  controls on normal completion, exceptions and cancellation.
- The autopilot checks observations between bounded callbacks. It cannot preempt
  arbitrary blocking Python skill code. Bridge input expiry limits held controls
  independently of those callbacks.
- Craft/place bridge helpers are supplied routines, not learned skills. A command
  acknowledgement alone does not establish a verified world-state outcome.

## Remaining experimental limits

Brightness is still a heuristic, not a calibrated daylight sensor. Live shelter
state is unknown; this change does not implement a shelter detector. Curiosity
remains bearing familiarity rather than spatial learning progress. Empowerment
is a supplied recipe heuristic rather than measured transferable capability.
The loop is a grounding foundation, not evidence of emergent skill acquisition
or validated day–night survival. Those require repeated live trials and ablations.

## Offline checks

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest test_streaming_and_autopilot test_minecraft_epistemic test_raw_motor_and_epistemic_emergence tests.test_grounding_substrate tests.test_grounding_boundaries
node --check reticle/adapters/minecraft_bridge/index.js
```
