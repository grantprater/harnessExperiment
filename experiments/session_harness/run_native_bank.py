"""Campaign driver for card E3-native-arm-018: card 007's 20 mutation tasks x 2 rollouts through Claude Code's own
agent loop (native_control.py), one invocation per run, strictly sequential, under the live-run lock.

Usage (from the repo root):
  python experiments/session_harness/run_native_bank.py --plan       # list invocations and blockers, no execution
  python experiments/session_harness/run_native_bank.py --controls   # scripted gold, noop on sqlparse-mut-001 (no CLI)
  python experiments/session_harness/run_native_bank.py --execute    # run; restartable (skips finished runs)
  [--scratch-root DIR]  parent of native_control's scratch base (default: the system temp folder)
  [--sandbox]           pass --sandbox to every run (the CLI's OS sandbox; needs `claude sandbox install`, else
                        every run refuses and the campaign stops at the first)

Rules:
- run names c018-<task>-r<k>; rollout 1 over all tasks in task-id order, then rollout 2 (rollout-major), the tasks
  read from E3-calibration-007-tasks.json; every run uses native_control.py with FLAGS (card 007's budgets);
- a run with native_runs/<name>/result.json is finished and skipped (restart safe);
- a crash (no result.json) is rerun once under the same name, after the crashed record directory is kept as
  <name>.interrupted-<time> and the run's scratch directory is removed; a second crash stops the campaign
  (evidence loss). A run's leftover record directory from an interrupted campaign is handled the same way;
- a leak-check refusal (native_control exit 3) or an init-check abort (stop isolation_abort) stops the campaign at
  once (integrity);
- three consecutive CLI failures (stop cli_error or isolation_abort: no result event, or an error result that is
  not the turn cap) stop the campaign (checkpoint);
- --execute needs the two controls recorded as expected (c018-control-gold accepted, c018-control-noop rejected);
- the live-run lock of the main checkout (.runtime/locks/live-run.lock, shared by every worktree) is created
  exclusively and released in `finally`; if it is held, --execute refuses. --controls make no model call and do
  not take it;
- idle priority and single-threaded BLAS for every native_control process (its CLI and evaluator inherit them);
- evidence (native_runs/c018-*, the campaign log) is committed after every 10 finished runs and at the end.

Exit codes: 0 done; 2 refused (controls missing or not as expected); 3 checkpoint stop (three consecutive CLI
failures); 4 integrity stop (evidence loss, leak-check refusal, init-check abort, failed control); 5 lock held.
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

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import native_control  # noqa: E402

PY = sys.executable
NATIVE = HERE / "native_control.py"
TASK_FILE = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
SELECTION = HERE / "E3-calibration-007-tasks.json"
RECORD_ROOT = native_control.RECORD_ROOT
LOG = HERE / "c018-campaign.jsonl"
LOCK = native_control.checkout_roots()[-1] / ".runtime" / "locks" / "live-run.lock"
CARD = "E3-native-arm-018"
PREFIX = "c018"
ROLLOUTS = (1, 2)
COMMIT_EVERY = 10
MAX_CONSECUTIVE_CLI_FAILURES = 3
RUN_TIMEOUT_SECONDS = 3600  # 1,200 s agent cap + evaluation (600 s pytest + 120 s) + materialization, with margin
SCRATCH_ROOT = None
SANDBOX = False
TRAILER = "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
EXIT_OK, EXIT_REFUSED, EXIT_CHECKPOINT, EXIT_INTEGRITY, EXIT_LOCKED = 0, 2, 3, 4, 5

# Card 007's per-run budgets as the native arm expresses them: 20 model turns, 1,200 s, model sonnet, OCI evaluator.
FLAGS = ["--model", "sonnet", "--max-turns", "20", "--wall-seconds", "1200", "--backend", "oci",
         "--pytest-timeout", "600"]
CONTROL_TASK = "sqlparse-mut-001"
CONTROLS = ((f"{PREFIX}-control-gold", "gold", "accepted"), (f"{PREFIX}-control-noop", "noop", "rejected"))


def selected_task_ids() -> list:
    data = json.loads(SELECTION.read_text(encoding="utf-8"))
    return sorted(data["task_ids"])


def command(name: str, task: str, extra=()) -> list:
    cmd = [PY, str(NATIVE), *FLAGS, "--tasks", str(TASK_FILE), task, "--run-name", name, *extra]
    if SCRATCH_ROOT:
        cmd += ["--scratch-root", str(SCRATCH_ROOT)]
    if SANDBOX:
        cmd.append("--sandbox")
    return cmd


def invocations() -> list:
    return [(f"{PREFIX}-{task}-r{k}", task, k, command(f"{PREFIX}-{task}-r{k}", task))
            for k in ROLLOUTS for task in selected_task_ids()]


def result_of(name: str):
    path = RECORD_ROOT / name / "result.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def log(row: dict) -> None:
    row["ts_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def commit_evidence(done: int) -> None:
    records = RECORD_ROOT.relative_to(ROOT).as_posix()
    subprocess.run(["git", "add", "--", f"{records}/{PREFIX}-*", LOG.relative_to(ROOT).as_posix()], cwd=ROOT,
                   check=False, capture_output=True)
    if not git("diff", "--cached", "--name-only"):
        return
    message = f"data({PREFIX}): native-arm evidence after {done} finished runs\n\n{TRAILER}\n"
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=ROOT, check=False)
    print(f"[{PREFIX}] committed evidence at {done} runs: {git('log', '--oneline', '-1')}", flush=True)


def clear_leftovers(name: str) -> list:
    """Before a (re)run: keep an unfinished record directory for audit under a new name, remove the run's scratch."""
    moved = []
    record = RECORD_ROOT / name
    if record.exists():
        target = record.with_name(f"{name}.interrupted-{dt.datetime.now():%Y%m%d%H%M%S}")
        record.rename(target)
        moved.append(target.name)
    scratch = native_control.scratch_base(SCRATCH_ROOT) / name
    if scratch.exists():
        error = native_control.remove_tree(scratch)
        if error:
            raise RuntimeError(f"cannot remove {scratch}: {error}")
        moved.append(f"removed {scratch}")
    return moved


