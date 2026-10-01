# E3 cloud replication 019: card 007 on a Claude Code cloud VM

Date: 2026-09-28  
Status: running; approved by the owner through experiments/cloud/RUN_IN_CLOUD.md, launched in a cloud session 2026-09-28 22:37 UTC  
Stage: S6 infrastructure. Machine-readable card: [`cards/019.json`](cards/019.json).

## Purpose

Replicate [card 007](E3-calibration-007.md) in a cloud VM to measure the environment effect before any treatment
runs there. Card 007 ran on the Windows host in the pinned OCI image; a cloud session has no container engine, so
every cloud card runs trusted-local inside the VM. If the incumbent's outcomes move in the cloud, a cloud treatment
card must be compared with a cloud incumbent (paired within one card, as card 020 does), never with host results.

## Hypothesis

Card 007's incumbent protocol, run in the cloud VM, gives per-task acceptance within sampling noise of card 007
(32/40 accepted; 2 contrastive tasks, 3 negative, 15 solved twice).

## Design (card 007's, unchanged)

The 20 seed-7 calibration tasks ([`E3-calibration-007-tasks.json`](E3-calibration-007-tasks.json), same hash),
2 rollouts each (40 runs, rollout-major), one runner invocation per task and rollout (`c019-<task>-r<n>`), runner v8,
`--client claude-cli` (adapter v2), `pressure-recent-v3`, `reticle-tools-v3`, repeat guard off. Per run: 20
responses, 24 attempts, 1,200 active seconds, 80,000 context bytes, 4,096 max tokens, 600 s pytest timeout, 3,600 s
invocation wall limit. Retries: at most 2 per invocation (60 s, 300 s backoff); 3 consecutive failed attempts stop
the campaign (plan 5.3). Gold and noop controls on `sqlparse-mut-001` and `-006` first, rerun on the VM.

## Known differences from card 007

| | Card 007 (host) | Card 019 (cloud VM) |
|---|---|---|
| backend | isolated OCI image `8b74015e5079` (podman), no network in the container | trusted-local (`isolation: vm-sandbox`): commands run in the VM, which has network and can read the VM's files |
| task interpreter | Python 3.13.15 in the image | `.runtime/bugs-venv` built by `experiments/cloud/setup_cloud.sh`: the host's pinned packages on uv's CPython 3.13.15 (the VM's own Python 3.11 only if uv cannot supply it; the setup summary says which) |
| Claude CLI | 2.1.283 | 2.1.284 |
| model | alias `sonnet` (reported `claude-sonnet-5`) | full id `claude-sonnet-5`, pinned: an attempt reporting another model stops the campaign (`model_pin_violation`). The alias now resolves to `claude-sonnet-5-5` on the VM |
| CLI start-up | about 1 s per response | 16.6 s spawn-to-request measured once; it counts toward the 1,200 active seconds |
| CPU | Ryzen 5 7600X, shared with the owner's jobs | 4 vCPUs, 15 GB, no swap |
| spend | subscription, billing unknown | the owner's credits; spend guard at $40 CLI list price (card 007 totalled $27.53 at list price) |

Seconds (active, wall, per response) are not comparable with card 007's. The protocol hash differs by construction
(backend, execution record with the VM's interpreter path, routing contract with `model_pin`, CLI version); the VM's
`--plan` prints the hashes the runs must record.

## Measurements

Card 007's: per run accepted, stop reason, responses, attempts, tool calls, active and wall seconds, tokens, first
edit, rejected calls, repeat flags, edits in gold files, verification before finish; per campaign acceptance with a
95% interval, per-task outcomes, outcome distribution. Plus the "Spend and time" section: nested model cost at CLI
list price and wall time.

## What counts

Environment check, not a promotion. The cloud environment is **equivalent for treatment work** if the accepted total
is within 6 runs of card 007's 32 and no task moves between 2/2 and 0/2; otherwise it is **different**, and cloud
treatment cards are read only against a cloud incumbent in the same card. Every run that stops on the active-seconds
cap is listed, since start-up latency eats into it.

## Fast stops

Plan section 5.3 and card 007's rules, plus: a `model_pin_violation`, a CLI auth error, or an isolation failure
(tools other than StructuredOutput, an MCP server, an `apiKeySource` naming an environment key) stops the campaign;
the spend guard stops it at $40 list price. Trusted-local gives the model's commands the VM's filesystem and
network, so the trajectory review checks every run for reads outside the workspace (notably the task clone
`.runtime/bug-mining/repos/sqlparse`, which holds the healthy code) and for fetches of upstream sqlparse; such a
run is an authority escape.

## Reporting

`experiments/session_harness/E3-cloud-replication-019-report.md` (run_card skeleton, with "Spend and time"), evidence
on the branch `cloud-results-019`.
