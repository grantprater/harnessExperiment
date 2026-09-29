# Mutation-generated repair tasks: prototype report

Status: prototype. 76 validated tasks from one source state. They have not been run with any
model, and the P6 runner cannot run them yet (see weakness 1).

## What was built

- [generate.py](generate.py) starts from the healthy sqlparse state at the `sqlparse-865` fix
  commit (`f66d12c`). It finds candidate mutations in `sqlparse/**/*.py` (never tests) with
  `ast`. The kinds are: comparison flips (`==`/`!=`, `<`/`<=`, `>`/`>=`), negating an
  `if`/`while` condition, dropping a `not`, off-by-one on integer literals in subscripts, slices
  and `range()`, deleting an early-return guard, and swapping if/else bodies or conditional
  expression branches. Each candidate is one text edit, recorded as a unified diff.
- Each candidate gets a fresh `git archive` export, and the diff is applied with `git apply`,
  so the recorded patch is itself tested. The whole suite then runs once: single process, idle
  priority, thread variables set to 1. A candidate is kept only if all of these hold:
  - at least one baseline-passing test fails;
  - at least 90% of baseline-passing tests still pass;
  - no collection errors, missing tests or timeout.
- The gold patch is the reverse diff.
- The statement is a template. It uses the humanized failing-test names, capped at three with a
  count of the rest, and the first line of the first failure message. That message is cleaned
  of file paths, `line N` and test ids. A leak check rejects any statement that contains the
  mutated file, the line or a test id. It fired 0 times.
- [tasks.mutations.json](tasks.mutations.json) has the 76 tasks.
- [generation_log.json](generation_log.json) has every candidate's verdict and timing, plus the
  gold checks.

Command:
`python experiments/mutation_tasks/generate.py --work-dir <scratch> --max-candidates 100 --budget-seconds 660 --gold-check 2`

- `generate.py` itself ran under `.runtime/test-venv` and needs only the standard library.
- Suites ran under the P6 task interpreter `.runtime/bugs-venv` (Python 3.13.15, pytest 9.1.1).
- pytest-timeout is not installed, so each run had a subprocess timeout of 60 s, which is
  max(60, 10 × baseline).
- The existing bug-mining clone was reused; nothing was cloned or fetched.
- Wall time was 553.8 s in total: 535.2 s in the candidate loop, the rest in the baseline and
  gold checks.

## Yield

Baseline suite: 491 pass, 2 skip (xfail), 3.7 s. The candidate pool was 531, with 0 invalid
after the edit:

| Kind | compare_flip | negate_condition | drop_not | off_by_one | remove_guard | swap_branches |
|---|---|---|---|---|---|---|
| Candidates in the pool | 98 | 250 | 33 | 78 | 17 | 55 |

Sampling was a seeded shuffle within each kind (seed 865), then round-robin across kinds. The
100-candidate cap stopped the loop, so 431 candidates were never tried.

| Kind | Tried | Kept | Survived | Too destructive | Timeout | Mean s/candidate |
|---|---|---|---|---|---|---|
| compare_flip | 17 | 12 | 4 | 0 | 1 | 6.67 |
| negate_condition | 17 | 11 | 0 | 6 | 0 | 3.84 |
| drop_not | 17 | 13 | 0 | 3 | 1 | 7.19 |
| off_by_one | 17 | 13 | 3 | 0 | 1 | 6.65 |
| remove_guard | 16 | 13 | 2 | 1 | 0 | 4.06 |
| swap_branches | 16 | 14 | 1 | 1 | 0 | 3.52 |
| **Total** | **100** | **76** | **10** | **11** | **3** | **5.35** |

Rejections by reason:

- **Survived: 10.** No test failed; mean 3.1 s each.
- **Too destructive: 11.** Pass fractions ranged from 0.075 to 0.841; mean 6.2 s each.
- **Timeout: 3.** Each took 60.2 s. Together they used 180.5 s, 34% of the loop.
- **Zero each:** whole suite failing, collection error, missing tests, statement leak.

