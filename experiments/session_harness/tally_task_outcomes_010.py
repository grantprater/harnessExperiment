"""Per-task historical outcome tally for card 010 (difficulty calibration).

Reads recorded run folders only (no model calls, no evaluation):
  - experiments/p6_pilot/runs/<prefix>-<task>-r<k>[-<arm>]/results.jsonl  (Reticle runner)
  - experiments/session_harness/native_runs/c018-<task>-r<k>/result.json   (native Claude Code)
Void folders (``*.void-*``) and control folders are skipped.

Usage:
  python experiments/session_harness/tally_task_outcomes_010.py [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
NATIVE = ROOT / "experiments" / "session_harness" / "native_runs"

# campaign -> (label, model/harness)
CAMPAIGNS = {
    "c007": "Sonnet 5, Reticle incumbent, 20 responses",
    "c011": "Sonnet 5, Reticle incumbent, 40 responses",
    "c012": "Nemotron 3 Super (free), Reticle, 20 responses",
    "c013": "Sonnet 5, Reticle, 20 responses (arms incumbent / finish-guard)",
    "c017": "Nemotron 3 Ultra (free), Reticle, 20 responses",
    "c018": "Sonnet 5, native Claude Code, 20 turns",
}

NAME = re.compile(r"^(c0\d\d)-(sqlparse-mut-\d+)-r(\d+)(?:-(.+))?$")


def reticle_runs():
    for d in sorted(RUNS.iterdir()):
        if not d.is_dir() or ".void" in d.name:
            continue
        m = NAME.match(d.name)
        if not m or m.group(1) not in CAMPAIGNS:
            continue
        res = d / "results.jsonl"
        if not res.exists():
            continue
        lines = [ln for ln in res.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for ln in lines:
            r = json.loads(ln)
            status = (r.get("acceptance") or {}).get("status")
            arm = m.group(4) or "incumbent"
            yield m.group(1), arm, m.group(2), int(m.group(3)), status, r.get("stop"), d.name


def native_runs():
    for d in sorted(NATIVE.iterdir()):
        if not d.is_dir() or ".void" in d.name:
            continue
        m = NAME.match(d.name)
        if not m:
            continue
        res = d / "result.json"
        if not res.exists():
            continue
        r = json.loads(res.read_text(encoding="utf-8"))
        status = (r.get("acceptance") or {}).get("status")
        yield m.group(1), "native", m.group(2), int(m.group(3)), status, r.get("stop"), d.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    rows = list(reticle_runs()) + list(native_runs())
    # (task) -> column -> [accepted, n]
    cols = []
    table = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for camp, arm, task, k, status, stop, name in rows:
        col = camp if arm in ("incumbent", "native") else f"{camp}:{arm}"
        if col not in cols:
            cols.append(col)
        cell = table[task][col]
        cell[1] += 1
        cell[0] += 1 if status == "accepted" else 0
    cols.sort()
    sonnet_cols = [c for c in cols if c.split(":")[0] in ("c007", "c011", "c013", "c018")]
    out = []
    print("| Task | " + " | ".join(cols) + " | Sonnet pooled |")
    print("|---|" + "---|" * (len(cols) + 1))
    for task in sorted(table):
        cells = []
        sa = sn = 0
        for c in cols:
            a, n = table[task].get(c, [0, 0])
            cells.append(f"{a}/{n}" if n else "")
            if c in sonnet_cols and n:
                sa += a
                sn += n
        print(f"| `{task}` | " + " | ".join(cells) + f" | {sa}/{sn} |")
        out.append({"task_id": task, "by_column": {c: table[task][c] for c in cols if table[task][c][1]},
                    "sonnet_accepted": sa, "sonnet_runs": sn})
    tot = defaultdict(lambda: [0, 0])
    for camp, arm, task, k, status, stop, name in rows:
        col = camp if arm in ("incumbent", "native") else f"{camp}:{arm}"
        tot[col][1] += 1
        tot[col][0] += 1 if status == "accepted" else 0
    print("\nColumn totals: " + ", ".join(f"{c} {tot[c][0]}/{tot[c][1]}" for c in cols))
    print("Columns: " + "; ".join(f"{c} = {CAMPAIGNS[c.split(':')[0]]}" for c in cols))
    if args.json:
        Path(args.json).write_text(json.dumps({"columns": cols, "column_totals": tot, "tasks": out},
                                              indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
