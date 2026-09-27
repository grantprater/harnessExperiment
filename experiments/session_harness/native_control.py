"""Arm N of E3-positive-control-006: the same repair task through a conventional coding harness.

Materializes the task's base commit exactly as the P6 runner does (ensure_commits and
materialize_workspace, no git history), gives the headless Claude Code CLI the Reticle arm's
opening request verbatim (run_pilot.INSTRUCTIONS with the task statement), and lets it work in
that workspace with its own coding tools. The final workspace is then scored by the runner's
evaluator path (build_evaluator, acceptance_plan, AcceptanceRunner) on the selected backend.

The CLI runs on the host with bypassPermissions. Its network access cannot be disabled; the
transcript is audited afterwards for network commands and paths outside the workspace. The
evaluator bundle (which holds the fix commit's tests) is built only after the CLI has exited,
and the workspace lives outside this repository, so neither is on disk near the workspace while
the model works. The task's Python environment (the runner's trusted-local interpreter, with
pytest) is first on PATH and PYTHONPATH is the workspace, as for the runner's run tool.

`--output-format stream-json --verbose` is used instead of `json`: the final `result` event is the
object `json` prints, and the stream also records every tool call, which the report needs.

Usage (from the repo root):
  python experiments/session_harness/native_control.py --task sqlparse-865 --model sonnet \\
      --max-turns 20 --wall-seconds 1200 --backend oci --run-name pc-native-sonnet-1 [--dry-run]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402
from claude_cli import child_environment, cli_version, resolve_executable  # noqa: E402
from reticle.evaluation import AcceptanceRunner  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402

NATIVE_VERSION = 1
# The CLI's coding tools. Excluded from its default set: Agent and other session/scheduling tools
# (sub-agents would spend model calls outside the matched turn budget), WebFetch/WebSearch (the most
# direct route to the upstream fix), notebooks, worktrees, and skills.
NATIVE_TOOLS = "Bash,PowerShell,Read,Edit,Write,Glob,Grep"
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
COMMAND_TOOLS = {"Bash", "PowerShell"}
PATH_KEYS = ("file_path", "path", "notebook_path")
NETWORK_PATTERN = re.compile(
    r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|pip3?\s+install|pip\s+download|git\s+clone|"
    r"git\s+fetch|git\s+pull|npm\s+install)\b|https?://", re.IGNORECASE)
ABSOLUTE_PATH = re.compile(r"(?:(?<!\w)[A-Za-z]:[\\/]|(?<![\w.:/])/[a-z]/)[^\s\"'`|;&<>]*")  # not URLs
CACHE_EXCLUDES = "__pycache__/\n.pytest_cache/\n*.pyc\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def native_arguments(model: str, max_turns: int, tools: str = NATIVE_TOOLS) -> list:
    return ["-p", "--model", model, "--max-turns", str(max_turns), "--permission-mode", "bypassPermissions",
            "--output-format", "stream-json", "--verbose", "--setting-sources", "", "--no-session-persistence",
            "--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--tools", tools]


def kill_tree(process: subprocess.Popen) -> None:
    """Stop the CLI and every process it started (only processes this script launched)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)


