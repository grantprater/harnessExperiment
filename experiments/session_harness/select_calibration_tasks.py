"""Select card 007's calibration tasks from the mutation-task bank (no model calls, no test runs).

Rule (E3-calibration-007.md, "Tasks"):
  1. drop tasks whose statement names the mutated function (statement_names_mutated_function: true);
  2. quotas: 3 tasks per mutation kind, and one more for (count - 3 x kinds) kinds drawn with the seed;
  3. shuffle the remaining tasks with the seed (from task-id order), then walk the shuffled list and take a
     task when its kind is under quota and no taken task has the same fail_to_pass set.

The same seed and bank give the same selection; the output records both, with the bank's sha256 (LF content).

Usage (from the repo root):
  python experiments/session_harness/select_calibration_tasks.py --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
OUTPUT = ROOT / "experiments" / "session_harness" / "E3-calibration-007-tasks.json"
PER_KIND = 3


def select(tasks: list, seed: int, count: int) -> dict:
    kinds = sorted({t["mutation_kind"] for t in tasks})
    extra = count - PER_KIND * len(kinds)
    if not 0 <= extra <= len(kinds):
        raise SystemExit(f"{count} tasks cannot be split {PER_KIND}-{PER_KIND + 1} per kind over {len(kinds)} kinds")
    rng = random.Random(seed)
    larger = sorted(rng.sample(kinds, extra))
    quotas = {kind: PER_KIND + (kind in larger) for kind in kinds}
    excluded = sorted(t["task_id"] for t in tasks if t.get("statement_names_mutated_function"))
    order = sorted((t for t in tasks if t["task_id"] not in excluded), key=lambda t: t["task_id"])
    rng.shuffle(order)
    taken, used_sets, counts = [], set(), dict.fromkeys(kinds, 0)
    for task in order:
        failing = frozenset(task["fail_to_pass"])
        if counts[task["mutation_kind"]] < quotas[task["mutation_kind"]] and failing not in used_sets:
            taken.append(task)
            used_sets.add(failing)
            counts[task["mutation_kind"]] += 1
    if counts != quotas:
        raise SystemExit(f"quotas not met: {counts} of {quotas}")
    taken.sort(key=lambda t: t["task_id"])
    return {
        "seed": seed, "count": count, "quotas": quotas,
        "excluded_statement_names_mutated_function": excluded,
        "eligible_tasks": len(order),
        "eligible_distinct_fail_to_pass_sets": len({frozenset(t["fail_to_pass"]) for t in order}),
        "task_ids": [t["task_id"] for t in taken],
        "tasks": [{
            "task_id": t["task_id"], "mutation_kind": t["mutation_kind"], "mutation_file": t["mutation_file"],
            "mutation_line": t["mutation_line"], "fail_to_pass": len(t["fail_to_pass"]),
            "statement_message_dropped": t["statement_message_dropped"],
        } for t in taken],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--bank", type=Path, default=BANK)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    raw = args.bank.read_bytes()
    selection = select(json.loads(raw)["tasks"], args.seed, args.count)
    try:
        bank = args.bank.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        bank = str(args.bank)
    result = {
        "card": "E3-calibration-007",
        "rule": ("exclude statement_names_mutated_function; 3 per mutation kind plus 1 for seeded kinds; seeded "
                 "shuffle from task-id order; take a task if its kind is under quota and its fail_to_pass set is new"),
        "selector": "experiments/session_harness/select_calibration_tasks.py",
        # LF content (as committed), so the digest does not depend on the checkout's core.autocrlf.
        "bank": {"path": bank, "sha256_lf": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()},
        **selection,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("seed", "quotas", "eligible_tasks",
                                             "eligible_distinct_fail_to_pass_sets", "task_ids")}, indent=2))


if __name__ == "__main__":
    main()