Kept candidates averaged 3.36 s.

## fail_to_pass sizes

Out of 491 baseline-passing tests:

| Failing tests | 1 | 2-3 | 4-10 | 11-25 | 26-49 |
|---|---|---|---|---|---|
| Tasks | 20 | 21 | 13 | 13 | 9 |

- Median 3, mean 9.6, maximum 49.
- 65 failing sets are distinct. 19 tasks share their set with at least one other task, in 8
  groups.
- Three tasks turned the one xpass test (`test_issue484_comments_and_newlines`) into an xfail.
  It is recorded in `excluded_fail_to_pass`, the same convention P6 uses.

## Gold check

The gold check ran for two tasks: `sqlparse-mut-001` (compare_flip, 1 failing test) and
`sqlparse-mut-002` (drop_not, 9 failing tests). For each:

1. The mutated workspace was rebuilt from `mutation_patch`, and the suite reran.
2. The failing set matched the recorded `fail_to_pass` exactly.
3. The gold patch was applied with `git apply`. It restored the file byte for byte.
4. After gold: `fail_to_pass` passed 1/1 and 9/9, with 0 `pass_to_pass` regressions. The suite
   was 491 pass / 0 fail / 2 skip in both.

In a separate spot check, `sqlparse-mut-038` was rebuilt from the JSON alone. Its one
`fail_to_pass` test failed on the mutated tree and passed after the gold patch.

Independent check by the orchestrating session (2026-09-27): `sqlparse-mut-010` (drop_not,
`sqlparse/sql.py` line 347) was rebuilt from the JSON alone with `git archive` + `git apply`.
The mutated tree failed exactly the 48 recorded tests (48 failed, 442 passed, 2 xfailed,
1 xpassed); after the gold patch the full suite gave 490 passed, 2 xfailed, 1 xpassed.

## Example statements

`sqlparse-mut-002` (drop_not in `TokenList.token_first`, 9 failing tests):

> sqlparse has a regression: 9 previously passing checks of its behaviour now fail. Affected
> behaviour: 'statement get type'; 'issue34' (2 cases); 'stream'; and 5 more. The first failing
> check reports: `AssertionError: assert 'UNKNOWN' == 'SELECT'`. Fix the library so this
> behaviour is correct again; behaviour that works today must keep working.

`sqlparse-mut-038` (remove_guard in `cli.main`, 1 failing test). This one shows the grep leak in
weakness 3:

> sqlparse has a regression: 1 previously passing check of its behaviour now fails. Affected
> behaviour: 'cli outfile with multiple files fails'. The first failing check reports:
> `AssertionError: assert 'Cannot use -o/--outfile with multiple files' in '[ERROR] Multiple
> files require --in-place flag\n'`. Fix the library so this behaviour is correct again;
> behaviour that works today must keep working.

## Schema

Every `tasks.json` key is kept. Some take mutation-specific values:

- `upstream_pr` is `null`.
- `base_commit` and `fix_commit` are both `f66d12c`.
- `evaluator_test_files` lists all 10 `tests/test_*.py` files, and `pass_to_pass` covers the
  whole suite. P6 tasks list only the fix's test files. That is why the file is 2.8 MB.
- `skipped_after_fix` holds the 2 baseline xfails.

Added keys:

- `hidden_tests: true` and `hidden_paths: ["tests"]`;
- `mutation_patch` and `gold_patch`;
- `mutation_file`, `mutation_line`, `mutation_end_line`, `mutation_kind`, `mutation_detail`,
  `mutated_function`;
- `source_task`, `generator_version`, `first_failure_message`;
- `statement_message_dropped` and `statement_names_mutated_function`.

To build a task workspace:

1. Export `base_commit`.
2. Apply `mutation_patch`.
3. Delete `hidden_paths`.

The evaluator needs no change: `build_evaluator` already restores the whole `tests` root from
`fix_commit`, which is the healthy suite.

## Known weaknesses

