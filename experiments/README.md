# Controlled reading-interface pilot

This document describes the earlier reading pilot. For current observation-strategy
work, start with [project state](../docs/PROJECT_STATE.md), the
[experiment register](REGISTER.md), or the [post-edit check probe](check_hook_probe/README.md).
The historical protocol and results below remain unchanged.

This pilot uses fresh native Codex agents explicitly selected as `gpt-5.6-luna`
with low reasoning effort and no conversation-history fork. It is a native-agent
pilot, not a direct API run of the original `harness.py`.

The configured OpenRouter connection returned HTTP 402 for
`openai/gpt-5.6-luna`. Its configured free Liquid model returned HTTP 429 with
`free-models-per-day`. No successful benchmark completions used that connection.

## Fixed protocol

- Three tasks: billing tax correction, KV-store skeletal infill, pagination.
- Two repetitions per task and reading mode: 12 independent agents total.
- Matching starting file hashes for every paired trial.
- Same task contract, file manifest, editing implementation, test suite, and
  24-action budget plus mandatory final verification.
- Full mode: `view FILE` returns the complete numbered source.
- Foveated mode: `view FILE` returns the existing AST outline;
  `view FILE START END` returns up to 40 numbered source lines.
- Both modes start with filenames, not preloaded source or outlines.
- Both modes use inclusive line edits with exact indentation and atomic
  syntax validation. Edits are sequential. Tests cannot be edited through the
  interface. `verify` runs the fixed suite; `finish` independently runs it again.
- No editorial pass, prediction pruning, consolidation, or parent-agent hints.
- Task agents are instructed to access files only through the controlled CLI.
  This is a protocol restriction, not OS-level isolation or a hostile-code sandbox.
- Existing source files and historical traces are preserved; candidate work,
  fixtures, reference solutions, and complete tool-result logs live under `pilot/`.

Each participant receives the same protocol wording, its task, filenames, mode,
and run ID. Native tool schemas and system context are supplied by the product;
this experiment cannot remove that overhead or enforce an identical context
window at the provider layer. The first mode-specific sentence describes the
assigned interface; the other interface is also described.

## Measurements and limitations

`pilot/summary.json` records independently verified public-suite success, action
count (including finish), rejected edits, tool-returned characters, source-view
characters, and elapsed seconds from first action to final verification.
Durations exclude agent startup and final prose, and include shared-runner
scheduling. Up to three trials run concurrently; latency is descriptive only.
Action counts exclude unsuccessful shell invocations that never reach the driver.

API input/output/reasoning tokens and sampling seeds are unavailable through
the native agent runner and are explicitly null, not estimated from characters.
Returned characters measure one-time interface output, not cumulative context
tokens or billing. The exact model snapshot is not exposed; the requested model
alias is recorded. Two repeats on three small tasks cannot support broad claims
about success rates, large repositories, or a model capability hierarchy.

`fixture_validation.json` preserves failing starting tests and passing reference
checks. Original-file hashes and all candidate snapshots support later auditing.

## Commands

Run with Python 3.10+ from the repository root:

```powershell
python -B experiments/test_controlled.py
python -B experiments/controlled.py summarize
```

`prepare` creates a new dataset only and refuses to overwrite existing fixtures.
For a new experiment, choose a new `HOME` dataset directory before preparing it.
The model invocation is performed through native `collaboration.spawn_agent`,
with `fork_turns="none"`, `model="gpt-5.6-luna"`, `reasoning_effort="low"`.
The CLI can also be reused by an API-driven loop when model access is available.
