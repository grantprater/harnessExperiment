"""Build the pooled task registry for cards 007, 023 and 010 (stage 1 + stage 2a).

Offline and deterministic: reads committed JSON only, makes no model calls and runs no tests.
Stdlib only.

    python experiments/session_harness/build_task_registry.py            # write task_registry.json
    python experiments/session_harness/build_task_registry.py --check    # rebuild, diff, exit 1 on mismatch

Card 023 (boltons) has not been merged into this branch. Its three source files are read from a
pinned commit (BOLTONS_REF, the card's final analysis commit on analysis/c023) with `git show`, so
the build is reproducible without copying them here. The blob sha256 of each is recorded.

Roles (exactly one per task, first match wins):
  1. eval-010-combined          in E3-difficulty-calibration-010.eval-combined.json `eval`
  2. boltons-evolution-excluded card 023 calibration task that was mixed or 0/2 (015, 023, 056);
                                owner: boltons is the near-transfer test, its evolution set is not used
  3. near-transfer-boltons      the other card 023 calibration tasks
  4. evolution-contrastive /    card 007's evolution set (E3-calibration-007-report.md, "Evolution set");
     evolution-negative         those tasks are also card 010 stage-1 dev core, tagged `dev`
  5. dev                        in either card 010 split file's `dev` list
  6. excluded-statement-names-function
                                listed as excluded by a sets file (010 stage 1, 010 stage 2a) or by
                                card 023's selector (statement names the mutated function)
  7. uncalibrated-pool          everything else in a bank task file
Secondary tags (`tags`): evolution-contrastive / evolution-negative for eval tasks in a stage's
evolution lists, `dev` for role-4 tasks, `same-mutation-as-other-id` when another id carries the
identical mutation patch.

`overlaps_eval` is a tag only: for each non-eval task, the eval ids with the same mutated function
and the eval ids with the same exact fail-to-pass set (within the same bank). Nothing is moved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SH = "experiments/session_harness"
MT = "experiments/mutation_tasks"
OUT = ROOT / SH / "task_registry.json"

FULL = f"{MT}/tasks.mutations.full.json"
REC = f"{MT}/tasks.mutations.json"
D010 = f"{MT}/tasks.difficulty010.json"
D010B = f"{MT}/tasks.difficulty010-stage2a.json"
SETS1 = f"{SH}/E3-difficulty-calibration-010.sets.json"
SPLIT1 = f"{SH}/E3-difficulty-calibration-010.split.json"
SETS2A = f"{SH}/E3-difficulty-calibration-010-stage2a.sets.json"
SPLIT2A = f"{SH}/E3-difficulty-calibration-010-stage2a.split.json"
COMBINED = f"{SH}/E3-difficulty-calibration-010.eval-combined.json"
T007 = f"{SH}/E3-calibration-007-tasks.json"
CAMP007 = f"{SH}/c007-campaign.jsonl"

BOLTONS_REF = "57161e64ff28c9600c856cf5393701f755299754"  # analysis(c023): boltons calibration 36/40, 2 contrastive; rule not met; card completed
BOLTONS_BANK = f"{MT}/tasks.boltons.json"
T023 = f"{SH}/E3-calibration-023-tasks.json"
SETS023 = f"{SH}/E3-calibration-023.sets.json"

C007 = "E3-calibration-007"
C010 = "E3-difficulty-calibration-010"
C010B = "E3-difficulty-calibration-010-stage2a"
C023 = "E3-calibration-023"

# Card 007 report, section "Evolution set (card rule applied)"; chosen by hand per that card, no machine file.
EVO007_CONTRASTIVE = ["sqlparse-mut-001", "sqlparse-mut-022"]
EVO007_NEGATIVE = ["sqlparse-mut-032", "sqlparse-mut-057", "sqlparse-mut-061"]

ROLE_ORDER = ["eval-010-combined", "boltons-evolution-excluded", "near-transfer-boltons", "evolution-contrastive",
              "evolution-negative", "dev", "excluded-statement-names-function", "uncalibrated-pool"]
STRATUM_LONG = {"single test": "single", "multi-test, message": "multi-msg", "multi-test, no message": "multi-nm"}

SOURCES: dict[str, dict] = {}


def _read(rel: str, ref: str | None = None) -> str:
    if ref is None:
        raw = (ROOT / rel).read_bytes()
    else:
        raw = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT, check=True,
                             capture_output=True).stdout
    text = raw.decode("utf-8").replace("\r\n", "\n")
    SOURCES[rel] = {"ref": ref or "worktree",
                    "sha256_lf": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return text


def load(rel: str, ref: str | None = None):
    return json.loads(_read(rel, ref))


def f2p_hash(f2p) -> str:
    return hashlib.sha256("\n".join(sorted(f2p)).encode("utf-8")).hexdigest()


def stratum_of(task) -> str:
    if len(task["fail_to_pass"]) == 1:
        return "single"
    return "multi-nm" if task.get("statement_message_dropped") else "multi-msg"


def category(accepted: int, runs: int) -> str:
    return "solved" if accepted == runs else ("hard" if accepted == 0 else "mixed")


def natural(tid: str):
    parts = tid.split("-")
    return [int(p) if p.isdigit() else p for p in parts]


def build():
    SOURCES.clear()
    issues: list[str] = []

    # ---- task definitions (card-specific file first, then the recorded bank, then the full bank)
    full = load(FULL)["tasks"]
    rec = load(REC)["tasks"]
    d1 = load(D010)["tasks"]
    d2 = load(D010B)["tasks"]
    bol = load(BOLTONS_BANK, BOLTONS_REF)["tasks"]
    files = [(D010B, d2), (D010, d1), (REC, rec), (FULL, full), (BOLTONS_BANK, bol)]
    defs: dict[str, tuple[str, dict]] = {}
    defined_in: dict[str, list[str]] = defaultdict(list)
    for path, tasks in files:
        ids = [t["task_id"] for t in tasks]
        for tid, n in Counter(ids).items():
            if n > 1:
                issues.append(f"{path}: task id {tid} appears {n} times")
        for t in tasks:
            defined_in[t["task_id"]].append(path)
            if t["task_id"] not in defs:
                defs[t["task_id"]] = (path, t)
            else:
                first = defs[t["task_id"]][1]
                if (first["mutated_function"], sorted(first["fail_to_pass"]), first["mutation_patch"]) != \
                        (t["mutated_function"], sorted(t["fail_to_pass"]), t["mutation_patch"]):
                    issues.append(f"{t['task_id']}: mutation or failing set differs between "
                                  f"{defs[t['task_id']][0]} and {path}")

    # ---- card 010 stage 1 / stage 2a
    sets1, split1 = load(SETS1), load(SPLIT1)
    sets2, split2 = load(SETS2A), load(SPLIT2A)
    comb = load(COMBINED)
    eval_ids = list(comb["eval"])
    eval_set = set(eval_ids)
    if eval_ids != list(split1["eval"]) + list(split2["eval"]):
        issues.append("combined eval is not stage-1 eval + stage-2a eval in order")
    stratum_card = {}
    for c in sets1["candidates"] + sets2["candidates"]:
        stratum_card[c["task_id"]] = STRATUM_LONG[c["stratum"]]

    p1 = split1["derived"]["per_arm"]["incumbent"]
    evo_tag = {}
    for t in p1["mixed"] + split2["evolution"]["contrastive_1of2"]:
        evo_tag[t] = "evolution-contrastive"
    for t in p1["none_accepted"] + split2["evolution"]["negative_0of2"]:
        evo_tag[t] = "evolution-negative"

    member: dict[str, list[str]] = defaultdict(list)
    calib: dict[str, dict] = defaultdict(dict)

    for t in sets1["calibration"]:
        member[t].append(f"{C010}:calibration")
        calib[t][C010] = {"accepted": split1["accepted_of_2"][t], "runs": 2, "category": split1["category"][t]}
    for t in sets1["dev_core"]:
        member[t].append(f"{C010}:dev_core")
    for t in sorted(sets1["dev_pool"]):
        member[t].append(f"{C010}:dev_pool")
    for t in sorted(sets1["excluded"]):
        member[t].append(f"{C010}:excluded")
    for t in sets2["calibration"]:
        member[t].append(f"{C010B}:calibration")
        calib[t][C010B] = {"accepted": split2["accepted_of_2"][t], "runs": 2, "category": split2["category"][t]}
    for t in sorted(sets2["dev_pool"]):
        member[t].append(f"{C010B}:dev_pool")
    for t in sorted(sets2["excluded"]):
        member[t].append(f"{C010B}:excluded")
    dev1, dev2 = set(split1["dev"]), set(split2["dev"])
    excluded = set(sets1["excluded"]) | set(sets2["excluded"])

    # ---- card 007
    t007 = load(T007)
    acc007: dict[str, list[int]] = defaultdict(list)
    seen_runs = set()
    for line in _read(CAMP007).splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "run" not in r:
            continue
        if r["run"] in seen_runs:
            issues.append(f"card 007 campaign: run {r['run']} recorded twice")
        seen_runs.add(r["run"])
        acc007[r["task"]].append(1 if r["acceptance"] == "accepted" else 0)
    for t in t007["task_ids"]:
        member[t].append(f"{C007}:calibration")
        a = acc007.get(t)
        calib[t][C007] = None if not a else {"accepted": sum(a), "runs": len(a), "category": category(sum(a), len(a))}
    excluded |= set(t007["excluded_statement_names_mutated_function"])
    for t in t007["excluded_statement_names_mutated_function"]:
        member[t].append(f"{C007}:excluded")

    # ---- card 023 (boltons)
    t023 = load(T023, BOLTONS_REF)
    p023 = load(SETS023, BOLTONS_REF)["derived"]["per_arm"]["incumbent"]
    acc023 = {**{t: 2 for t in p023["all_accepted"]}, **{t: 1 for t in p023["mixed"]},
              **{t: 0 for t in p023["none_accepted"]}}
    for t in t023["task_ids"]:
        member[t].append(f"{C023}:calibration")
        calib[t][C023] = None if t not in acc023 else {"accepted": acc023[t], "runs": 2,
                                                       "category": category(acc023[t], 2)}
    boltons_evo = set(p023["mixed"]) | set(p023["none_accepted"])
    bexcl = set(t023["excluded_statement_names_mutated_function"])
    excluded |= bexcl
    for t in sorted(bexcl):
        member[t].append(f"{C023}:excluded")

    # ---- identity checks
    for t in list(member) + eval_ids:
        if t not in defs:
            issues.append(f"{t}: listed by a card but defined in no task file")

    # ---- same mutation under several ids
    by_patch: dict[str, list[str]] = defaultdict(list)
    for tid, (_, t) in defs.items():
        by_patch[hashlib.sha256((t["repo"] + "\n" + t["mutation_patch"]).encode("utf-8")).hexdigest()].append(tid)
    same_mut = {}
    for ids in by_patch.values():
        if len(ids) > 1:
            for tid in ids:
                same_mut[tid] = sorted((x for x in ids if x != tid), key=natural)

    # ---- roles
    evo007 = {**{t: "evolution-contrastive" for t in EVO007_CONTRASTIVE},
              **{t: "evolution-negative" for t in EVO007_NEGATIVE}}
    records = {}
    for tid, (path, t) in defs.items():
        bank = t["repo"]
        tags: list[str] = []
        if tid in eval_set:
            role, role_source = "eval-010-combined", COMBINED
            if tid in evo_tag:
                tags.append(evo_tag[tid])
        elif tid in boltons_evo:
            role, role_source = "boltons-evolution-excluded", f"{SETS023}@{BOLTONS_REF} (mixed + none_accepted); owner decision"
        elif f"{C023}:calibration" in member[tid]:
            role, role_source = "near-transfer-boltons", f"{T023}@{BOLTONS_REF}; owner decision"
        elif tid in evo007:
            role, role_source = evo007[tid], f"{SH}/E3-calibration-007-report.md (Evolution set)"
            if tid in dev1 or tid in dev2:
                tags.append("dev")
        elif tid in dev1 or tid in dev2:
            role = "dev"
            role_source = " + ".join(p for p, s in ((SPLIT1, dev1), (SPLIT2A, dev2)) if tid in s)
        elif tid in excluded:
            role, role_source = "excluded-statement-names-function", "sets/tasks file `excluded` lists"
        else:
            role, role_source = "uncalibrated-pool", path
        if tid in evo_tag and tid not in eval_set:
            issues.append(f"{tid}: in a stage evolution list but not in eval")
        if tid in eval_set and (tid in dev1 or tid in dev2):
            issues.append(f"{tid}: eval task also in a dev list")
        if tid in same_mut:
            tags.append("same-mutation-as-other-id")
        cards = sorted({m.split(":")[0] for m in member[tid]})
        st = stratum_of(t)
        if tid in stratum_card and stratum_card[tid] != st:
            issues.append(f"{tid}: stratum {stratum_card[tid]} in sets file, derived {st}")
        records[tid] = {
            "id": tid,
            "bank": bank,
            "task_definition_file": path,
            "also_defined_in": [p for p in defined_in[tid] if p != path],
            "source_cards": cards,
            "memberships": member[tid],
            "stratum": st,
            "calibration": {c: calib[tid].get(c) for c in cards},
            "mutation_file": t["mutation_file"],
            "mutated_function": t["mutated_function"],
            "mutation_kind": t["mutation_kind"],
            "variant_of": t.get("variant_of"),
            "fail_to_pass_count": len(t["fail_to_pass"]),
            "fail_to_pass_sha256": f2p_hash(t["fail_to_pass"]),
            "same_mutation_as": same_mut.get(tid, []),
            "role": role,
            "role_source": role_source,
            "tags": tags,
            "overlaps_eval": None,
        }

    # ---- overlap tags (same bank; function name and exact failing set, as apply_split_010_stage2a.py)
    for tid, r in records.items():
        if r["role"] == "eval-010-combined":
            continue
        fn = [e for e in eval_ids if records[e]["bank"] == r["bank"]
              and records[e]["mutated_function"] == r["mutated_function"]]
        fs = [e for e in eval_ids if records[e]["bank"] == r["bank"]
              and records[e]["fail_to_pass_sha256"] == r["fail_to_pass_sha256"]]
        r["overlaps_eval"] = {"same_function": fn, "same_failing_set": fs}

    rest = sorted((t for t in records if t not in eval_set), key=lambda t: (records[t]["bank"], natural(t)))
    ordered = [records[t] for t in eval_ids] + [records[t] for t in rest]

    counts = defaultdict(Counter)
    for r in ordered:
        counts[r["bank"]][r["role"]] += 1
    ov = {"same_function_pairs": sum(len(r["overlaps_eval"]["same_function"]) for r in ordered if r["overlaps_eval"]),
          "same_failing_set_pairs": sum(len(r["overlaps_eval"]["same_failing_set"]) for r in ordered
                                        if r["overlaps_eval"]),
          "tasks_with_function_overlap": sum(1 for r in ordered if r["overlaps_eval"]
                                             and r["overlaps_eval"]["same_function"]),
          "tasks_with_failing_set_overlap": sum(1 for r in ordered if r["overlaps_eval"]
                                                and r["overlaps_eval"]["same_failing_set"])}
    reg = {
        "schema_version": 1,
        "generated_by": f"{SH}/build_task_registry.py",
        "note": ("Pooled task registry, cards 007, 023, 010 stage 1 + 2a. overlaps_eval is a tag only; "
                 "no task was moved or excluded because of it."),
        "boltons_ref": BOLTONS_REF,
        "sources": dict(sorted(SOURCES.items())),
        "roles": ROLE_ORDER,
        "counts": {b: {r: counts[b][r] for r in ROLE_ORDER if counts[b][r]} for b in sorted(counts)},
        "overlap_totals": ov,
        "eval_order": eval_ids,
        "tasks": ordered,
    }
    return reg, issues, (split1, split2, t007, t023, dev1, dev2)


def render(reg) -> str:
    return json.dumps(reg, indent=1, ensure_ascii=False) + "\n"


def report(reg, issues, ctx) -> int:
    split1, split2, t007, t023, dev1, dev2 = ctx
    by = {r["id"]: r for r in reg["tasks"]}
    bad = list(issues)
    print("counts (bank x role):")
    for b, c in reg["counts"].items():
        print(f"  {b}: " + ", ".join(f"{k} {v}" for k, v in c.items()) + f"  (total {sum(c.values())})")
    ev = [r["id"] for r in reg["tasks"] if r["role"] == "eval-010-combined"]
    ok_order = ev == reg["eval_order"]
    print(f"eval-010-combined: {len(ev)} tasks, combined-file order {'yes' if ok_order else 'NO'}")
    if not ok_order:
        bad.append("eval order mismatch")

    def has_dev(t):
        return by[t]["role"] == "dev" or "dev" in by[t]["tags"]

    rows = []
    for name, split in (("010 stage 1", split1), ("010 stage 2a", split2)):
        r_eval = sum(1 for t in split["eval"] if by[t]["role"] == "eval-010-combined")
        r_dev = sum(1 for t in split["dev"] if has_dev(t))
        rows.append((name, "eval", len(split["eval"]), r_eval))
        rows.append((name, "dev", len(split["dev"]), r_dev))
    c7 = [by[t]["calibration"]["E3-calibration-007"] for t in t007["task_ids"]]
    rows.append(("007", "tasks", len(t007["task_ids"]), sum(1 for t in t007["task_ids"] if t in by)))
    rows.append(("007", "accepted/runs", "32/40",
                 f"{sum(x['accepted'] for x in c7)}/{sum(x['runs'] for x in c7)}"))
    c23 = [by[t]["calibration"]["E3-calibration-023"] for t in t023["task_ids"]]
    rows.append(("023", "tasks", len(t023["task_ids"]),
                 sum(1 for t in t023["task_ids"] if by[t]["role"] in ("near-transfer-boltons",
                                                                     "boltons-evolution-excluded"))))
    rows.append(("023", "accepted/runs", "36/40",
                 f"{sum(x['accepted'] for x in c23)}/{sum(x['runs'] for x in c23)}"))
    print("reconciliation (card | set | split/source | registry | match):")
    for name, what, want, got in rows:
        m = str(want) == str(got)
        print(f"  {name:13s} | {what:13s} | {str(want):>6s} | {str(got):>6s} | {'ok' if m else 'MISMATCH'}")
        if not m:
            bad.append(f"reconciliation {name} {what}: {want} vs {got}")

    dev_all = dev1 | dev2
    fn = sum(len(by[t]["overlaps_eval"]["same_function"]) for t in dev_all)
    fs = sum(len(by[t]["overlaps_eval"]["same_failing_set"]) for t in dev_all)
    print(f"overlap restricted to the 010 dev lists ({len(dev_all)} tasks): function pairs {fn} (expected 38), "
          f"failing-set pairs {fs} (expected 26)")
    if (fn, fs) != (38, 26):
        bad.append(f"dev overlap {fn}/{fs} != 38/26")
    o = reg["overlap_totals"]
    print(f"overlap over all non-eval tasks: function pairs {o['same_function_pairs']} "
          f"({o['tasks_with_function_overlap']} tasks), failing-set pairs {o['same_failing_set_pairs']} "
          f"({o['tasks_with_failing_set_overlap']} tasks)")
    by_role = Counter()
    for r in reg["tasks"]:
        if r["overlaps_eval"] and (r["overlaps_eval"]["same_function"] or r["overlaps_eval"]["same_failing_set"]):
            by_role[r["role"]] += 1
    print("  non-eval tasks with any overlap, by role: " + ", ".join(f"{k} {v}" for k, v in sorted(by_role.items())))
    ids = [r["id"] for r in reg["tasks"]]
    dup = [t for t, n in Counter(ids).items() if n > 1]
    print(f"duplicate ids: {dup or 'none'} ({len(ids)} records)")
    if dup:
        bad.append(f"duplicate ids {dup}")
    sm = [r for r in reg["tasks"] if r["same_mutation_as"]]
    print(f"same mutation under several ids: {len(sm)} records")
    for r in sm:
        print(f"  {r['id']} ({r['role']}) = {', '.join(r['same_mutation_as'])}")
    for i in issues:
        print(f"ISSUE: {i}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="rebuild and diff against the committed file")
    args = ap.parse_args()
    reg, issues, ctx = build()
    text = render(reg)
    status = report(reg, issues, ctx)
    if args.check:
        if not OUT.exists():
            print(f"CHECK FAIL: {OUT} missing")
            return 1
        old = OUT.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if old != text:
            a, b = old.splitlines(), text.splitlines()
            first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            print(f"CHECK FAIL: {OUT.name} differs from a rebuild (first difference at line {first + 1})")
            return 1
        print(f"CHECK OK: {OUT.name} matches a rebuild")
        return status
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(reg['tasks'])} tasks)")
    return status


if __name__ == "__main__":
    sys.exit(main())
