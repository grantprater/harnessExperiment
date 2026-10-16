**Card 010, amendment 1: stage 2a generation of more sqlparse mutation tasks. CPU only; it makes no model call and
runs no campaign. Use any model in the picker (Sonnet is enough). Setup takes a few minutes and generation up to about
65 min (a 3600 s loop cap, plus the baseline and 2 gold checks).**

Start a Claude Code cloud session on `grantprater/harnessExperiment` (or launch it as a one-shot routine) and paste
everything between the two lines. The amendment it carries out is "Amendment 1 (2026-10-01): stage 2a" in
`experiments/session_harness/E3-difficulty-calibration-010.md`.

---

You run card 010's stage-2a generator on this VM and report its result. I, the owner, wrote this prompt. Follow it
exactly, and keep your replies short (at most the last 20 lines of any output).

Rules for the whole session:
- Start every shell command with
  `cd "$(git rev-parse --show-toplevel)" && export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PY=.runtime/bugs-venv/bin/python;`
  (the shell does not keep variables between commands).
- Make no model calls beyond this session: no `claude -p`, no `run_card.py --execute`, no smoke, no campaign.
- One heavy process at a time.
- Edit, add or commit no file except the three outputs in step 8. Step 2 writes five setup files from another commit;
  they stay uncommitted.
- Do not work around a failure: no retries with changed flags, budgets or paths. If a step fails, or a command is
  refused, stop and report. Step 7 is the one exception: whatever its verdict, continue to step 8.

1. `git fetch origin && git checkout exp/ontology-pilot && git pull --ff-only && git checkout -b cloud-results-010-stage2a && git log -1 --oneline`
   - Then find the amendment commit:
     `A=$(git log -1 --format=%H --grep='cards(010): amendment 1') && echo "$A"`.
   - Then confirm that nothing the generator reads has changed since it. This must print nothing:
     `git diff --stat "$A" HEAD -- experiments/mutation_tasks/generate.py experiments/mutation_tasks/check_stage2a_010.py experiments/mutation_tasks/tasks.mutations.json experiments/mutation_tasks/generation_log.json experiments/p6_pilot/evaluate_task.py experiments/p6_pilot/tasks.json`
     (run it with the same `A=...` assignment in front).
2. Setup files. This branch has no `experiments/cloud/` setup. Take the five files the setup needs from the pinned
   integration commit, without staging them:
   ```
   git fetch origin integration/2026-10 && S=68333e2385667dfd781cea282dc1fbcfc4b2201e && mkdir -p experiments/cloud && for f in experiments/cloud/setup_cloud.sh experiments/cloud/bugs-venv.requirements.txt experiments/cloud/test-venv.requirements.txt experiments/cloud/test-venv.requirements-py311.txt experiments/p6_pilot/interpreters.py; do test -e "$f" && { echo "exists: $f"; exit 1; }; git show "$S:$f" > "$f" || exit 1; done; git status --short
   ```
   `git status --short` must list exactly these five paths as untracked (`??`), or their directory
   `experiments/cloud/` and the one file `experiments/p6_pilot/interpreters.py`.
3. `bash experiments/cloud/setup_cloud.sh 2>&1 | tail -25`. The last line must be `READY`. Note every `NOTE` line, the
   task interpreter's Python version, and the `sqlparse clone` line, which must name commit
   `f66d12c245412f28c58f045b646eb53c0e691b8b`.
4. Schedule check, AST only and no suites:
   `$PY experiments/mutation_tasks/check_stage2a_010.py --schedule`. It must end with `SCHEDULE: SAME`, and report a
   candidate pool of 531 and 431 untried. Otherwise stop: do not generate.
