# Post-edit observation strategy probe

This tests one workflow transition: what the model receives after editing source.
It separates automatic check execution from selective result representation.

| Arm | Post-edit behavior |
|---|---|
| `manual` | Model invokes `verify` when useful |
| `automatic-full` | Fixed tests run after each successful source-changing edit; full output returned |
| `automatic-selective` | Same tests run; passing receipt or exact failure diagnostics returned |

All conditions have identical tools: glob, AST outline, numbered source, text
search, literal replacement, file writing, patch editing, output retrieval,
`verify`, and `finish`. Explicit `verify` always returns full results, including
in the selective condition. No general command execution is exposed in any arm.
Only listed existing source files can be edited; tests are read-only. No-op byte
writes, rejected edits and reads do not trigger automatic checks. A newline-only
byte change counts as a source change. Hooks run per edit, including between
multiple edits in the same model response; they are not coalesced.

The success receipt includes test count, source fingerprint and a full-evidence
handle. Failed checks name every failure and show exact traceback excerpts.
Large traceback middles may be omitted with retrieval guidance. Execution errors,
timeouts, empty/all-skipped suites and source changes during checks never appear
as successful evidence. Full structured check results are always saved through
the existing journal/artifact/output-handle machinery.

## Fixed initial comparison

Reuse the earlier mini-Aider reading pilot's billing, pagination and KV fixtures.
Billing and pagination are bug fixes; KV is missing-method implementation rather
than pure bug repair. Pagination requires coordinating query and service changes;
KV repairs exercise incomplete multi-file states and failure investigation.
These familiar small tasks are smoke tests, not a capability frontier.

Two repetitions per task and condition produce 18 fresh attempts, shuffled with
seed 53. Default model: `gpt-6.1-sol`, through the existing subscription adapter.
Each attempt is capped at 12 provider/model calls, 48 tools and 240 active seconds;
checks have a 15-second timeout. The whole schedule allows at most 216 provider
attempts. There are no automatic retries; a provider error stops the campaign.

The existing `AgentController` is used with an experiment-specific policy retaining
the complete transcript and the same 200,000-byte request ceiling in all arms.
There is no observation truncation or semantic compaction. A request exceeding
the ceiling stops that attempt; context pressure is not another treatment.
Starting representations, schemas, tasks, test suite, editing tools, budgets and
acceptance criteria are identical across arms. Only the condition sentence and
hook behavior differ. Both automatic arms run exactly the same check program.

Acceptance is evaluated after every attempt, including unfinished attempts, by
copying candidate source into a fresh snapshot with the original public tests.
No hook result or model finish claim substitutes for that evaluation. This verifies
the public contract only; it is not a hidden-test or general correctness claim.
Original fixtures and historical results are preserved. Model work and evaluation
execute locally as trusted code; this probe does not provide process isolation.

Protocol, source/fixture hashes and schedule are saved before execution. Offline
controls check failing starting fixtures, passing reference fixtures, and gold,
noop and breaker controller attempts in all three arms (27 control attempts).

## Commands

Build and validate the schedule without model calls:

```powershell
& ./.venv/Scripts/python.exe experiments/check_hook_probe/run_probe.py --output-dir experiments/check_hook_probe/runs/NEW-PREFLIGHT
```

Run the comparison explicitly, using a fresh directory:

```powershell
& ./.venv/Scripts/python.exe experiments/check_hook_probe/run_probe.py --execute --output-dir experiments/check_hook_probe/runs/NEW-LIVE
```

Focused tests:

```powershell
& ./.venv/Scripts/python.exe -m unittest tests.test_check_hooks
```

## Reading the results

Each attempt saves `summary.json`, `evaluation.json`, `usage.json`, provider calls,
workspace and exact session evidence. Root `progress.json` and `comparison.json`
are updated after each live attempt. Compare:

- Independent accepted completion and model finish separately.
- Total provider-reported input plus output per accepted completion, including
  failed attempts. Unknown usage stays unknown; it is never imputed as zero.
- Model calls, tool calls, manual and automatic checks, and check execution time.
- Output retrievals and full versus model-visible check bytes.

Output retrievals are an investigation/recovery indicator, not proof of omitted
information: they can retrieve code output as well as hook evidence. Full
materialized requests support tracing the difference. Latency includes the extra
checks. Hooks consume execution time even when they save model decisions.
Two repetitions on three small tasks support descriptive diagnosis, not a broad
ranking. There is no automatic promotion gate.

This probe is a conditional observation procedure in the
[refinement framework](../observation_probe/REFINEMENT_DESIGN.md): established tests
and source-changing edits are its trigger conditions; full or selective check
results are its representations. AST/source choice remains available and fixed
across arms. It does not try to learn all representation transitions at once,
silently suppress successful results, or discover missing test coverage.
