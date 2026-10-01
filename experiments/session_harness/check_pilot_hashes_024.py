"""Card 024: does each eval task's planned incumbent hash equal the hash card 010 recorded for that task?

The method is card 010's control-hash check: `run_card.py --plan` computes each invocation's protocol hash with the
runner's own functions, and the plan's value is compared with what the recorded runs wrote. Here the recorded value
is each valid calibration run's config.json `protocol_hash` (and every results.jsonl row's), from the run folders
c010-<task>-r<k> (stage 1) and c010b-<task>-r<k> (stage 2a); folders renamed *.void-* are skipped.
No model calls; --plan runs nothing.

    python experiments/session_harness/check_pilot_hashes_024.py [--plan PLAN.json] [--json]

Exit 0 when every task matches, 1 otherwise. --plan reads a saved `run_card.py cards/024.json --plan --json`;
without it the plan is computed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "experiments/session_harness/cards/024.json"
RUNS = ROOT / "experiments/p6_pilot/runs"
COMBINED = ROOT / "experiments/session_harness/E3-difficulty-calibration-010.eval-combined.json"
PREFIX = {"stage1": "c010", "stage2a": "c010b"}


def recorded(task: str, prefix: str) -> dict:
    found = {}
    for rollout in (1, 2):
        run = RUNS / f"{prefix}-{task}-r{rollout}"
        config = run / "config.json"
        if not config.is_file():
            continue
        hashes = {json.loads(config.read_text(encoding="utf-8"))["protocol_hash"]}
        results = run / "results.jsonl"
        if results.is_file():
            for line in results.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    hashes.add(json.loads(line)["protocol_hash"])
        found[run.name] = sorted(hashes)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    else:
        done = subprocess.run([sys.executable, str(ROOT / "experiments/session_harness/run_card.py"), str(CARD),
                               "--plan", "--json"], capture_output=True, text=True, cwd=ROOT)
        plan = json.loads(done.stdout)
    combined = json.loads(COMBINED.read_text(encoding="utf-8"))
    stage = {t: "stage1" for t in combined["from_stage1"]} | {t: "stage2a" for t in combined["from_stage2a"]}
    planned = defaultdict(lambda: defaultdict(set))
    for inv in plan["invocations"]:
        if inv["kind"] == "run" and len(inv["task_ids"]) == 1:
            planned[inv["name"]][inv["task_ids"][0]].add(inv.get("expected_protocol_hash"))
    rows, bad = [], 0
    for task in combined["eval"]:
        mine = sorted(h for h in planned["incumbent"][task] if h)
        runs = recorded(task, PREFIX[stage[task]])
        theirs = sorted({h for hs in runs.values() for h in hs})
        ok = len(mine) == 1 and len(theirs) == 1 and mine == theirs and len(runs) == 2
        bad += not ok
        rows.append({"task": task, "stage": stage[task], "planned_incumbent": mine, "recorded": theirs,
                     "recorded_runs": sorted(runs), "match": ok,
                     **{f"planned_{arm}": sorted(h for h in planned[arm][task] if h)
                        for arm in sorted(planned) if arm != "incumbent"}})
    if args.json:
        print(json.dumps({"rows": rows, "mismatches": bad}, indent=1))
    else:
        print(f"{'task':22s} {'stage':8s} {'planned':14s} {'card 010 recorded':18s} runs match")
        for r in rows:
            print(f"{r['task']:22s} {r['stage']:8s} {','.join(r['planned_incumbent']) or '-':14s} "
                  f"{','.join(r['recorded']) or '-':18s} {len(r['recorded_runs'])}    {'yes' if r['match'] else 'NO'}")
        print(f"{len(rows) - bad}/{len(rows)} eval tasks: the incumbent's planned hash equals card 010's recorded hash")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
