# Resume Reticle: observation-strategy refinement

Saved 2026-10-03 at the user's request. Wrap-up is complete; no experiment is
pending. Do not start a new experiment merely to complete this handoff.

## Read first

1. [Project state](docs/PROJECT_STATE.md): objective, component map, tested evidence and integration gaps.
2. [Latest result](experiments/check_hook_probe/runs/live-001/REPORT.md).
3. [Check protocol](experiments/check_hook_probe/README.md) if continuing that experiment.

Use [runtime guide](docs/RUNTIME_GUIDE.md) for feature details. The old roadmap and
register preserve earlier work; do not treat their old next steps as current.
The previous handoff is preserved in [history](docs/history/HANDOFF_2026-10-02.md).

## Current direction

Refine a versioned observation procedure with explicit applicability conditions
and evidence. Representation depends on substrate, goal and progress. Derive
mechanical invariants; test conditional policies and transfer. Ontology, knowledge,
checks, generated tools and runtime updates support this loop rather than each
requiring an independent research program.

## Latest completed comparison

18/18 attempts finished and passed fresh-snapshot original-public-test evaluation:

| Condition | Total tokens | Model calls |
|---|---:|---:|
| Manual verification | 95,751 | 35 |
| Automatic full results | 77,439 | 28 |
| Automatic selective results | 75,555 | 28 |

Savings relative to manual: 19.1% and 21.1%; selective added 2.4% over automatic
full. Both automatic arms had four intermediate failures and six passing checks;
no evidence retrievals or provider errors. Three small saturated tasks, two repeats
per condition. This supports further testing, not production promotion.

## Suggested next decision

Choose a small task where failed-check diagnosis genuinely requires investigation,
then vary one applicability condition (verbose/concise output or local/cross-file
repair). Keep model, tools, checks and acceptance fixed. Measure accepted completion,
all-attempt tokens, recovery reads and extra execution cost. This is a recommendation,
not authorization to launch another batch automatically.

The delta selector, refinement records and check hooks are implemented opt-in.
They are not wired to default CLI observers or general learned selection. Automatic
ontology/knowledge publication, model-proposed conditions, configurable production
hooks and edit coalescing remain unimplemented/untested. CLI defaults are unchanged.

## Workspace and validation

Working directory: `C:/Users/grant/harnessExperiment`; PowerShell; Python:
`& ./.venv/Scripts/python.exe`. Preserve extensive existing modified/untracked work
and original reports. No commit or publication was requested. Reuse the protected
Reticle login and exact `gpt-6.1-sol` model for authorized future tests; never print
credentials or blanket-publish raw session directories.

Latest focused code validation: 20 tests passed; all 27 offline controls behaved
as expected. Documentation links were checked; live hook implementation hashes
still match their frozen protocol. The local source/docs recovery checkpoint is
`.runtime/checkpoints/wrapup-2026-10-03.zip`, with a manifest beside it. It excludes
credentials, environments and raw result/session directories. It is not a commit.
Live probe status and complete raw results are under
`experiments/check_hook_probe/runs/live-001/`.
