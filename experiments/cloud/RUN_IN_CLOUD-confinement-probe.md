**The cloud integrity fix: does `--sandbox unshare-confined` confine the run tool on the cloud VM? Any model in the
picker. The probe makes no model call and runs no campaign. The setup takes a few minutes; the probe takes under two.**

Start a Claude Code cloud session on `grantprater/harnessExperiment` and paste everything between the two lines.

---

You set up this VM for the Reticle harness, run one confinement probe, and report its output. I, the owner, wrote this
prompt. Follow it exactly and keep your replies short.

Rules:
- No model calls of your own beyond this session: no `claude -p`, no campaign, no `run_card.py --execute`, no smoke.
- Edit no file except the one result file in step 4.
- If a step fails or a command is refused, stop and report.

1. `git fetch origin && git checkout fix/cloud-run-confinement && git pull --ff-only && git checkout -b cloud-probe-confinement`
2. `cd "$(git rev-parse --show-toplevel)" && bash experiments/cloud/setup_cloud.sh 2>&1 | tail -25`. The last line
   must be `READY`. Note every `NOTE` line for the report.
3. `OMP_NUM_THREADS=1 .runtime/test-venv/bin/python -m unittest tests.test_cloud_confinement 2>&1 | tail -5`, for the
   report only; continue whatever it prints.
4. `{ uname -a; id; grep -E '^(Cap|Seccomp|NoNewPrivs)' /proc/self/status; bash experiments/cloud/probe_confinement.sh; echo "exit $?"; } 2>&1 | tee experiments/cloud/probe-confinement-result.txt`
5. `git add experiments/cloud/probe-confinement-result.txt && git commit -m "cloud: confinement probe result (integrity fix)" && git push -u origin cloud-probe-confinement`

Final report, and nothing else about it (the owner and the build session interpret it):
- the last line of step 2 and its `NOTE` lines;
- the output of step 3;
- every `INFO`, `FAIL`, `SUMMARY` and `CONFINEMENT` line of step 4, verbatim, plus its `exit` line;
- the pushed commit.

---

How to read the result (for the owner): the probe ends with one of three lines.
- `CONFINEMENT: PASS` (exit 0): every escape route of cards 020, 021 and 023 was blocked on the VM, and the positive
  controls worked. The escape routes are `find /`, the healthy clone, the task and verifier files, the evaluator, the
  host `/tmp`, `git` on the harness repo, pip and curl downloads, and the Python network. The positive controls are
  python, pytest, and workspace writes. Cloud cards can then resume with `"sandbox": "unshare-confined"`; this is a
  new protocol hash, so it starts new runs and replays none of the old ones.
- `CONFINEMENT: FAIL` (exit 1): at least one `FAIL` line names what got through or which control broke. Cloud cards
  stay paused.
- `CONFINEMENT: UNAVAILABLE` (exit 2): the backend refused to run on this VM, so it fails closed and the runner would
  refuse the same way. Cloud cards stay paused.

The probe was first run on the host on 2026-09-30, under podman with python:3.11-slim-bookworm, `--cpus 1` and
`seccomp=unconfined`, as root. It printed `SUMMARY 36 passed, 0 failed` and `CONFINEMENT: PASS`. That image has no
git and no curl, so their checks were skipped there.
