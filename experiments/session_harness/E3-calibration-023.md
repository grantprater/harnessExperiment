# E3 calibration 023: the second (boltons) mutation bank, near-transfer baseline

Date: 2026-09-28  
Status: proposed; awaiting owner approval (then set `cards/023.json` status to running). Not run.  
Stage: S6 near-transfer. Machine-readable card: [`cards/023.json`](cards/023.json). Bank:
[`tasks.boltons.json`](../mutation_tasks/tasks.boltons.json) (63 tasks), with its
[generation log](../mutation_tasks/generation_log.boltons.json) and
[Linux cross-check](../mutation_tasks/linux_check.boltons.json). The section "The bank" below describes it.

## Purpose

Harness changes are selected on sqlparse repair tasks (cards 007-020). This card calibrates the incumbent on a
second codebase so that a later treatment card can ask whether a change selected on sqlparse carries over. boltons
is a utility grab-bag rather than a parser. The bank comes from the same generator, with the same operators, filters
and statement template, at a pinned commit.

## Hypothesis

A capable model succeeds on some boltons mutation tasks and fails on others under the incumbent, so some of the 20
tasks land in the 30-70% zone. The acceptance rate may differ from card 007's 0.80. It is reported per
`fail_to_pass` size, because card 007's difficulty sat in single-test tasks, and 23 of this bank's
63 tasks have a single failing test.

## Design (card 007's, on card 019's backend)

- **Selection.** 20 tasks from `tasks.boltons.json`, chosen by
  [`select_calibration_tasks.py`](select_calibration_tasks.py)
  `--seed 23 --card E3-calibration-023 --shortfall redistribute`. This is card 007's rule: drop tasks whose statement
  names the mutated function, then 3-4 tasks per mutation kind with distinct `fail_to_pass` sets. It carries one
  amendment, explained under "Selected tasks". The selection was recorded before any run in
  [`E3-calibration-023-tasks.json`](E3-calibration-023-tasks.json).
- **Runs.** 2 rollouts, 40 runs in total, rollout-major. One runner invocation per task and rollout, named
  `c023-<task>-r<n>`.
- **Arm.** Runner v8, `--client claude-cli` with model `claude-sonnet-5` (pinned), `pressure-recent-v3`,
  `reticle-tools-v3`, repeat guard off.
