# Conditional observation refinement: initial probe

All twelve decisions passed independent fixture scoring. Both sparse-delta
decisions correctly retained the unchanged failure from the baseline and excluded
resolved historical failures. The same selector worked on checks and the
predeclared UI-measurement transfer domain. Dense changes and missing baselines
selected full snapshots; paired fallback requests were identical.

| Condition | Full input tokens | Adaptive input tokens | Reduction |
|---|---:|---:|---:|
| Sparse, checks | 840 | 782 | 6.9% |
| Sparse, UI | 1,031 | 921 | 10.7% |
| Dense, both domains | 1,868 | 1,868 | 0% |
| Missing baseline, both domains | 766 | 766 | 0% |
| All conditions | 4,505 | 4,337 | 3.7% |

Sparse cells combined saved 9.0% input tokens (1,871 to 1,703) and 8.8% total
tokens (1,915 to 1,747). Across the complete probe, provider-reported input plus
output was 4,784 full versus 4,692 adaptive: 1.9% less. The missing-baseline pairs
had variable completion-token counts despite identical requests, reducing the
net saving by 76 tokens. Those differences cannot be attributed to the selector.
All reported cached-token counts were zero. No provider failures occurred.

The saving is smaller than the earlier four-call probe: these fixtures have fewer
records, two historical snapshots in retained prefixes, and version/hash metadata
in the observation format. Four of the six paired conditions intentionally fall
back to full observations. Latest-result byte savings do not establish comparable
whole-request token savings.

The predeclared gate recorded `scoped_support`: accepted decisions and lower
aggregate total tokens on these frozen fixtures. That is a descriptive smoke-test
conclusion, not a statistically established improvement. One sample per cell,
simple status-based decisions, fixed prerecorded observation sequences, no
interactive completion or visual review, and no agent-discovered applicability
conditions limit the inference. No CLI defaults were changed.

The implemented refinement loop preserved its original proposal and appended
immutable evidence and a scoped conclusion using the existing journal/artifact
store. See [evaluation.json](evaluation.json),
[refinement-record.json](refinement-record.json), and [protocol.json](protocol.json).

The next useful test is an opt-in real observer with repeated tool use, checking
accepted completion, recovery reads and total usage. Repeating these simple
fixtures would chiefly establish interpretation reliability rather than practical
task-level savings.
