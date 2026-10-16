"""Card 019: serial Reticle-v4 / native Codex block, shared sealed evaluator.

--probe verifies the native sandbox without calling a model. --execute requires
the existing gold/noop controls, takes the shared live lock, and records results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native_control as native
import run_card

pilot = native.run_pilot
ROOT = pilot.ROOT
BANK = ROOT / "experiments/mutation_tasks/tasks.mutations.json"
OUT = HERE / "c019_runs"
PILOT_RUNS = ROOT / "experiments/p6_pilot/runs"
CODEX = Path("C:/Users/grant/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe")
TASKS = ("sqlparse-mut-032", "sqlparse-mut-061")
ORDER = ((TASKS[0], "reticle"), (TASKS[0], "codex"),
         (TASKS[1], "codex"), (TASKS[1], "reticle"))
PILOT_METADATA = {
    "evidence_class": "exploratory_pilot",
    "equivalent_to_controlled_cards": False,
    "pool_with_existing_cards": False,
    "limitations": ["different models and response budgets", "selected known failures",
                    "parallel workloads may affect latency and cache reuse",
                    "four trials; no statistical or promotion decision"],
}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def records(path):
    return run_card.read_jsonl(path)


def overrides(workspace):
    # Elevated Windows currently requires root read; deny experiment material
    # explicitly, then grant the Python environments and candidate workspace.
    filesystem = {":root": "read",
                  BANK.resolve().as_posix(): "deny",
                  (ROOT / ".runtime/bug-mining/repos/sqlparse").resolve().as_posix(): "deny",
                  workspace.parent.resolve().as_posix(): "deny",
                  ":workspace_roots": {".": "write"}}
    for root in native.interpreter_roots(native.task_interpreter()):
        filesystem[root.resolve().as_posix()] = "read"
    values = {
        "default_permissions": "mini",
        "permissions.mini.filesystem": filesystem,
        "permissions.mini.network.enabled": False,
        "approval_policy": "never", "windows.sandbox": "elevated",
        "model_reasoning_effort": "medium", "project_doc_max_bytes": 0,
        "web_search": "disabled", "features.multi_agent": False,
        "features.memories": False, "features.plugins": False,
        "features.apps": False, "features.hooks": False,
    }
    def toml(v):
        if isinstance(v, dict):
            return "{" + ", ".join(json.dumps(k) + " = " + toml(x) for k, x in v.items()) + "}"
        return json.dumps(v)
    args = []
    for key, value in values.items():
        args += ["-c", key + "=" + toml(value)]
    return args


def environment(workspace):
    env, removed = native.child_environment({
        "PATH": str(native.task_interpreter().parent) + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONPATH": str(workspace), "PYTHONIOENCODING": "utf-8",
    })
    # Prevent a child CLI from connecting to this task's app-server/session.
    for key in list(env):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            removed.append(key)
            del env[key]
    return env, removed


def probe():
    scratch = Path(tempfile.mkdtemp(prefix="reticle-c019-probe-"))
    workspace = scratch / "work"
    workspace.mkdir()
    canary = scratch / "hidden-canary.txt"
    canary.write_text("hidden evaluator sentinel", encoding="utf-8")
    code = ("import json,pathlib,socket\n"
            "p=pathlib.Path('probe-write.txt'); p.write_text('ok')\n"
            "try:\n pathlib.Path(" + repr(str(canary)) + ").read_text(); blocked=False\n"
            "except (PermissionError,OSError):\n blocked=True\n"
            "try:\n s=socket.create_connection(('1.1.1.1',443),timeout=3); s.close(); net=False\n"
            "except OSError:\n net=True\n"
            "print(json.dumps(dict(workspace_write=p.read_text()=='ok',hidden_read_blocked=blocked,network_blocked=net)))")
    args = [str(CODEX), "sandbox", "-P", "mini", "-C", str(workspace),
            *overrides(workspace), str(native.task_interpreter()), "-c", code]
    env, removed = environment(workspace)
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    data = {"argv": args, "exit_code": result.returncode, "stdout": result.stdout,
            "stderr": result.stderr, "removed_environment": removed, "scratch": str(scratch)}
    try:
        data["checks"] = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        data["checks"] = {}
    data["passed"] = result.returncode == 0 and all(data["checks"].get(k) is True for k in
        ("workspace_write", "hidden_read_blocked", "network_blocked"))
    save(OUT / "sandbox-probe.json", data)
    print(json.dumps(data, indent=2), flush=True)
    return data["passed"]


def controls():
    expected = {}
    for client, status in (("gold", "accepted"), ("noop", "rejected")):
        path = PILOT_RUNS / f"c019-controls-{client}" / "results.jsonl"
        rows = records(path)
        for task_id in TASKS:
            row = next((r for r in rows if r["task_id"] == task_id), None)
            if row is None or row["acceptance"]["status"] != status:
                raise RuntimeError(f"missing or failed {client} control: {task_id}")
            if client == "gold":
                expected[task_id] = row["initial_workspace_revision"]
    return expected


def summarize_codex(events):
    completed = [r for r in events if r["event"].get("type") == "item.completed"]
    items = [r["event"].get("item", {}) for r in completed]
    usage = [r["event"].get("usage") for r in events if r["event"].get("type") == "turn.completed"]
    errors = [r["event"] for r in events if r["event"].get("type") in ("error", "turn.failed")]
    edits = [r for r in completed if r["event"].get("item", {}).get("type") == "file_change"]
    calls = [i for i in items if i.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search")]
    # Command-based edits are not classified as first edits by this metric.
    return {"usage": usage, "errors": errors, "completed_items": len(items),
            "tool_actions": len(calls), "responses": sum(i.get("type") == "agent_message" for i in items),
            "first_file_change_seconds": edits[0]["t"] if edits else None,
            "first_edit_metric": "file_change events only; shell-based edits may occur earlier"}


def codex_run(task, expected):
    name = f"c019-{task['task_id']}-r1-codex"
    record_dir = OUT / name
    if record_dir.exists():
        raise RuntimeError(f"refusing existing run: {record_dir}")
    scratch = Path(tempfile.mkdtemp(prefix=name + "-"))
    workspace = scratch / "workspace"
    repo = pilot.ensure_commits(task)
    pilot.materialize_workspace(task, repo, workspace)
    runtime = native.LocalRuntime(scratch / "session", workspace)
    initial = runtime.workspace.revision()
    if initial != expected:
        raise RuntimeError(f"starting hash mismatch: {initial} != {expected}")
    if any((workspace / path).exists() for path in task.get("hidden_paths", [])):
        raise RuntimeError("hidden paths present")
    argv = [str(CODEX), "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--json", "--color", "never", "-m", "gpt-6.1-sol",
            "-C", str(workspace), *overrides(workspace), "-"]
    prompt = native.opening_prompt(task)
    env, removed = environment(workspace)
    record_dir.mkdir(parents=True)
    save(record_dir / "config.json", {"argv": argv, "prompt": prompt,
        **PILOT_METADATA,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "model": "gpt-6.1-sol", "reasoning_effort": "medium", "wall_seconds": 1200,
        "initial_workspace_revision": initial, "scratch": str(scratch),
        "removed_environment": removed, "execution": pilot.resolve_execution("oci", pilot.DEFAULT_OCI_IMAGE)[1]})
    run = native.run_cli(argv, prompt, workspace, env, 1200,
                         record_dir / "stream.jsonl", record_dir / "stderr.txt")
    summary = summarize_codex(run.pop("events"))
    # Neither the evaluator nor the pristine tree exists during the agent run.
    pristine, bundle = scratch / "pristine", scratch / "evaluator"
    pilot.materialize_workspace(task, repo, pristine)
    diff = native.workspace_diff(pristine, workspace)
    (record_dir / "diff.patch").write_text(diff["patch"], encoding="utf-8")
    backend, execution = pilot.resolve_execution("oci", pilot.DEFAULT_OCI_IMAGE)
    version = pilot.build_evaluator(task, repo, bundle, 600, execution["guest_python"])
    decision = native.AcceptanceRunner(runtime, backend).evaluate(
        pilot.acceptance_plan(task, version), evaluator_root=bundle, timeout_seconds=720)
    details = pilot.evaluator_details(runtime, decision.report_artifact_id)
    result = {"task_id": task["task_id"], "arm": "codex", "run_name": name,
              **PILOT_METADATA,
              "initial_workspace_revision": initial, **run, **summary,
              "acceptance": {"status": decision.status, "criterion_outcomes": decision.criterion_outcomes,
                             "test_counts": native.evaluator_test_counts(task, details), **details},
              "valid": (run["timed_out"] or run["exit_code"] == 0) and not summary["errors"],
              "audit_status": "sandbox probe passed; transcript still requires review for leaks",
              "scratch": str(scratch)}
    save(record_dir / "result.json", result)
    return result


def reticle_run(task, expected):
    name = f"c019-{task['task_id']}-r1-reticle"
    argv = [sys.executable, str(ROOT / "experiments/p6_pilot/run_pilot.py"),
            "--client", "claude-cli", "--models", "sonnet", "--backend", "oci",
            "--arm", "pressure-recent-v4", "--tasks", str(BANK), task["task_id"],
            "--run-name", name, "--max-calls-per-run", "20", "--max-attempts-per-run", "24",
            "--max-total-calls", "24", "--elapsed-cap-seconds", "1200", "--max-tokens", "4096"]
    record_dir = OUT / name
    record_dir.mkdir(exist_ok=False, parents=True)
    save(record_dir / "invocation.json", {"argv": argv})
    with (record_dir / "stdout.txt").open("wb") as out, (record_dir / "stderr.txt").open("wb") as err:
        subprocess.run(argv, cwd=ROOT, stdout=out, stderr=err, check=True, timeout=1800)
    row, = records(PILOT_RUNS / name / "results.jsonl")
    if row["initial_workspace_revision"] != expected:
        raise RuntimeError("Reticle starting hash differs")
    row["arm_label"] = "reticle"
    row["run_name"] = name
    row.update(PILOT_METADATA)
    calls = records(PILOT_RUNS / name / "calls.jsonl")
    usages = [(call.get("cli_result") or {}).get("usage") for call in calls]
    cache_keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    complete = bool(usages) and all(isinstance(u, dict) and all(k in u for k in cache_keys) for u in usages)
    row["cache_usage"] = {"reported_calls": sum(isinstance(u, dict) for u in usages),
                          "calls": len(calls), "complete": complete}
    if complete:
        totals = {key: sum(u[key] for u in usages) for key in cache_keys}
        denominator = sum(totals.values())
        row["cache_usage"].update(totals, cache_read_share=totals["cache_read_input_tokens"] / denominator
                                 if denominator else None)
    run_root = PILOT_RUNS / name / "sessions" / row["run_id"]
    pristine = record_dir / "pristine"
    pilot.materialize_workspace(task, pilot.ensure_commits(task), pristine)
    diff = native.workspace_diff(pristine, run_root / "workspace")
    (record_dir / "diff.patch").write_text(diff["patch"], encoding="utf-8")
    save(record_dir / "result.json", row)
    return row


def report(results, state):
    lines = ["# P019 exploratory pilot results", "", f"Status: {state}.", "",
             "Evidence class: exploratory pilot; separate from the controlled experiment cards.",
             "Do not pool these results with existing cards or use them as equivalent evidence.",
             "Other campaigns may run concurrently; timing and cache behavior are descriptive.", "",
             "Reticle: Sonnet / pressure-recent-v4. Codex: gpt-6.1-sol / medium.", "",
             "| Task | Arm | Accepted | Seconds | Responses | Tool actions | Cache usage |",
             "|---|---|---|---|---|---|---|"]
    for row in results:
        if row.get("arm") == "codex":
            seconds, responses, tools = row["wall_seconds"], row["responses"], row["tool_actions"]
            cache = json.dumps(row["usage"])
            valid = row["valid"]
        else:
            seconds, responses, tools = row["elapsed_s"], row["totals"]["model_calls"], row["totals"]["tool_calls"]
            share = row["cache_usage"].get("cache_read_share")
            cache = f"{share:.1%} reads" if share is not None else "unknown (missing provider fields)"
            valid = row["stop"] not in ("model_error",)
        status = row["acceptance"]["status"] + (" (invalid run)" if not valid else "")
        lines.append(f"| {row['task_id']} | {row.get('arm_label', row['arm'])} | {status} | {seconds} | {responses} | {tools} | {cache} |")
    lines += ["", "Provider failures and leaks require separate review. Response counters differ by product.",
              "Final diffs and independent acceptance results are saved per run. No statistical superiority claim."]
    (HERE / "E3-codex-mini-019-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute(parallel=False):
    expected = controls()
    if not json.loads((OUT / "sandbox-probe.json").read_text())["passed"]:
        raise RuntimeError("native sandbox preflight failed")
    lock = run_card.LiveRunLock(OUT / "pilot.lock" if parallel else run_card.default_lock_path())
    queued_at = pilot.utc_now()
    while True:
        try:
            lock.acquire({"owner": "P019 exploratory pilot", "parallel": parallel})
            break
        except run_card.LockHeld:
            holder = lock.holder()
            save(OUT / "campaign.json", {"status": "queued", "pid": os.getpid(),
                                         "queued_at": queued_at, "waiting_for": holder, "order": ORDER})
            report([], f"queued behind {holder}")
            # A background queue, not an active parent polling loop. Never break
            # another campaign's lock, even when its owner appears stale.
            time.sleep(30)
    results = []
    try:
        _, tasks = pilot.load_tasks([str(BANK), *TASKS])
        by_id = {t["task_id"]: t for t in tasks}
        save(OUT / "campaign.json", {"status": "running", "order": ORDER, "pid": os.getpid(),
                                     **PILOT_METADATA, "parallel_with_other_campaigns": parallel,
                                     "started_at": pilot.utc_now(), "expected_hashes": expected})
        for task_id, arm in ORDER:
            print(f"starting {task_id} {arm}", flush=True)
            row = (codex_run if arm == "codex" else reticle_run)(by_id[task_id], expected[task_id])
            results.append(row)
            report(results, "running")
            print(f"finished {task_id} {arm}: {row['acceptance']['status']}", flush=True)
            if arm == "codex" and not row["valid"]:
                raise RuntimeError("Codex infrastructure failure; stop campaign for review")
        report(results, "completed; transcript audit pending")
        save(OUT / "campaign.json", {"status": "completed", "order": ORDER, **PILOT_METADATA,
                                     "parallel_with_other_campaigns": parallel, "finished_at": pilot.utc_now()})
    except Exception as exc:
        report(results, f"stopped: {exc}")
        save(OUT / "campaign-error.json", {"error": repr(exc), "at": pilot.utc_now()})
        raise
    finally:
        lock.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--parallel-pilot", action="store_true",
                        help="owner-authorized exploratory pilot: use a pilot-only duplicate-run lock")
    args = parser.parse_args()
    if args.probe:
        sys.exit(0 if probe() else 1)
    execute(args.parallel_pilot)
