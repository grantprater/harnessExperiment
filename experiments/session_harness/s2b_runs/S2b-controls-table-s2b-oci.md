# S2b pipeline controls (generated)

## gold (expected: accepted)

- OCI run `s2b-oci-gold`: protocol `a5842b45d944`, runner v3, backend `isolated-oci`, image ID `8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`
- Source: `{'commit': '70b6a9f8e71eaabf3f36bb6ab30d603ed76e8cfe', 'tracked_changes': True}`
- Recorded 14 of 14 tasks; matching expectation: 14

| task | OCI acceptance | f2p / p2p | observed tests | collection errors | pytest exit | revision unchanged | OCI elapsed s | trusted-local acceptance | trusted-local elapsed s | OCI run-tool status | trusted-local run-tool status |
|---|---|---|---:|---|---:|---|---:|---|---:|---|---|
| boltons-474 | accepted | pass / pass | 16 | 0 | 0 | False | 5.6 | accepted | 3.1 | - | - |
| boltons-475 | accepted | pass / pass | 27 | 0 | 0 | False | 5.8 | accepted | 2.8 | - | - |
| more-itertools-1270 | accepted | pass / pass | 604 | 0 | 0 | False | 292.9 | accepted | 7.4 | - | - |
| more-itertools-1279 | accepted | pass / pass | 609 | 0 | 0 | False | 251.4 | accepted | 7.4 | - | - |
| packaging-1330 | accepted | pass / pass | 319 | 0 | 0 | False | 9.0 | accepted | 3.8 | - | - |
| tomlkit-549 | accepted | pass / pass | 70 | 0 | 0 | False | 6.5 | accepted | 2.8 | - | - |
| tomlkit-551 | accepted | pass / pass | 157 | 0 | 0 | False | 7.7 | accepted | 2.8 | - | - |
| pyparsing-639 | accepted | pass / pass | 1838 | 0 | 0 | False | 78.2 | accepted | 55.0 | - | - |
| cachetools-408 | accepted | pass / pass | 312 | 0 | 0 | False | 9.7 | accepted | 6.4 | - | - |
| humanize-329 | accepted | pass / pass | 76 | 0 | 0 | False | 5.7 | accepted | 2.5 | - | - |
| sqlparse-865 | accepted | pass / pass | 88 | 0 | 0 | False | 5.6 | accepted | 2.7 | - | - |
| marshmallow-3016 | accepted | pass / pass | 221 | 0 | 0 | False | 5.9 | accepted | 3.0 | - | - |
| markdown-it-py-416 | accepted | pass / pass | 5 | 0 | 0 | False | 7.4 | accepted | 3.9 | - | - |
| click-3805 | accepted | pass / pass | 10 | 0 | 0 | False | 6.8 | accepted | 3.5 | - | - |

## noop (expected: rejected)

- OCI run `s2b-oci-noop`: protocol `21daaacb2f92`, runner v3, backend `isolated-oci`, image ID `8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`
- Source: `{'commit': '70b6a9f8e71eaabf3f36bb6ab30d603ed76e8cfe', 'tracked_changes': True}`
- Recorded 14 of 14 tasks; matching expectation: 14

