"""Card 010 stage-1 calibration: integrity checks, per-stratum outcomes, and the preregistered keep/drop rule.

Offline only: reads recorded run folders and the campaign log; calls no model and evaluates nothing.

Inputs:
  experiments/p6_pilot/runs/c010-<task>-r<k>[-aN]/{results,calls}.jsonl     (calibration runs and their retries)
  experiments/p6_pilot/runs/card-E3-difficulty-calibration-010/campaign.jsonl
  experiments/session_harness/E3-difficulty-calibration-010.sets.json      (calibration order, strata; never edited)
  experiments/mutation_tasks/tasks.difficulty010.json                      (mutation patches, for the audit)
  run_card.py cards/010.json --plan --json  (expected protocol hash per run; run here unless --plan is given)

Valid run per (task, rollout): the planned folder, or its latest `-aN` retry when the earlier attempt stopped on an
adapter failure (model_error / model_mismatch), which the card voids and reruns.

Keep/drop rule (card markdown, "Keep/drop rule"; machine card decision_rule), applied literally:
  solved 2/2, mixed 1/2, hard 0/2; eval starts as all mixed + hard; predicted acceptance = task-weighted mean of
  0.94 / 0.25 / 0.08; add solved tasks in calibration-list order while predicted < 0.40 (checked before each add);
  if still < 0.30 with no solved task left, move hard tasks to dev from the end of the list until >= 0.30;
  every other calibration task goes to dev.

Usage:
  python experiments/session_harness/apply_split_010.py [--plan PLAN.json] [--write] [--markdown OUT.md]
  --write updates E3-difficulty-calibration-010.split.json (keeps run_card's "derived" block).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
HERE = ROOT / "experiments" / "session_harness"
SETS = HERE / "E3-difficulty-calibration-010.sets.json"
SPLIT = HERE / "E3-difficulty-calibration-010.split.json"
BANK = ROOT / "experiments" / "mutation_tasks" / "tasks.difficulty010.json"
CAMPAIGN = RUNS / "card-E3-difficulty-calibration-010" / "campaign.jsonl"

MODEL = "claude-sonnet-5"
CLI_VERSION = "2.1.286"
ADAPTER_FAILURE_STOPS = ("model_error", "model_mismatch")
PREDICTOR = {"solved": 0.94, "mixed": 0.25, "hard": 0.08}
ADD_WHILE_BELOW, FLOOR = 0.40, 0.30
NAME = re.compile(r"^c010-(sqlparse-mut-\d+(?:-nm)?)-r(\d+)(?:-a(\d+))?$")


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (centre - half, centre + half)


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def model_check(folder):
    """Every model identity the run recorded: results, each call's request model, CLI init, response, modelUsage."""
    problems, seen = [], set()
    for r in read_jsonl(folder / "results.jsonl"):
        seen.add(("results.model", r.get("model")))
        for m in r.get("reported_models") or []:
            seen.add(("results.reported_models", m))
        for key in ("model_mismatch", "model_pin_violation"):
            if key in r:
                problems.append(f"results has {key}")
    calls = read_jsonl(folder / "calls.jsonl")
    for c in calls:
        seen.add(("call.model", c.get("model")))
        init = c.get("cli_init") or {}
        if init:
            seen.add(("cli_init.model", init.get("model")))
            if init.get("claude_code_version") != CLI_VERSION:
                problems.append(f"cli version {init.get('claude_code_version')}")
        resp = c.get("response") or {}
        if resp.get("model") is not None:
            seen.add(("response.model", resp.get("model")))
        for m in c.get("reported_models") or []:
            seen.add(("call.reported_models", m))
        for m in ((c.get("cli_result") or {}).get("modelUsage") or {}):
            seen.add(("modelUsage", m))
        for key in ("model_mismatch", "model_pin_violation"):
            if key in c:
                problems.append(f"call has {key}")
    bad = sorted({f"{where}={m}" for where, m in seen if m != MODEL})
    sources = sorted({where for where, _ in seen})
    return problems + bad, len(calls), sources


