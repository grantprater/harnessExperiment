# Weakness mining on card 007 (S6b): 40 Sonnet runs on the mutation bank

Date: 2026-09-28  
Tools: [`weakness_mining.py`](weakness_mining.py) (signatures, clusters, rule phases, evidence bundles),
[`label_phases.py`](label_phases.py) (`label --labeller rules|jev`, `develop`), [`jev_labeller.py`](jev_labeller.py)
(questions unchanged); schema [`labels/SCHEMA.md`](labels/SCHEMA.md)  
Inputs, read-only: the 40 runs `experiments/p6_pilot/runs/c007-*` of [card 007](E3-calibration-007-report.md). The
repository tracks their `calls.jsonl`, `config.json` and `results.jsonl`. The session journals (`sessions/`,
git-ignored) were read in place from the `wt/s6a-calibration` worktree and not modified. The task file
`experiments/mutation_tasks/tasks.mutations.json` supplied the gold files only.  
Outputs: this report; [`labels/labels_c007_rules.jsonl`](labels/labels_c007_rules.jsonl) (533 responses, 40 run
records); [`labels/labels_c007_jev.jsonl`](labels/labels_c007_jev.jsonl) (533 responses);
[`labels/diagnose-devset.jsonl`](labels/diagnose-devset.jsonl) (development set, 332 adjudicated responses);
[`evidence-bundles-c007.json`](evidence-bundles-c007.json) (5 bundles)

## Result in brief

- **5 minable clusters, none with more than 2 distinct tasks.** Only the top cluster, `fail_to_pass_failed |
  edit_outside_gold | edit_verified` (3 runs: 001-r1 and both 057 runs), covers 2 tasks. Every other cluster covers
  1 task, and task 061's two runs fall into two different clusters.
- **The report's two-mechanism reading holds in outline, but four of its specifics are wrong.**
  - Stops are 4 finish and 4 budget, not 5 and 3.
  - None of the 4 finishers ended "without verification". Each ran a check after its last edit
    (`verified_before_finish` true in 4 of 4), but the check covered its own reproduction, not the reported failure.
  - "Pytest found no tests" happened in 19 of the 32 accepted runs, so it does not separate 057.
  - 061 failed on a pass-to-pass regression in both runs. 061-r2 was a near miss: it had fixed 13 of the 15 target
    tests when the budget ran out.
- **Two rules misfired, and both are fixed.**
  - All 3 `stuck` responses in the 40 runs were re-reads of results that `pressure-recent-v3` had dropped from the
    context. They now get their own flag, `refetch_after_omission`, read from the journal's context manifests.
  - `pytest --collect-only` and `pip` now count as look-only (explore).
  - Only 022-r1's signature changed. The held-out labels and the baseline signatures are unchanged.
- **Jev agrees with the rules on 488 of 533 responses (91.6%, kappa 0.86).** The exception is `edit`, at 23/41:
  when a response both edits and runs a check, Jev picks verify, although the schema ranks edit higher.
- **Diagnose: 29 real cases (7 clear, 22 borderline) in 12 runs.** The mining subagent (Claude Opus 5.5) adjudicated
  them as a stand-in for a human reviewer.
  - 16 of the 29 are in the 8 rejected runs: 2.0 per rejected run against 0.4 per accepted run. 7 are in 022-r1
    alone.
  - Jev flags 18 responses at diagnose probability >= 0.3. Counting clear cases only, its precision is 4/18 (0.22)
    and its recall 4/7 (0.57). Counting all cases, precision is 7/18 (0.39) and recall 7/29 (0.24).
  - Jev misses every carried hypothesis, because its input shows earlier responses only as call summaries.
- Cost: 533 Jev calls, $0.058, about 105 s; every call succeeded on its first attempt.

## Rule fixes (and why)

| Fix | Misfire on card 007 | Change | Effect |
|---|---|---|---|
| A repeat counts as stuck only if the earlier result is still in context | 001-r2 #16 and 022-r1 #14 and #20 were labelled `stuck`, but each re-read a result the context policy had omitted. For example, request 14 of 022-r1 omits responses 1-4, which hold the `+=` search and the `formatter.py` read that #14 repeats | `Response.omitted` comes from each `context_manifest` (unit k = response k + 1; checked on 3,546/3,546 transcript units). A repeat requires the earlier identical call's result to be in context. Otherwise the call is a refetch: counted in `refetch_calls` and flagged `refetch_after_omission` | Stuck responses go from 3 to 0. 022-r1 moves from `budget / repeated_call / reproduce_no_edit` to `budget / refetch_after_omission / explore_only` (9 refetched calls). 001-r2, an accepted run, gains the flag (1 call) |
| Test discovery and `pip` are look-only | `python -m pytest --collect-only` runs no test, yet was labelled reproduce or verify (022-r1 #11, 057-r2 #13; in 042-r1 #13 and 043-r1 #10 another check outranks it). `pip download` (060-r1 #12) was labelled verify | `LOOK_ONLY_RUN`: `pytest`/`py.test` with `--collect-only` or `--co`, and `pip` or `python -m pip` | 3 response phases change. 022-r1 turns out never to have run library code, so its mechanism becomes `explore_only` |

Checks:
- Rerunning the rules on the 9 baseline runs gives identical records apart from the two new fields. The baseline
  runs are E3 runs 1-4, the positive control, the native arm, and the gold and noop controls. "Identical" covers
  every phase, every stuck response and every signature.
- So the 49 held-out responses in [`labels/labels.jsonl`](labels/labels.jsonl) keep their rule labels, and that
  file is unchanged.
- The Jev questions are unchanged (sha256 `c199d959aeda...`).
- There are 7 new unit tests: refetch with and without manifests, look-only commands, evaluator test counts,
  evidence bundles, the rules labeller, and the development tables.

One addition that is not a fix: the evaluator's per-test outcomes are in the journal (acceptance decision, then the
report artifact, then the tool output artifact). `test_counts` now reads them; they appear in the per-run table and
in the bundles, but not in the signature.

