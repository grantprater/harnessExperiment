"""Select a calibration card's tasks from a mutation-task bank (card 007 by default; no model calls, no test runs).

Rule (E3-calibration-007.md, "Tasks"; --shortfall redistribute is card 023's amendment, see E3-calibration-023.md):
  1. drop tasks whose statement names the mutated function (statement_names_mutated_function: true);
  2. quotas: 3 tasks per mutation kind, and one more for (count - 3 x kinds) kinds drawn with the seed;
  3. shuffle the remaining tasks with the seed (from task-id order), then walk the shuffled list and take a
     task when its kind is under quota and no taken task has the same fail_to_pass set.
  4. --shortfall redistribute only: a kind the walk leaves under quota keeps what it has; its free slots go one
     at a time to the kinds that filled their quota (in a seeded order), and the walk reruns on the same list.

The same seed and bank give the same selection; the output records both, with the bank's sha256 (LF content).

Usage (from the repo root):
  python experiments/session_harness/select_calibration_tasks.py --seed 7
  python experiments/session_harness/select_calibration_tasks.py --seed 23 --card E3-calibration-023 \\
      --bank experiments/mutation_tasks/tasks.boltons.json --shortfall redistribute \\
      --output experiments/session_harness/E3-calibration-023-tasks.json
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


def walk(order: list, quotas: dict) -> tuple:
    """Take a task when its kind is under quota and its fail_to_pass set is new; (taken, counts)."""
    taken, used_sets, counts = [], set(), dict.fromkeys(quotas, 0)
    for task in order:
        failing = frozenset(task["fail_to_pass"])
        if counts[task["mutation_kind"]] < quotas[task["mutation_kind"]] and failing not in used_sets:
            taken.append(task)
            used_sets.add(failing)
            counts[task["mutation_kind"]] += 1
    return taken, counts


def select(tasks: list, seed: int, count: int, shortfall: str = "strict") -> dict:
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
    taken, counts = walk(order, quotas)
    initial_quotas, redistributions = dict(quotas), []
    while counts != quotas and shortfall == "redistribute":
        # A kind that cannot fill its quota keeps what the walk gave it; its free slots go one at a time to the other
        # kinds, in a seeded order, and the same shuffled list is walked again.
        short = sorted(kind for kind in kinds if counts[kind] < quotas[kind])
        free = sum(quotas[kind] - counts[kind] for kind in short)
        open_kinds = [kind for kind in kinds if kind not in short and counts[kind] == quotas[kind]]
        if not open_kinds:
            break
        rng.shuffle(open_kinds)
        for kind in short:
            quotas[kind] = counts[kind]
        for i in range(free):
            quotas[open_kinds[i % len(open_kinds)]] += 1
        redistributions.append({"short": {kind: counts[kind] for kind in short}, "quotas": dict(quotas)})
        taken, counts = walk(order, quotas)
    if counts != quotas:
        raise SystemExit(f"quotas not met: {counts} of {quotas}")
    taken.sort(key=lambda t: t["task_id"])
    extra_fields = ({"shortfall": shortfall, "initial_quotas": initial_quotas, "redistributions": redistributions}
                    if redistributions else {})
    return {
        "seed": seed, "count": count, "quotas": quotas, **extra_fields,
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
    parser.add_argument("--card", default="E3-calibration-007", help="card id recorded in the output")
    parser.add_argument("--shortfall", choices=["strict", "redistribute"], default="strict",
                        help="strict (card 007): fail when a kind cannot fill its quota; redistribute: that kind keeps "
                             "what it has and its free slots go to the other kinds in a seeded order")
    args = parser.parse_args()
    raw = args.bank.read_bytes()
    selection = select(json.loads(raw)["tasks"], args.seed, args.count, args.shortfall)
    try:
        bank = args.bank.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        bank = str(args.bank)
    result = {
        "card": args.card,
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
