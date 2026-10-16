"""Card 021's grader-free instrument, scored offline: commitments and predictions per run, against the outcome.

Per run (one runner directory each, experiments/p6_pilot/runs/<prefix>-*), from results.jsonl and the session
journal only (events.jsonl, read without touching it):
  prediction   none (no commit_hypothesis), unchecked (a commitment never followed by record_observation),
               matched or mismatched (the last observation's self-reported match);
  located      whether the last committed file is the task's mutation_file and its function names the mutated
               function (the method name or the full Class.method); line_distance from the mutated line. These
               three use the task file's mutation fields, so they are an analysis of the record, never shown to
               the model and never part of a run;
  nudged       whether the commitment nudge fired, and whether a commitment followed it;
  accepted     final acceptance.
The table answers card 021's secondary question: does a failed or absent prediction predict rejection?

Usage: python experiments/session_harness/score_commitments.py --runs experiments/p6_pilot/runs --prefix c021 \\
           --tasks experiments/mutation_tasks/tasks.mutations.json [--json]
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


def read_events(session_dir: Path) -> List[dict]:
    path = session_dir / "events.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def function_matches(committed: Optional[str], mutated: Optional[str]) -> bool:
    if not committed or not mutated:
        return False
    committed, mutated = committed.strip().rstrip("()"), mutated.strip()
    return committed == mutated or committed == mutated.split(".")[-1] or mutated.endswith("." + committed)


def score_run(record: dict, events: List[dict], task: dict) -> Dict[str, Any]:
    commits = [e["payload"] for e in events if e["kind"] == "hypothesis_commit"]
    observations = [e["payload"] for e in events if e["kind"] == "hypothesis_observation"]
    nudge = [e["payload"] for e in events if e["kind"] == "harness_message" and e["payload"].get("name") == "commit"]
    last = commits[-1] if commits else None
    if not commits:
        prediction = "none"
    elif not observations or observations[-1].get("commit") != last["n"]:
        prediction = "unchecked"
    else:
        prediction = "matched" if observations[-1].get("matched") else "mismatched"
    line = task.get("mutation_line")
    return {
        "run_id": record.get("run_id"), "task_id": record.get("task_id"),
        "accepted": (record.get("acceptance") or {}).get("status") == "accepted",
        "stop": record.get("stop"), "commits": len(commits), "observations": len(observations),
        "prediction": prediction, "nudged": bool(nudge),
        "committed_after_nudge": any(c.get("after_nudge") for c in commits),
        "located_file": bool(last) and str(last.get("file", "")).replace("\\", "/").removeprefix("./") == task.get(
            "mutation_file"),
        "located_function": bool(last) and function_matches(last.get("function"), task.get("mutated_function")),
        "line_distance": abs(int(last["line"]) - int(line)) if last and line is not None else None,
    }


def score(runs_dir: Path, prefix: str, tasks_file: Path) -> List[Dict[str, Any]]:
    tasks = {task["task_id"]: task for task in json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"]}
    rows = []
    for run_dir in sorted(runs_dir.glob(f"{prefix}-*")):
        results = run_dir / "results.jsonl"
        if not results.exists():
            continue
        for line in results.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            session = run_dir / "sessions" / record["run_id"] / "session"
            rows.append({"run": run_dir.name, **score_run(record, read_events(session), tasks[record["task_id"]])})
    return rows


def table(rows: List[Dict[str, Any]]) -> str:
    counts = Counter((row["prediction"], row["accepted"]) for row in rows)
    lines = ["| Prediction | Runs | Accepted | Rejected |", "|---|---|---|---|"]
    for prediction in ("none", "unchecked", "matched", "mismatched"):
        accepted, rejected = counts[(prediction, True)], counts[(prediction, False)]
        lines.append(f"| {prediction} | {accepted + rejected} | {accepted} | {rejected} |")
    located = [row for row in rows if row["commits"]]
    lines.append("")
    lines.append(f"Runs with a commitment: {len(located)}; last commitment in the mutated file: "
                 f"{sum(r['located_file'] for r in located)}, naming the mutated function: "
                 f"{sum(r['located_function'] for r in located)}.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = score(args.runs, args.prefix, args.tasks)
    print(json.dumps(rows, indent=2) if args.json else table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