def run_cli(argv: list, prompt: str, cwd: Path, env: dict, wall_seconds: float, stream_path: Path,
            stderr_path: Path) -> dict:
    """Run the CLI with a hard wall-clock cap, recording each stdout line with its arrival time."""
    events: list = []
    start = time.monotonic()
    with stream_path.open("w", encoding="utf-8") as sink, stderr_path.open("wb") as err:
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=err, start_new_session=(os.name != "nt"))

        def pump():
            for raw in iter(process.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"unparsed": line}
                record = {"t": round(time.monotonic() - start, 2), "event": event}
                events.append(record)
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        timed_out = False
        try:
            process.wait(timeout=wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(process)
            process.wait()
        reader.join(timeout=30)
    return {"timed_out": timed_out, "exit_code": process.returncode,
            "wall_seconds": round(time.monotonic() - start, 1), "events": events}


def _inside(path_text: str, workspace: Path) -> bool:
    text = path_text.strip().strip("\"'")
    if re.match(r"^/[a-z]/", text):  # Git Bash form of a Windows drive path
        text = f"{text[1]}:/{text[3:]}"
    try:
        resolved = (workspace / text).resolve() if not os.path.isabs(text) else Path(text).resolve()
        resolved.relative_to(workspace.resolve())
        return True
    except (ValueError, OSError):
        return False


def summarize_stream(events: list, workspace: Path, base_files: set, allowed_roots: tuple = ()) -> dict:
    init = next((r["event"] for r in events if r["event"].get("type") == "system"
                 and r["event"].get("subtype") == "init"), None)
    result = next((r["event"] for r in reversed(events) if r["event"].get("type") == "result"), None)
    response_ids, uses, results = [], [], {}
    for record in events:
        event = record["event"]
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            if message.get("id") not in response_ids:
                response_ids.append(message.get("id"))
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    uses.append({"response": response_ids.index(message.get("id")) + 1, "seconds": record["t"],
                                 "id": block.get("id"), "name": block.get("name"), "input": block.get("input") or {}})
        elif event.get("type") == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[block.get("tool_use_id")] = bool(block.get("is_error"))
    for use in uses:
        use["is_error"] = results.get(use["id"])

    def relative(use):
        for key in PATH_KEYS:
            value = use["input"].get(key)
            if isinstance(value, str) and _inside(value, workspace):
                full = (workspace / value).resolve() if not os.path.isabs(value) else Path(value).resolve()
                return full.relative_to(workspace.resolve()).as_posix()
        return None

    def first(predicate):
        hit = next((u for u in uses if predicate(u)), None)
        return None if hit is None else {"response": hit["response"], "seconds": hit["seconds"], "tool": hit["name"]}

    outside, network = [], []
    for use in uses:
        for key in PATH_KEYS:
            value = use["input"].get(key)
            if isinstance(value, str) and not _inside(value, workspace):
                outside.append({"response": use["response"], "tool": use["name"], key: value})
        command = use["input"].get("command")
        if isinstance(command, str):
            if NETWORK_PATTERN.search(command):
                network.append({"response": use["response"], "tool": use["name"], "command": command[:300]})
            for path_text in ABSOLUTE_PATH.findall(command):
                if not _inside(path_text, workspace) and not any(
                        _inside(path_text, root) for root in allowed_roots):
                    outside.append({"response": use["response"], "tool": use["name"], "command_path": path_text})
    by_name: dict = {}
    for use in uses:
        by_name[use["name"]] = by_name.get(use["name"], 0) + 1
    commands = [u for u in uses if u["name"] in COMMAND_TOOLS]
    return {
        "init": None if init is None else {k: init.get(k) for k in (
            "model", "tools", "mcp_servers", "apiKeySource", "permissionMode", "claude_code_version", "skills",
            "slash_commands", "cwd")},
        "result": None if result is None else {k: result.get(k) for k in (
            "subtype", "is_error", "num_turns", "stop_reason", "terminal_reason", "duration_ms", "duration_api_ms",
            "total_cost_usd", "usage", "permission_denials", "result")},
        "responses": len(response_ids),
        "tool_calls": len(uses),
        "tool_calls_by_name": by_name,
        "tool_errors": sum(1 for u in uses if u["is_error"]),
        "first_command": first(lambda u: u["name"] in COMMAND_TOOLS),
        "first_base_file_edit": first(lambda u: u["name"] in EDIT_TOOLS and u["is_error"] is False
                                      and relative(u) in base_files),
        "first_any_edit": first(lambda u: u["name"] in EDIT_TOOLS and u["is_error"] is False),
        "test_commands": sum(1 for u in commands if "pytest" in (u["input"].get("command") or "")),
        "edited_files": sorted({relative(u) or str(u["input"].get("file_path"))
                                for u in uses if u["name"] in EDIT_TOOLS and u["is_error"] is False}),
        "audit": {"paths_outside_workspace": outside, "network_commands": network,
                  "tools_outside_allowed_set": sorted(set(by_name) - set(NATIVE_TOOLS.split(",")))},
        "tool_sequence": [{"response": u["response"], "seconds": u["seconds"], "tool": u["name"],
                           "is_error": u["is_error"], "input": json.dumps(u["input"], ensure_ascii=False)[:200]}
                          for u in uses],
    }


def workspace_diff(pristine: Path, workspace: Path) -> dict:
    """`git diff --stat` of the final workspace against an untouched export of the base commit.

    The git directory lives in the pristine copy, never in the workspace; cache files are excluded.
    """
    git = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
           "-c", "user.name=native-control", "-c", "user.email=native-control@localhost"]
    subprocess.run([*git, "init", "-q", str(pristine)], check=True)
    (pristine / ".git" / "info" / "exclude").write_text(CACHE_EXCLUDES, encoding="utf-8")
    subprocess.run([*git, "-C", str(pristine), "add", "-A", "-f"], check=True)
    subprocess.run([*git, "-C", str(pristine), "commit", "-q", "-m", "base"], check=True)
    tree = [*git, f"--git-dir={pristine / '.git'}", f"--work-tree={workspace}"]

    def out(*args):
        return subprocess.run([*tree, *args], capture_output=True, check=True).stdout.decode("utf-8", "replace")

    out("add", "-A")
    ignored = [line[3:] for line in out("status", "--porcelain", "--ignored").splitlines()
               if line.startswith("!! ") and not any(part in line for part in ("__pycache__", ".pytest_cache", ".pyc"))]
    return {"stat": out("diff", "--cached", "--stat"), "numstat": out("diff", "--cached", "--numstat"),
            "patch": out("diff", "--cached"), "ignored_untracked": ignored}