def run_one(name: str, cmd: list):
    """(exit code or None on timeout, result record or None, seconds) for one native_control invocation."""
    RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
    started = time.time()
    with (RECORD_ROOT / f"{name}.driver.log").open("a", encoding="utf-8") as out:
        process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            code = process.wait(timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            native_control.kill_tree(process)
            process.wait()
            code = None
    return code, result_of(name), time.time() - started


def controls_problem():
    """Why the recorded controls do not allow --execute, or None."""
    for name, kind, expected in CONTROLS:
        record = result_of(name)
        if record is None:
            return f"control {name} is not recorded; run --controls first"
        status = (record.get("acceptance") or {}).get("status")
        if status != expected:
            return f"control {name} ({kind}) was {status}, expected {expected}"
    return None


def run_controls() -> int:
    """The no-model control of the whole path: scripted gold and noop through native_control (no CLI, no lock)."""
    failed = False
    for name, kind, expected in CONTROLS:
        record = result_of(name)
        if record is None:
            print(f"[{PREFIX}] control {name}: scripted {kind} on {CONTROL_TASK}", flush=True)
            code, record, seconds = run_one(name, command(name, CONTROL_TASK, ["--scripted", kind]))
            log({"control": name, "kind": kind, "exit": code, "seconds": round(seconds, 1),
                 "acceptance": ((record or {}).get("acceptance") or {}).get("status")})
            if record is None:
                print(f"[{PREFIX}] control {name}: no record (exit {code}); see {name}.driver.log", flush=True)
                failed = True
                continue
        acceptance = record["acceptance"]
        print(f"[{PREFIX}] control {name}: {acceptance['status']} (expected {expected}) "
              f"{json.dumps(acceptance['criterion_outcomes'])} {json.dumps(acceptance.get('test_counts'))}", flush=True)
        failed = failed or acceptance["status"] != expected
    return EXIT_INTEGRITY if failed else EXIT_OK


def acquire_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, json.dumps({"card": CARD, "argv": sys.argv, "pid": os.getpid(),
                             "acquired_at": dt.datetime.now(dt.timezone.utc).isoformat()}).encode("utf-8"))
    os.close(fd)
    return True


