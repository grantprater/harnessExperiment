# E1: pressure-recent-v1 offline context mechanics

Date: 2026-09-15  
Status: completed  
Source base: `08871ac3d083bd72b33ac18499d0391c9c9cd20e` plus the working-tree S0/S1a changes.

## Question

Does the materialized context preserve required evidence under ample space, forced pressure,
and an oversized latest exchange without calling a model?

## Fixtures and outcomes

| Fixture | Required outcome | Result |
|---|---|---|
| Ample budget | Both recent 3 KB observations remain complete | Pass |
| Forced pressure | Older exchange may leave; latest paired result, status, and handle remain | Pass |
| Oversized latest | Latest result is bounded and names an exact `read_output` range | Pass |
| Trailing prompt | Text-only reply and no-tool-call prompt after the latest exchange remain | Pass after review fix |
| Later correction | A user message after the latest exchange remains under pressure | Pass after review fix |
| Contiguity | A newer unit that does not fit ends selection; no older unit is admitted | Pass after review fix |
| Impossible minimum | Controller records exhaustion and makes zero provider calls | Pass |
| Legacy control | `bounded-recent-v2` retains its 512/4,000-byte views | Pass |

The executable fixture is `tests/test_pressure_context.py`.

## Validation

```powershell
.\.runtime\test-venv\Scripts\python.exe -m unittest tests.test_pressure_context tests.test_context_runtime tests.test_output_paging tests.test_agent_controller -v
# 28 passed (25 before the review fix, plus trailing-prompt, correction, and contiguity)

.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests -q
# 161 passed; 3 OCI integration tests skipped (includes concurrent S1b tests)
```

No scripted or live model was used. This establishes the offline E1 mechanics only. History
discovery after complete exchange eviction now passes in the S1b offline fixture; actual model
use of that interface remains the separately gated E2 experiment.
