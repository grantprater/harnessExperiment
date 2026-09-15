"""Interface friction metrics for runner sessions, computed from saved logs only.

Per run:
- tool calls, rejected calls and rate, tool errors;
- recovery turns after each rejected call: responses until the same tool next runs without a
  rejection (None = never recovered in the run);
- unsuccessful lookups: searches that returned 0 matches, and reads/listings that errored;
- first meaningful actions, as response number and seconds from the first request: first command
  (`run`), first successful edit of a file that existed at the task's base commit, and first
  successful edit of any file.

Accepted repairs remain the primary outcome; these numbers describe how the interface was used.

Usage: python experiments/session_harness/interface_friction.py RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.context import TranscriptStore  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402

LOOKUP_TOOLS = {"search_text", "search", "search_output", "search_history"}
READ_TOOLS = {"read_file", "glob_files", "list_files", "outline", "read_output", "read_artifact"}
EDIT_TOOLS = {"write_file", "replace_text"}


def summarize_actions(actions: list[dict], base_files: set[str]) -> dict:
    rejected = [a for a in actions if a["status"] == "rejected"]
    recovery = []
    for action in rejected:
        later = next((b for b in actions if b["response"] > action["response"]
                      and b["tool"] == action["tool"] and b["status"] != "rejected"), None)
        recovery.append(None if later is None else later["response"] - action["response"])

    def first(predicate):
        hit = next((a for a in actions if predicate(a)), None)
        return None if hit is None else {"response": hit["response"], "seconds": hit.get("seconds")}

    total = len(actions)
    return {
        "tool_calls": total,
        "rejected": len(rejected),
        "rejected_rate": round(len(rejected) / total, 3) if total else None,
        "errors": sum(1 for a in actions if a["status"] == "error"),
        "recovery_turns": recovery,
        "failed_lookups": sum(
            1 for a in actions
            if (a["tool"] in LOOKUP_TOOLS and a["status"] == "success"
                and any(line.startswith("0 match(es)") for line in a["content"].splitlines()))
            or (a["tool"] in READ_TOOLS and a["status"] == "error")
        ),
        "first_command": first(lambda a: a["tool"] == "run" and a["status"] != "rejected"),
        "first_base_file_edit": first(lambda a: a["tool"] in EDIT_TOOLS and a["status"] == "success"
                                      and a.get("path") in base_files),
        "first_any_edit": first(lambda a: a["tool"] in EDIT_TOOLS and a["status"] == "success"),
    }


def load_actions(run_dir: Path) -> tuple[dict, list[dict]]:
    result = json.loads((run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    return result, actions_from_session(run_dir / "sessions" / result["run_id"] / "session", run_dir / "calls.jsonl")


def actions_from_session(session_dir: Path, calls_path: Path) -> list[dict]:
    runtime = LocalRuntime(session_dir)
    transcript = TranscriptStore(runtime).load()
    calls = ([json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
             if calls_path.exists() else [])
    responses = [c for c in calls if (c.get("response") or {}).get("choices")]
    start = datetime.fromisoformat(calls[0]["time"]) if calls else None
    results = {m.get("tool_call_id"): m for m in transcript if m.get("role") == "tool"}
    actions, response_number = [], 0
    for message in transcript:
        if message.get("role") != "assistant":
            continue
        response_number += 1
        seconds = None
        if start is not None and response_number <= len(responses):
            row = responses[response_number - 1]
            seconds = round((datetime.fromisoformat(row["time"]) - start).total_seconds() + (row.get("latency_s") or 0), 1)
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_message = results.get(tool_call.get("id")) or {}
            actions.append({
                "response": response_number,
                "tool": function.get("name"),
                "status": (tool_message.get("_reticle_output") or {}).get("status"),
                "content": tool_message.get("content", ""),
                "path": arguments.get("path") if isinstance(arguments, dict) else None,
                "seconds": seconds,
            })
    return actions


def base_files_for(task_id: str) -> set[str]:
    tasks = {t["task_id"]: t for t in json.loads((ROOT / "experiments" / "p6_pilot" / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
    task = tasks[task_id]
    repo = ROOT / ".runtime" / "bug-mining" / "repos" / task["repo"]
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", task["base_commit"]],
                             capture_output=True, text=True, check=True).stdout
    return set(listing.splitlines())


def main() -> None:
    rows = []
    for argument in sys.argv[1:]:
        run_dir = Path(argument)
        result, actions = load_actions(run_dir)
        summary = summarize_actions(actions, base_files_for(result["task_id"]))
        rows.append((run_dir.name, result, summary))
        print(json.dumps({"run": run_dir.name, **summary}))
    print()
    print("| run | stop | acceptance | tool calls | rejected (rate) | recovery turns | failed lookups | first command (resp / s) | first base-file edit | first any edit |")
    print("|---|---|---|---:|---|---|---:|---|---|---|")
    fmt = lambda item: "-" if item is None else f"{item['response']} / {item['seconds']}"
    for name, result, s in rows:
        print(f"| {name} | {result.get('stop') or result['agent'].get('stop_reason')} | {result['acceptance']['status']} | "
              f"{s['tool_calls']} | {s['rejected']} ({s['rejected_rate']}) | {s['recovery_turns']} | {s['failed_lookups']} | "
              f"{fmt(s['first_command'])} | {fmt(s['first_base_file_edit'])} | {fmt(s['first_any_edit'])} |")


if __name__ == "__main__":
    main()