- **Backend.** Trusted-local in the cloud VM (`isolation: vm-sandbox`), CLI 2.1.284, as in card 019.
- **Reply recovery.** `--cli-reply-recovery lenient-json+second-turn-on-retry`, as in card 020.
- **Per-run budgets (card 007's).** 20 responses, 24 attempts, 1,200 active seconds, 80,000 context bytes, 4,096
  max tokens, 600 s pytest timeout, 3,600 s invocation wall limit.
- **Retries and stops.** At most 2 retries per invocation, with 60 s and 300 s backoff. 3 consecutive failures
  stop the campaign. A spend guard stops it at $40 CLI list price, as in card 019.
- **Controls.** Gold and noop on ``boltons-mut-010`` and ``boltons-mut-001``, run first on the VM. They already passed on the host;
  see "Evidence before approval".

## Known differences from cards 007 and 019

| | Card 007 | Card 019 | Card 023 |
|---|---|---|---|
| bank | sqlparse, 76 tasks | same as 007 | boltons, 63 tasks (`boltons-mut-*`) |
| backend | OCI image on the host | trusted-local, cloud VM | trusted-local, cloud VM |
| model | `sonnet` alias | `claude-sonnet-5`, pinned | `claude-sonnet-5`, pinned |
| CLI reply recovery | off (adapter v2) | off | `lenient-json+second-turn-on-retry` (adapter v3), as card 020 |
| visible checks | none (the tests are hidden) | none | boltons modules carry doctests, which the model can run (`python -m doctest`, `pytest --doctest-modules boltons`); they are not part of acceptance |

The protocol hash contains each task's contract and the VM's task-interpreter path, so `--plan` on the VM prints the
hashes the runs must record. It is not comparable with any sqlparse card's hash.

## Measurements

Card 007's measurements:

- **Per run:** accepted, stop reason, responses, attempts, tool calls, active and wall seconds, tokens, first edit,
  rejected calls, repeat flags, edits in the gold files, verification before finish.
- **Per campaign:** acceptance with a 95% interval, per-task outcomes, outcome distribution, evolution set, and
  acceptance by mutation kind and by `fail_to_pass` size.

Additionally, for each run, whether the model ran the library's doctests. This comes from the trajectory review, not
from the evaluator.

## What counts

Calibration, not a promotion. The card passes if all 40 runs complete with evidence and at least 5 tasks are
contrastive (1/2).

If it fails, the report gives the distribution, and card 010's difficulty decision applies to both banks. Card 010's
difficulty arms are a separate decision: the statements are not tuned on these tasks.

After the card, these 20 tasks are held-in for near-transfer work. The bank's other tasks stay fresh. A near-transfer
treatment card then pairs the incumbent and the sqlparse-selected treatment on this bank's evolution set, within one
card and one environment.

## Fast stops

Plan section 5.3, card 007's rules and card 019's cloud rules apply:

- A `model_pin_violation` stops the campaign.
- So do a CLI auth error and an isolation failure.
- So does the spend guard at $40 list price.

Trusted-local gives the model's commands the VM's filesystem and network. The trajectory review therefore checks every
run for:

- reads outside the workspace, notably `.runtime/bug-mining/repos/boltons`, which holds the healthy code;
- `pip install boltons` or fetches of upstream boltons.

Any such run is an authority escape.

## Evidence before approval

Everything below was measured on the Windows host, with no model call.

**Generation.** A 5-candidate trial (3 kept) ran first, then 100 candidates: 63 kept, 33 survived, 3 collection
errors, 1 too destructive. The two generator gold checks (`boltons-mut-001`, `-002`) passed.

**Linux cross-check.**
[`check_linux.py`](../mutation_tasks/check_linux.py) rebuilt every task's mutated tree and ran it in the pinned image
`localhost/reticle-p6-task:py313-v1` (id `8b74015e5079`), with `podman --cpus 1 --network none`, one container at a
time. Result: **63/63**. The failing set equalled `fail_to_pass` in every task, and every `pass_to_pass` test
passed. This matters because the cloud VM is Linux and the bank was generated on Windows.

**Controls.** Gold and noop ran with `run_pilot.py --arm pressure-recent-v3` on `boltons-mut-001`, `-010`, `-027`,
`-045` and `-063`. Their `fail_to_pass` sizes are 1, 4, 1, 44 and 14. These are runs `br-control-{gold,noop}-{local,oci}`
under `experiments/p6_pilot/runs/`.

| Backend | Gold | Noop | Tests seen |
|---|---|---|---|
| trusted-local (host, Windows) | 5/5 accepted | 5/5 rejected (fail-to-pass fail, pass-to-pass pass) | 510 |
| OCI (`8b74015e5079`) | 5/5 accepted | 5/5 rejected (same) | 510 |

- On trusted-local, pytest exits 1 even under gold. The cause is the one excluded test, which fails on Windows; the
  evaluator does not expect it. Under OCI, gold exits 0.
- The OCI backend passes `--memory 512m` and `--pids-limit 128` but no `--cpus` flag. The runner was not changed, so
  each evaluation there was one single-process pytest.

**Workspaces (noop runs, trusted-local).** In all 5, `tests/` was absent. All 88 files and directories carried one
modification time, the commit time, so no timestamp marks the mutated file (materializer `mutation-workspace-v2`).

## The bank

**Source.** boltons (BSD-3, 33 modules, 17.7k lines, no runtime dependencies) at `45a251181fba`, the fix commit of
P6 task boltons-475. Its suite needs only pytest.

**Candidates considered:**

| Candidate | Outcome |
|---|---|
| boltons | chosen |
| marshmallow | rejected: two test ids embed the wall-clock time, so ids differ between runs. A 12-candidate trial classified every candidate `missing_tests`, and the evaluator would score those two tests `missing`. |
| click | rejected: `tests/test_deprecations.py` needs installed click metadata, which conflicts with the task interpreter's no-healthy-copy rule. It is also terminal-heavy, so Windows and Linux would diverge. |
| more-itertools | not chosen: two modules, and a 20 s suite, 3x boltons' |
| cachetools, humanize | not chosen: about 1.6k lines each |
| pyparsing, tomlkit, markdown-it-py, packaging | excluded as parsers; packaging is also installed in the task interpreter |

**Generator.** [`generate.py`](../mutation_tasks/generate.py) `--repo boltons`, with the entry in
[`repos.json`](../mutation_tasks/repos.json). The mutation operators, the keep filters and the statement template and
leak checks are sqlparse's.

**One test excluded.** `tests.test_jsonutils::test_reverse_iter_lines` is platform-dependent: it fails on Windows
and passes on Linux, because it compares a text-mode read of an LF file with a binary read. It is left out of every
task's `fail_to_pass` and `pass_to_pass`.

**Departure: `prefilter_unexecuted` (boltons only; off for sqlparse).**

- *Why:* without it, a 20-candidate trial kept 9 (45%), which projects to about 45 tasks from 100 candidates.
- *What it does:* before scheduling, it drops a candidate whose smallest enclosing statement never executed in one
  probed healthy run (`sys.monitoring` LINE events). Such a mutant cannot change any test outcome, so the prefilter
  changes the sample, not the keep rule.
- *Effect on the pool:* it dropped 558 of 2,230 candidates.
- *Soundness check on the no-prefilter trial:* it would have kept all 9 kept candidates and dropped 6 of the 10
  survivors.

**Yield by kind (tried → kept):** compare_flip 17 → 8, negate_condition 17 → 11, drop_not 17 → 16, off_by_one
17 → 9, remove_guard 16 → 6, swap_branches 16 → 13.

**`fail_to_pass` sizes:**

| Failing tests | 1 | 2-3 | 4-10 | 11-25 | 26+ |
|---|---|---|---|---|---|
| boltons (63 tasks) | 23 | 18 | 17 | 3 | 2 |
| sqlparse (76 tasks) | 20 | 21 | 13 | 13 | 9 |

Median 3, mean 4.5, maximum 44. More single-test tasks than sqlparse (37% against 26%): boltons' tests are focused
per function. Nothing was tuned.

**Statements (same template):**

- `statement_names_mutated_function` is true for 26/63 (sqlparse 3/76), because boltons' test names are mostly the
  function under test.
- 4 statements dropped the failure message after a leak.
- 9 messages are bare `assert ...` lines.

**Correlation:**

- 53 distinct failing sets. 9 tasks fail only `tests.test_setutils::test_complement_set`.
- Pairs `-003`/`-054` and `-020`/`-035` share failing sets.
- Pairs `-005`/`-028` and `-020`/`-035` have identical statements.
- `-011` and `-016` mutate the same line (`strutils.py`:1208), with different failing sets. Both are selected below.

**Visible doctests.** boltons docstrings carry doctests. They stay in the workspace, and the model may run them;
acceptance ignores them.

**Backends:**

- *Cloud.* [`setup_cloud.sh`](../cloud/setup_cloud.sh) clones boltons at `45a2511` next to sqlparse. Its readiness
  check fails if the task interpreter imports either package. `bugs-venv.requirements.txt` needs no new package.
  None of this has run on a VM yet.
- *Host OCI.* The existing image suffices; no new tag is needed.

**Weaknesses:**

- The source is public: GitHub, PyPI, likely model memory.
- On trusted-local, the healthy clone under `.runtime` and `pip install boltons` are escape routes that the review
  must check.
- Each candidate ran once on Windows and once on Linux, and no more.
- The 1,572 prefiltered candidates that were never tried remain unused.
- Survivors were not classified.

## Reporting

`experiments/session_harness/E3-calibration-023-report.md` (run_card skeleton, with "Spend and time"); evidence on a
`cloud-results-023` branch.

## Selected tasks

Recorded 2026-09-28, before any run. The selector ran once, with seed 23 (the card's number).

[`E3-calibration-023-tasks.json`](E3-calibration-023-tasks.json). Bank: `tasks.boltons.json`, sha256 of its LF
content `d958410c25897fb4048736a0292b1a1b6029a65c0c04b8ce7568784a8d04eb5e`.

**Amendment to card 007's rule (`--shortfall redistribute`).**

1. The rule drops the 26 tasks whose statement names the mutated function. That leaves 37 eligible tasks with 32
   distinct `fail_to_pass` sets.
2. Only one eligible `remove_guard` task remains (`boltons-mut-060`), so card 007's strict quotas cannot be met. The
   seed-23 quotas were compare_flip 4, drop_not 3, negate_condition 4, off_by_one 3, remove_guard 3, swap_branches 3.
3. Under the amendment, remove_guard keeps its 1. Its 2 free slots go one at a time, in a seeded order, to kinds that
   filled their quota; they went to off_by_one and swap_branches. The same shuffled list is then walked again.

The final quotas are compare_flip 4, drop_not 3, negate_condition 4, off_by_one 4, remove_guard 1 and swap_branches 4.
The redistribution is recorded in the selection file. Without the flag, the selector still reproduces card 007's
selection byte for byte.

| Task | Kind | Site | `fail_to_pass` |
|---|---|---|---|
| `boltons-mut-010` | drop_not | `boltons/setutils.py`:164 | 4 |
| `boltons-mut-011` | swap_branches | `boltons/strutils.py`:1208 | 3 |
| `boltons-mut-015` | drop_not | `boltons/debugutils.py`:189 | 6 |
| `boltons-mut-016` | off_by_one | `boltons/strutils.py`:1208 | 5 |
| `boltons-mut-021` | off_by_one | `boltons/urlutils.py`:298 | 19 |
| `boltons-mut-023` | swap_branches | `boltons/listutils.py`:176 | 8 |
| `boltons-mut-027` | off_by_one | `boltons/cacheutils.py`:867 | 1 |
| `boltons-mut-029` | compare_flip | `boltons/iterutils.py`:642 | 1 |
| `boltons-mut-031` | swap_branches | `boltons/cacheutils.py`:516 | 1 |
| `boltons-mut-033` | negate_condition | `boltons/iterutils.py`:802 | 2 |
| `boltons-mut-034` | drop_not | `boltons/dictutils.py`:380 | 6 |
| `boltons-mut-044` | compare_flip | `boltons/setutils.py`:240 | 2 |
| `boltons-mut-045` | negate_condition | `boltons/urlutils.py`:218 | 44 |
| `boltons-mut-047` | off_by_one | `boltons/formatutils.py`:134 | 3 |
| `boltons-mut-048` | swap_branches | `boltons/funcutils.py`:820 | 8 |
| `boltons-mut-049` | negate_condition | `boltons/urlutils.py`:726 | 4 |
| `boltons-mut-056` | compare_flip | `boltons/urlutils.py`:925 | 6 |
| `boltons-mut-057` | negate_condition | `boltons/setutils.py`:856 | 1 |
| `boltons-mut-060` | remove_guard | `boltons/strutils.py`:1233 | 1 |
| `boltons-mut-062` | compare_flip | `boltons/iterutils.py`:648 | 4 |

By `fail_to_pass` size: 1 test 5 tasks; 2-3 tests 4; 4-10 tests 9; 11+ tests 2. Controls: `boltons-mut-010` (in the
set) and `boltons-mut-001` (not in the set; one of the 9 `test_complement_set` tasks).
