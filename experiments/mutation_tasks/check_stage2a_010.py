"""Card 010, amendment 1 (stage 2a): checks around the generator continuation. No model calls, no suite runs.

Two modes, standard library only (plus generate.py's AST code):

  --schedule   Before generation. Export the healthy sqlparse tree (git archive of the pinned commit), list the
               candidates with generate.find_candidates, order them with generate.schedule, and check that the first
               100 scheduled candidates equal the 100 in generation_log.json (file, line, kind, detail, function) and
               that every kept one's patch equals the recorded mutation_patch of its task id. AST only.

  --compare    After generation. The determinism check of amendment 1:
               (a) the full run tried at least 100 candidates and its first 100 log entries equal the recorded ones
                   in file, line, kind, detail, function and verdict;
               (b) tasks sqlparse-mut-001..076 of the full output have the recorded ids, in order, with identical
                   mutation_patch and statement. A statement that differs only in CPython memory addresses (0x...)
                   is reported separately as ADDRESS-ONLY (the recorded case is sqlparse-mut-072, whose failure
                   message prints an object repr; mutation_tasks/REPORT.md weakness 11 on integration/2026-10).
               Verdict: PASS (strict), PASS-ADDRESS-ONLY (only (b) addresses differ), or FAIL.
               Then the counts, and the amendment's PROPOSED selection rule applied to the new kept tasks (ids after
               sqlparse-mut-076): counts only, nothing is written except the --result text file.

Usage (from the repository root):
  python experiments/mutation_tasks/check_stage2a_010.py --schedule [--repo-dir PATH]
  python experiments/mutation_tasks/check_stage2a_010.py --compare --full-tasks F --full-log L [--result OUT.txt]
Exit code 0 on PASS or PASS-ADDRESS-ONLY, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402

RECORDED_TASKS = HERE / "tasks.mutations.json"
RECORDED_LOG = HERE / "generation_log.json"
RECORDED_KEPT = 76
RECORDED_TRIED = 100
ADDRESS = re.compile(r"0x[0-9A-Fa-f]+")
LOG_KEYS = ("file", "line", "kind", "detail", "function")
SELECTION_SEED = "10:stage-2a"  # PROPOSED (amendment 1); stage 1 used 10


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schedule_check(repo_dir: Path | None) -> int:
    source = next(t for t in load(generate.ROOT / "experiments" / "p6_pilot" / "tasks.json")["tasks"]
                  if t["task_id"] == generate.SOURCE_TASK)
    repo = repo_dir or generate.runtime_dir() / "bug-mining" / "repos" / source["repo"]
    log = load(RECORDED_LOG)["candidates"]
    tasks = {t["task_id"]: t for t in load(RECORDED_TASKS)["tasks"]}
    with tempfile.TemporaryDirectory(prefix="c010-2a-schedule-") as tmp:
        pristine = Path(tmp) / "pristine"
        generate.export(repo, source["fix_commit"], pristine)
        candidates, invalid = generate.find_candidates(pristine)
        order = generate.schedule(candidates)
    bad = []
    for entry, cand in zip(log, order[:len(log)]):
        got = {"file": cand.file, "line": cand.line, "kind": cand.kind, "detail": cand.detail, "function": cand.function}
        if any(entry[k] != got[k] for k in LOG_KEYS):
            bad.append(f"n={entry['n']}: log {[entry[k] for k in LOG_KEYS]} vs scheduled {[got[k] for k in LOG_KEYS]}")
        elif "task_id" in entry and tasks[entry["task_id"]]["mutation_patch"] != cand.patch():
            bad.append(f"n={entry['n']} {entry['task_id']}: patch differs")
    kept = sum("task_id" in e for e in log)
    print(f"commit {source['fix_commit']}; candidate pool {len(candidates)} (invalid after edit {invalid}); "
          f"untried after the first {len(log)}: {len(candidates) - len(log)}")
    print(f"first {len(log)} scheduled vs generation_log.json: {len(log) - len(bad)} equal, {len(bad)} differ; "
          f"kept patches checked: {kept}")
    for line in bad[:20]:
        print("  DIFF", line)
    ok = not bad and len(log) == RECORDED_TRIED and kept == RECORDED_KEPT
    print("SCHEDULE: " + ("SAME" if ok else "DIFFERENT"))
    return 0 if ok else 1


def failing_key(task: dict) -> tuple:
    return tuple(sorted(task["fail_to_pass"]))


def propose_selection(new: list, recorded: list) -> dict:
    """Amendment 1, PROPOSED: the stage-1 rule (build_bank_010.py steps 2-5) with 'dev core' read as every recorded
    bank task (the 76 of tasks.mutations.json), seed '10:stage-2a'. Counts only."""
    old_fn = {t["mutated_function"] for t in recorded}
    old_sets = {failing_key(t) for t in recorded}
    excluded, dev_pool, fresh = [], [], []
    for t in new:
        if t["statement_names_mutated_function"]:
            excluded.append(t["task_id"])
        elif t["mutated_function"] in old_fn or failing_key(t) in old_sets:
            dev_pool.append(t["task_id"])
        else:
            fresh.append(t["task_id"])
    by_id = {t["task_id"]: t for t in new}
    order = sorted(fresh)
    random.Random(SELECTION_SEED).shuffle(order)
    candidates, seen_fn, seen_set, duplicates = [], set(), set(), []
    for tid in order:
        t = by_id[tid]
        if t["mutated_function"] in seen_fn or failing_key(t) in seen_set:
            duplicates.append(tid)
        else:
            candidates.append(tid)
            seen_fn.add(t["mutated_function"])
            seen_set.add(failing_key(t))
    single = sum(len(by_id[t]["fail_to_pass"]) == 1 for t in candidates)
    return {"new_kept": len(new), "excluded_names_function": len(excluded),
            "dev_pool_shares_function_or_set_with_recorded_bank": len(dev_pool),
            "duplicates_among_new": len(duplicates), "candidates_function_distinct": len(candidates),
            "candidates_single_test": single, "candidates_multi_test": len(candidates) - single}


def compare(full_tasks: Path, full_log: Path, result: Path | None) -> int:
    rec_tasks = load(RECORDED_TASKS)["tasks"]
    rec_log = load(RECORDED_LOG)["candidates"]
    doc = load(full_log)
    summary, log = doc["summary"], doc["candidates"]
    tasks = load(full_tasks)["tasks"]
    lines, problems = [], []

    if len(log) < RECORDED_TRIED:
        problems.append(f"only {len(log)} candidates tried (< {RECORDED_TRIED})")
    for old, new in zip(rec_log, log):
        keys = LOG_KEYS + ("verdict",)
        if any(old[k] != new.get(k) for k in keys):
            problems.append(f"log n={old['n']}: recorded {[old[k] for k in keys]} vs {[new.get(k) for k in keys]}")
    address_only = []
    for i, old in enumerate(rec_tasks):
        new = tasks[i] if i < len(tasks) else None
        if new is None or new["task_id"] != old["task_id"]:
            problems.append(f"{old['task_id']}: missing or out of order in the full output")
            continue
        if new["mutation_patch"] != old["mutation_patch"]:
            problems.append(f"{old['task_id']}: mutation_patch differs")
        if new["statement"] != old["statement"]:
            if ADDRESS.sub("0x?", new["statement"]) == ADDRESS.sub("0x?", old["statement"]):
                address_only.append(old["task_id"])
            else:
                problems.append(f"{old['task_id']}: statement differs")
    verdict = "FAIL" if problems else ("PASS-ADDRESS-ONLY" if address_only else "PASS")

    new_tasks = tasks[len(rec_tasks):] if not problems else []
    lines.append("card 010 amendment 1, stage 2a generation result")
    lines.append(f"command summary: max_candidates={summary['max_candidates']} budget_seconds={summary['budget_seconds']} "
                 f"commit={summary['commit']} task_python={summary['task_python']} "
                 f"pytest_timeout_plugin={summary['pytest_timeout_plugin']} "
                 f"per_run_timeout_seconds={summary['per_run_timeout_seconds']}")
    lines.append(f"baseline: {summary['baseline']}")
    lines.append(f"candidate pool: {summary['candidate_pool_total']}; tried: {summary['tried']}; "
                 f"budget stopped the loop: {summary['tried'] < summary['max_candidates']}; "
                 f"loop_seconds: {summary['loop_seconds']}; mean_candidate_seconds: {summary['mean_candidate_seconds']}")
    lines.append(f"verdicts: {summary['verdicts']}")
    lines.append(f"kept: {summary['kept']} (recorded bank: {len(rec_tasks)}; new ids after "
                 f"{rec_tasks[-1]['task_id']}: {max(0, len(tasks) - len(rec_tasks))})")
    lines.append(f"gold checks: " + "; ".join(f"{c['task_id']} ok={c['ok']}" for c in doc.get("gold_checks", [])))
    lines.append(f"DETERMINISM: {verdict}")
    if address_only:
        lines.append(f"  address-only statement differences: {', '.join(address_only)}")
    for p in problems[:40]:
        lines.append(f"  FAIL {p}")
    if new_tasks:
        sel = propose_selection(new_tasks, rec_tasks)
        lines.append("PROPOSED selection (amendment 1; counts only): " + json.dumps(sel))
    elif problems:
        lines.append("selection not computed: the determinism check failed, so no new id is used")
    else:
        lines.append("selection not computed: no new kept task")
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if result:
        Path(result).write_text(text, encoding="utf-8", newline="\n")
    return 1 if verdict == "FAIL" else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--schedule", action="store_true")
    mode.add_argument("--compare", action="store_true")
    ap.add_argument("--repo-dir", type=Path, default=None, help="sqlparse clone (default: generate.runtime_dir())")
    ap.add_argument("--full-tasks", type=Path, default=HERE / "tasks.mutations.full.json")
    ap.add_argument("--full-log", type=Path, default=HERE / "generation_log.full.json")
    ap.add_argument("--result", type=Path, default=None)
    args = ap.parse_args()
    sys.exit(schedule_check(args.repo_dir) if args.schedule else compare(args.full_tasks, args.full_log, args.result))


if __name__ == "__main__":
    main()
