# E4 midpoint nudge 014: one harness message at half the response budget when nothing is edited

Date: 2026-09-28  
Status: proposed; awaiting owner approval  
Stage: S6 (agent-loop module, continuation-rule surface). Machine-readable card: [`cards/014.json`](cards/014.json).
Relation to [card 009](E4-diagnostic-commitment-009.md): the same "diagnostic commitment" weakness, addressed by a
triggered message instead of opening-instruction text.

## Evidence (weakness to address)

Card 007 ([report](E3-calibration-007-report.md)): 3 of 8 rejections were budget exhaustion without an edit
(022-r1, 032-r1, 032-r2): long exploration or reproduction with no commitment to a cause. E3 run 4 showed the same
shape with a weaker model (16 of 20 responses reading, no library edit). Weakness mining of the 40 card-007
journals (2026-09-28): among rejected runs that edited, the median first edit came at response 15; among accepted
runs, at response 6. A trigger at half the budget (response 10) sits between the two, so 0.5 is the default.

## Candidate (runner flag `--nudge midpoint`, `midpoint-nudge-v1`, fraction 0.5)

Once per run, when half of the response budget is spent (after response 10 of 20) and no pre-existing source file
has been edited (`pre-existing-python-source-v1`, content comparison, so edits made by a `run` command count), the
controller appends one harness message after the latest tool results:

> Half of the response budget is spent and no source file has been edited. State the single most likely cause and
> edit it now; verify after.

The text is fixed in [`reticle/runtime/nudges.py`](../../reticle/runtime/nudges.py). It is a `system` message (the
role the CLI adapter describes as coming from the harness), not a user turn; the journal records a
`harness_message` event (name, version, text, response index, transcript artifact) and the context manifest marks
the message's item with `harness_message`. The fraction is a parameter (`--nudge-fraction`, default 0.5) and is
hashed with the text under `treatments.nudge`. Nothing else changes.

## Arms and tasks

As [card 013](E4-finish-guard-013.md): incumbent versus incumbent plus `--nudge midpoint`, on card 007's evolution
set (`sqlparse-mut-001`, `-022`, `-032`, `-057`, `-061`) and three solved-twice tasks (`-025`, `-034`, `-040`), 2
rollouts, arm order seeded per task and rollout (seed 14), scripted gold and noop controls under the treatment arm
first. The nudge cannot fire on runs that edit before response 10, which card 007 suggests is most of them; the
card measures how often it fires and what follows.

## Budgets

32 runs plus 2 controls, 20 responses and 24 attempts each (campaign cap 900 attempts), about two hours, no
monetary cost.

## Acceptance rule

Mechanism check, not a promotion (held-in tasks, 16 paired units per arm). Report: runs where the nudge fired, the
response of the first edit after it, whether that edit was in the gold file, and acceptance, per arm and set. Earn
a held-out card only if no accepted run is lost on the efficiency set and, on the evolution set, fewer runs end at
the budget without an edit than under the incumbent. Otherwise reject and log.

## Fast stops

Plan section 5.3 and card 007's rules; stop if a run carries more than one `harness_message` or a treatment run's
recorded hash or `treatments` record differs from the plan.

## Reporting

`experiments/session_harness/E4-midpoint-nudge-014-report.md`.
