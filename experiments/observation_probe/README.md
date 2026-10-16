# Retained-baseline observation probe

The follow-up design and implemented refinement loop are documented in
[REFINEMENT_DESIGN.md](REFINEMENT_DESIGN.md). Its twelve-call driver tests the
conditional selector and full fallback on checks and UI measurements, and stores
versioned proposal/evidence/conclusion records using the existing runtime store.

Four fresh, one-decision requests using `gpt-6.1-sol`: two cases crossed with
full versus delta observation. Order is shuffled with seed 23. Each pair has an
identical retained prefix, including the complete initial tool observation.
Only the final tool output changes. No context compaction or manager model.

The test case resolves one failed check and introduces a different failure.
The generative case represents a regenerated illustration through structured
measurements, introducing palette and outline inconsistencies. The model must
identify all changed records and select the prescribed next action. Acceptance
is independently checked against fixture expectations, not model self-report.

Deltas include baseline/current hashes and exact before/after records. Offline
preflight verifies reconstruction, identical prefixes, and baseline rejection.
Requests, responses, provider usage and failures are saved. No automatic retries;
the probe stops after a provider error. No production tool behavior is changed.

Run from the repository root with a fresh output directory:

```powershell
& ./.venv/Scripts/python.exe experiments/observation_probe/run_probe.py --run-dir experiments/observation_probe/runs/NEW
```

Add `--offline` to verify fixtures and observation sizes without model calls.

This is a smoke probe with one sample per condition, not a policy ranking or an
end-to-end efficiency benchmark. The asset case does not generate or visually
review images. Structured deltas can cover scene objects, materials, dimensions,
palette measurements and check findings; composition and aesthetic assessment
still require visual observations. A later visual probe could retain the original
preview and return a current preview with localized change regions. Global
changes (lighting, camera, layout) may require a complete current preview.

Latest-observation byte reductions are distinct from request-token reductions:
the shared baseline remains in both requests. Cached usage depends on provider
behavior and is recorded when reported, rather than assumed from prefix equality.
