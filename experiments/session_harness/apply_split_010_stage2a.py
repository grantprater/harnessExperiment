"""Card 010 stage 2a (amendment 1): integrity checks, per-stratum outcomes, the keep/drop rule, the combined eval list.

Offline only: reads recorded run folders, the campaign log and the stage-1 split; calls no model and evaluates nothing.
The stage-1 twin is apply_split_010.py; its helpers are imported unchanged and its output is not affected.

Inputs:
  experiments/p6_pilot/runs/c010b-<task>-r<k>[-aN]/{results,calls}.jsonl, config.json   (calibration runs, retries)
  experiments/p6_pilot/runs/c010b-<task>-r<k>.void-<reason>/                            (voided attempts, side data)
  experiments/p6_pilot/runs/c010b-control-gold/sessions/<task>__gold-client/workspace   (upstream code, for diffs)
  experiments/p6_pilot/runs/card-E3-difficulty-calibration-010-stage2a/campaign.jsonl
  experiments/session_harness/E3-difficulty-calibration-010-stage2a.sets.json  (calibration order, strata; never edited)
  experiments/session_harness/E3-difficulty-calibration-010.split.json         (stage-1 split; read only, never edited)
  experiments/mutation_tasks/tasks.difficulty010-stage2a.json                  (mutation patches, for the audit)
  experiments/mutation_tasks/tasks.mutations.full.json                         (functions and failing sets of dev tasks)
  run_card.py cards/010-stage2a.json --plan --json  (expected protocol hash per run; run here unless --plan is given)

Keep/drop rule (cards/010-stage2a.json decision_rule; amendment 1, A1.4), applied literally to the 39 stage-2a tasks
alone, in stage-2a calibration-list order: solved 2/2, mixed 1/2, hard 0/2; eval starts as all mixed + hard;
predicted acceptance = task-weighted mean of 0.94 / 0.25 / 0.08; add solved tasks in list order while predicted
< 0.40 (checked before each add); if still < 0.30 with no solved task left, move hard tasks to dev from the end of the
list until >= 0.30; every other task goes to dev. The kept eval tasks are added to stage 1's 12 (stage-1 split
unchanged); the combined list is stage 1's eval in its order, then stage 2a's eval in its order.

Usage:
  python experiments/session_harness/apply_split_010_stage2a.py [--plan PLAN.json] [--write] [--markdown OUT.md]
                                                                [--diffs DIR]
  --write  updates E3-difficulty-calibration-010-stage2a.split.json (keeps run_card's "derived" block) and writes
           E3-difficulty-calibration-010.eval-combined.json.
  --diffs  writes each non-accepted run's final-workspace diff against upstream (gold control workspace) to DIR.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_split_010 import call_errors, mutation_reverted, read_jsonl, wilson  # noqa: E402  (stage-1 helpers)

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
HERE = ROOT / "experiments" / "session_harness"
CARD = HERE / "cards" / "010-stage2a.json"
SETS = HERE / "E3-difficulty-calibration-010-stage2a.sets.json"
SPLIT = HERE / "E3-difficulty-calibration-010-stage2a.split.json"
SPLIT1 = HERE / "E3-difficulty-calibration-010.split.json"
COMBINED = HERE / "E3-difficulty-calibration-010.eval-combined.json"
BANK = ROOT / "experiments" / "mutation_tasks" / "tasks.difficulty010-stage2a.json"
FULL = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.full.json"
CAMPAIGN = RUNS / "card-E3-difficulty-calibration-010-stage2a" / "campaign.jsonl"
GOLD = RUNS / "c010b-control-gold" / "sessions"

MODEL = "claude-sonnet-5"
CLI_VERSION = "2.1.286"
ADAPTER_FAILURE_STOPS = ("model_error", "model_mismatch", "cli_version_mismatch")
PREDICTOR = {"solved": 0.94, "mixed": 0.25, "hard": 0.08}
ADD_WHILE_BELOW, FLOOR = 0.40, 0.30
PREFIX = "c010b"
NAME = re.compile(rf"^{PREFIX}-(sqlparse-mut-\d+(?:-nm)?)-r(\d+)(?:-a(\d+))?$")
VOID = re.compile(rf"^({PREFIX}-sqlparse-mut-\d+(?:-nm)?-r\d+(?:-a\d+)?)\.void-(.+)$")
STRATA = ("single test", "multi-test, message", "multi-test, no message")
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}
# Power table of the card markdown ("Power note"): (design, eval tasks needed). Recompute with power_010.py.
POWER = [
    ("delta 0.15, p0 0.45, optimistic (0.15, 0.00), r = 2", 40), ("delta 0.15, p0 0.45, optimistic, r = 3", 27),
    ("delta 0.15, p0 0.45, optimistic, r = 4", 20),
    ("delta 0.15, p0 0.45, central (0.10, 0.02), r = 2", 70), ("delta 0.15, p0 0.45, central, r = 3", 49),
    ("delta 0.15, p0 0.45, central, r = 4", 39),
    ("delta 0.15, p0 0.45, pessimistic (0.05, 0.04), r = 2", 99), ("delta 0.15, p0 0.45, pessimistic, r = 3", 72),
    ("delta 0.15, p0 0.45, pessimistic, r = 4", 58),
    ("delta 0.15, p0 0.30, central, r = 2", 63), ("delta 0.15, p0 0.30, central, r = 3", 45),
    ("delta 0.15, p0 0.30, central, r = 4", 36),
    ("delta 0.15, p0 0.60, central, r = 2", 57), ("delta 0.15, p0 0.60, central, r = 3", 41),
    ("delta 0.15, p0 0.60, central, r = 4", 33),
    ("delta 0.15, one primary comparison (alpha 0.05), central, r = 2", 58),
    ("delta 0.20, central, r = 2", 38), ("delta 0.20, central, r = 4", 22),
]


def run_calls(folder):
    return read_jsonl(folder / "calls.jsonl")


def model_and_cli(folder):
    """Every model identity the run recorded, and the CLI version of every call (cli_init per call + config.json)."""
    problems, seen, versions = [], set(), Counter()
    for r in read_jsonl(folder / "results.jsonl"):
        seen.add(("results.model", r.get("model")))
        for m in r.get("reported_models") or []:
            seen.add(("results.reported_models", m))
        for key in ("model_mismatch", "model_pin_violation", "cli_version_mismatch"):
            if key in r:
                problems.append(f"results has {key}")
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    for m in cfg.get("models") or []:
        seen.add(("config.models", m))
    calls = run_calls(folder)
    for c in calls:
        seen.add(("call.model", c.get("model")))
        init = c.get("cli_init") or {}
        if init:
            seen.add(("cli_init.model", init.get("model")))
        versions[init.get("claude_code_version")] += 1
        resp = c.get("response") or {}
        if resp.get("model") is not None:
            seen.add(("response.model", resp.get("model")))
        for m in c.get("reported_models") or []:
            seen.add(("call.reported_models", m))
        for m in ((c.get("cli_result") or {}).get("modelUsage") or {}):
            seen.add(("modelUsage", m))
        for key in ("model_mismatch", "model_pin_violation", "cli_version_mismatch"):
            if key in c:
                problems.append(f"call has {key}")
    bad = sorted({f"{where}={m}" for where, m in seen if m != MODEL})
    sources = sorted({where for where, _ in seen})
    return problems + bad, len(calls), sources, versions, cfg


def cost(folder):
    return sum(float((c.get("cli_result") or {}).get("total_cost_usd") or 0.0) for c in run_calls(folder))


def tree(root):
    out = {}
    if root is None or not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
            out[p.relative_to(root).as_posix()] = p
    return out


def workspace_diff(folder, task_id):
    """Unified diff (CR stripped) of the run's final workspace against the gold control's workspace (= upstream)."""
    ws = next((folder / "sessions").glob("*/workspace"), None)
    gold = GOLD / f"{task_id}__gold-client" / "workspace"
    a, b = tree(gold), tree(ws)
    chunks, changed = [], []
    for rel in sorted(set(a) | set(b)):
        ta = a[rel].read_text(encoding="utf-8", errors="replace").replace("\r", "").splitlines(True) if rel in a else []
        tb = b[rel].read_text(encoding="utf-8", errors="replace").replace("\r", "").splitlines(True) if rel in b else []
        if ta != tb:
            changed.append(rel if rel in a and rel in b else f"{rel} ({'removed' if rel in a else 'added'})")
            chunks.extend(difflib.unified_diff(ta, tb, f"upstream/{rel}", f"final/{rel}"))
    return changed, "".join(chunks)


def changed_lines(patch):
    return [ln for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("---", "+++"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, help="saved `run_card.py --plan --json` output (default: compute it now)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--diffs", type=Path)
    args = ap.parse_args()

    sets = json.loads(SETS.read_text(encoding="utf-8"))
    order = sets["calibration"]
    stratum = {c["task_id"]: c["stratum"] for c in sets["candidates"]}
    tasks = {t["task_id"]: t for t in json.loads(BANK.read_text(encoding="utf-8"))["tasks"]}
    split1 = json.loads(SPLIT1.read_text(encoding="utf-8"))
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    else:  # offline: run_card.py --plan computes hashes in-process and calls no model
        out = subprocess.run([sys.executable, str(HERE / "run_card.py"), str(CARD), "--plan", "--json"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", check=True)
        plan = json.loads(out.stdout)
    expected = {i["run_name"]: i["expected_protocol_hash"] for i in plan["invocations"] if i["kind"] == "run"}
    camp = read_jsonl(CAMPAIGN)
    void_events = {e["renamed_to"]: e for e in camp if e["event"] == "void"}
    md, issues = [], []
    say = md.append

    # ---- folders -> attempts per planned run; voided folders kept apart
    attempts, stray, voids = defaultdict(list), [], []
    for d in sorted(RUNS.iterdir()):
        if not d.is_dir() or not d.name.startswith(f"{PREFIX}-sqlparse"):
            continue
        v = VOID.match(d.name)
        if v:
            voids.append((d, v.group(1), v.group(2)))
            continue
        m = NAME.match(d.name)
        base = f"{PREFIX}-{m.group(1)}-r{m.group(2)}" if m else None
        if not m or base not in expected:
            stray.append(d.name)
            continue
        attempts[base].append((int(m.group(3) or 1), d))
    if stray:
        issues.append(f"run folders outside the plan: {stray}")
    missing = sorted(set(expected) - set(attempts))
    if missing:
        issues.append(f"planned runs with no folder: {missing}")

    valid, voided = {}, []
    for base, lst in attempts.items():
        lst.sort()
        good = []
        for n, d in lst:
            recs = read_jsonl(d / "results.jsonl")
            if len(recs) != 1:
                issues.append(f"{d.name}: {len(recs)} result records")
                continue
            if recs[0].get("stop") in ADAPTER_FAILURE_STOPS:
                voided.append((d, recs[0]))
            else:
                good.append((d, recs[0]))
        if len(good) != 1:
            issues.append(f"{base}: {len(good)} valid attempts")
            continue
        if lst[-1][1] != good[0][0]:
            issues.append(f"{base}: the valid attempt is not the last one")
        valid[base] = good[0]

    # ---- integrity
    say("#### Integrity")
    say("")
    model_bad, hash_bad, srcs, n_calls = [], [], set(), 0
    versions_valid, version_bad = Counter(), []
    for base, (d, rec) in sorted(valid.items()):
        probs, nc, sources, vers, cfg = model_and_cli(d)
        n_calls += nc
        srcs.update(sources)
        versions_valid.update(vers)
        if probs:
            model_bad.append(f"{d.name}: {probs}")
        off = {k: n for k, n in vers.items() if k != CLI_VERSION}
        if off:
            version_bad.append(f"{d.name}: {off}")
        for h in {rec.get("protocol_hash"), cfg.get("protocol_hash")}:
            if h != expected[base]:
                hash_bad.append(f"{d.name}: {h} != planned {expected[base]}")
    per_task_hash = defaultdict(set)
    for base, (d, rec) in valid.items():
        per_task_hash[rec["task_id"]].add(rec["protocol_hash"])
    split_hash = {t: h for t, h in per_task_hash.items() if len(h) != 1}
    issues += model_bad + hash_bad + version_bad + (
        [f"rollouts differ in protocol hash: {split_hash}"] if split_hash else [])
    if voided:
        issues.append(f"adapter-failure attempts not renamed void: {[d.name for d, _ in voided]}")

    starts = [i for i, e in enumerate(camp) if e["event"] == "campaign_start"]
    ends_all = [e for e in camp if e["event"] == "invocation_end"]
    last = camp[starts[-1]:]
    ends = [e for e in last if e["event"] == "invocation_end"]
    skips = [e for e in last if e["event"] == "skip"]
    fails = [e for e in last if e["event"] == "invocation_end" and e.get("outcome") != "ok"]
    pres = [e for e in camp if e["event"] == "preflight"]
    say(f"- Planned calibration runs: {len(expected)}; folders matched to the plan: "
        f"{sum(len(v) for v in attempts.values())} ({len(valid)} valid, {len(voided)} adapter-failure attempts); "
        f"voided folders (`*.void-*`, not outcomes): {len(voids)}; folders outside the plan: {len(stray)}; "
        f"planned runs without a folder: {len(missing)}.")
    say(f"- Model: {n_calls} recorded provider calls across the {len(valid)} valid runs; every model field "
        f"({', '.join(sorted(srcs))}) reads `{MODEL}`: {'yes' if not model_bad else 'NO: ' + '; '.join(model_bad)}. "
        f"No `model_mismatch` / `model_pin_violation` / `cli_version_mismatch` record in a valid run.")
    say(f"- CLI version per call (`calls.jsonl` `cli_init.claude_code_version`), valid runs: "
        f"{dict(sorted(versions_valid.items(), key=str))}; exceptions: "
        f"{'none' if not version_bad else '; '.join(version_bad)}.")
    say(f"- Protocol hash: each valid run's `results.jsonl` and `config.json` hash equals the hash `run_card.py --plan` "
        f"computes for that run (card sha256 `{plan['card_sha256'][:12]}`; the campaign's last start used card sha256 "
        f"`{last[0]['card_sha256'][:12]}`; the card's status line is not a hash input): "
        f"{'yes' if not hash_bad else 'NO: ' + '; '.join(hash_bad)}. {len(per_task_hash)} distinct hashes, one per "
        f"task, identical across both rollouts of every task ({'yes' if not split_hash else 'NO'}). Arm preflights: "
        f"{', '.join(f"{p['time']} {p['expected']}={p['observed']}" for p in pres)}.")
    say(f"- Campaign log: {len(starts)} starts; {len(ends_all)} invocation ends in all, {len(ends)} after the last start "
        f"({last[0]['time']}), which skipped {len(skips)} complete units; not ok after the last start: "
        f"{len(fails)}{' (' + ', '.join(e['run'] for e in fails) + ')' if fails else ''}; integrity stops: "
        f"{[e['reason'] for e in camp if e['event'] == 'integrity_stop']}; end event: "
        f"{next((e.get('reason') for e in last if e['event'] == 'campaign_end'), 'MISSING')}.")
    say("")
    say("Voided folders (side data, not calibration outcomes):")
    say("")
    say("| Folder | Reason | Calls | CLI versions per call | Recorded hash (planned) | Stop | Status | Cost USD |")
    say("|---|---|--:|---|---|---|---|--:|")
    void_rows = []
    for d, base, reason in voids:
        probs, nc, _, vers, cfg = model_and_cli(d)
        rec = read_jsonl(d / "results.jsonl")
        rec = rec[0] if rec else {}
        ev = void_events.get(d.name, {})
        c = cost(d)
        void_rows.append({"folder": d.name, "reason": reason, "detail": ev.get("detail"), "calls": nc,
                          "versions": dict(vers), "hash": cfg.get("protocol_hash"), "planned": expected.get(base),
                          "stop": rec.get("stop"), "status": (rec.get("acceptance") or {}).get("status"),
                          "cost_usd": round(c, 4), "model_problems": probs})
        say(f"| {d.name} | {ev.get('detail') or reason} | {nc} | {dict(sorted(vers.items(), key=str))} | "
            f"`{cfg.get('protocol_hash')}` (`{expected.get(base)}`) | {rec.get('stop')} | "
            f"{(rec.get('acceptance') or {}).get('status')} | {c:.4f} |")
    say("")
    if issues:
        say(f"- **Integrity issues:** {issues}")
        say("")

    # ---- outcomes
    acc = defaultdict(list)
    for base, (d, rec) in valid.items():
        acc[rec["task_id"]].append(rec["acceptance"]["status"] == "accepted")
    cat = {}
    for t in order:
        k = sum(acc[t])
        cat[t] = "solved" if k == 2 else "mixed" if k == 1 else "hard"
        if len(acc[t]) != 2:
            issues.append(f"{t}: {len(acc[t])} valid runs")

    say("#### Outcomes by stratum")
    say("")
    say("| Stratum | Tasks | Runs accepted | Rate | Wilson 95% | 2/2 | 1/2 | 0/2 |")
    say("|---|--:|--:|--:|---|--:|--:|--:|")
    table = {}
    for s, ts in [(s, [t for t in order if stratum[t] == s]) for s in STRATA] + [(f"all {len(order)} tasks", list(order))]:
        k = sum(sum(acc[t]) for t in ts)
        n = sum(len(acc[t]) for t in ts)
        lo, hi = wilson(k, n)
        c = {x: sum(cat[t] == x for t in ts) for x in PREDICTOR}
        table[s] = {"tasks": len(ts), "accepted": k, "runs": n, "rate": round(k / n, 4),
                    "wilson95": [round(lo, 4), round(hi, 4)], "solved": c["solved"], "mixed": c["mixed"],
                    "hard": c["hard"]}
        say(f"| {s} | {len(ts)} | {k}/{n} | {k / n:.2f} | {lo:.2f}-{hi:.2f} | {c['solved']} | {c['mixed']} | "
            f"{c['hard']} |")
    say("")
    say("Stage 1 (from `E3-difficulty-calibration-010.split.json` `strata`) beside stage 2a:")
    say("")
    say("| Stratum | Stage 1 tasks | Stage 1 accepted | Stage 1 rate (Wilson 95%) | Stage 1 2/2-1/2-0/2 | "
        "Stage 2a tasks | Stage 2a accepted | Stage 2a rate (Wilson 95%) | Stage 2a 2/2-1/2-0/2 |")
    say("|---|--:|--:|---|---|--:|--:|---|---|")
    s1 = split1["strata"]
    for s, s1key in [(x, x) for x in STRATA] + [("all", "all 30 tasks")]:
        a = s1[s1key]
        b = table[s if s != "all" else f"all {len(order)} tasks"]
        say(f"| {s} | {a['tasks']} | {a['accepted']}/{a['runs']} | {a['rate']:.2f} ({a['wilson95'][0]:.2f}-"
            f"{a['wilson95'][1]:.2f}) | {a['solved']}-{a['mixed']}-{a['hard']} | {b['tasks']} | "
            f"{b['accepted']}/{b['runs']} | {b['rate']:.2f} ({b['wilson95'][0]:.2f}-{b['wilson95'][1]:.2f}) | "
            f"{b['solved']}-{b['mixed']}-{b['hard']} |")
    k1 = s1["all 30 tasks"]["accepted"] + table[f"all {len(order)} tasks"]["accepted"]
    n1 = s1["all 30 tasks"]["runs"] + table[f"all {len(order)} tasks"]["runs"]
    lo, hi = wilson(k1, n1)
    say(f"| both stages | | | | | {30 + len(order)} | {k1}/{n1} | {k1 / n1:.2f} ({lo:.2f}-{hi:.2f}) | |")
    say("")

    # ---- keep/drop rule
    def predicted(ts, cats):
        return sum(PREDICTOR[cats[t]] for t in ts) / len(ts) if ts else float("nan")

    trace = []
    eval_ = [t for t in order if cat[t] in ("mixed", "hard")]
    trace.append(f"start: {len(eval_)} mixed+hard tasks, predicted {predicted(eval_, cat):.4f}")
    solved_left = [t for t in order if cat[t] == "solved"]
    while solved_left and predicted(eval_, cat) < ADD_WHILE_BELOW:
        t = solved_left.pop(0)
        eval_.append(t)
        trace.append(f"add solved {t}: {len(eval_)} tasks, predicted {predicted(eval_, cat):.4f}")
    if not solved_left and predicted(eval_, cat) < FLOOR:
        for t in [x for x in reversed(order) if cat[x] == "hard"]:
            if predicted(eval_, cat) >= FLOOR:
                break
            eval_.remove(t)
            trace.append(f"move hard {t} to dev: predicted {predicted(eval_, cat):.4f}")
    eval_ = [t for t in order if t in eval_]
    dev_cal = [t for t in order if t not in eval_]

    say("#### Keep/drop rule, stage 2a alone (applied mechanically)")
    say("")
    for line in trace:
        say(f"- {line}")
    say(f"- Result: **stage-2a eval {len(eval_)} tasks** (predicted acceptance {predicted(eval_, cat):.4f}; observed "
        f"in calibration {sum(sum(acc[t]) for t in eval_)}/{2 * len(eval_)}, which the card does not use), "
        f"**{len(dev_cal)} calibration tasks to dev**.")
    say(f"- Stage-2a eval: {', '.join(eval_)}")
    say(f"- Dev (from stage-2a calibration): {', '.join(dev_cal)}")
    say("")

    # ---- combined eval
    cat1 = split1["category"]
    eval1 = list(split1["eval"])
    combined = eval1 + eval_
    cats_all = {**cat1, **cat}
    p1, p2, pu = predicted(eval1, cat1), predicted(eval_, cat), predicted(combined, cats_all)
    full = {t["task_id"]: t for t in json.loads(FULL.read_text(encoding="utf-8"))["tasks"]}

    def base_id(t):
        return t[:-3] if t.endswith("-nm") else t

    def sig(t):
        src = tasks.get(t) or full.get(base_id(t))
        return src["mutated_function"], tuple(sorted(src["fail_to_pass"]))

    dev_all = list(split1["dev"]) + list(sets["dev_core"]) + sorted(sets["dev_pool"]) + dev_cal
    dev_all = list(dict.fromkeys(dev_all))
    overlap_fn, overlap_fail = [], []
    dev_sig = {}
    for t in dev_all:
        try:
            dev_sig[t] = sig(t)
        except (KeyError, TypeError):
            issues.append(f"dev task {t}: no function/failing set found")
    for e in combined:
        fe, xe = sig(e)
        for t, (fd, xd) in dev_sig.items():
            if fd == fe:
                overlap_fn.append(f"{e}~{t}")
            if xd == xe:
                overlap_fail.append(f"{e}~{t}")
    task_overlap = sorted(set(combined) & set(dev_all))
    if task_overlap:
        issues.append(f"eval task also in dev: {task_overlap}")
    if len(set(combined)) != len(combined):
        issues.append("combined eval has duplicates")
    met = [(d, n) for d, n in POWER if len(combined) >= n]
    smallest = min(POWER, key=lambda x: x[1])

    say("#### Combined eval (stage 1's 12 + stage 2a)")
    say("")
    say(f"- Predicted acceptance: stage 1 eval {p1:.4f} ({len(eval1)} tasks); stage 2a eval {p2:.4f} ({len(eval_)} "
        f"tasks); union {pu:.4f} (**{len(combined)} tasks**: "
        f"{sum(cats_all[t] == 'solved' for t in combined)} solved, {sum(cats_all[t] == 'mixed' for t in combined)} "
        f"mixed, {sum(cats_all[t] == 'hard' for t in combined)} hard).")
    say(f"- Combined eval, stage 1 then stage 2a: {', '.join(combined)}")
    say(f"- Disjointness from dev ({len(dev_all)} tasks: stage-1 dev, stage-2a dev pool, stage-2a calibration tasks "
        f"moved to dev): by task id {'yes' if not task_overlap else 'NO ' + str(task_overlap)}; same mutated "
        f"function as a dev task: {len(overlap_fn)} pairs{' (' + ', '.join(overlap_fn) + ')' if overlap_fn else ''}; "
        f"same exact failing set as a dev task: {len(overlap_fail)} pairs"
        f"{' (' + ', '.join(overlap_fail) + ')' if overlap_fail else ''}.")
    say(f"- Power table (card markdown, \"Power note\"): designs whose task count the union ({len(combined)}) meets: "
        f"{'; '.join(f'{d} (needs {n})' for d, n in sorted(met, key=lambda x: x[1])) if met else 'none'}. "
        f"Smallest n in the table: {smallest[1]} ({smallest[0]}).")
    say(f"- Bank stopping rule: stage 2a added {len(eval_)} eval tasks ({'>= 5' if len(eval_) >= 5 else '< 5'}).")
    say("")

    # ---- evolution sets
    contrastive = [t for t in order if cat[t] == "mixed"]
    negative = [t for t in order if cat[t] == "hard"]
    say("#### Evolution sets (stage 2a)")
    say("")
    def where(ts):
        return ", ".join(f"{t} ({'eval' if t in eval_ else 'dev'})" for t in ts)

    say(f"- Contrastive (1/2): {where(contrastive)}")
    say(f"- Negative (0/2): {where(negative)}")
    say(f"- In eval: {sum(t in eval_ for t in contrastive + negative)} of {len(contrastive + negative)}.")
    say("")

    # ---- cost
    say("#### Cost (sum of `cli_result.total_cost_usd` over `calls.jsonl`, list price; the CLI subscription bills "
        "nothing)")
    say("")
    costs = {base: cost(d) for base, (d, rec) in valid.items()}
    say("| Run | Status | Calls | Cost USD |")
    say("|---|---|--:|--:|")
    for base in sorted(costs):
        d, rec = valid[base]
        say(f"| {d.name} | {rec['acceptance']['status']} | {len(run_calls(d))} | {costs[base]:.4f} |")
    for r in void_rows:
        say(f"| {r['folder']} (voided) | {r['status']} | {r['calls']} | {r['cost_usd']:.4f} |")
    v_total = sum(costs.values())
    void_total = sum(r["cost_usd"] for r in void_rows)
    acc_c = [costs[b] for b, (d, rec) in valid.items() if rec["acceptance"]["status"] == "accepted"]
    rej_c = [costs[b] for b, (d, rec) in valid.items() if rec["acceptance"]["status"] != "accepted"]
    say("")
    say(f"- Valid runs: {len(costs)}, **${v_total:.2f}** (mean ${v_total / len(costs):.3f}; accepted "
        f"{len(acc_c)} at mean ${sum(acc_c) / max(len(acc_c), 1):.3f}, rejected {len(rej_c)} at mean "
        f"${sum(rej_c) / max(len(rej_c), 1):.3f}).")
    say(f"- Voided attempts: {len(void_rows)}, **${void_total:.2f}**.")
    say(f"- Stage-2a calibration total: **${v_total + void_total:.2f}** (approved estimate about $70).")
    say("")

    # ---- audit
    say("#### Audit of non-accepted runs and voided attempts")
    say("")
    say("| Run | Stop | Responses / attempts | Fail-to-pass failing | Pass-to-pass failing | Timeout / collection errors / "
        "measurement errors | Mutation reverted in final workspace | Final diff vs upstream is exactly the mutation | "
        "Files differing from upstream | Retried calls (kinds) |")
    say("|---|---|---|---|---|---|---|---|---|---|")
    audit = []
    rows = [(d, rec, False) for d, rec in valid.values() if rec["acceptance"]["status"] != "accepted"]
    rows += [(d, (read_jsonl(d / "results.jsonl") or [{}])[0], True) for d, _, _ in voids]
    if args.diffs:
        args.diffs.mkdir(parents=True, exist_ok=True)
    for d, rec, is_void in sorted(rows, key=lambda x: x[0].name):
        a = rec["acceptance"]
        cr = a.get("criteria", {})
        f2p, p2p = cr.get("fail-to-pass", {}), cr.get("pass-to-pass", {})
        rev = mutation_reverted(d, tasks[rec["task_id"]])
        errs = call_errors(d)
        changed, diff = workspace_diff(d, rec["task_id"])
        if args.diffs:
            (args.diffs / f"{d.name}.diff").write_text(diff, encoding="utf-8")
        only_mut = changed_lines(diff) == changed_lines(tasks[rec["task_id"]]["mutation_patch"])
        tot = rec.get("totals") or {}
        row = {"run": d.name, "voided": is_void, "stop": rec["stop"], "status": a["status"],
               "responses": tot.get("model_calls"), "provider_attempts": tot.get("provider_attempts"),
               "diff_is_mutation_only": only_mut,
               "f2p_failing": len(f2p.get("failing", [])) + len(f2p.get("missing", [])),
               "f2p_total": len(tasks[rec["task_id"]]["fail_to_pass"]),
               "p2p_failing": (p2p.get("failing", []) + p2p.get("missing", [])),
               "timeout": a.get("pytest_timed_out"), "collection_errors": len(a.get("collection_errors") or []),
               "measurement_errors": len(a.get("measurement_errors") or []),
               "mutation_reverted": rev, "files_changed": changed, "call_errors": errs}
        audit.append(row)
        say(f"| {d.name}{' (voided, ' + a['status'] + ')' if is_void else ''} | {rec['stop']} | "
            f"{row['responses']} / {row['provider_attempts']} | {row['f2p_failing']}/{row['f2p_total']} | {len(row['p2p_failing'])}"
            f"{' (' + ', '.join(row['p2p_failing'][:3]) + ')' if row['p2p_failing'] else ''} | "
            f"{row['timeout']} / {row['collection_errors']} / {row['measurement_errors']} | {rev} | {only_mut} | "
            f"{', '.join(changed) if changed else 'none'} | {len(errs)}"
            f"{' (' + ', '.join(f'{k} x{n}' for k, n in Counter(errs).items()) + ')' if errs else ''} |")
    say("")
    inv_valid = Counter()
    for base, (d, rec) in valid.items():
        inv_valid[rec["acceptance"]["status"]] += len(call_errors(d))
    short = [r["run"] for r in audit if not r["voided"] and r["stop"] != "finish_requested" and r["responses"] != 20]
    say(f"- Non-accepted valid runs that stopped before finishing with fewer than 20 responses (attempt budget spent "
        f"on retries): {', '.join(short) if short else 'none'}.")
    say(f"- Non-accepted valid runs whose final workspace is exactly the mutated code (no edit kept): "
        f"{sum(r['diff_is_mutation_only'] for r in audit if not r['voided'])} of {sum(not r['voided'] for r in audit)}.")
    say(f"- Retried provider attempts (no parsed response) in valid runs: accepted runs {inv_valid['accepted']}, "
        f"rejected runs {inv_valid['rejected']}.")
    say("")

    print("\n".join(md))
    if issues:
        print("\nINTEGRITY ISSUES:", *issues, sep="\n  ")
    if args.markdown:
        args.markdown.write_text("\n".join(md) + "\n", encoding="utf-8")
    if args.write:
        data = json.loads(SPLIT.read_text(encoding="utf-8")) if SPLIT.exists() else {}
        derived = data.get("derived")
        data = {"derived": derived} if derived is not None else {}
        combined_block = {
            "rule": "stage 1's eval (E3-difficulty-calibration-010.split.json, unchanged) in its order, then stage 2a's "
                    "eval in stage-2a calibration-list order (amendment 1, A1.4)",
            "eval": combined,
            "size": len(combined),
            "from_stage1": eval1,
            "from_stage2a": eval_,
            "predicted_acceptance": {"stage1": round(p1, 4), "stage2a": round(p2, 4), "union": round(pu, 4)},
            "power_designs_met": [{"design": d, "tasks_needed": n} for d, n in sorted(met, key=lambda x: x[1])],
            "stage2a_added_at_least_5": len(eval_) >= 5,
        }
        data.update({
            "card": "E3-difficulty-calibration-010-stage2a",
            "stage": "2a",
            "generated_by": "experiments/session_harness/apply_split_010_stage2a.py --write",
            "rule": "cards/010-stage2a.json decision_rule (stage 1's keep/drop rule on the 39 stage-2a tasks alone), "
                    "applied mechanically",
            "predictors": PREDICTOR,
            "add_solved_while_below": ADD_WHILE_BELOW,
            "floor": FLOOR,
            "valid_runs": {b: v[0].name for b, v in sorted(valid.items())},
            "voided": [{k: r[k] for k in ("folder", "reason", "detail")} for r in void_rows],
            "category": {t: cat[t] for t in order},
            "accepted_of_2": {t: sum(acc[t]) for t in order},
            "trace": trace,
            "eval": eval_,
            "eval_predicted_acceptance": round(p2, 4),
            "dev_from_calibration": dev_cal,
            "dev": sorted(sets["dev_pool"]) + dev_cal,
            "dev_note": "stage-2a dev = stage-2a dev pool (220) from the sets file + every stage-2a calibration task not "
                        "kept for eval (stage 2a has no dev core); the 16 excluded tasks are in neither, as in stage 1",
            "evolution": {"contrastive_1of2": contrastive, "negative_0of2": negative},
            "strata": table,
            "combined": combined_block,
        })
        SPLIT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        COMBINED.write_text(json.dumps({
            "card": "E3-difficulty-calibration-010 (stage 1 + stage 2a, amendment 1)",
            "generated_by": "experiments/session_harness/apply_split_010_stage2a.py --write",
            "sources": ["experiments/session_harness/E3-difficulty-calibration-010.split.json",
                        "experiments/session_harness/E3-difficulty-calibration-010-stage2a.split.json"],
            "task_files": {"stage1": "experiments/mutation_tasks/tasks.difficulty010.json",
                           "stage2a": "experiments/mutation_tasks/tasks.difficulty010-stage2a.json"},
            **combined_block,
            "category": {t: cats_all[t] for t in combined},
        }, indent=2) + "\n", encoding="utf-8")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