def call_errors(folder):
    """Provider attempts that did not yield a parsed response (retried calls): their `failure` kind."""
    out = []
    for c in read_jsonl(folder / "calls.jsonl"):
        if c.get("failure") or c.get("unparsed_lines") or "response" not in c:
            out.append(str(c.get("failure") or f"unparsed_lines={c.get('unparsed_lines')}"))
    return out


def mutation_reverted(folder, task):
    """True if the final workspace has every original ('-') line of the mutation patch and none of its '+' lines."""
    ws = next((folder / "sessions").glob("*/workspace"), None)
    if ws is None:
        return None
    f = ws / task["mutation_file"]
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8", errors="replace")
    minus = [ln[1:] for ln in task["mutation_patch"].splitlines() if ln.startswith("-") and not ln.startswith("---")]
    plus = [ln[1:] for ln in task["mutation_patch"].splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    lines = text.splitlines()
    has_orig = all(m in lines for m in minus)
    has_mut = any(p in lines for p in plus if p not in minus)
    return has_orig and not has_mut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, help="saved `run_card.py --plan --json` output (default: compute it now)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--markdown", type=Path)
    args = ap.parse_args()

    sets = json.loads(SETS.read_text(encoding="utf-8"))
    order = sets["calibration"]
    stratum = {c["task_id"]: c["stratum"] for c in sets["candidates"]}
    tasks = {t["task_id"]: t for t in json.loads(BANK.read_text(encoding="utf-8"))["tasks"]}
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    else:  # offline: run_card.py --plan computes hashes in-process and calls no model
        out = subprocess.run([sys.executable, str(HERE / "run_card.py"), str(HERE / "cards" / "010.json"), "--plan",
                              "--json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        plan = json.loads(out.stdout)
    expected = {i["run_name"]: i["expected_protocol_hash"] for i in plan["invocations"] if i["kind"] == "run"}
    md, issues = [], []
    say = md.append

    # ---- folders -> attempts per planned run
    attempts = defaultdict(list)
    stray = []
    for d in sorted(RUNS.iterdir()):
        if not d.is_dir() or not d.name.startswith("c010-sqlparse") or ".void" in d.name:
            continue
        m = NAME.match(d.name)
        base = f"c010-{m.group(1)}-r{m.group(2)}" if m else None
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
    say("### Integrity")
    say("")
    model_bad, n_calls, hash_bad, srcs = [], 0, [], set()
    for d, rec in list(valid.values()) + voided:
        probs, nc, sources = model_check(d)
        n_calls += nc
        srcs.update(sources)
        if probs:
            model_bad.append(f"{d.name}: {probs}")
        base = NAME.match(d.name)
        base = f"c010-{base.group(1)}-r{base.group(2)}"
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        for h in {rec.get("protocol_hash"), cfg.get("protocol_hash")}:
            if h != expected[base]:
                hash_bad.append(f"{d.name}: {h} != planned {expected[base]}")
    per_task_hash = defaultdict(set)
    for base, (d, rec) in valid.items():
        per_task_hash[rec["task_id"]].add(rec["protocol_hash"])
    split_hash = {t: h for t, h in per_task_hash.items() if len(h) != 1}
    issues += model_bad + hash_bad + ([f"rollouts differ in protocol hash: {split_hash}"] if split_hash else [])

    camp = read_jsonl(CAMPAIGN)
    starts = [i for i, e in enumerate(camp) if e["event"] == "campaign_start"]
    last = camp[starts[-1]:]
    pre = [e for e in camp[: starts[-1]] if e["event"] == "preflight"][-1]
    ends = [e for e in last if e["event"] == "invocation_end"]
    fails = [e for e in ends if e.get("outcome") != "ok"]
    say(f"- Planned calibration runs: {len(expected)}; folders matched to the plan: {sum(len(v) for v in attempts.values())} "
        f"({len(valid)} valid, {len(voided)} adapter-failure attempts voided and rerun as `-a2`); folders outside the plan: "
        f"{len(stray)}; planned runs without a folder: {len(missing)}.")
    say(f"- Model: {n_calls} recorded provider calls across all {len(valid) + len(voided)} attempts; every model field "
        f"({', '.join(sorted(srcs))}) reads `{MODEL}`, CLI `{CLI_VERSION}` in every init: "
        f"{'yes' if not model_bad else 'NO: ' + '; '.join(model_bad)}. No `model_mismatch` / `model_pin_violation` record.")
    say(f"- Protocol hash: each run's `results.jsonl` and `config.json` hash equals the hash `run_card.py --plan` computes "
        f"for that run from the card given to `--plan` (sha256 `{plan['card_sha256'][:12]}`; the campaign started "
        f"from card sha256 `{last[0]['card_sha256'][:12]}`; the card's status line is not a hash input): {'yes' if not hash_bad else 'NO: ' + '; '.join(hash_bad)}. The card "
        f"declares no single hash (`expected_protocol_hash: null`): the hash includes the task contract, so there are "
        f"{len(per_task_hash)} distinct hashes, one per task, identical across both rollouts of every task "
        f"({'yes' if not split_hash else 'NO'}). Arm preflight before the campaign: expected `{pre['expected']}`, "
        f"observed `{pre['observed']}`.")
    say(f"- Campaign log (last start {last[0]['time']}): {len(ends)} invocation ends, {len(fails)} not ok "
        f"({', '.join(e['run'] for e in fails)}), end event: "
        f"{next((e.get('reason') for e in last if e['event'] == 'campaign_end'), 'MISSING')}.")
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

    say("### Outcomes by stratum")
    say("")
    say("| Stratum | Tasks | Runs accepted | Rate | Wilson 95% | Predicted (card) | 2/2 | 1/2 | 0/2 |")
    say("|---|--:|--:|--:|---|---|--:|--:|--:|")
    pred = {"single test": "0.10-0.40", "multi-test, message": "0.75-0.95", "multi-test, no message": "0.45-0.85"}
    rows = [(s, [t for t in order if stratum[t] == s]) for s in pred] + [("all 30 tasks", list(order))]
    table = {}
    for s, ts in rows:
        k = sum(sum(acc[t]) for t in ts)
        n = sum(len(acc[t]) for t in ts)
        lo, hi = wilson(k, n)
        c = {x: sum(cat[t] == x for t in ts) for x in PREDICTOR}
        table[s] = {"tasks": len(ts), "accepted": k, "runs": n, "rate": round(k / n, 4),
                    "wilson95": [round(lo, 4), round(hi, 4)], "solved": c["solved"], "mixed": c["mixed"], "hard": c["hard"]}
        say(f"| {s} | {len(ts)} | {k}/{n} | {k / n:.2f} | {lo:.2f}-{hi:.2f} | {pred.get(s, '0.50-0.75')} | "
            f"{c['solved']} | {c['mixed']} | {c['hard']} |")
    say("")

    # ---- keep/drop rule
    def predicted(ts):
        return sum(PREDICTOR[cat[t]] for t in ts) / len(ts) if ts else float("nan")

    trace = []
    eval_ = [t for t in order if cat[t] in ("mixed", "hard")]
    trace.append(f"start: {len(eval_)} mixed+hard tasks, predicted {predicted(eval_):.4f}")
    solved_left = [t for t in order if cat[t] == "solved"]
    while solved_left and predicted(eval_) < ADD_WHILE_BELOW:
        t = solved_left.pop(0)
        eval_.append(t)
        trace.append(f"add solved {t}: {len(eval_)} tasks, predicted {predicted(eval_):.4f}")
    if not solved_left and predicted(eval_) < FLOOR:
        for t in [x for x in reversed(order) if cat[x] == "hard"]:
            if predicted(eval_) >= FLOOR:
                break
            eval_.remove(t)
            trace.append(f"move hard {t} to dev: predicted {predicted(eval_):.4f}")
    eval_ = [t for t in order if t in eval_]  # calibration-list order
    dev_cal = [t for t in order if t not in eval_]

    say("### Keep/drop rule (applied mechanically)")
    say("")
    for line in trace:
        say(f"- {line}")
    say(f"- Result: **eval {len(eval_)} tasks** (predicted acceptance {predicted(eval_):.4f}; observed in calibration "
        f"{sum(sum(acc[t]) for t in eval_)}/{2 * len(eval_)}, which the card does not use), **{len(dev_cal)} calibration "
        f"tasks to dev**.")
    say(f"- Eval: {', '.join(eval_)}")
    say(f"- Dev (from calibration): {', '.join(dev_cal)}")
    say("")

    # ---- audit of non-accepted valid runs and voided attempts
    say("### Audit of non-accepted runs and voided attempts")
    say("")
    say("| Run | Stop | Fail-to-pass failing | Pass-to-pass failing | Timeout / collection errors | Mutation reverted in final workspace | Retried calls |")
    say("|---|---|---|---|---|---|---|")
    audit = []
    for d, rec in sorted([v for v in valid.values() if v[1]["acceptance"]["status"] != "accepted"] + voided,
                         key=lambda x: x[0].name):
        a = rec["acceptance"]
        cr = a.get("criteria", {})
        f2p = cr.get("fail-to-pass", {})
        p2p = cr.get("pass-to-pass", {})
        rev = mutation_reverted(d, tasks[rec["task_id"]])
        errs = call_errors(d)
        row = {"run": d.name, "stop": rec["stop"], "status": a["status"],
               "f2p_failing": len(f2p.get("failing", [])) + len(f2p.get("missing", [])),
               "f2p_total": len(tasks[rec["task_id"]]["fail_to_pass"]),
               "p2p_failing": (p2p.get("failing", []) + p2p.get("missing", [])),
               "timeout": a.get("pytest_timed_out"), "collection_errors": len(a.get("collection_errors", [])),
               "mutation_reverted": rev, "call_errors": errs}
        audit.append(row)
        say(f"| {d.name}{' (voided attempt, ' + a['status'] + ')' if rec['stop'] in ADAPTER_FAILURE_STOPS else ''} | "
            f"{rec['stop']} | {row['f2p_failing']}/{row['f2p_total']} | {len(row['p2p_failing'])} "
            f"{'(' + ', '.join(row['p2p_failing'][:3]) + ')' if row['p2p_failing'] else ''} | "
            f"{row['timeout']} / {row['collection_errors']} | {rev} | {len(errs)} |")
    say("")

    print("\n".join(md))
    if issues:
        print("\nINTEGRITY ISSUES:", *issues, sep="\n  ")
    if args.markdown:
        args.markdown.write_text("\n".join(md) + "\n", encoding="utf-8")
    if args.write:
        data = json.loads(SPLIT.read_text(encoding="utf-8")) if SPLIT.exists() else {}
        dev_pool = sets["dev_pool"]
        dev_pool_ids = sorted(dev_pool) if isinstance(dev_pool, dict) else [
            x if isinstance(x, str) else x["task_id"] for x in dev_pool]
        data.update({
            "card": "E3-difficulty-calibration-010",
            "stage": 1,
            "generated_by": "experiments/session_harness/apply_split_010.py --write",
            "rule": "card markdown 'Keep/drop rule' (machine card decision_rule), applied mechanically",
            "predictors": PREDICTOR,
            "add_solved_while_below": ADD_WHILE_BELOW,
            "floor": FLOOR,
            "valid_runs": {b: v[0].name for b, v in sorted(valid.items())},
            "category": {t: cat[t] for t in order},
            "accepted_of_2": {t: sum(acc[t]) for t in order},
            "trace": trace,
            "eval": eval_,
            "eval_predicted_acceptance": round(predicted(eval_), 4),
            "dev_from_calibration": dev_cal,
            "dev": list(sets["dev_core"]) + dev_pool_ids + dev_cal,
            "dev_note": "dev = dev core (21) + dev pool (22) from the sets file + every calibration task not kept for eval",
            "strata": table,
        })
        SPLIT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
