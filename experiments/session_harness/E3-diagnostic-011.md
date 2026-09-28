# E3 diagnostic 011: budget or diagnosis? Card 007's 0/2 tasks at 40 responses

Date: 2026-09-28  
Status: complete 2026-09-28: 0 of 6 accepted at 40 responses; diagnosis failures, not pacing ([report](E3-diagnostic-011-report.md))  
Stage: S6a follow-up. Hypothesis, arms, tasks, budgets and stop rules are in the JSON card; this file records intent and results.

Question: did sqlparse-mut-032, -057 and -061 fail both rollouts of card 007 because 20 responses was too few, or because the model cannot locate the fault? Same arm as card 007 with the response budget doubled to 40, 2 rollouts each, 6 runs.

Decision rule: tasks that resolve at 40 responses were budget-limited (pacing treatments apply); tasks that still fail are diagnosis failures (pacing will not help; verification or oracle treatments apply). Results go in `E3-diagnostic-011-report.md`.