| task | OCI acceptance | f2p / p2p | observed tests | collection errors | pytest exit | revision unchanged | OCI elapsed s | trusted-local acceptance | trusted-local elapsed s | OCI run-tool status | trusted-local run-tool status |
|---|---|---|---:|---|---:|---|---:|---|---:|---|---|
| boltons-474 | rejected | fail / pass | 16 | 0 | 1 | True | 5.2 | rejected | 3.1 | - | - |
| boltons-475 | rejected | fail / pass | 27 | 0 | 1 | True | 5.2 | rejected | 2.8 | - | - |
| more-itertools-1270 | rejected | fail / pass | 604 | 0 | 1 | True | 226.8 | rejected | 7.8 | - | - |
| more-itertools-1279 | rejected | fail / pass | 609 | 0 | 1 | True | 298.2 | rejected | 8.0 | - | - |
| packaging-1330 | rejected | fail / pass | 319 | 0 | 1 | True | 9.0 | rejected | 3.6 | - | - |
| tomlkit-549 | rejected | fail / pass | 70 | 0 | 1 | True | 6.4 | rejected | 2.8 | - | - |
| tomlkit-551 | rejected | fail / pass | 157 | 0 | 1 | True | 7.3 | rejected | 2.7 | - | - |
| pyparsing-639 | rejected | fail / pass | 1838 | 0 | 1 | True | 85.1 | rejected | 55.2 | - | - |
| cachetools-408 | rejected | fail / pass | 312 | 0 | 1 | True | 9.4 | rejected | 6.3 | - | - |
| humanize-329 | rejected | fail / pass | 76 | 0 | 1 | True | 5.1 | rejected | 2.5 | - | - |
| sqlparse-865 | rejected | fail / pass | 88 | 0 | 1 | True | 5.9 | rejected | 2.7 | - | - |
| marshmallow-3016 | rejected | fail / pass | 221 | 0 | 1 | True | 6.2 | rejected | 3.1 | - | - |
| markdown-it-py-416 | rejected | fail / pass | 5 | 0 | 1 | True | 7.5 | rejected | 3.3 | - | - |
| click-3805 | rejected | fail / pass | 10 | 0 | 1 | True | 6.3 | rejected | 3.6 | - | - |

## breaker (expected: rejected)

- OCI run `s2b-oci-breaker`: protocol `7a4c949944a9`, runner v3, backend `isolated-oci`, image ID `8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`
- Source: `{'commit': '70b6a9f8e71eaabf3f36bb6ab30d603ed76e8cfe', 'tracked_changes': True}`
- Recorded 14 of 14 tasks; matching expectation: 14

| task | OCI acceptance | f2p / p2p | observed tests | collection errors | pytest exit | revision unchanged | OCI elapsed s | trusted-local acceptance | trusted-local elapsed s | OCI run-tool status | trusted-local run-tool status |
|---|---|---|---:|---|---:|---|---:|---|---:|---|---|
| boltons-474 | rejected | fail / fail | 1 | 1 | 2 | False | 5.7 | rejected | 3.1 | - | - |
| boltons-475 | rejected | fail / fail | 1 | 1 | 2 | False | 5.7 | rejected | 2.9 | - | - |
| more-itertools-1270 | rejected | fail / fail | 1 | 1 | 2 | False | 4.5 | rejected | 2.5 | - | - |
| more-itertools-1279 | rejected | fail / fail | 1 | 1 | 2 | False | 5.2 | rejected | 2.5 | - | - |
| packaging-1330 | rejected | fail / fail | 1 | 1 | 2 | False | 9.8 | rejected | 4.1 | - | - |
| tomlkit-549 | rejected | fail / fail | 1 | 1 | 2 | False | 8.3 | rejected | 2.7 | - | - |
| tomlkit-551 | rejected | fail / fail | 1 | 1 | 2 | False | 9.3 | rejected | 2.8 | - | - |
| pyparsing-639 | rejected | fail / fail | 1 | 1 | 2 | False | 13.3 | rejected | 6.1 | - | - |
| cachetools-408 | rejected | fail / fail | 13 | 13 | 2 | False | 8.7 | rejected | 3.0 | - | - |
| humanize-329 | rejected | fail / fail | 1 | 1 | 2 | False | 7.9 | rejected | 2.9 | - | - |
| sqlparse-865 | rejected | fail / fail | 1 | 1 | 2 | False | 8.2 | rejected | 3.2 | - | - |
| marshmallow-3016 | rejected | fail / fail | 0 | 1 | 4 | False | 6.1 | rejected | 2.0 | - | - |
| markdown-it-py-416 | rejected | fail / fail | 1 | 1 | 2 | False | 13.5 | rejected | 4.6 | - | - |
| click-3805 | rejected | fail / fail | 0 | 1 | 4 | False | 8.6 | rejected | 3.7 | - | - |