Known limits left alone, since neither changes a signature:
- `python -c "print(sqlparse.__file__)"` (042-r2 #10, 060-r1 #12) is labelled verify, although it only looks.
- A scratch script written after the first edit (024-r2 #15, 060-r1 #13) is labelled reproduce. That follows the
  schema's rule text, but its phase table defines reproduce as happening "before any edit".

## Clusters (ranked by distinct-task support)

```
python experiments/session_harness/weakness_mining.py <the 40 c007 run directories> \
  --tasks experiments/mutation_tasks/tasks.mutations.json --json --bundles experiments/session_harness/evidence-bundles-c007.json
```

| # | Verifier cause | Causal status | Mechanism | Runs | Tasks | Minable | Runs in cluster |
|---:|---|---|---|---:|---:|---|---|
| 1 | `fail_to_pass_failed` | `edit_outside_gold` | `edit_verified` | 3 | 2 | yes | c007-sqlparse-mut-001-r1, c007-sqlparse-mut-057-r1, c007-sqlparse-mut-057-r2 |
| 2 | `budget` | `none` | `reproduce_no_edit` | 2 | 1 | yes | c007-sqlparse-mut-032-r1, c007-sqlparse-mut-032-r2 |
| 3 | `budget` | `refetch_after_omission` | `explore_only` | 1 | 1 | yes | c007-sqlparse-mut-022-r1 |
| 4 | `pass_to_pass_regression` | `none` | `edit_unverified` | 1 | 1 | yes | c007-sqlparse-mut-061-r2 |
| 5 | `pass_to_pass_regression` | `none` | `edit_verified` | 1 | 1 | yes | c007-sqlparse-mut-061-r1 |
| 6 | `accepted` | `none` | `edit_verified` | 29 | 16 | no | c007-sqlparse-mut-002-r1, c007-sqlparse-mut-002-r2, c007-sqlparse-mut-022-r2, c007-sqlparse-mut-023-r1, c007-sqlparse-mut-023-r2, c007-sqlparse-mut-024-r1, c007-sqlparse-mut-024-r2, c007-sqlparse-mut-025-r1, c007-sqlparse-mut-025-r2, c007-sqlparse-mut-033-r1, c007-sqlparse-mut-033-r2, c007-sqlparse-mut-034-r1, c007-sqlparse-mut-034-r2, c007-sqlparse-mut-040-r1, c007-sqlparse-mut-040-r2, c007-sqlparse-mut-042-r2, c007-sqlparse-mut-043-r1, c007-sqlparse-mut-044-r1, c007-sqlparse-mut-044-r2, c007-sqlparse-mut-046-r1, c007-sqlparse-mut-046-r2, c007-sqlparse-mut-060-r1, c007-sqlparse-mut-060-r2, c007-sqlparse-mut-073-r1, c007-sqlparse-mut-073-r2, c007-sqlparse-mut-075-r1, c007-sqlparse-mut-075-r2, c007-sqlparse-mut-076-r1, c007-sqlparse-mut-076-r2 |
| 7 | `accepted` | `edit_outside_gold` | `edit_verified` | 1 | 1 | no | c007-sqlparse-mut-043-r2 |
| 8 | `accepted` | `refetch_after_omission+edit_outside_gold` | `edit_verified` | 1 | 1 | no | c007-sqlparse-mut-001-r2 |
| 9 | `accepted` | `rejected_calls` | `edit_verified` | 1 | 1 | no | c007-sqlparse-mut-042-r1 |

## Per run

"Tests failing (f2p, p2p)" gives the target tests still failing out of those expected, then the previously passing
tests now failing. Both come from the evaluator output in the journal.

| Run | Task | Source | Stop (class) | Acceptance | Tests failing (f2p, p2p) | Rejected | Stuck responses | Refetched calls | First edit | Edit in gold | Verified before finish | Phases (rule) | results.jsonl |
|---|---|---|---|---|---|---:|---|---:|---:|---|---|---|---|
| c007-sqlparse-mut-001-r1 | sqlparse-mut-001 | reticle-journal | `finish_requested` (finish) | rejected | 1/1, 0/490 | 0 | - | 0 | 13 | False | True | explorex8 reproduce explore reproduce explore edit verify finish | agrees |
| c007-sqlparse-mut-001-r2 | sqlparse-mut-001 | reticle-journal | `finish_requested` (finish) | accepted | 0/1, 0/490 | 0 | - | 1 | 17 | False | True | explorex6 reproducex2 explore reproducex3 explore reproduce explorex2 edit verify finish | agrees |
| c007-sqlparse-mut-002-r1 | sqlparse-mut-002 | reticle-journal | `finish_requested` (finish) | accepted | 0/9, 0/482 | 0 | - | 0 | 13 | True | True | explorex8 reproducex3 explore edit verify explore finish | agrees |
| c007-sqlparse-mut-002-r2 | sqlparse-mut-002 | reticle-journal | `finish_requested` (finish) | accepted | 0/9, 0/482 | 0 | - | 0 | 8 | True | True | explorex7 edit verify explore verify explore finish | agrees |
| c007-sqlparse-mut-022-r1 | sqlparse-mut-022 | reticle-journal | `model_call_limit` (budget) | rejected | 41/41, 0/450 | 0 | - | 9 | - | False | False | explorex20 | agrees |
| c007-sqlparse-mut-022-r2 | sqlparse-mut-022 | reticle-journal | `finish_requested` (finish) | accepted | 0/41, 0/450 | 0 | - | 0 | 15 | True | True | explorex3 reproduce explorex7 reproduce explorex2 edit verify finish | agrees |
| c007-sqlparse-mut-023-r1 | sqlparse-mut-023 | reticle-journal | `finish_requested` (finish) | accepted | 0/34, 0/456 | 0 | - | 0 | 13 | True | True | explorex9 reproduce explore reproduce edit verify finish | agrees |
| c007-sqlparse-mut-023-r2 | sqlparse-mut-023 | reticle-journal | `finish_requested` (finish) | accepted | 0/34, 0/456 | 0 | - | 0 | 14 | True | True | explorex7 reproduce explorex5 edit verify finish | agrees |
| c007-sqlparse-mut-024-r1 | sqlparse-mut-024 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 11 | True | True | explorex7 reproducex3 edit verify finish | agrees |
| c007-sqlparse-mut-024-r2 | sqlparse-mut-024 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 9 | True | True | explorex8 edit verify explore verifyx3 reproduce verify finish | agrees |
| c007-sqlparse-mut-025-r1 | sqlparse-mut-025 | reticle-journal | `finish_requested` (finish) | accepted | 0/1, 0/490 | 0 | - | 0 | 4 | True | True | explorex3 edit explore verify finish | agrees |
| c007-sqlparse-mut-025-r2 | sqlparse-mut-025 | reticle-journal | `finish_requested` (finish) | accepted | 0/1, 0/490 | 0 | - | 0 | 5 | True | True | explorex4 edit verify finish | agrees |
| c007-sqlparse-mut-032-r1 | sqlparse-mut-032 | reticle-journal | `model_call_limit` (budget) | rejected | 1/1, 0/490 | 0 | - | 0 | - | False | False | explorex14 reproducex6 | agrees |
| c007-sqlparse-mut-032-r2 | sqlparse-mut-032 | reticle-journal | `model_call_limit` (budget) | rejected | 1/1, 0/490 | 0 | - | 0 | - | False | False | explorex10 reproducex2 explorex2 reproducex2 explorex2 reproducex2 | agrees |
| c007-sqlparse-mut-033-r1 | sqlparse-mut-033 | reticle-journal | `finish_requested` (finish) | accepted | 0/43, 0/448 | 0 | - | 0 | 6 | True | True | explorex5 edit verify explore verifyx2 other finish | agrees |
| c007-sqlparse-mut-033-r2 | sqlparse-mut-033 | reticle-journal | `finish_requested` (finish) | accepted | 0/43, 0/448 | 0 | - | 0 | 17 | True | True | explorex11 reproduce explorex2 reproducex2 edit verify other finish | agrees |
| c007-sqlparse-mut-034-r1 | sqlparse-mut-034 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 4 | True | True | explorex3 edit verify finish | agrees |
| c007-sqlparse-mut-034-r2 | sqlparse-mut-034 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 3 | True | True | explorex2 edit verifyx2 finish | agrees |
| c007-sqlparse-mut-040-r1 | sqlparse-mut-040 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 3 | True | True | explorex2 edit verify explorex3 verify other finish | agrees |
| c007-sqlparse-mut-040-r2 | sqlparse-mut-040 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 4 | True | True | explorex3 edit explorex3 verify other finish | agrees |
| c007-sqlparse-mut-042-r1 | sqlparse-mut-042 | reticle-journal | `finish_requested` (finish) | accepted | 0/3, 0/488 | 1 | - | 0 | 12 | True | True | explorex9 reproduce explore edit verify other finish | agrees |
| c007-sqlparse-mut-042-r2 | sqlparse-mut-042 | reticle-journal | `finish_requested` (finish) | accepted | 0/3, 0/488 | 0 | - | 0 | 6 | True | True | explorex5 edit explore edit explore verifyx3 finish | agrees |
| c007-sqlparse-mut-043-r1 | sqlparse-mut-043 | reticle-journal | `finish_requested` (finish) | accepted | 0/11, 0/480 | 0 | - | 0 | 9 | True | True | explorex8 edit verifyx2 other finish | agrees |
| c007-sqlparse-mut-043-r2 | sqlparse-mut-043 | reticle-journal | `finish_requested` (finish) | accepted | 0/11, 0/480 | 0 | - | 0 | 8 | True | True | explorex7 edit explorex2 edit verify finish | agrees |
| c007-sqlparse-mut-044-r1 | sqlparse-mut-044 | reticle-journal | `finish_requested` (finish) | accepted | 0/3, 0/488 | 0 | - | 0 | 4 | True | True | explorex3 edit verifyx3 finish | agrees |
| c007-sqlparse-mut-044-r2 | sqlparse-mut-044 | reticle-journal | `finish_requested` (finish) | accepted | 0/3, 0/488 | 0 | - | 0 | 6 | True | True | explorex5 edit verify finish | agrees |
| c007-sqlparse-mut-046-r1 | sqlparse-mut-046 | reticle-journal | `finish_requested` (finish) | accepted | 0/4, 0/487 | 0 | - | 0 | 4 | True | True | explorex3 edit verifyx2 explorex2 finish | agrees |
| c007-sqlparse-mut-046-r2 | sqlparse-mut-046 | reticle-journal | `finish_requested` (finish) | accepted | 0/4, 0/487 | 0 | - | 0 | 5 | True | True | explorex4 edit verifyx2 explorex2 verify other finish | agrees |
| c007-sqlparse-mut-057-r1 | sqlparse-mut-057 | reticle-journal | `finish_requested` (finish) | rejected | 1/1, 0/490 | 0 | - | 0 | 15 | False | True | explorex9 reproduce explorex3 reproduce edit other finish | agrees |
| c007-sqlparse-mut-057-r2 | sqlparse-mut-057 | reticle-journal | `finish_requested` (finish) | rejected | 1/1, 0/490 | 0 | - | 0 | 11 | False | True | explorex7 reproduce explore reproduce edit explorex2 finish | agrees |
| c007-sqlparse-mut-060-r1 | sqlparse-mut-060 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 6 | True | True | explorex5 edit verify explore verifyx4 reproduce verify finish | agrees |
| c007-sqlparse-mut-060-r2 | sqlparse-mut-060 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 7 | True | True | explorex6 edit verifyx3 explore verifyx3 finish | agrees |
| c007-sqlparse-mut-061-r1 | sqlparse-mut-061 | reticle-journal | `finish_requested` (finish) | rejected | 15/15, 1/476 | 0 | - | 0 | 15 | True | True | explorex7 reproduce explorex5 reproduce edit verifyx2 edit finish | agrees |
| c007-sqlparse-mut-061-r2 | sqlparse-mut-061 | reticle-journal | `model_call_limit` (budget) | rejected | 2/15, 1/476 | 0 | - | 0 | 17 | True | False | explorex10 reproduce explore reproducex3 explore edit verify explore edit | agrees |
| c007-sqlparse-mut-073-r1 | sqlparse-mut-073 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 4 | True | True | explorex3 edit verify explorex2 other finish | agrees |
| c007-sqlparse-mut-073-r2 | sqlparse-mut-073 | reticle-journal | `finish_requested` (finish) | accepted | 0/2, 0/489 | 0 | - | 0 | 4 | True | True | explorex3 edit verify explore other finish | agrees |
| c007-sqlparse-mut-075-r1 | sqlparse-mut-075 | reticle-journal | `finish_requested` (finish) | accepted | 0/22, 0/469 | 0 | - | 0 | 5 | True | True | explorex4 edit explore verify other finish | agrees |
| c007-sqlparse-mut-075-r2 | sqlparse-mut-075 | reticle-journal | `finish_requested` (finish) | accepted | 0/22, 0/469 | 0 | - | 0 | 6 | True | True | explorex5 edit verify explore verify finish | agrees |
| c007-sqlparse-mut-076-r1 | sqlparse-mut-076 | reticle-journal | `finish_requested` (finish) | accepted | 0/26, 0/465 | 0 | - | 0 | 7 | True | True | explorex6 edit verify explorex2 verify finish | agrees |
| c007-sqlparse-mut-076-r2 | sqlparse-mut-076 | reticle-journal | `finish_requested` (finish) | accepted | 0/26, 0/465 | 0 | - | 0 | 10 | True | True | explorex5 reproducex3 explore edit verify explorex2 verify finish | agrees |

## The evolution set in S6 step-2 terms

Each task has two rollouts, one row per run:

| Task (kind) | Run | Verifier cause | Causal status | Mechanism | First edit | Verified before finish | Tests failing (f2p, p2p) |
|---|---|---|---|---|---:|---|---|
| 001 (contrastive) | r1 rejected | `fail_to_pass_failed` | `edit_outside_gold` | `edit_verified` | 13 | true | 1/1, 0/490 |
| | r2 accepted | `accepted` | `refetch_after_omission+edit_outside_gold` | `edit_verified` | 17 | true | 0/1, 0/490 |
| 022 (contrastive) | r1 rejected | `budget` | `refetch_after_omission` | `explore_only` | - | false | 41/41, 0/450 |
| | r2 accepted | `accepted` | `none` | `edit_verified` | 15 | true | 0/41, 0/450 |
| 032 (negative) | r1 rejected | `budget` | `none` | `reproduce_no_edit` | - | false | 1/1, 0/490 |
| | r2 rejected | `budget` | `none` | `reproduce_no_edit` | - | false | 1/1, 0/490 |
| 057 (negative) | r1 rejected | `fail_to_pass_failed` | `edit_outside_gold` | `edit_verified` | 15 | true | 1/1, 0/490 |
| | r2 rejected | `fail_to_pass_failed` | `edit_outside_gold` | `edit_verified` | 11 | true | 1/1, 0/490 |
| 061 (negative) | r1 rejected | `pass_to_pass_regression` | `none` | `edit_verified` | 15 | true | 15/15, 1/476 |
| | r2 rejected | `pass_to_pass_regression` | `none` | `edit_unverified` | 17 | false | 2/15, 1/476 |

What separates each pair, from reading the trajectories:

- **001, contrastive: how widely the run reproduced, not which file it edited.**
  - Both runs edited only `sqlparse/filters/reindent.py`. The gold file is `filters/others.py`, where the mutation
    flipped StripWhitespaceFilter's `depth == 0` check.
  - The statement's diff is truncated, so neither run could see the expected output.
  - r1 tried 6 inputs (#9, #11) and found an anomaly that is not the reported failure: `'select foo;\nselect bar'`
    gives three newlines. It edited `_split_statements` (#13), re-ran its own inputs (#14), and finished.
  - r2 tried about 20 inputs in five responses (#7-#14). One of them, a comment followed by an indented statement,
    exposed the extra blank line. r2 compensated for it in `process()` (#17), and the evaluator accepted that.
- **022, contrastive: running the library to get a traceback.**
  - r2 ran `sqlparse.format('select 1; select 2;', reindent=True)` at #12 and got the reported `TypeError` with a
    traceback into `token_next_by`. It read that frame (#13) and its caller `_next_token` (#14), fixed the negated
    `BETWEEN` condition (#15), checked the fix, and finished at #17.
  - r1 never ran library code; its only command was `pytest --collect-only`, which found no tests.
  - Instead r1 spent 20 responses on static searches for `+=`. 7 of them are hypothesis-driven reads (diagnose, by
    the adjudication below), and 9 calls re-read files the context policy had dropped.
- **032, negative: no triggering input, and no commitment to a fix.**
  - The statement gives only `ValueError: None is not in list` for "format invalid where clause".
  - Both runs searched for an input that raises it. r1 ran `python -c` over WHERE variants in 6 rounds; r2 wrote
    four `repro*.py` scripts. Neither found one, and neither edited.
  - r1's #18 named the right frame: `_process_where`, where a `None` `tidx` reaches `insert_before`. That is where
    the mutation removed an early-return guard. r1 spent its last 2 responses fuzzing instead of adding the guard.
  - r2 never opened `_process_where`.
- **057, negative: the same misattribution twice.**
  - Both runs "fixed" the same pre-existing quirk: a case-sensitive `AS` check in `group_functions`
    (`engine/grouping.py`).
  - The actual mutation is in `sql.py`: `Function.get_window` returns `tokens[-2]` instead of `tokens[-1]`. The
    statement gives only `AssertionError: assert False` for "grouping function".
  - Each run checked its quirk with `python -c` after the edit, saw pytest find no tests, and finished.
  - r2 read all of `sql.py` (#7) without flagging `get_window`.
- **061, negative: the right file, a regression in both runs, and one near miss.**
  - Both runs edited `_process_identifierlist` in `filters/reindent.py`, the gold file. Both broke
    `test_insert_values`.
  - The mutation dropped a `not` from `tlist.within(sql.Values)`, on the VALUES path.
  - r1 first spent #10-#13 on a wrong hypothesis about the CHANGELOG's value-caching change (4 diagnose responses).
    It then removed a `wrap_after > 0` guard (#15), restored half of it (#18), and finished. Its check passed on
    `select foo, bar`, but all 15 target tests still failed.
  - r2 made its first edit at #17 and its second at #20, its last response. 13 of the 15 target tests then passed,
    but nothing checked that final edit.

## The report's two-mechanism reading, checked

| Claim in the [card 007 report](E3-calibration-007-report.md) | Journal numbers | Verdict |
|---|---|---|
| Rejections by stop: 5 after `finish`, 3 at the budget | finish 4 (001-r1, 057-r1, 057-r2, 061-r1); budget 4 (022-r1, 032-r1, 032-r2, 061-r2) | Wrong. The report's own acceptance table lists 061-r2 as budget |
| Mechanism 1, a confident wrong fix (5 of 8): the model edits, sometimes in the wrong file, then finishes | 5 of 8 edited and were rejected; 4 of them finished; 3 of the 5 edited outside the gold file | Holds as "edited, rejected". The file does not separate the runs: 001-r2 was accepted with an edit only outside the gold file |
| 001-r1 and 061-r1 "finished without verification"; "ran pytest: no" | `verified_before_finish` true for 4 of 4 finishers (001-r1 #14, 057-r1 #15, 057-r2 #11, 061-r1 #18, all `python -c`) | Wrong by the schema. They verified, but only against their own reproduction, and in 3 of 4 (001-r1 and both 057 runs) the reported failure was never reproduced |
| 057: "pytest found no tests (hidden), finished anyway"; "treats no tests ran as a pass" | Pytest found no tests (exit 4 or 5) in 19 of 32 accepted and 4 of 8 rejected runs, and every such run also used ad hoc checks | Not specific to the failures. 057 is a misattribution: the same quirk "fixed" in both rollouts |
| 061: "right file, wrong fix" | `pass_to_pass_regression` in both runs (`test_insert_values`); target tests still failing: 15/15 (r1), 2/15 (r2) | Incomplete: a regression in both runs, and a near miss at the budget in r2 |
| Mechanism 2, budget exhaustion without an edit (3 of 8) | 022-r1, 032-r1, 032-r2 (2 tasks) | Holds. 022-r1 never ran library code (`explore_only`, 9 refetches); 032 ran code but found no triggering input |

The refined reading:
- **A: finishing on a self-chosen check** (4 runs, 3 tasks). The agent's check passed on inputs it chose, and the
  evaluator's target tests failed. When the statement carries no input (001's truncated diff, 057's `assert
  False`), such a check cannot reach the reported behaviour. This points at task completion detection: what the
  pre-finish rule should ask a check to cover.
- **B: no commitment within the budget** (3 runs on 2 tasks, plus the late edit of 061-r2, whose first edit came at
  response 17). This points at the agent loop, with a context symptom (refetches) in 022-r1.
- For scale: among rejected runs that edited, the median first edit is at response 15; among accepted runs, at
  response 6.

## Labels: rules and Jev on all 533 responses

- **Rules:** `label_phases.py label <runs> --labeller rules --labels labels/labels_c007_rules.jsonl`.
- **Jev:** `label <runs> --labeller jev --labels labels/labels_c007_jev.jsonl`. It uses the unchanged three-question
  request and reads the OpenRouter key from the environment, never writing it. Every record carries
  `questions_sha256` `c199d959aeda...` and the model `typesafe/jev-1.13-20260917`.
- **Agreement:** this set has no gold phase, so agreement is Jev against the rules (`label_phases.py develop`).

Responses: 533 in 40 runs. Jev = rules 488/533 (91.6%), Cohen's kappa 0.86.

| Phase | Rule | Jev | Both | Jev = rule, of rule | Specific agreement |
|---|---:|---:|---:|---:|---:|
| explore | 329 | 324 | 322 | 322/329 | 0.99 |
| reproduce | 50 | 53 | 48 | 48/50 | 0.93 |
| diagnose | 0 | 7 | 0 | 0/0 | 0.00 |
| edit | 41 | 23 | 23 | 23/41 | 0.72 |
| verify | 66 | 81 | 59 | 59/66 | 0.80 |
| finish | 36 | 44 | 36 | 36/36 | 0.90 |
| stuck | 0 | 1 | 0 | 0/0 | 0.00 |
| other | 11 | 0 | 0 | 0/11 | 0.00 |

Confusion (rows: rule phase; columns: Jev phase):

| Rule \ Jev | explore | reproduce | diagnose | edit | verify | finish | stuck | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| explore | 322 | 1 | 4 | 0 | 1 | 0 | 1 | 0 |
| reproduce | 0 | 48 | 2 | 0 | 0 | 0 | 0 | 0 |
| diagnose | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| edit | 0 | 0 | 0 | 23 | 18 | 0 | 0 | 0 |
| verify | 2 | 4 | 1 | 0 | 59 | 0 | 0 | 0 |
| finish | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 |
| stuck | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| other | 0 | 0 | 0 | 0 | 3 | 8 | 0 | 0 |

Yes/no questions against the rule facts (yes = Jev's value >= 0.5):

| Question | Rule yes | Jev yes when rule yes | Lowest Jev value when rule yes | Rule no | Jev yes when rule no | Highest Jev value when rule no |
|---|---:|---:|---:|---:|---:|---:|
| edited_existing_source | 41 | 41 | 0.920 | 492 | 6 | 0.810 |
| verified_after_edit | 87 | 77 | 0.240 | 446 | 28 | 0.950 |

Where Jev and the rules differ:

- **Edit labelled verify (18):** the response edits and then runs a check. The schema's precedence (finish > edit >
  verify) gives edit; Jev gives verify.
- **Other labelled finish or verify (11):** text-only summaries written just before the `finish` call, because the
  CLI adapter ends a turn with text. The schema says `other`; Jev reads the narration.
- **Verify labelled reproduce (4):** a scratch script or `python -c` run after the edit, which the schema calls
  verify.
- **Verify labelled explore (2):** `print(sqlparse.__file__)` and `pip download`. Here Jev is arguably right; see the
  known limits above.
- **Explore labelled reproduce or verify (2):** `pytest --collect-only`. Jev agrees with the old rule.
- **Explore labelled stuck (1):** 022-r1 #20, a refetch. Jev cannot see omissions.
- **Labelled diagnose (7):** see the next section.
- **Yes/no questions:**
  - `edited_existing_source` finds all 41 rule edits. Its 6 false positives are all finish or verify responses that
    narrate an edit.
  - `verified_after_edit` misses 10 rule verifications. 8 of those are verify responses whose only command
    exercised nothing: pytest on the test-less workspace, or a script that could not be opened. Jev scores "a check
    ran"; the rule scores "a check was attempted".
  - 26 of its 28 false positives are finish or summary responses that narrate checks. This is the held-out set's
    narration error, now at scale.

## Diagnose: candidates, adjudication, and Jev's precision and recall

**The adjudicator is Claude Opus 5.5, the mining subagent, standing in for a human. No human labelled these.**
[`labels/diagnose-devset.jsonl`](labels/diagnose-devset.jsonl) is a **development set, not a held-out one**. Its
header record says so and states the conventions:

- **Stated hypothesis:** a response is diagnose only if text names specific code as the suspected cause.
- **Calls:** its calls must read or search that code. A search that only finds a definition counts as locating, as
  in the held-out adjudication.
- **Carry:** a response without text inherits an earlier hypothesis only through an unbroken chain of responses
  that pursue it.
- **Post-edit review:** re-reading code after an edit counts as review, not diagnose.
- **Precedence:** the schema's phase precedence applies.
- **Strength:** "clear" when the response's own text asserts the cause and its calls read that code; otherwise
  "borderline".

Scope: the file lists all 329 rule-explore responses, plus the 3 flagged responses in other phases. That makes all
40 runs complete for diagnose under these conventions. The 10 evolution-set runs were read response by response. In
the other 30 runs, every explore response with text was read, and every explore response without text was judged
from the latest earlier text.

Every response whose Jev diagnose probability was >= 0.3 (a threshold fixed before the pass), with the adjudication:

| Run | # | Rule | Jev | Jev's diagnose probability | Adjudicated | Note |
|---|---:|---|---|---:|---|---|
| c007-sqlparse-mut-033-r2 | 13 | explore | diagnose | 0.620 | diagnose | borderline: investigates _get_offset/_flatten_up_to_token as the source of the wrong offset seen in #12; reads reindent.py 1-60 |
| c007-sqlparse-mut-076-r2 | 7 | reproduce | diagnose | 0.610 | reproduce | runs python -c on the token pipeline before any edit; reproduce outranks diagnose |
| c007-sqlparse-mut-061-r1 | 10 | explore | diagnose | 0.590 | diagnose | clear: the CHANGELOG's value-caching change 'looks suspicious as the regression source'; reads Token/TokenList value handling |
| c007-sqlparse-mut-002-r1 | 11 | reproduce | diagnose | 0.490 | reproduce | runs python -c before any edit; reproduce outranks diagnose |
| c007-sqlparse-mut-043-r2 | 7 | explore | explore | 0.480 | diagnose | clear: group_as's valid_prev 'lacks a None check'; reads _group and normalized to confirm |
| c007-sqlparse-mut-022-r1 | 15 | explore | diagnose | 0.460 | diagnose | borderline: narrows the None += int bug to offset/indent in OffsetFilter and reindent.py and reads them; hedged ('might be None') |
| c007-sqlparse-mut-057-r2 | 12 | explore | diagnose | 0.450 | explore | no text; re-reads the lines edited in #11 (post-edit review) |
| c007-sqlparse-mut-061-r2 | 3 | explore | explore | 0.450 | explore | no text and no earlier hypothesis; first read of _process_identifierlist |
| c007-sqlparse-mut-033-r2 | 11 | explore | explore | 0.430 | explore | locates code from the failing test's description; no suspected cause |
| c007-sqlparse-mut-044-r2 | 3 | explore | explore | 0.430 | explore | no text and no earlier hypothesis; the suspect is named only in #5 |
| c007-sqlparse-mut-024-r1 | 12 | verify | diagnose | 0.410 | verify | runs python -c after the edit; verify outranks diagnose (the text narrates the fix) |
| c007-sqlparse-mut-024-r2 | 5 | explore | explore | 0.400 | explore | no text; no earlier hypothesis (#2 looks for tests) |
| c007-sqlparse-mut-023-r2 | 13 | explore | explore | 0.360 | explore | no text; #9 is locating (tests, Token.match) |
| c007-sqlparse-mut-061-r1 | 11 | explore | explore | 0.360 | diagnose | clear: group_tokens/value caching are 'prime suspects'; searches group_tokens and grp.value |
| c007-sqlparse-mut-044-r2 | 5 | explore | explore | 0.340 | diagnose | clear: the python/else branches in formatter.py 193-202 'appear to have been swapped'; reads OutputPythonFilter to confirm |
| c007-sqlparse-mut-022-r1 | 13 | explore | explore | 0.330 | explore | no text; #11 says to stop guessing; no suspect |
| c007-sqlparse-mut-046-r1 | 8 | explore | explore | 0.300 | explore | narrates the applied fix and re-reads the edited lines (post-edit review) |
| c007-sqlparse-mut-076-r2 | 5 | explore | explore | 0.300 | diagnose | borderline: checks is_keyword and token_next_by/token_matching 'to see if a regression broke FROM keyword splitting'; reads them |

Adjudicated: 332 responses; 40 runs adjudicated completely (533 responses). True diagnose: 7 clear, 29 clear or borderline.

| Truth | Jev says diagnose when | Flagged | True among flagged | Precision | Recall (complete runs) |
|---|---|---:|---:|---:|---:|
| clear only | Jev's choice is diagnose | 7 | 1 | 1/7 = 0.14 | 1/7 = 0.14 |
| clear only | diagnose probability >= 0.3 | 18 | 4 | 4/18 = 0.22 | 4/7 = 0.57 |
| clear or borderline | Jev's choice is diagnose | 7 | 3 | 3/7 = 0.43 | 3/29 = 0.10 |
| clear or borderline | diagnose probability >= 0.3 | 18 | 7 | 7/18 = 0.39 | 7/29 = 0.24 |

The 29 adjudicated diagnose responses:

| Run | # | Strength | Rule | Jev | Jev's diagnose probability | Hypothesis stated in |
|---|---:|---|---|---|---:|---|
| c007-sqlparse-mut-001-r1 | 12 | borderline | explore | explore | 0.050 | #12 |
| c007-sqlparse-mut-002-r1 | 4 | borderline | explore | explore | 0.050 | #3 |
| c007-sqlparse-mut-002-r1 | 6 | borderline | explore | explore | 0.020 | #6 |
| c007-sqlparse-mut-002-r1 | 7 | borderline | explore | explore | 0.010 | #6 |
| c007-sqlparse-mut-002-r1 | 8 | borderline | explore | explore | 0.020 | #6 |
| c007-sqlparse-mut-022-r1 | 5 | borderline | explore | explore | 0.260 | #5 |
| c007-sqlparse-mut-022-r1 | 7 | clear | explore | explore | 0.220 | #7 |
| c007-sqlparse-mut-022-r1 | 15 | borderline | explore | diagnose | 0.460 | #15 |
| c007-sqlparse-mut-022-r1 | 16 | borderline | explore | explore | 0.050 | #15 |
| c007-sqlparse-mut-022-r1 | 18 | borderline | explore | explore | 0.160 | #17 |
| c007-sqlparse-mut-022-r1 | 19 | clear | explore | explore | 0.240 | #19 |
| c007-sqlparse-mut-022-r1 | 20 | borderline | explore | stuck | 0.180 | #20 |
| c007-sqlparse-mut-023-r1 | 4 | borderline | explore | explore | 0.130 | #3 |
| c007-sqlparse-mut-023-r2 | 4 | borderline | explore | explore | 0.090 | #3 |
| c007-sqlparse-mut-023-r2 | 6 | borderline | explore | explore | 0.100 | #5 |
| c007-sqlparse-mut-032-r2 | 13 | borderline | explore | explore | 0.010 | #11 |
| c007-sqlparse-mut-032-r2 | 14 | borderline | explore | explore | 0.210 | #11 |
| c007-sqlparse-mut-032-r2 | 18 | borderline | explore | explore | 0.160 | #18 |
| c007-sqlparse-mut-033-r2 | 4 | borderline | explore | explore | 0.090 | #4 |
| c007-sqlparse-mut-033-r2 | 13 | borderline | explore | diagnose | 0.620 | #13 |
| c007-sqlparse-mut-043-r2 | 7 | clear | explore | explore | 0.480 | #7 |
| c007-sqlparse-mut-044-r2 | 5 | clear | explore | explore | 0.340 | #5 |
| c007-sqlparse-mut-046-r1 | 3 | clear | explore | explore | 0.140 | #3 |
| c007-sqlparse-mut-057-r2 | 6 | borderline | explore | explore | 0.020 | #5 |
| c007-sqlparse-mut-061-r1 | 10 | clear | explore | diagnose | 0.590 | #10 |
| c007-sqlparse-mut-061-r1 | 11 | clear | explore | explore | 0.360 | #11 |
| c007-sqlparse-mut-061-r1 | 12 | borderline | explore | explore | 0.080 | #11 |
| c007-sqlparse-mut-061-r1 | 13 | borderline | explore | explore | 0.130 | #11 |
| c007-sqlparse-mut-076-r2 | 5 | borderline | explore | explore | 0.300 | #5 |

Reading:

- **How many real diagnose cases there are:** 7 clear and 22 borderline, in 12 of the 40 runs; the held-out set has
  none. 13 of the 22 borderline cases are carried: the response has no text, and the hypothesis was stated earlier.
- **Precision:** at probability >= 0.3, Jev's precision is 4/18 on clear cases and 7/18 counting borderline ones.
  Its 11 false positives break down as:
  - 3 break the precedence: the response ran `python -c`, so reproduce or verify outranks diagnose.
  - 2 are post-edit re-reads.
  - 5 are first reads with no stated hypothesis at all. 4 of these read the code that was later fixed, so Jev may be
    judging the code rather than the agent's intent.
  - 1 locates code from the failing test's description.
- **Recall:** 4/7 on clear cases and 7/29 on all of them. By source, Jev catches 7/16 own-text cases and 0/13
  carried cases. Its input renders earlier responses only as call summaries, so a hypothesis stated earlier is
  invisible to it.
- **Jev's own diagnose choice is worse:** it flags 7 responses, of which 1 is clear and 3 count if borderline cases
  are included.
- **Next steps, to be developed on this set only:**
  - Show earlier responses' text in the state. That renderer change must be measured on the held-out set without
    tuning on it.
  - Add the two yes/no questions proposed in [jev-agreement.md](labels/jev-agreement.md): "does the text state a
    hypothesis about the cause?" and "do the calls read the code it names?".
  - Tell the phase question that a response containing a command is reproduce or verify, not diagnose.
  - Until then, keep the rules for every phase, and use Jev's diagnose probability only to flag responses for a
    human look.

## Evidence bundles

[`evidence-bundles-c007.json`](evidence-bundles-c007.json) holds one bundle per **minable** cluster (5). The
accepted clusters are not weaknesses. Their runs appear inside the bundles as contrastive partners, with each
partner's signature, first edit, and phases.

Each bundle holds:
- the size, the distinct tasks, and one representative run per task;
- the symptoms: the members' rule facts, test counts, and phase strings. Gold file names are left out;
- contrastive and negative pairs;
- the module, primary from how the members stopped and secondary from the flags (`module_for`);
- an empty `prior_attempts`.

| # | Signature | Size / tasks | Pairs | Module (primary; secondary) |
|---:|---|---|---|---|
| 1 | `fail_to_pass_failed / edit_outside_gold / edit_verified` | 3 / 2 | contrastive 001-r1 vs 001-r2; negative 057 | task completion detection |
| 2 | `budget / none / reproduce_no_edit` | 2 / 1 | negative 032 | agent loop |
| 3 | `budget / refetch_after_omission / explore_only` | 1 / 1 | contrastive 022-r1 vs 022-r2 | agent loop; context management |
| 4 | `pass_to_pass_regression / none / edit_unverified` | 1 / 1 | negative 061 | agent loop |
| 5 | `pass_to_pass_regression / none / edit_verified` | 1 / 1 | negative 061 | task completion detection |

No proposals are made here. With 1-2 tasks per cluster, any proposal aimed at one cluster rests on at most two
tasks. That agrees with the card's own verdict: the set is too small to separate harnesses.

## Cost and reproduction

Jev: 533 calls, all succeeding on the first attempt; $0.058118; 1,383,751 input tokens; 105 s wall, from 03:25:05 to
03:26:50 UTC. No Claude or Anthropic call and no live run was made.

```
python experiments/session_harness/label_phases.py label <40 run dirs> --labeller rules --labels experiments/session_harness/labels/labels_c007_rules.jsonl
OPENROUTER_API_KEY=... python experiments/session_harness/label_phases.py label <40 run dirs> --labeller jev --labels experiments/session_harness/labels/labels_c007_jev.jsonl
python experiments/session_harness/label_phases.py develop --rules experiments/session_harness/labels/labels_c007_rules.jsonl \
  --jev experiments/session_harness/labels/labels_c007_jev.jsonl --devset experiments/session_harness/labels/diagnose-devset.jsonl
```

The run directories must contain `sessions/`. On this machine, only the `wt/s6a-calibration` worktree has the
card-007 journals.

## Not done, and gaps in the journal

- **No proposals and no human labels.** The diagnose adjudication is the mining agent's, and its conventions are
  judgement calls. The 22 borderline cases are the soft part; the clear-only numbers are the safer ones to quote.
- **No Jev question was changed, and no second Jev pass was run.** Determinism was already measured on the held-out
  set. No threshold was chosen: 0.3 was fixed before the pass, and the 0.5 yes/no cut comes from the held-out
  report.
- **Non-explore rule phases were not re-adjudicated**, beyond the 3 Jev-flagged responses and the disagreements
  listed above.
- **Gaps in the journal:**
  - Gold file names still come from the task file.
  - Neither the model nor the miner can see the reported failure's actual input or whether a reproduction matched
    it; only the hidden tests hold it. So "never reproduced the reported failure" comes from reading the
    trajectories, not from a rule.
  - The context manifests name omitted transcript units, not calls. The mapping unit k = response k + 1 is a
    convention, checked here but not stated in any field.
  - No field needed for the signatures was missing.

Provenance: analysis, adjudication and text by a subagent (Claude Opus 5.5) in this repository's worktree on
2026-09-28; the orchestrating session verified the label counts, the rule-versus-Jev agreement, the flagged-response
count and the bundle sizes from the committed files before committing this report.
