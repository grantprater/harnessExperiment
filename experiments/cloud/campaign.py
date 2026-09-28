"""Run a card's campaign in a cloud session: no-model controls, the supervised campaign, and its status.

Everything a campaign does is still done by run_card.py (plan, lock, preflight, stop rules, evidence); this script
only wraps it for a session that must keep committing evidence and must not overspend.

  controls CARD            run the card's scripted controls (gold/noop; no model call) under the live-run lock with
                           run_card's own invocation, classification and campaign log; allowed while the card is
                           still waiting for approval. Exit 0 when every control has its expected outcome.
  run CARD --branch B      start `run_card.py CARD --execute --resume` (own process group, idle priority, one thread
                           per math library) and supervise it: every --commit-every finished runs, commit the card's
                           evidence and push it to B; if the campaign's CLI list-price total passes the spend cap
                           (the card's budgets.campaign.list_price_cap_usd unless --spend-cap), interrupt the
                           campaign (run_card releases the lock). At the end rewrite the report skeleton (its
                           "Spend and time" section), commit, push, and exit with run_card's exit code. Progress
                           goes to runs/card-<id>/supervisor.jsonl, run_card's output to runs/card-<id>/driver.log.
  wait CARD                block until the supervisor has ended (FINISHED), died without an end (GONE), or --timeout
                           seconds pass (RUNNING), then print that word and one status line; for a session whose tool
                           calls have a time limit.
  status CARD              one status line (or --json; --smoke CALLS.jsonl adds the smoke's list-price cost).
  report CARD              rewrite the report skeleton (run_card --report) and print its path.

The nested model cost (in status and in the report's "Spend and time" section, which run_card writes for cards with
budgets.campaign.list_price_cap_usd) is the sum of the CLI's list-price estimates (`cli_result.total_cost_usd`) over every attempt
of the campaign's run directories: what the owner's credits pay for the nested `claude -p` calls, at list price.
The supervising session's own usage is not in it; the usage page minus this figure estimates it.

Usage (from the repo root, on Linux):
  python experiments/cloud/campaign.py controls experiments/session_harness/cards/019.json
  python experiments/cloud/campaign.py run experiments/session_harness/cards/019.json --branch cloud-results-019
  python experiments/cloud/campaign.py wait experiments/session_harness/cards/019.json --timeout 540
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import run_card  # noqa: E402

RUN_CARD = ROOT / "experiments" / "session_harness" / "run_card.py"
THREAD_VARIABLES = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
DEFAULT_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
# Blockers a no-model control may run under: the card is only waiting for approval.
APPROVAL_BLOCKERS = ("card status is ", "prerequisite not done: ")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_plan(card_path: Path) -> run_card.Plan:
    card_path = card_path if card_path.is_absolute() else (Path.cwd() / card_path)
    card = run_card.load_card(card_path)
    errors = run_card.validate_card(card)
    if errors:
        raise SystemExit(f"{card_path}: invalid card: {errors}")
    return run_card.build_plan(card, card_path.resolve())


def supervisor_path(plan: run_card.Plan) -> Path:
    return run_card.Campaign(plan).directory / "supervisor.jsonl"


def log_supervisor(plan: run_card.Plan, event: str, **fields) -> None:
    path = supervisor_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": utc_now(), "event": event, **fields}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------------------------------------------

def status(plan: run_card.Plan, smoke_calls: Optional[Path] = None) -> dict:
    """Counts from the run directories and the campaign log; nothing is run."""
    campaign = run_card.Campaign(plan)
    runs = plan.runs
    finished, accepted, model_errors = 0, 0, 0
    for inv in runs:
        name = run_card.completed_attempt(campaign, inv)
        if name:
            finished += 1
            accepted += sum(1 for r in campaign.records(inv, name)
                            if (r.get("acceptance") or {}).get("status") == "accepted")
    controls = {}
    for inv in plan.controls:
        name = run_card.completed_attempt(campaign, inv)
        if name:
            outcome = run_card.classify(plan, campaign, inv, name, 0)
            controls[inv.name] = outcome.kind
        else:
            controls[inv.name] = "not run"
    events = run_card.read_jsonl(campaign.log_path)
    for event in events:
        if event.get("event") == "invocation_end" and event.get("outcome") == "failure":
            model_errors += 1
    stops = [e for e in events if e.get("event") in ("campaign_end", "checkpoint_stop", "integrity_stop", "stop")]
    result = {
        "card": plan.card["id"], "runs_planned": len(runs), "runs_finished": finished, "runs_accepted": accepted,
        "failed_attempts": model_errors, "controls": controls, **run_card.campaign_spend(campaign, events),
        "last_stop": (stops[-1] if stops else None),
        "spend_cap_usd": plan.card["budgets"]["campaign"].get("list_price_cap_usd"),
    }
    if smoke_calls is not None and smoke_calls.exists():
        rows = run_card.read_jsonl(smoke_calls)
        result["smoke_cost_usd"] = round(sum(float((r.get("cli_result") or {}).get("total_cost_usd") or 0)
                                             for r in rows), 6)
    return result


def status_line(value: dict) -> str:
    stop = value.get("last_stop") or {}
    wall = value.get("wall_seconds")
    return (f"{value['card']}: {value['runs_finished']}/{value['runs_planned']} runs finished, "
            f"{value['runs_accepted']} accepted, {value['failed_attempts']} failed attempts; controls "
            f"{value['controls']}; nested model cost (CLI list price) ${value['nested_cost_usd']:.2f} over "
            f"{value['nested_calls']} calls (cap {value['spend_cap_usd']}); wall "
            f"{'n/a' if wall is None else f'{wall / 3600:.2f} h'}"
            + (f"; smoke ${value['smoke_cost_usd']:.4f}" if "smoke_cost_usd" in value else "")
            + (f"; last stop {stop.get('event')}: {stop.get('reason')}" if stop else ""))


# ---------------------------------------------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------------------------------------------

def run_controls(plan: run_card.Plan, python: str = sys.executable, lock_path: Optional[Path] = None,
                 out=print) -> int:
    other = [b for b in plan.blockers if not b.startswith(APPROVAL_BLOCKERS)]
    if other:
        out("refused: blockers other than approval: " + "; ".join(other))
        return run_card.EXIT_REFUSED
    problems = run_card.engine_problems(plan)
    if problems:
        out("refused: " + "; ".join(problems))
        return run_card.EXIT_REFUSED
    lock = run_card.LiveRunLock(lock_path or run_card.default_lock_path())
    try:
        lock.acquire({"card": plan.card["id"], "owner": "campaign.py controls"})
    except run_card.LockHeld as exc:
        out(f"refused: {exc}")
        return run_card.EXIT_LOCKED
    campaign, code = run_card.Campaign(plan), run_card.EXIT_OK
    try:
        campaign.log("host", **run_card.machine_facts(plan, python))
        wall = plan.card["budgets"]["per_run"].get("invocation_wall_seconds")
        for inv in plan.controls:
            done = run_card.completed_attempt(campaign, inv)
            name = done or campaign.next_attempt_name(inv)
            exit_code = 0
            if not done:
                campaign.log("control_precheck_start", base=inv.run_name, run=name)
                exit_code = run_card.run_process(python, inv, name, campaign.directory / "logs" / f"{name}.log", wall)
            outcome = run_card.classify(plan, campaign, inv, name, exit_code)
            campaign.log("control_precheck_end", base=inv.run_name, run=name, exit_code=exit_code,
                         outcome=outcome.kind, detail=outcome.detail, reused=bool(done))
            out(f"control {inv.name} ({name}): {outcome.kind} ({outcome.detail})")
            if outcome.kind != "ok":
                code = run_card.EXIT_INTEGRITY
    finally:
        lock.release()
    return code


# ---------------------------------------------------------------------------------------------------------------
# Supervised campaign
# ---------------------------------------------------------------------------------------------------------------

def evidence_paths(plan: run_card.Plan) -> List[Path]:
    """What a commit of the campaign's evidence adds: every attempt directory of the plan's invocations (sessions/
    is ignored by .gitignore), the campaign directory, and the report skeleton and sets file."""
    campaign = run_card.Campaign(plan)
    paths = [campaign.directory]
    for inv in plan.invocations:
        if inv.script is not None:
            paths += [campaign.runs_root(inv) / name for name in campaign.attempt_names(inv)]
    report = plan.card["report"]
    paths.append(run_card.resolve_path(report["path"]))
    if report.get("sets_path"):
        paths.append(run_card.resolve_path(report["sets_path"]))
    return [path for path in paths if path.exists()]


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=check)


def commit_evidence(plan: run_card.Plan, message: str, branch: str, push: bool = True) -> str:
    paths = [str(path) for path in evidence_paths(plan)]
    if paths:
        git("add", "--", *paths)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return "nothing to commit"
    trailer = os.environ.get("RETICLE_COMMIT_TRAILER", DEFAULT_TRAILER)
    git("commit", "-q", "-m", message, "-m", trailer)
    if not push:
        return "committed"
    for attempt in range(4):
        pushed = git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", check=False)
        if pushed.returncode == 0:
            return "committed and pushed"
        time.sleep(2 ** (attempt + 1))
    return f"committed; push failed: {pushed.stderr.strip()[-300:]}"


def over_spend(cost: float, cap: Optional[float]) -> bool:
    return cap is not None and cost > cap


def interrupt(process: subprocess.Popen, grace: float = 180.0) -> None:
    """SIGINT to the campaign's process group (run_card releases its lock in `finally`), then SIGKILL after grace."""
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def child_environment() -> dict:
    environment = dict(os.environ)
    environment.update({name: "1" for name in THREAD_VARIABLES})
    return environment


