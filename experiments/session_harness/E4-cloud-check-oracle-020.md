# E4 cloud check oracle 020: card 015's arms, paired, on the cloud VM backend

Date: 2026-09-28  
Status: proposed; awaiting owner approval, which follows card 019's report  
Stage: S6 (tool-use module) on cloud compute. Machine-readable card: [`cards/020.json`](cards/020.json).

## Purpose

Run [card 015](E4-check-oracle-015.md)'s comparison (incumbent versus incumbent plus `--oracle hidden-tests:3`) in a
Claude Code cloud VM, with both arms in one card, so the delta is paired within one environment whatever card 019
finds about the environment effect.

## Design

Card 015's (the [card 013](E4-finish-guard-013.md) layout): evolution set `sqlparse-mut-001`, `-022`, `-032`,
`-057`, `-061` and efficiency set `-025`, `-034`, `-040`, 2 rollouts, arm order seeded per task and rollout (seed
15), scripted gold and noop controls under the treatment arm first; 32 runs, 20 responses and 24 attempts each, card
015's stop rules and decision rule. Backend, CLI and model as [card 019](E3-cloud-replication-019.md): trusted-local
in the VM (`isolation: vm-sandbox`), CLI 2.1.284, model pinned as `claude-sonnet-5`. Spend guard: $50 at CLI list
price (card 013, the same design, totalled $33.35).

## Differences that matter for this treatment

On trusted-local the oracle runs the evaluator on a scratch copy outside the workspace, through the same backend as
the model's commands; the model's commands can read the VM's filesystem (the task clone under `.runtime`, and the
scratch copy while a check runs). Card 015's leakage stop therefore needs a trajectory review for reads outside the
workspace in every treatment run, not only for hidden test names in requests.

## Reporting

`experiments/session_harness/E4-cloud-check-oracle-020-report.md`; evidence on a `cloud-results-020` branch.