1. **Not runnable yet.** `run_pilot.py` reads only `p6_pilot/tasks.json`. Its
   `materialize_workspace` exports `base_commit` but does not apply `mutation_patch` or delete
   `hidden_paths`. Wired in without those two steps, the agent would get a healthy tree with
   the failing tests visible, and every task would pass at once. The fix is two small changes
   in `materialize_workspace`; they were not made here.
2. **The pristine source is public.** sqlparse at this commit is on GitHub and PyPI and is
   probably in model memory. Diffing against a downloaded copy finds any mutation at once. A
   no-network backend (OCI) removes the download route but not memorization. Claims that need
   contamination-free tasks need private code.
3. **Some statements grep to the bug.**
   - 13 of 76 statements share a token with the source within 3 lines of the mutation. The
     tokens come from a quoted literal in the message or a humanized test name rejoined with
     underscores.
   - Most of these tokens are common words (`where`, `python`, `SELECT`, `tokens`,
     `compact`).
   - Some point straight at the bug. `mut-038` quotes the exact error string next to the
     deleted guard. `mut-049` names `remove_quotes`, which is the mutated function. `mut-025`
     names `_TokenType`.
   - For 6 tasks the statement's tokens grep to the mutated file only.
   - `statement_names_mutated_function` is true for 3 tasks.
   - The leak check only enforces file, line and test id. It does not enforce identifiers.
4. **Some messages carry no information.** pytest truncates long strings on the first line, so
   `mut-001` reports `assert 'select foo; ...n\nselect bar' == 'select foo; ...n\nselect bar'`,
   where both sides look the same. Others say only `assert False` (`mut-005`) or
   `assert 1 == 2` (`mut-003`). In those tasks the humanized test name is the only real clue.
5. **Test names reveal what the hidden tests check.** The humanized names are close to
   verbatim function names, and the upstream suite is public. Hiding `tests/` and blocking the
   network stops the agent running those tests, but not recognising them.
6. **Equivalent mutants are not classified.** The 10 survivors were rejected without deciding
   whether each is equivalent or just untested. Kept tasks cannot be equivalent, since a test
   tells them apart. A kept task may accept fixes other than the revert; acceptance is by tests
   only, by design.
7. **Tasks are correlated.**
   - 19 tasks share a failing set with another task.
   - Two pairs have identical statements for bugs on neighbouring lines: `mut-021`/`mut-044`
     in `formatter.py` lines 197 and 198, and `mut-057`/`mut-070` in `sql.py` lines 644 and 646.
   - 25 of 76 mutations are in `sql.py`.
   - An evaluation sample should take at most one task per failing set (65 available).
8. **The bugs are small and syntactic.** Each fix reverts one site in one file, while real
   repairs often span files. Difficulty is uncalibrated.
9. **Flakiness is barely checked.** Each candidate ran once. Only the 2 gold-checked tasks were
   re-run whole, and only `mut-038` was spot-checked on its failing test.
10. **Timeouts are expensive.** Three looping mutants took a third of the loop time. Installing
    pytest-timeout or lowering the cap to 30 s would recover most of it. The 90% threshold and
    the timeout were chosen by rule, not tuned.
11. **One source state (resolved 2026-09-28).** The generator hard-coded `sqlparse`, `tests` and
    the source task id. They are now parameters of a [repos.json](repos.json) entry (`--repo`,
    default `sqlparse`), with `pythonpath` for src layouts; the sqlparse bank regenerates byte for
    byte from its entry. The second bank, boltons ([tasks.boltons.json](tasks.boltons.json)), is described in [card 023](../session_harness/E3-calibration-023.md).

## Not done

- No model runs.
- No runner wiring (weakness 1).
- 431 of 531 candidates never tried, because of the 100-candidate cap.
- Survivors not classified as equivalent or untested.
- No difficulty calibration.
- No human review of statements beyond the ones quoted here.

Provenance: generator, data and text by a subagent (Claude Opus 5.5) in this repository's
worktree on 2026-09-27; the orchestrating session validated the JSON schema and counts and ran
the independent gold check on `sqlparse-mut-010` recorded above before committing this file.