def base_files_for(repo: Path, task: dict) -> set:
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", task["base_commit"]],
                             capture_output=True, text=True, check=True).stdout
    return set(listing.splitlines())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--wall-seconds", type=float, default=1200.0)
    parser.add_argument("--backend", default="trusted-local", choices=["trusted-local", "oci"])
    parser.add_argument("--oci-image", default=run_pilot.DEFAULT_OCI_IMAGE)
    parser.add_argument("--pytest-timeout", type=int, default=600)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--scratch-root", default=None,
                        help="where the workspace lives (default: the system temp folder, outside this repository)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tasks = {t["task_id"]: t for t in json.loads((run_pilot.HERE / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
    if args.task not in tasks:
        raise SystemExit(f"Unknown task: {args.task}")
    task = tasks[args.task]
    backend, execution = run_pilot.resolve_execution(args.backend, args.oci_image)
    executable = resolve_executable("claude")
    if executable is None:
        raise SystemExit("claude is not on PATH")
    record_dir = HERE / "native_runs" / args.run_name
    scratch = Path(args.scratch_root or tempfile.gettempdir()).resolve() / "reticle-native-control" / args.run_name
    workspace, pristine = scratch / "workspace", scratch / "pristine"
    prompt = run_pilot.INSTRUCTIONS.format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"])
    arguments = native_arguments(args.model, args.max_turns)
    config = {
        "native_version": NATIVE_VERSION, "task_id": task["task_id"], "model": args.model,
        "cli_version": cli_version(), "arguments": arguments, "prompt": prompt,
        "prompt_source": "run_pilot.INSTRUCTIONS.format(repo, repo_url, statement): the Reticle arm's opening request",
        "budgets": {"max_turns": args.max_turns, "wall_seconds": args.wall_seconds, "enforcement":
                    "--max-turns in the CLI; hard kill of the CLI process tree at the wall cap"},
        "workspace": str(workspace), "execution": execution, "pytest_timeout_seconds": args.pytest_timeout,
        "environment_added": {"PATH": f"{run_pilot.TASK_PYTHON.parent} (prepended)", "PYTHONPATH": "workspace",
                              "PYTHONIOENCODING": "utf-8", "OMP/MKL/OPENBLAS_NUM_THREADS": "1"},
        "authority": "host process with bypassPermissions (not isolated); network available, cannot be disabled",
        "evaluator": "run_pilot.build_evaluator + acceptance_plan + AcceptanceRunner on the final workspace",
    }
    print(json.dumps({k: v for k, v in config.items() if k != "prompt"}, indent=2))
    if args.dry_run:
        print(prompt)
        return
    if record_dir.exists() or scratch.exists():
        raise SystemExit(f"{record_dir} or {scratch} exists; use a new --run-name")
    record_dir.mkdir(parents=True)
    repo = run_pilot.ensure_commits(task)
    run_pilot.materialize_workspace(task, repo, workspace)
    runtime = LocalRuntime(scratch / "session", workspace)
    initial_revision = runtime.workspace.revision()
    config.update(created_at=utc_now(), source_revision=run_pilot.source_revision(), initial_workspace_revision=initial_revision)
    (record_dir / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    src = workspace / "src"
    environment, removed = child_environment({
        "PATH": str(run_pilot.TASK_PYTHON.parent) + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONPATH": str(src if src.is_dir() else workspace), "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    })
    started_at = utc_now()
    print(f"running the CLI in {workspace} (wall cap {args.wall_seconds:.0f} s, max turns {args.max_turns})", flush=True)
    run = run_cli([executable, *arguments], prompt, workspace, environment, args.wall_seconds,
                  record_dir / "stream.jsonl", record_dir / "stderr.txt")
    summary = summarize_stream(run["events"], workspace, base_files_for(repo, task),
                               allowed_roots=(run_pilot.TASK_PYTHON.parent.parent,))
    run_pilot.materialize_workspace(task, repo, pristine)  # after the run, so the CLI never sees a second tree
    diff = workspace_diff(pristine, workspace)
    (record_dir / "diff.patch").write_text(diff["patch"], encoding="utf-8")

    # The evaluator bundle holds the fix commit's tests: built only now that the CLI has exited.
    bundle = scratch / "evaluator"
    version = run_pilot.build_evaluator(task, repo, bundle, args.pytest_timeout, execution["guest_python"])
    decision = AcceptanceRunner(runtime, backend).evaluate(
        run_pilot.acceptance_plan(task, version), evaluator_root=bundle, timeout_seconds=args.pytest_timeout + 120)
    record = {
        "run_name": args.run_name, "task_id": task["task_id"], "model": args.model, "started_at": started_at,
        "finished_at": utc_now(), "wall_seconds": run["wall_seconds"], "timed_out": run["timed_out"],
        "exit_code": run["exit_code"], "turns_used": (summary["result"] or {}).get("num_turns"),
        "removed_environment": removed, **summary,
        "diff_stat": diff["stat"], "diff_numstat": diff["numstat"], "ignored_untracked_files": diff["ignored_untracked"],
        "initial_workspace_revision": initial_revision,
        "acceptance": {"status": decision.status, "criterion_outcomes": decision.criterion_outcomes,
                       "report_artifact_id": decision.report_artifact_id,
                       **run_pilot.evaluator_details(runtime, decision.report_artifact_id)},
        "billing": "unknown (local Claude Code subscription login); total_cost_usd is the CLI's list-price estimate",
    }
    (record_dir / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("wall_seconds", "timed_out", "turns_used", "responses", "tool_calls",
                                              "tool_calls_by_name", "first_base_file_edit", "acceptance")}, indent=2))
    print(diff["stat"])


if __name__ == "__main__":
    main()
