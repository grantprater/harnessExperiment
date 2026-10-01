"""Card 010, amendment 1 (stage 2a): select the stage-2a calibration candidates (no model, no suite runs).

Deterministic for the pinned source files (LF sha256) and seeds. Standard library only; the statement-form helper is
imported from the stage-1 builder (build_bank_010.no_message), which is not changed.

Rule: amendment 1, section A1.3 of experiments/session_harness/E3-difficulty-calibration-010.md (owner-approved
2026-10-01): the stage-1 rule of build_bank_010.py with three substitutions.

1. Pool: the kept tasks of tasks.mutations.full.json after sqlparse-mut-076 (the cloud generation of 2026-10-01,
   determinism check PASS-ADDRESS-ONLY, accepted by the owner).
2. Excluded: tasks whose statement names the mutated function (statement_names_mutated_function).
3. Dev pool: tasks whose mutated_function or whose exact fail_to_pass set equals that of any of the 76 recorded bank
   tasks (tasks.mutations.json: stage-1 dev core, dev pool, excluded and candidates alike).
4. The remaining fresh tasks are shuffled with random.Random("10:stage-2a") from task-id order and walked; a task is a
   calibration candidate when both its mutated_function and its sorted fail_to_pass set are new among candidates;
   otherwise it joins the dev pool as a duplicate.
5. Statement form: candidates with one failing test keep the generated statement. Candidates with two or more are
   sorted by id, shuffled with random.Random("10:stage-2a:statement-form"), and the first half (rounded down) become
   weak-signal variants `<id>-nm` (the sentence "The first failing check reports: `...`." removed).
6. No cap: every candidate is calibrated (after the gold/noop controls).

The candidate count must equal check_stage2a_010.py --compare's candidates_function_distinct (39 on the cloud
output); the builder stops otherwise.

Outputs:
  experiments/mutation_tasks/tasks.difficulty010-stage2a.json                 the candidate tasks, final form
  experiments/session_harness/E3-difficulty-calibration-010-stage2a.sets.json ids, strata, dev pool, exclusions

Usage (from the repository root):
  python experiments/mutation_tasks/build_bank_010_stage2a.py [--check]
  --check recomputes everything and fails if the committed outputs differ.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_bank_010 as stage1  # noqa: E402
import check_stage2a_010  # noqa: E402

ROOT = HERE.parents[1]
SOURCE = HERE / "tasks.mutations.full.json"
SOURCE_SHA256_LF = "407b8ab728c452d2cb32faa791595272620cd7fb033fc976c3bde35f9225e95a"
RECORDED = HERE / "tasks.mutations.json"
RECORDED_SHA256_LF = stage1.SOURCE_SHA256_LF
LAST_RECORDED = "sqlparse-mut-076"
OUT_BANK = HERE / "tasks.difficulty010-stage2a.json"
OUT_SETS = ROOT / "experiments" / "session_harness" / "E3-difficulty-calibration-010-stage2a.sets.json"
SEED = "10:stage-2a"
FORM_SEED = "10:stage-2a:statement-form"
EXPECTED_CANDIDATES = 39


def failing_key(task: dict) -> tuple:
    return tuple(sorted(task["fail_to_pass"]))


def build():
    for path, want in ((SOURCE, SOURCE_SHA256_LF), (RECORDED, RECORDED_SHA256_LF)):
        got = stage1.sha256_lf(path)
        if got != want:
            raise SystemExit(f"{path.name} changed: {got}")
    full = json.loads(SOURCE.read_text(encoding="utf-8"))["tasks"]
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))["tasks"]
    n_rec = len(recorded)
    if [t["task_id"] for t in full[:n_rec]] != [t["task_id"] for t in recorded] or recorded[-1]["task_id"] != LAST_RECORDED:
        raise SystemExit("full output does not start with the 76 recorded task ids")
    new = full[n_rec:]
    by_id = {t["task_id"]: t for t in new}
    rec_functions = {}
    rec_sets = {}
    for t in recorded:
        rec_functions.setdefault(t["mutated_function"], t["task_id"])
        rec_sets.setdefault(failing_key(t), t["task_id"])

    excluded, dev_pool, fresh = {}, {}, []
    for t in new:
        tid = t["task_id"]
        if t["statement_names_mutated_function"]:
            excluded[tid] = "statement names the mutated function"
        elif t["mutated_function"] in rec_functions:
            dev_pool[tid] = f"same mutated function as recorded {rec_functions[t['mutated_function']]}"
        elif failing_key(t) in rec_sets:
            dev_pool[tid] = f"same fail_to_pass set as recorded {rec_sets[failing_key(t)]}"
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

    counts = check_stage2a_010.propose_selection(new, recorded)
    if len(candidates) != counts["candidates_function_distinct"] or len(candidates) != EXPECTED_CANDIDATES:
        raise SystemExit(f"candidate count {len(candidates)} != check_stage2a_010 "
                         f"{counts['candidates_function_distinct']} / expected {EXPECTED_CANDIDATES}")

    multi = sorted(tid for tid in candidates if len(by_id[tid]["fail_to_pass"]) >= 2)
    random.Random(FORM_SEED).shuffle(multi)
    dropped = set(multi[: len(multi) // 2])

    bank, strata = [], {}
    for tid in candidates:
        t = by_id[tid]
        if tid in dropped:
            v = stage1.no_message(t)
            bank.append(v)
            strata[v["task_id"]] = "multi-test, no message"
        else:
            bank.append(copy.deepcopy(t))
            strata[tid] = "single test" if len(t["fail_to_pass"]) == 1 else "multi-test, message"

    bank_doc = {"schema_version": 1, "bank": "difficulty-010-stage2a", "source_file":
                "experiments/mutation_tasks/tasks.mutations.full.json", "source_sha256_lf": SOURCE_SHA256_LF,
                "recorded_file": "experiments/mutation_tasks/tasks.mutations.json",
                "recorded_sha256_lf": RECORDED_SHA256_LF,
                "builder": "experiments/mutation_tasks/build_bank_010_stage2a.py", "seed": SEED,
                "statement_form_seed": FORM_SEED, "tasks": bank}
    rows = []
    for t in bank:
        rows.append({"task_id": t["task_id"], "source_task_id": t.get("variant_of", t["task_id"]),
                     "stratum": strata[t["task_id"]], "mutation_kind": t["mutation_kind"],
                     "mutation_file": t["mutation_file"], "mutation_line": t["mutation_line"],
                     "mutated_function": t["mutated_function"], "fail_to_pass": len(t["fail_to_pass"])})
    sets_doc = {
        "card": "E3-difficulty-calibration-010",
        "stage": "2a",
        "seed": SEED,
        "statement_form_seed": FORM_SEED,
        "source_sha256_lf": SOURCE_SHA256_LF,
        "recorded_sha256_lf": RECORDED_SHA256_LF,
        "calibration": [t["task_id"] for t in bank],
        "candidates": rows,
        "dev_core": [],
        "dev_core_note": "Stage 2a has no dev core of its own: step 3 compares with all 76 recorded bank tasks "
                         "(tasks.mutations.json).",
        "dev_pool": dict(sorted(dev_pool.items())),
        "excluded": dict(sorted(excluded.items())),
        "note": "Fixed before any stage-2a calibration run and never edited afterwards. The keep/drop rule is applied "
                "to these tasks alone; its output goes to E3-difficulty-calibration-010-stage2a.split.json, and the "
                "eval tasks it keeps are added to stage 1's 12 (amendment 1, owner-approved 2026-10-01).",
    }
    return bank_doc, sets_doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    bank_doc, sets_doc = build()
    if args.check:
        ok = True
        for path, doc in ((OUT_BANK, bank_doc), (OUT_SETS, sets_doc)):
            want = stage1.dump(doc).encode("utf-8")
            have = path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else b""
            print(f"{path.name}: {'same' if have == want else 'DIFFERENT'}")
            ok &= have == want
        sys.exit(0 if ok else 1)
    OUT_BANK.write_text(stage1.dump(bank_doc), encoding="utf-8", newline="\n")
    OUT_SETS.write_text(stage1.dump(sets_doc), encoding="utf-8", newline="\n")
    counts = {}
    for r in sets_doc["candidates"]:
        counts[r["stratum"]] = counts.get(r["stratum"], 0) + 1
    print(f"candidates {len(bank_doc['tasks'])} {counts}; dev pool {len(sets_doc['dev_pool'])}; "
          f"excluded {len(sets_doc['excluded'])}")
    print(f"bank sha256 (LF) {stage1.sha256_lf(OUT_BANK)}")
    print(f"sets sha256 (LF) {stage1.sha256_lf(OUT_SETS)}")


if __name__ == "__main__":
    main()
