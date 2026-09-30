# E4 diagnostic commitment 009: one manual round of the harness self-improvement loop

Date: 2026-09-27  
Status: proposed; prerequisites 007 and S6b complete (2026-09-30); awaiting owner approval  
Stage: S6c. This card is the loop of S6 executed once by hand, with the proposal written by a person from
recorded evidence rather than by the proposer invocation.

## Evidence (weakness to address)

- E3 run 4 (Qwen3-Coder-Next): 16 of 20 responses reading before writing anything; no library edit; three
  identical rejected `run` calls at the end ([report](E3-sqlparse-qwen-parasail-4.md)).
- Positive control (Sonnet): first edit at response 6 of 9, verification by pytest before `finish`
  ([report](E3-positive-control-006-report.md)). The capable model commits early and verifies.
- Card 007 will add contrastive pairs on the same tasks; the signature cluster to target is chosen from
  its mining output, expected to be "no edit before budget" or "edit without verification".

## Candidate (agent-loop module, opening-instructions surface only)

A minimal addition to the opening instructions, three sentences at most, along the lines of: state the
suspected cause before editing; make the first edit no later than the midpoint of the response budget;
run the narrowest available check before calling `finish`. Exact wording is fixed in this card before any
run and never changed during the round. Nothing else in the bundle changes.

## Arms and tasks

Incumbent bundle versus candidate bundle. Held-in D_in: the card-007 tasks whose trajectories produced the
evidence (up to 8). Held-out D_oh: 8 different tasks from the evolution set, never inspected while writing
the candidate. 2 rollouts per task per arm; arm order randomised per task; a no-change arm (incumbent
twice more on 4 tasks) estimates evaluation noise.

## Budgets

(8 + 8) tasks x 2 rollouts x 2 arms = 64 runs, plus 8 no-change runs, serialised under the live-run lock,
20 responses each. At roughly 90 s per run this is about two hours of wall time and no monetary cost.

## Acceptance rule

Promote only if delta_in >= 0 and delta_oh >= 0 and max(delta_in, delta_oh) exceeds the no-change arm's
observed spread. Otherwise reject and log. A rejected candidate with delta_oh < 0 is also evidence for S6's
diff-review gate: record what the edit encoded.

## Fast stops

Plan section 5.3 rules apply. Additionally stop if the candidate changes any surface other than the opening
instructions (bundle hash check) or if the held-out list is read by anyone writing the candidate.

## Reporting

`experiments/session_harness/E4-diagnostic-commitment-009-report.md` with the paired table, the noise
estimate, the decision, and what the automated proposer would have needed to produce this edit unaided.
