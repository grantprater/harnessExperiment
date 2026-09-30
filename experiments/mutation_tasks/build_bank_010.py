"""Card 010, stage 1: select calibration candidates from the existing mutation bank (no model, no suite runs).

Deterministic for a given source bank (pinned by its LF sha256) and seed. Standard library only.

Rule (fixed in experiments/session_harness/E3-difficulty-calibration-010.md before any calibration run):

1. dev core = the 20 card-007 tasks (run and mined: c007, c011, c013, c018, c012, c017) plus sqlparse-mut-006
   (seen by the S6a one-response smoke). These are for development only.
2. Excluded: tasks whose statement names the mutated function (statement_names_mutated_function).
3. Dev pool (untried, but correlated with the dev core): tasks whose mutated_function or whose exact
   fail_to_pass set equals a dev-core task's.
4. The remaining fresh tasks are shuffled with random.Random(SEED) from task-id order and walked; a task is a
   calibration candidate when both its mutated_function and its sorted fail_to_pass set are new among
   candidates; otherwise it joins the dev pool as a duplicate.
5. Statement form: candidates with one failing test keep the generated statement. Candidates with two or more
   are sorted by id, shuffled with random.Random(f"{SEED}:statement-form"), and the first half (rounded down)
   become weak-signal variants `<id>-nm`: the generated statement with its sentence
   "The first failing check reports: `...`." removed (generate.build_statement(..., with_message=False)).
   Everything else in the task (mutation, gold, tests) is unchanged.

Outputs:
  experiments/mutation_tasks/tasks.difficulty010.json   the candidate tasks, in final statement form
  experiments/session_harness/E3-difficulty-calibration-010.sets.json   ids, strata, dev pool, exclusions
  (both fixed before the calibration run; the keep/drop output goes to a separate .split.json)

Usage:
  python experiments/mutation_tasks/build_bank_010.py [--check]
  --check recomputes everything and fails if the committed outputs differ.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "tasks.mutations.json"
SOURCE_SHA256_LF = "fa185723735d56e7ff6858b7188bd603ed8f2ee0170637273fcaa71038db1daa"
C007_TASKS = ROOT / "experiments" / "session_harness" / "E3-calibration-007-tasks.json"
OUT_BANK = HERE / "tasks.difficulty010.json"
OUT_SETS = ROOT / "experiments" / "session_harness" / "E3-difficulty-calibration-010.sets.json"
SEED = 10
EXTRA_DEV = ["sqlparse-mut-006"]
MESSAGE_SENTENCE = re.compile(r" The first failing check reports: `[^`]*`\.")
VARIANT = "no-message-v1"


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def failing_key(task: dict) -> tuple:
    return tuple(sorted(task["fail_to_pass"]))


def no_message(task: dict) -> dict:
    stripped, n = MESSAGE_SENTENCE.subn("", task["statement"])
    if n != 1:
        raise SystemExit(f"{task['task_id']}: expected one failure-message sentence, found {n}")
    variant = copy.deepcopy(task)
    variant["task_id"] = task["task_id"] + "-nm"
    variant["statement"] = stripped
    variant["statement_message_dropped"] = True
    variant["variant_of"] = task["task_id"]
    variant["statement_variant"] = VARIANT
    return variant


def build():
    digest = sha256_lf(SOURCE)
    if digest != SOURCE_SHA256_LF:
        raise SystemExit(f"source bank changed: {digest}")
    tasks = json.loads(SOURCE.read_text(encoding="utf-8"))["tasks"]
    by_id = {t["task_id"]: t for t in tasks}
    dev_core = list(json.loads(C007_TASKS.read_text(encoding="utf-8"))["task_ids"]) + EXTRA_DEV
    dev_functions = {by_id[i]["mutated_function"]: i for i in dev_core}
    dev_sets = {failing_key(by_id[i]): i for i in dev_core}

    excluded, dev_pool, fresh = {}, {}, []
    for t in tasks:
        tid = t["task_id"]
        if tid in dev_core:
            continue
        if t["statement_names_mutated_function"]:
            excluded[tid] = "statement names the mutated function"
        elif t["mutated_function"] in dev_functions:
            dev_pool[tid] = f"same mutated function as dev-core {dev_functions[t['mutated_function']]}"
        elif failing_key(t) in dev_sets:
            dev_pool[tid] = f"same fail_to_pass set as dev-core {dev_sets[failing_key(t)]}"
        else:
            fresh.append(tid)

    order = sorted(fresh)
    random.Random(SEED).shuffle(order)
    candidates, seen_fn, seen_set = [], {}, {}
    for tid in order:
        t = by_id[tid]
        if t["mutated_function"] in seen_fn:
            dev_pool[tid] = f"duplicate mutated function of candidate {seen_fn[t['mutated_function']]}"
        elif failing_key(t) in seen_set:
            dev_pool[tid] = f"duplicate fail_to_pass set of candidate {seen_set[failing_key(t)]}"
        else:
            candidates.append(tid)
            seen_fn[t["mutated_function"]] = tid
            seen_set[failing_key(t)] = tid

    multi = sorted(tid for tid in candidates if len(by_id[tid]["fail_to_pass"]) >= 2)
    random.Random(f"{SEED}:statement-form").shuffle(multi)
    dropped = set(multi[: len(multi) // 2])

    bank, strata = [], {}
    for tid in candidates:
        t = by_id[tid]
        if tid in dropped:
            v = no_message(t)
            bank.append(v)
            strata[v["task_id"]] = "multi-test, no message"
        else:
            bank.append(copy.deepcopy(t))
            strata[tid] = "single test" if len(t["fail_to_pass"]) == 1 else "multi-test, message"

    bank_doc = {"schema_version": 1, "bank": "difficulty-010-stage1", "source_file":
                "experiments/mutation_tasks/tasks.mutations.json", "source_sha256_lf": SOURCE_SHA256_LF,
                "builder": "experiments/mutation_tasks/build_bank_010.py", "seed": SEED, "tasks": bank}
    rows = []
    for t in bank:
        rows.append({"task_id": t["task_id"], "source_task_id": t.get("variant_of", t["task_id"]),
                     "stratum": strata[t["task_id"]], "mutation_kind": t["mutation_kind"],
                     "mutation_file": t["mutation_file"], "mutation_line": t["mutation_line"],
                     "mutated_function": t["mutated_function"], "fail_to_pass": len(t["fail_to_pass"])})
    sets_doc = {
        "card": "E3-difficulty-calibration-010",
        "stage": 1,
        "seed": SEED,
        "source_sha256_lf": SOURCE_SHA256_LF,
        "calibration": [t["task_id"] for t in bank],
        "candidates": rows,
        "dev_core": dev_core,
        "dev_pool": dict(sorted(dev_pool.items())),
        "excluded": dict(sorted(excluded.items())),
        "note": "Fixed before any calibration run and never edited afterwards. The keep/drop rule's output (eval and "
                "dev splits) goes to E3-difficulty-calibration-010.split.json after the calibration run.",
    }
    return bank_doc, sets_doc


def dump(doc) -> str:
    return json.dumps(doc, indent=2) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    bank_doc, sets_doc = build()
    if args.check:
        ok = True
        for path, doc in ((OUT_BANK, bank_doc), (OUT_SETS, sets_doc)):
            want = dump(doc).encode("utf-8")
            have = path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else b""
            print(f"{path.name}: {'same' if have == want else 'DIFFERENT'}")
            ok &= have == want
        sys.exit(0 if ok else 1)
    OUT_BANK.write_text(dump(bank_doc), encoding="utf-8", newline="\n")
    OUT_SETS.write_text(dump(sets_doc), encoding="utf-8", newline="\n")
    counts = {}
    for r in sets_doc["candidates"]:
        counts[r["stratum"]] = counts.get(r["stratum"], 0) + 1
    print(f"candidates {len(bank_doc['tasks'])} {counts}; dev core {len(sets_doc['dev_core'])}; "
          f"dev pool {len(sets_doc['dev_pool'])}; excluded {len(sets_doc['excluded'])}")
    print(f"bank sha256 (LF) {sha256_lf(OUT_BANK)}")


if __name__ == "__main__":
    main()
