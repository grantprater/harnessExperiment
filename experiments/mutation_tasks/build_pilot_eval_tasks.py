"""Build the task file of the ontology pilot (card 024): the 31 combined-eval tasks of card 010, copied verbatim.

Offline and deterministic: reads committed JSON only. Stdlib only.

    python experiments/mutation_tasks/build_pilot_eval_tasks.py           # write tasks.pilot024-eval.json
    python experiments/mutation_tasks/build_pilot_eval_tasks.py --check   # rebuild, diff, exit 1 on mismatch

A run card names one task file, and card 010's eval split spans two (stage 1 and stage 2a). Each task dict is
copied unchanged from the file card 010 calibrated it in, so the runner's task_contract, and therefore each task's
protocol hash, is the one card 010 recorded (the protocol hash covers the contract, not the task file's path).
The order is the combined eval order (E3-difficulty-calibration-010.eval-combined.json, key `eval`). The builder
refuses any task the pooled registry does not give the role `eval-010-combined`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMBINED = "experiments/session_harness/E3-difficulty-calibration-010.eval-combined.json"
REGISTRY = "experiments/session_harness/task_registry.json"
OUT = ROOT / "experiments/mutation_tasks/tasks.pilot024-eval.json"


def read(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> dict:
    combined_text = read(COMBINED)
    combined = json.loads(combined_text)
    registry = json.loads(read(REGISTRY))
    roles = {r["id"]: r["role"] for r in registry["tasks"]}
    sources, by_id = {}, {}
    for stage, rel in combined["task_files"].items():
        text = read(rel)
        sources[stage] = {"path": rel, "sha256_lf": sha(text)}
        for task in json.loads(text)["tasks"]:
            if task["task_id"] in by_id:
                raise SystemExit(f"{task['task_id']} is defined in more than one stage task file")
            by_id[task["task_id"]] = (stage, task)
    tasks, origin = [], {}
    for tid in combined["eval"]:
        if roles.get(tid) != "eval-010-combined":
            raise SystemExit(f"{tid}: registry role is {roles.get(tid)!r}, not eval-010-combined")
        stage, task = by_id[tid]
        if tid not in combined[f"from_{stage}"]:
            raise SystemExit(f"{tid}: defined in the {stage} file but not listed under from_{stage}")
        tasks.append(task)
        origin[tid] = stage
    return {
        "schema_version": 1,
        "bank": "pilot-024-eval",
        "builder": "experiments/mutation_tasks/build_pilot_eval_tasks.py",
        "eval_list": {"path": COMBINED, "key": "eval", "sha256_lf": sha(combined_text)},
        "source_files": sources,
        "task_origin": origin,
        "note": "Card 010's 31 combined-eval tasks, each copied unchanged from the task file it was calibrated in.",
        "tasks": tasks,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="rebuild and compare with the committed file")
    args = parser.parse_args()
    text = render(build())
    if args.check:
        old = OUT.read_bytes().decode("utf-8").replace("\r\n", "\n") if OUT.exists() else None
        if old != text:
            print(f"CHECK FAIL: {OUT.name} differs from a rebuild")
            return 1
        print(f"CHECK OK: {OUT.name} matches a rebuild ({len(json.loads(text)['tasks'])} tasks)")
        return 0
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(json.loads(text)['tasks'])} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
