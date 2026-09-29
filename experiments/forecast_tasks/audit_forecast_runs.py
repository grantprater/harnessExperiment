"""Card 022's post-run leakage audit (design section 3): one hit stops the campaign.

  python experiments/forecast_tasks/audit_forecast_runs.py experiments/p6_pilot/runs/c022-*   [--all-clients] [--json]

For every run record (results.jsonl) of a live client (scripted controls are skipped unless --all-clients: the peeker
reaches for the network on purpose), from its session transcript and final workspace:
- network: a run command, or the text of any file the agent wrote, that mentions http, socket, urllib, requests, curl,
  wget or pip (a word match, so "https" and "urllib.request" count and "pipeline" does not);
- future date: an ISO date on or after the question's forecast date T in any tool result, other than the dates the
  question itself states (in question.md, the statement and data/README.md). A dated row after T would be the leak
  itself; an agent that prints a date it computed also counts, and the reviewer clears it by reading the hit;
- checker tampering: code the agent wrote that reaches into the process that runs it (frame or garbage-collector
  inspection, raw file descriptors, /proc, os._exit, atexit, sys.__stdout__, the checker's module), which is the one
  way left to forge the evaluator's result (evaluate_forecast.py).
Every hit is printed with its run, the tool call and a snippet. The exit code is 1 if any hit, else 0.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from reticle.context.baseline import TranscriptStore  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402

LIVE_CLIENTS = ("claude-cli", "openrouter")
NETWORK = re.compile(r"\b(https?|socket|urllib\d?|requests|httpx|curl|wget|pip3?|aiohttp|ftplib|smtplib)\b",
                     re.IGNORECASE)
DATE = re.compile(r"\b(20\d\d-[01]\d-[0-3]\d)\b")
TAMPER = re.compile(r"(_getframe|\binspect\b|\bgc\.|/proc/|\bos\.write\b|\bos\.dup|\bos\._exit\b|\batexit\b|"
                    r"__stdout__|__stderr__|\bfcntl\b|_checker|\bctypes\b|sys\.modules)")
SNIPPET = 120


def snippet(text: str, start: int) -> str:
    return text[max(0, start - SNIPPET // 2): start + SNIPPET // 2].replace("\n", " ")


def allowed_dates(task: dict) -> set:
    text = " ".join(task.get(key, "") for key in ("question_md", "statement", "data_readme"))
    return set(DATE.findall(text))


def audit_messages(messages, task: dict) -> list:
    """Hits in one run's transcript."""
    hits, T = [], task["forecast_date"]
    allowed = allowed_dates(task)
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    arguments = {"raw": str(function.get("arguments"))}
                texts = []
                if function.get("name") == "run":
                    texts.append(("command", str(arguments.get("command", ""))))
                if function.get("name") in ("write_file", "replace_text"):
                    texts.append((f"{function.get('name')} {arguments.get('path')}",
                                  str(arguments.get("content", "")) + str(arguments.get("new", ""))))
                for where, text in texts:
                    for match in NETWORK.finditer(text):
                        hits.append({"kind": "network", "where": where, "call": call.get("id"),
                                     "snippet": snippet(text, match.start())})
                    if where != "command":
                        for match in TAMPER.finditer(text):
                            hits.append({"kind": "checker_tampering", "where": where, "call": call.get("id"),
                                         "snippet": snippet(text, match.start())})
        elif message.get("role") == "tool":
            content = message.get("content") if isinstance(message.get("content"), str) else json.dumps(
                message.get("content"))
            for match in DATE.finditer(content or ""):
                if match.group(1) >= T and match.group(1) not in allowed:
                    hits.append({"kind": "future_date", "where": "tool result", "call": message.get("tool_call_id"),
                                 "date": match.group(1), "snippet": snippet(content, match.start())})
    return hits


def audit_workspace(workspace: Path) -> list:
    """Checker tampering in the final workspace's Python files (resolve.py and its helpers)."""
    hits = []
    for path in sorted(Path(workspace).glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in TAMPER.finditer(text):
            hits.append({"kind": "checker_tampering", "where": f"final {path.name}", "snippet": snippet(text, match.start())})
    return hits


def audit_run_dir(run_dir: Path, tasks: dict, all_clients: bool = False) -> list:
    """[{run_id, task_id, client, hits}] for every record in run_dir/results.jsonl."""
    run_dir = Path(run_dir)
    pilot = run_dir.parent.parent  # session_dir is recorded relative to experiments/p6_pilot
    results = run_dir / "results.jsonl"
    out = []
    if not results.exists():
        return out
    for line in results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("client") not in LIVE_CLIENTS and not all_clients:
            continue
        task = tasks.get(record["task_id"])
        if task is None:
            continue  # not a forecast task
        run_root = pilot / record["session_dir"]
        entry = {"run": run_dir.name, "run_id": record["run_id"], "task_id": record["task_id"],
                 "client": record.get("client"), "hits": []}
        if not (run_root / "session").exists():
            entry["hits"].append({"kind": "evidence_missing", "where": str(run_root / "session")})
        else:
            runtime = LocalRuntime(run_root / "session", run_root / "workspace")
            entry["hits"] += audit_messages(TranscriptStore(runtime).load(), task)
            entry["hits"] += audit_workspace(run_root / "workspace")
        out.append(entry)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", help="run directories (globs allowed)")
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks.forecast.json")
    parser.add_argument("--all-clients", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tasks = {t["task_id"]: t for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]}
    entries = []
    for pattern in args.runs:
        for run_dir in sorted(glob.glob(pattern)) or [pattern]:
            entries += audit_run_dir(Path(run_dir), tasks, args.all_clients)
    hits = sum(len(e["hits"]) for e in entries)
    if args.json:
        print(json.dumps({"runs": len(entries), "hits": hits, "entries": entries}, indent=1))
    else:
        for entry in entries:
            for hit in entry["hits"]:
                print(f"HIT {hit['kind']} {entry['run_id']} [{hit.get('where')}] {hit.get('snippet', '')}")
        print(f"{len(entries)} runs audited, {hits} hits: {'STOP' if hits else 'clean'}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
