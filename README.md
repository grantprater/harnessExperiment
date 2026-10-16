# Reticle: observational and belief refinement

Reticle is a durable agent runtime and experiment framework. The research goal is
an agent that improves how it acquires evidence, updates beliefs and chooses
actions, with demonstrated transfer to future tasks. Recursive self-improvement
is the longer-term objective; current probes test smaller conditional procedures.

Representation depends on the substrate, goal and progress. AST outlines, exact
source, test results, deltas and visual observations serve different decisions.
The task loop observes, revises beliefs, acts and checks. The refinement loop
proposes a versioned procedure, tests its applicability conditions and retains,
restricts or rejects its scope.

## Start here

- [NEXT_SESSION.md](NEXT_SESSION.md): short handoff and the next useful decision.
- [Project state](docs/PROJECT_STATE.md): current design, evidence and integration gaps.
- [Runtime guide](docs/RUNTIME_GUIDE.md): CLI, context policies, extensions, runtime updates, style and knowledge tools.
- [Latest check-hook results](experiments/check_hook_probe/runs/live-001/REPORT.md): the completed 18-run comparison.

## Latest findings

All 18 post-edit check attempts passed fresh-snapshot evaluation against the
original public tests. Automatic full reporting used **19.1% fewer total tokens**
than manual verification; automatic selective reporting used **21.1% fewer**.
Selective reporting added 2.4% savings over automatic full reporting. Three small
tasks, two repetitions per condition: descriptive evidence, not broad reliability.

Earlier probes found that exact deltas preserve simple decisions with retained
baselines, but savings depend on observation size and history overhead. The autumn
context-policy comparison missed the 10k target and had provider failures; it did
not establish a winning context policy. See [project state](docs/PROJECT_STATE.md)
for the evidence map and limitations.

## Run the harness

From a configured checkout/environment:

```powershell
& ./.venv/Scripts/python.exe -m reticle.cli --help
reticle
reticle "Run the tests and fix the failure" --once
reticle --resume PATH_TO_SESSION
reticle --check
```

If the `reticle` command is not installed, use
`powershell -ExecutionPolicy Bypass -File tools/install-cli.ps1`, then open a new
terminal. The existing Reticle subscription connection defaults to `gpt-6.1-sol`.
`--check` checks local setup without an inference request. Multi-turn sessions
show intermediate tool activity and provider token usage. See the runtime guide
for provider setup, model feedback, isolation and runtime activation.

The CLI defaults to `minimal` context at 32,000 bytes including schemas. The
experimental `decision` policy remains opt-in. Delta selection and post-edit hooks
are experimental components, not default CLI behavior. Candidate activation and
demonstrated improvement are separate.

## Reproduce the current probes

- [Observation/delta probes](experiments/observation_probe/README.md).
- [Refinement records and conditional selector](experiments/observation_probe/REFINEMENT_DESIGN.md).
- [Post-edit check protocol and commands](experiments/check_hook_probe/README.md).

The check probe validates offline by default. Its live 18-run comparison requires
`--execute` and a fresh output directory. Full requests, evidence and reported
usage are retained; failed or unreported usage is not imputed as zero. New runs
should answer a specific question rather than repeat saturated fixtures.

## Validation and historical work

Use the checkout's Python environment for focused tests:

```powershell
& ./.venv/Scripts/python.exe -m unittest tests.test_check_hooks tests.test_observation_refinements tests.test_toolset_v4
```

The older [implementation ledger](IMPLEMENTATION_PLAN.md) and
[experiment register](experiments/REGISTER.md) preserve stage history, controls and
reports. They are not the current resume checklist. The earlier reading pilot is
in [experiments/README.md](experiments/README.md); modality prototypes and superseded
plans remain in [archive](archive/). The retired self-refactoring loop optimized a
complexity metric rather than task outcomes; see [archive/RETIRED.md](archive/RETIRED.md).

This working checkout includes substantial uncommitted implementation and result
files. Preserve existing work when resuming. Sessions and raw experiment data are
local research artifacts, not a publication bundle.
