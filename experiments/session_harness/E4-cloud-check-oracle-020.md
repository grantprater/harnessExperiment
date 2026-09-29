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
price (card 013, the same design, totalled $33.35). Both arms add CLI reply recovery (below).

## Differences that matter for this treatment

On trusted-local the oracle runs the evaluator on a scratch copy outside the workspace, through the same backend as
the model's commands; the model's commands can read the VM's filesystem (the task clone under `.runtime`, and the
scratch copy while a check runs). Card 015's leakage stop therefore needs a trajectory review for reads outside the
workspace in every treatment run, not only for hidden test names in requests.

## CLI reply recovery (both arms)

Both arms run with `--cli-reply-recovery lenient-json+second-turn` (claude-cli adapter v3, `claude_cli.py`). Card
019 lost 5 runs (`c019-sqlparse-mut-057-r2`, `-075-r1`, `-075-r1-a2`, `-076-r1`, `-076-r1-a2`), each restarted by
`run_card.py`, because the CLI could not parse the model's StructuredOutput input as JSON three attempts in a row. It
reported the input as `__unparsedToolInput` and rejected it, and at `--max-turns 1` the model had no second try.
Across card 019's 620 attempts there were 27 such inputs, on 14 requests; card 007 (CLI 2.1.283) had 9 in 555
attempts, and each of those succeeded on the next attempt.

With the option on:

- a first message that v2 can use is still the reply;
- else, if the unparsed raw text passes `json.loads(raw, strict=False)`, that text is the reply;
- else the CLI (now at `--max-turns 2`) returns its rejection and the model's second StructuredOutput call is the
  reply.

Each attempt records `structured_output_repair`, `structured_output_retries`, `structured_output_rejections` (with
the full raw text) and `cli_model_messages`. Each run's results carry the counts under `cli_reply_recovery`, so the
report can say how often each rule applied.

The option is the same in both arms, so it is not part of the delta. It is in the CLI contract, so no run's hash
equals card 019's; without the option, the incumbent's hashes still equal card 019's. The scripted controls ignore
it.

Cost: in card 019, 402 of 586 replies called the harness tools directly. Such a reply is still the reply, but at
`--max-turns 2` the CLI answers its rejection with a second model turn, which is discarded. Model time and CLI list
price rise for those replies. In card 019, direct replies cost $17.07 of the $29.17 total, so card 020 might cost
20-60% more than it would without the option. Card 013's $33.35 plus that is $40-53, so the $50 spend-guard
checkpoint may fire before the campaign ends. CLI time per run (card 019:
median 102 s, max 428 s) stays well inside the 1200 s active budget. `cli_model_messages` measures the overhead.

## Reporting

`experiments/session_harness/E4-cloud-check-oracle-020-report.md`; evidence on a `cloud-results-020` branch.
