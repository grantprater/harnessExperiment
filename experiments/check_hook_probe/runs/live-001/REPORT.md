# Post-edit check probe: completed comparison

All 18 attempts finished and passed independent evaluation on fresh snapshots
using the original public test suites. No provider failures occurred, reported
usage was complete, and reported cached input tokens were zero.

| Condition | Accepted | Total input + output tokens | Mean tokens per accepted attempt | Model calls | Checks |
|---|---:|---:|---:|---:|---:|
| Manual verification | 6/6 | 95,751 | 15,958.5 | 35 | 6 |
| Automatic full results | 6/6 | 77,439 | 12,906.5 | 28 | 10 |
| Automatic selective results | 6/6 | 75,555 | 12,592.5 | 28 | 10 |

Automatic full reporting used 19.1% fewer total tokens than manual verification.
Selective automatic reporting used 21.1% fewer than manual, and 2.4% fewer than
automatic full reporting. The major observed saving was associated with automatic
verification and fewer model decisions, rather than output compression alone.

| Task | Manual mean total tokens | Automatic full mean | Automatic selective mean |
|---|---:|---:|---:|
| Billing | 18,125 | 13,213 | 13,067 |
| KV implementation | 16,484 | 13,690.5 | 13,372.5 |
| Pagination | 13,266.5 | 11,816 | 11,338 |

Manual runs invoked verify once per attempt; automatic runs made no explicit
verify calls. Both automatic conditions recorded four failed checks during
intermediate edits and six passing checks. There were no output retrieval calls
in any condition. The selective observations were sufficient for these attempts;
this does not establish sufficiency for difficult failure diagnosis.

Input/output breakdown: manual 92,854/2,897; automatic full 74,481/2,958;
automatic selective 72,577/2,978. Automatic execution increased the number of
tests run because hooks executed between partial multi-file changes. Test
execution costs and durations are retained separately in the attempt summaries.

This is a descriptive comparison on three familiar small tasks with two repeats
per condition. All tasks saturated acceptance. KV is implementation of missing
methods, not a pure bug fix. The experiment does not demonstrate transfer to
large repositories, incomplete tests, expensive suites, or genuinely difficult
investigation. A fixed full transcript was retained; no context management
treatment was tested. Condition instructions and hook behavior differ as declared
in the protocol. There is no automatic promotion or change to CLI defaults.

The result supports further testing of the conditional procedure: after relevant
source changes, run an established inexpensive check automatically and expose an
actionable result. A next comparison should challenge failure diagnosis and check
selection, rather than simply repeat these saturated tasks.

See [comparison.json](comparison.json) for all attempt metrics,
[protocol.json](protocol.json) for frozen configuration and source hashes,
and each attempt's evaluation, usage, check events and exact session evidence.
