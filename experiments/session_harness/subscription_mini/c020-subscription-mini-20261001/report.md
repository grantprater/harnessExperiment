# Card 020 subscription mini-run

Integration check: one task, one rollout per arm.

| Arm | Accepted | Responses | Attempts | Tools | Seconds |
|---|---|---:|---:|---:|---:|
| gold | accepted | 2 | 2 | 2 | 9.0 |
| noop | rejected | 1 | 1 | 1 | 8.8 |
| incumbent | rejected | 18 | 18 | 40 | 228.2 |
| check-oracle | rejected | 20 | 20 | 38 | 239.4 |

See plan.json for protocol differences and status.json for check counts and evidence paths.
This small integration test does not estimate treatment effects or update card 020's campaign.