5. Generation, as ONE background command. Run it with the Bash tool's background option; do not add `&`:
   ```
   echo $$ > .runtime/c010-2a.pid; nice -n 19 $PY experiments/mutation_tasks/generate.py --python "$PWD/.runtime/bugs-venv/bin/python" --work-dir /tmp/c010-2a-work --max-candidates 531 --budget-seconds 3600 --out experiments/mutation_tasks/tasks.mutations.full.json --log experiments/mutation_tasks/generation_log.full.json > .runtime/c010-2a-generate.out 2>&1; echo "generate exit $?" >> .runtime/c010-2a-generate.out
   ```
   Put the rules' `cd ... export ...;` prefix in front, as for every command. Record the UTC start time.
6. Wait with this single blocking command, tool timeout 600000 ms:
   ```
   timeout 540 tail --pid="$(cat .runtime/c010-2a.pid)" -f /dev/null; if grep -q '^generate exit' .runtime/c010-2a-generate.out; then echo FINISHED; elif kill -0 "$(cat .runtime/c010-2a.pid)" 2>/dev/null; then echo RUNNING; else echo GONE; fi; tail -n 1 .runtime/c010-2a-generate.out
   ```
   - On `RUNNING`, issue the same command again at once and nothing else: no log reading and no commentary beyond one
     line.
   - On `GONE`: `tail -20 .runtime/c010-2a-generate.out`, then report and stop. Commit nothing.
   - On `FINISHED`: `tail -40 .runtime/c010-2a-generate.out`. The last line must be `generate exit 0`, and the
     summary JSON must be printed above it; otherwise report and stop. Record the UTC end time.
7. Determinism check and counts. This runs no suites:
   ```
   $PY experiments/mutation_tasks/check_stage2a_010.py --compare --full-tasks experiments/mutation_tasks/tasks.mutations.full.json --full-log experiments/mutation_tasks/generation_log.full.json --result experiments/mutation_tasks/stage2a-010-result.txt; echo "check exit $?"
   ```
   The `DETERMINISM:` line reads `PASS`, `PASS-ADDRESS-ONLY` or `FAIL`. Whatever it says, continue to step 8. Do not
   interpret it, and do not use or examine any new task id.
8. Commit and push only the three outputs:
   ```
   git add experiments/mutation_tasks/tasks.mutations.full.json experiments/mutation_tasks/generation_log.full.json experiments/mutation_tasks/stage2a-010-result.txt && git diff --cached --name-only && git commit -m "data(c010): stage 2a generation output and determinism check (cloud)" && git push -u origin cloud-results-010-stage2a && git log -1 --oneline && git ls-remote origin cloud-results-010-stage2a
   ```
   - `git diff --cached --name-only` must list exactly those three files.
   - `git status --short` afterwards may show only the five untracked setup files from step 2.

Final report (short):
- the commit from step 1 and the amendment commit `A`;
- the last line of step 3, its `NOTE` lines, the task Python version and the sqlparse clone line;
- step 4's three output lines;
- the UTC start and end of generation;
- the contents of `stage2a-010-result.txt`, verbatim;
- the pushed branch and commit;
- everything you did not do.

---

How to read the result (for the owner and the build session):
- `DETERMINISM: PASS`: the first 100 candidates gave the same verdicts, and tasks `sqlparse-mut-001` to `-076`
  reappeared with byte-identical patches and statements. The new ids (`-077` onward) may be used under amendment 1.
- `DETERMINISM: PASS-ADDRESS-ONLY`: the same, except for a statement whose only difference is a CPython memory address.
  `sqlparse-mut-072` is the expected case. Under the amendment this counts as a pass only once the owner accepts the
  proposed exception; until then, no new id is used.
- `DETERMINISM: FAIL`: stop. No new id is used, nothing is calibrated, and the outputs on `cloud-results-010-stage2a`
  serve for diagnosis only.
- The `PROPOSED selection` line counts the new candidates under amendment 1's proposed rule (A1.3).
  `candidates_function_distinct` is the number that would go to controls and then calibration, 2 runs each. The
  calibration's run count and cost still need the owner's approval.