def execute() -> int:
    problem = controls_problem()
    if problem:
        print(f"[{PREFIX}] refusing to start: {problem}", flush=True)
        return EXIT_REFUSED
    if not acquire_lock():
        print(f"[{PREFIX}] lock held: {LOCK}; refusing to start", flush=True)
        return EXIT_LOCKED
    plan = invocations()
    done = finished_at_start = sum(1 for name, *_ in plan if result_of(name))
    consecutive_cli_failures = 0
    status, code = "complete", EXIT_OK
    try:
        for name, task, k, cmd in plan:
            if result_of(name):
                continue
            crashes = 0
            while True:
                moved = clear_leftovers(name)
                print(f"[{PREFIX}] start {name}" + (f" (kept/removed: {moved})" if moved else ""), flush=True)
                exit_code, record, seconds = run_one(name, cmd)
                row = {"run": name, "task": task, "rollout": k, "exit": exit_code, "seconds": round(seconds, 1),
                       "stop": (record or {}).get("stop"),
                       "acceptance": ((record or {}).get("acceptance") or {}).get("status"),
                       "turns": (record or {}).get("turns_used"), "responses": (record or {}).get("responses"),
                       "cli_failure": (record or {}).get("cli_failure"),
                       "audit_clean": (record or {}).get("audit_clean"),
                       "crash_retry": crashes}
                log(row)
                print(f"[{PREFIX}] {json.dumps(row)}", flush=True)
                if record is None and exit_code == native_control.EXIT_REFUSED:
                    break
                if record is None:
                    crashes += 1
                    if crashes >= 2:
                        break
                    continue
                break
            if record is None and exit_code == native_control.EXIT_REFUSED:
                status, code = f"stopped: {name} refused by a leak check (see {name}.driver.log)", EXIT_INTEGRITY
                break
            if record is None:
                status, code = f"stopped: evidence loss on {name} (two crashes)", EXIT_INTEGRITY
                break
            done += 1
            if record.get("stop") == "isolation_abort":
                status, code = f"stopped: {name} init check failed: {record.get('aborted')}", EXIT_INTEGRITY
                break
            consecutive_cli_failures = consecutive_cli_failures + 1 if record.get("cli_failure") else 0
            if consecutive_cli_failures >= MAX_CONSECUTIVE_CLI_FAILURES:
                status, code = f"stopped: three consecutive CLI failures, last {name}", EXIT_CHECKPOINT
                break
            if (done - finished_at_start) % COMMIT_EVERY == 0:
                commit_evidence(done)
    finally:
        log({"campaign": CARD, "status": status, "finished_runs": done})
        commit_evidence(done)
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass
        print(f"[{PREFIX}] {status}; finished runs {done}/{len(plan)}", flush=True)
    return code


def print_plan() -> None:
    plan = invocations()
    finished = [name for name, *_ in plan if result_of(name)]
    print(f"{len(plan)} invocations ({len(selected_task_ids())} tasks x {len(ROLLOUTS)} rollouts, rollout-major), "
          f"{len(finished)} already finished; lock {'HELD' if LOCK.exists() else 'free'} ({LOCK})")
    print(f"controls: {controls_problem() or 'recorded as expected'}")
    print(f"scratch base: {native_control.scratch_base(SCRATCH_ROOT)}")
    for name, task, k, cmd in plan[:3]:
        print(name, "->", " ".join(cmd[1:]))
    print("...")
    name, task, k, cmd = plan[-1]
    print(name, "->", " ".join(cmd[1:]))


def main(argv=None) -> int:
    global SCRATCH_ROOT, SANDBOX
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--controls", action="store_true")
    group.add_argument("--execute", action="store_true")
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--sandbox", action="store_true")
    args = parser.parse_args(argv)
    SANDBOX = args.sandbox
    if args.scratch_root:
        SCRATCH_ROOT = args.scratch_root
    if args.plan:
        print_plan()
        return EXIT_OK
    if args.controls:
        return run_controls()
    return execute()


if __name__ == "__main__":
    sys.exit(main())
