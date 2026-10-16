"""Card 010 offline filters: check the recorded gold/noop control runs of the stage-1 candidates.

Reads only recorded runs (experiments/p6_pilot/runs/c010-control-*/results.jsonl); runs nothing.
A candidate passes when, in every recorded control run that covers it:
  gold  accepted: fail-to-pass pass, pass-to-pass pass, no collection errors, no pytest timeout;
  noop  rejected: fail-to-pass fails on exactly the task's recorded fail_to_pass set (no missing/skipped),
        pass-to-pass passes, no collection errors, no pytest timeout;
  and at least 2 gold and 2 noop runs exist (determinism: identical outcomes and failing sets across repeats),
  and every control evaluation took at most RUNTIME_LIMIT_S seconds (runtime limit).

Usage: python experiments/session_harness/check_controls_010.py [--json OUT]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
BANK = ROOT / "experiments" / "mutation_tasks" / "tasks.difficulty010.json"
RUNTIME_LIMIT_S = 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    tasks = {t["task_id"]: t for t in json.loads(BANK.read_text(encoding="utf-8"))["tasks"]}
    seen = defaultdict(lambda: {"gold": [], "noop": []})
    for d in sorted(RUNS.glob("c010-control-*")):
        res = d / "results.jsonl"
        if not d.is_dir() or not res.exists():
            continue
        for line in res.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            a = r.get("acceptance") or {}
            crit = a.get("criteria") or {}
            seen[r["task_id"]][r["client"]].append({
                "run": d.name, "status": a.get("status"),
                "f2p": (crit.get("fail-to-pass") or {}).get("outcome"),
                "p2p": (crit.get("pass-to-pass") or {}).get("outcome"),
                "f2p_failing": sorted((crit.get("fail-to-pass") or {}).get("failing") or []),
                "f2p_missing": (crit.get("fail-to-pass") or {}).get("missing") or [],
                "f2p_skipped": (crit.get("fail-to-pass") or {}).get("skipped") or [],
                "p2p_failing": (crit.get("pass-to-pass") or {}).get("failing") or [],
                "collection_errors": a.get("collection_errors") or [],
                "timed_out": a.get("pytest_timed_out"),
                "tests": a.get("observed_test_count"),
                "elapsed_s": r.get("elapsed_s"),
            })
    rows, n_pass = [], 0
    print("| Task | gold runs | gold accepted | noop runs | noop rejected on exact set | max s | verdict |")
    print("|---|---:|---:|---:|---:|---:|---|")
    for tid, t in tasks.items():
        g, n = seen[tid]["gold"], seen[tid]["noop"]
        want = sorted(t["fail_to_pass"])
        g_ok = [x for x in g if x["status"] == "accepted" and x["f2p"] == "pass" and x["p2p"] == "pass"
                and not x["collection_errors"] and not x["timed_out"]]
        n_ok = [x for x in n if x["status"] == "rejected" and x["f2p"] == "fail" and x["p2p"] == "pass"
                and x["f2p_failing"] == want and not x["f2p_missing"] and not x["f2p_skipped"]
                and not x["collection_errors"] and not x["timed_out"]]
        times = [x["elapsed_s"] for x in g + n if x["elapsed_s"] is not None]
        reasons = []
        if len(g) < 2 or len(n) < 2:
            reasons.append("fewer than 2 repeats")
        if len(g_ok) != len(g):
            reasons.append("gold not accepted in every run")
        if len(n_ok) != len(n):
            reasons.append("noop not rejected on the exact fail_to_pass set in every run")
        if times and max(times) > RUNTIME_LIMIT_S:
            reasons.append(f"control over {RUNTIME_LIMIT_S:.0f} s")
        verdict = "pass" if not reasons else "FAIL: " + "; ".join(reasons)
        n_pass += not reasons
        mx = max(times) if times else None
        print(f"| `{tid}` | {len(g)} | {len(g_ok)} | {len(n)} | {len(n_ok)} | {mx} | {verdict} |")
        rows.append({"task_id": tid, "gold_runs": len(g), "gold_accepted": len(g_ok), "noop_runs": len(n),
                     "noop_rejected_exact": len(n_ok), "max_elapsed_s": mx, "verdict": verdict,
                     "runs": sorted({x["run"] for x in g + n})})
    print(f"\n{n_pass} of {len(tasks)} candidates pass the offline filters")
    if args.json:
        Path(args.json).write_text(json.dumps({"runtime_limit_s": RUNTIME_LIMIT_S, "passed": n_pass,
                                               "candidates": len(tasks), "tasks": rows}, indent=1) + "\n",
                                   encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