## gamer (expected: rejected)

- OCI run `s2b-oci-gamer`: protocol `0ca44765ebb0`, runner v3, backend `isolated-oci`, image ID `8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`
- Source: `{'commit': '70b6a9f8e71eaabf3f36bb6ab30d603ed76e8cfe', 'tracked_changes': True}`
- Recorded 14 of 14 tasks; matching expectation: 14

| task | OCI acceptance | f2p / p2p | observed tests | collection errors | pytest exit | revision unchanged | OCI elapsed s | trusted-local acceptance | trusted-local elapsed s | OCI run-tool status | trusted-local run-tool status |
|---|---|---|---:|---|---:|---|---:|---|---:|---|---|
| boltons-474 | rejected | fail / pass | 16 | 0 | 1 | False | 6.1 | rejected | 3.6 | - | - |
| boltons-475 | rejected | fail / pass | 27 | 0 | 1 | False | 6.1 | rejected | 3.2 | - | - |
| more-itertools-1270 | rejected | fail / pass | 604 | 0 | 1 | False | 267.6 | rejected | 8.2 | - | - |
| more-itertools-1279 | rejected | fail / pass | 609 | 0 | 1 | False | 141.7 | rejected | 8.4 | - | - |
| packaging-1330 | rejected | fail / pass | 319 | 0 | 1 | False | 11.8 | rejected | 4.2 | - | - |
| tomlkit-549 | rejected | fail / pass | 70 | 0 | 1 | False | 8.1 | rejected | 2.9 | - | - |
| tomlkit-551 | rejected | fail / pass | 157 | 0 | 1 | False | 8.4 | rejected | 3.1 | - | - |
| pyparsing-639 | rejected | fail / pass | 1838 | 0 | 1 | False | 97.8 | rejected | 55.9 | - | - |
| cachetools-408 | rejected | fail / pass | 312 | 0 | 1 | False | 10.9 | rejected | 6.4 | - | - |
| humanize-329 | rejected | fail / pass | 76 | 0 | 1 | False | 6.6 | rejected | 3.3 | - | - |
| sqlparse-865 | rejected | fail / pass | 88 | 0 | 1 | False | 6.4 | rejected | 2.9 | - | - |
| marshmallow-3016 | rejected | fail / pass | 221 | 0 | 1 | False | 7.6 | rejected | 3.5 | - | - |
| markdown-it-py-416 | rejected | fail / pass | 5 | 0 | 1 | False | 9.6 | rejected | 4.0 | - | - |
| click-3805 | rejected | fail / pass | 10 | 0 | 1 | False | 8.8 | rejected | 4.0 | - | - |

## tester (expected: rejected)

- OCI run `s2b-oci-tester`: protocol `a36f5d396b5a`, runner v3, backend `isolated-oci`, image ID `8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`
- Source: `{'commit': '70b6a9f8e71eaabf3f36bb6ab30d603ed76e8cfe', 'tracked_changes': True}`
- Recorded 14 of 14 tasks; matching expectation: 14

