"""Campaign driver for card E3-calibration-007: 20 tasks x 2 rollouts, one run_pilot.py
invocation per run, strictly sequential, under the live-run lock.

Usage (from the repo root):
  python experiments/session_harness/run_card007.py --plan      # list invocations, no execution
  python experiments/session_harness/run_card007.py --execute   # run; restartable (skips finished runs)

Rules implemented from the card and the S6a report:
- run names c007-<task>-r<k>; rollout 1 over all tasks in task-id order, then rollout 2;
- a run with a results.jsonl line is finished and skipped (restart safe);
- a runner crash (non-zero exit, no results line) is rerun once under the same name; a second crash
  stops the campaign as evidence loss;
- three consecutive runs stopping in model_error stop the campaign;
- .runtime/locks/live-run.lock is created exclusively and released in `finally`;
- idle priority and single-threaded env for the runner process;
- evidence committed after every 10 finished runs and at the end.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
RUNNER = ROOT / "experiments" / "p6_pilot" / "run_pilot.py"
TASK_FILE = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
SELECTION = ROOT / "experiments" / "session_harness" / "E3-calibration-007-tasks.json"
RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
LOG = ROOT / "experiments" / "session_harness" / "c007-campaign.jsonl"
LOCK = ROOT / ".runtime" / "locks" / "live-run.lock"
COMMIT_EVERY = 10
TRAILER = "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"

FLAGS = [
    "--client", "claude-cli", "--models", "sonnet", "--backend", "oci", "--arm", "pressure-recent-v3",
    "--max-calls-per-run", "20", "--max-attempts-per-run", "24", "--elapsed-cap-seconds", "1200",
    "--max-tokens", "4096", "--max-total-calls", "48",
]


def selected_task_ids() -> list[str]:
    data = json.loads(SELECTION.read_text(encoding="utf-8"))
    items = data["tasks"] if isinstance(data, dict) else data
    ids = [t if isinstance(t, str) else t["task_id"] for t in items]
    return sorted(ids)


def invocations() -> list[tuple[str, str, int, list[str]]]:
    out = []
    for k in (1, 2):
        for task in selected_task_ids():
            name = f"c007-{task}-r{k}"
            cmd = [PY, str(RUNNER), *FLAGS, "--tasks", str(TASK_FILE), task, "--run-name", name]
            out.append((name, task, k, cmd))
    return out


def result_line(name: str) -> dict | None:
    p = RUNS / name / "results.jsonl"
    if not p.exists():
        return None
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def log(row: dict) -> None:
    row["ts_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def commit_evidence(done: int) -> None:
    subprocess.run(["git", "add", "experiments/p6_pilot/runs", str(LOG.relative_to(ROOT))], cwd=ROOT, check=False)
    if not git("diff", "--cached", "--name-only"):
        return
    msg = f"data(c007): calibration evidence after {done} finished runs\n\n{TRAILER}\n"
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=ROOT, check=False)
    print(f"[c007] committed evidence at {done} runs: {git('log', '--oneline', '-1')}", flush=True)


def run_one(name: str, cmd: list[str]) -> tuple[int, dict | None, float]:
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
    t0 = time.time()
    with (RUNS / name).with_suffix(".driver.log").open("a", encoding="utf-8") as out:
        rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=flags, timeout=3600).returncode
    return rc, result_line(name), time.time() - t0


def execute() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"[c007] lock held: {LOCK}; refusing to start", flush=True)
        return 2
    os.write(fd, f"c007 pid {os.getpid()} {dt.datetime.now().isoformat()}".encode()); os.close(fd)
    RUNS.mkdir(parents=True, exist_ok=True)
    done = finished_at_start = sum(1 for n, *_ in invocations() if result_line(n))
    consecutive_model_errors = 0
    status = "complete"
    try:
        for name, task, k, cmd in invocations():
            if result_line(name):
                continue
            crashes = 0
            while True:
                print(f"[c007] start {name}", flush=True)
                rc, res, secs = run_one(name, cmd)
                row = {"run": name, "task": task, "rollout": k, "exit": rc, "seconds": round(secs, 1),
                       "stop": (res or {}).get("stop"), "acceptance": ((res or {}).get("acceptance") or {}).get("status"),
                       "crash_retry": crashes}
                log(row); print(f"[c007] {json.dumps(row)}", flush=True)
                if res is None:
                    crashes += 1
                    if crashes >= 2:
                        status = f"stopped: evidence loss on {name} (two crashes)"; break
                    continue
                break
            if res is None:
                break
            done += 1
            consecutive_model_errors = consecutive_model_errors + 1 if res.get("stop") == "model_error" else 0
            if consecutive_model_errors >= 3:
                status = f"stopped: three consecutive model_error runs, last {name}"; break
            if (done - finished_at_start) % COMMIT_EVERY == 0:
                commit_evidence(done)
    finally:
        commit_evidence(done)
        log({"campaign": "E3-calibration-007", "status": status, "finished_runs": done})
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass
        print(f"[c007] {status}; finished runs {done}/{len(invocations())}", flush=True)
    return 0 if status == "complete" else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    inv = invocations()
    if a.plan:
        fin = [n for n, *_ in inv if result_line(n)]
        print(f"{len(inv)} invocations, {len(fin)} already finished; lock {'HELD' if LOCK.exists() else 'free'}")
        for name, task, k, cmd in inv[:3]:
            print(name, "->", " ".join(cmd[1:]))
        print("...")
        return
    sys.exit(execute())


if __name__ == "__main__":
    main()
