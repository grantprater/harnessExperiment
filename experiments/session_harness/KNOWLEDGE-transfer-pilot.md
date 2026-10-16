# Knowledge transfer and regime change

This pilot acquires reusable procedures from one live learning session, freezes
that experience, and compares three ways of retrieving it on fresh coding tasks:

1. Authorized prior transcript and tool-output excerpts.
2. Evidence-linked hypotheses/procedures and graph relationships.
3. The same graph with file fingerprint checks, transitive invalidation,
   supersession, and model-declared contradictions marked for rechecking.

The journal remains authoritative. Claims and dependency completeness remain
assertions. An unchanged file is evidence of unchanged bytes, not proof of a
claim's correctness. A changed dependency is a revalidation trigger, not proof
that its claims are false. This implements explicit change signals, not Bayesian
change-point detection or posterior probabilities.

Two synthetic protocol families cover timeout conversion and reply parsing.
Each has a stable transfer task, an unrelated-edit task, and an abrupt change in
semantics. One shared acquisition session learns the original procedures. Each
of the six confirmation tasks runs once per arm in seeded randomized arm order.
The source snapshot stays fixed throughout confirmation; independently evaluated
outcomes never enter subsequent model contexts.

Model: `gpt-6.1-sol` through the existing Reticle Harness OpenAI subscription.
Limits: six acquisition responses, five per trial, 96 responses total maximum.
All arms have the same model, tools, context budget, retrieval byte cap and local
backend. The token-overlap scoring rule is shared; the transcript index and graph
index contain different representations of the same source experience.

Primary measure: independent correctness within budget, with only `client.py`
changed. Secondary measures include model responses, tool actions, tokens,
runtime, retrieval truncation, and dependency findings. Gold/noop controls test
each evaluator before any live call. Mechanism unit tests separately cover
staleness, unrelated edits, transitive dependencies, supersession and snapshots.

This is a small transfer/mechanism pilot. Ceiling performance or equal results
are valid outcomes; no general capability or statistical treatment-effect claim
is warranted. The copied task folders use trusted-local execution, not a security
sandbox. No production changes are automatically promoted.

```powershell
.runtime\test-venv\Scripts\python.exe experiments/session_harness/knowledge_transfer.py --prepare
.runtime\test-venv\Scripts\python.exe experiments/session_harness/knowledge_transfer.py --execute
```

Artifacts: `.runtime/knowledge-transfer-002/`, including frozen protocol/source
hashes, shared snapshot, per-run sessions, independent results, `report.md` and
`outer-loop-proposals.json`. Proposals require the issue to appear in at least
two distinct sessions and remain hypotheses needing a controlled experiment.