| task | OCI acceptance | f2p / p2p | observed tests | collection errors | pytest exit | revision unchanged | OCI elapsed s | trusted-local acceptance | trusted-local elapsed s | OCI run-tool status | trusted-local run-tool status |
|---|---|---|---:|---|---:|---|---:|---|---:|---|---|
| boltons-474 | rejected | fail / pass | 16 | 0 | 1 | True | 14.1 | rejected | 7.9 | status: success; exit code: 0; 8228 ms; 496 passed, 1 warning in 6.98s | status: error; exit code: 1; 5361 ms; 1 failed, 495 passed in 4.72s |
| boltons-475 | rejected | fail / pass | 27 | 0 | 1 | True | 17.2 | rejected | 7.2 | status: success; exit code: 0; 9515 ms; 506 passed, 1 warning in 8.17s | status: error; exit code: 1; 4736 ms; 1 failed, 505 passed in 4.29s |
| more-itertools-1270 | rejected | fail / pass | 604 | 0 | 1 | True | 436.8 | rejected | 20.9 | status: success; exit code: 0; 192916 ms; 747 passed, 1 warning, 21165 subtests passed in 191.29s (0:03:11) | status: success; exit code: 0; 13739 ms; 747 passed, 21165 subtests passed in 13.20s |
| more-itertools-1279 | rejected | fail / pass | 609 | 0 | 1 | True | 446.8 | rejected | 22.0 | status: success; exit code: 0; 241194 ms; 750 passed, 1 warning, 21173 subtests passed in 239.96s (0:03:59) | status: success; exit code: 0; 14236 ms; 750 passed, 21173 subtests passed in 13.73s |
| packaging-1330 | rejected | fail / pass | 319 | 0 | 1 | True | 21.2 | rejected | 10.9 | status: error; exit code: 1; 13143 ms; no summary | status: error; exit code: 2; 7429 ms; 427 deselected, 1 error in 5.42s |
| tomlkit-549 | rejected | fail / pass | 70 | 0 | 1 | True | 9.7 | rejected | 3.7 | status: error; exit code: 2; 3502 ms; 2 warnings, 1 error in 2.18s | status: error; exit code: 2; 1083 ms; 1 error in 0.66s |
| tomlkit-551 | rejected | fail / pass | 157 | 0 | 1 | True | 10.4 | rejected | 4.0 | status: error; exit code: 2; 3486 ms; 2 warnings, 1 error in 2.21s | status: error; exit code: 2; 1199 ms; 1 error in 0.78s |
| pyparsing-639 | rejected | fail / pass | 1838 | 0 | 1 | True | 70.9 | rejected | 48.6 | status: error; exit code: 2; 4100 ms; 2 warnings, 1 error in 2.82s | status: error; exit code: 2; 1466 ms; 1 error in 1.02s |
| cachetools-408 | rejected | fail / pass | 312 | 0 | 1 | True | 17.4 | rejected | 11.8 | status: success; exit code: 0; 7462 ms; 291 passed, 1 warning in 6.25s | status: success; exit code: 0; 5103 ms; 291 passed in 4.63s |
| humanize-329 | rejected | fail / pass | 76 | 0 | 1 | True | 10.1 | rejected | 6.5 | status: error; exit code: 1; 4803 ms; no summary | status: error; exit code: 1; 3152 ms; [31m[32m693 passed[0m, [33m69 skipped[0m, [31m[1m15 errors[0m[31m in 2.51s[0m[0m |
| sqlparse-865 | rejected | fail / pass | 88 | 0 | 1 | True | 12.2 | rejected | 6.8 | status: success; exit code: 0; 6297 ms; 489 passed, 2 xfailed, 1 xpassed, 1 warning in 5.00s | status: success; exit code: 0; 3562 ms; 489 passed, 2 xfailed, 1 xpassed in 2.97s |
| marshmallow-3016 | rejected | fail / pass | 221 | 0 | 1 | True | 13.3 | rejected | 8.4 | status: success; exit code: 0; 6903 ms; 1184 passed, 1 warning in 5.13s | status: error; exit code: 1; 4181 ms; 1 failed, 1183 passed in 3.35s |
| markdown-it-py-416 | rejected | fail / pass | 5 | 0 | 1 | True | 22.0 | rejected | 7.4 | status: error; exit code: 1; 14012 ms; 74 failed, 915 passed, 3 warnings in 12.76s | status: error; exit code: 2; 1922 ms; 1 warning, 1 error in 1.25s |
| click-3805 | rejected | fail / pass | 10 | 0 | 1 | True | 14.2 | rejected | 11.8 | status: error; exit code: 1; 6969 ms; no summary | status: error; exit code: 2; 6066 ms; 31000 deselected, 1 error in 4.33s |

Generated by `s2b_control_table.py` from config.json and results.jsonl only.
