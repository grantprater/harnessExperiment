**Card 022's cloud-first check: can the cloud VM deny a child process the network? Any model in the picker; the probe
itself makes no model call and runs no campaign, and it takes under a minute.**

Start a Claude Code cloud session on `grantprater/harnessExperiment` and paste everything between the two lines.

---

You run one read-only probe on this VM for the Reticle harness and report its output. I, the owner, wrote this prompt;
follow it exactly and keep your replies short.

Rules: no model calls of your own beyond this session (no `claude -p`), no campaign, no setup script, no package
installs, no edits to any file except the one result file in step 3. If a step fails or a command is refused, stop and
report.

1. `git fetch origin && git checkout wt/forecast-design && git pull --ff-only && git checkout -b cloud-probe-isolation`
2. `cd "$(git rev-parse --show-toplevel)" && { uname -a; id; grep -E '^(Cap|Seccomp|NoNewPrivs)' /proc/self/status; bash experiments/cloud/probe_isolation.sh; echo "exit $?"; } 2>&1 | tee experiments/cloud/probe-isolation-result.txt`
3. `git add experiments/cloud/probe-isolation-result.txt && git commit -m "cloud: isolation probe result (card 022 prerequisite)" && git push -u origin cloud-probe-isolation`

Final report: the whole output of step 2 (it is short), verbatim, and the pushed commit. Say nothing else about it;
the owner and the build session interpret it.

---

How to read the result (for the owner): the last line is `ISOLATION: NETWORK+FILES` (cloud first works: the forecast
runs can go to the VM once the runner wraps its commands in `unshare -rnm`, the card's isolation prerequisite),
`ISOLATION: NETWORK ONLY` (the network can be denied, but the checkout cannot be hidden: the cloud variant must then be
the design's single-T campaign with only that date's snapshots on the VM), or `ISOLATION: NONE` (use the host OCI
backend, the fallback). A `FAIL 1` line means the VM itself had no network, so nothing was tested. On the host
(2026-09-28, podman, python:3.11-slim, `--cpus 1`) the probe printed `NETWORK+FILES` both as root and as uid 1000 with
`--cap-drop ALL --security-opt no-new-privileges`, and `NONE` with `FAIL 1` under `--network none`.