def start_campaign(plan: run_card.Plan, python: str, log_path: Path, lock_path: Optional[Path] = None) -> subprocess.Popen:
    command = [python, str(RUN_CARD), str(plan.card_path), "--execute", "--resume", "--python", python]
    if lock_path is not None:
        command += ["--lock", str(lock_path)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    handle.write(f"# {utc_now()} {' '.join(command)}\n")
    handle.flush()
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
        options["preexec_fn"] = lambda: os.nice(19)
    try:
        return subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, env=child_environment(),
                                **options)
    finally:
        handle.close()  # the child holds its own copy


def supervise(plan: run_card.Plan, branch: Optional[str], *, python: str = sys.executable, commit_every: int = 10,
              poll_seconds: float = 60.0, spend_cap: Optional[float] = None, push: bool = True,
              lock_path: Optional[Path] = None, out=print) -> int:
    if branch is not None:
        current = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if current != branch:
            out(f"refused: the checkout is on {current}, not {branch}; check out the results branch first")
            return run_card.EXIT_REFUSED
    cap = spend_cap if spend_cap is not None else plan.card["budgets"]["campaign"].get("list_price_cap_usd")
    log_path = run_card.Campaign(plan).directory / "driver.log"
    process = start_campaign(plan, python, log_path, lock_path)
    log_supervisor(plan, "start", pid=process.pid, supervisor_pid=os.getpid(), branch=branch,
                   commit_every=commit_every, spend_cap_usd=cap)
    committed_at, guard = status(plan)["runs_finished"], None
    while True:
        try:
            exit_code = process.wait(timeout=poll_seconds)
            break
        except subprocess.TimeoutExpired:
            pass
        value = status(plan)
        if branch is not None and value["runs_finished"] >= committed_at + commit_every:
            result = commit_evidence(plan, f"data({plan.card['run_prefix']}): cloud evidence after "
                                           f"{value['runs_finished']} finished runs", branch, push)
            committed_at = value["runs_finished"]
            log_supervisor(plan, "commit", runs_finished=committed_at, result=result)
        if over_spend(value["nested_cost_usd"], cap):
            guard = f"spend guard: nested model cost ${value['nested_cost_usd']:.2f} passed the cap ${cap:.2f}"
            log_supervisor(plan, "spend_guard", cost=value["nested_cost_usd"], cap=cap)
            out(guard)
            interrupt(process)
            exit_code = process.returncode
            break
    value = status(plan)
    detail = guard or f"run_card exited {exit_code}"
    record = {"exit_code": exit_code, "detail": detail, "finished_at": utc_now()}
    path = run_card.write_report(plan)  # run_card wrote it too, unless the spend guard interrupted it
    if branch is not None:
        result = commit_evidence(plan, f"data({plan.card['run_prefix']}): cloud campaign stopped after "
                                       f"{value['runs_finished']} finished runs ({detail})", branch, push)
        record["commit"] = result
    log_supervisor(plan, "end", **record, status=value)
    out(status_line(value))
    out(f"report: {run_card.display_path(path)}")
    return exit_code if isinstance(exit_code, int) else run_card.EXIT_CHECKPOINT


def alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        found = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in found.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait(plan: run_card.Plan, timeout: float, poll: float = 20.0, out=print) -> str:
    """Block until the latest supervisor has logged its end, has died without one, or timeout seconds pass; print
    one line starting with FINISHED, GONE (the supervisor process is gone without an end: stop and look), or RUNNING.
    Returns that word."""
    deadline = time.monotonic() + timeout
    while True:
        events = run_card.read_jsonl(supervisor_path(plan))
        starts = [i for i, e in enumerate(events) if e.get("event") == "start"]
        if not starts:
            state = "GONE"
        elif any(e.get("event") == "end" for e in events[starts[-1]:]):
            state = "FINISHED"
        elif not alive(events[starts[-1]].get("supervisor_pid")):
            state = "GONE"
        else:
            state = "RUNNING"
        if state != "RUNNING" or time.monotonic() >= deadline:
            break
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
    out(f"{state} " + status_line(status(plan)))
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["controls", "run", "wait", "status", "report"])
    parser.add_argument("card", type=Path)
    parser.add_argument("--branch", default=None, help="run: the results branch to commit to and push")
    parser.add_argument("--commit-every", type=int, default=10)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--spend-cap", type=float, default=None, help="run: USD at CLI list price (default: the card's)")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--timeout", type=float, default=540.0, help="wait: seconds")
    parser.add_argument("--smoke", type=Path, default=None, help="status: the smoke's calls.jsonl")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    plan = load_plan(args.card)
    if args.command == "controls":
        return run_controls(plan, python=args.python)
    if args.command == "run":
        if args.branch is None:
            raise SystemExit("run needs --branch (the results branch)")
        return supervise(plan, args.branch, python=args.python, commit_every=args.commit_every,
                         poll_seconds=args.poll_seconds, spend_cap=args.spend_cap, push=not args.no_push)
    if args.command == "wait":
        wait(plan, args.timeout)
        return 0
    if args.command == "report":
        print(run_card.display_path(run_card.write_report(plan)))
        return 0
    value = status(plan, args.smoke)
    print(json.dumps(value, indent=2) if args.json else status_line(value))
    return 0


if __name__ == "__main__":
    sys.exit(main())
