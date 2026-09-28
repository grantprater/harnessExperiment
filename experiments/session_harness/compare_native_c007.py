"""Paired comparison of the native arm (card 018) with the Reticle incumbent (card 007) on card 007's 20 tasks.

Inputs, read-only:
  card 007  c007-campaign.jsonl (which runs exist) and experiments/p6_pilot/runs/c007-*/results.jsonl: responses =
            agent.model_calls, seconds = the agent's active seconds (evaluation excluded), acceptance; and
            labels/labels_c007_rules.jsonl: first_edit_response (first response with a successful edit of a
            pre-existing file, weakness_mining's rule);
  card 018  native_runs/c018-<task>-r<k>/result.json: responses = distinct assistant messages (API responses),
            turns = the CLI's num_turns, seconds = the CLI's wall time (evaluation excluded), first edit =
            first_base_file_edit.response (first Edit/Write of a pre-existing file), acceptance, audit_clean.
Partial data is fine: every task of the card 007 set is listed, and a task with no native run yet is left out of the
paired statistics.

Per task: accepted n/k in each arm; mean responses and seconds over accepted runs ("to accept"); mean first-edit index
over runs that made such an edit. Paired over tasks: the acceptance-rate difference (native - Reticle) where both arms
have runs; responses, seconds and first edit where both arms have a value. Mean, SD and n of each difference.

Detectability, as in the card 007 efficiency baseline: a run's within-task noise sigma_w (default 1.8 responses and
55 s). One task's difference of arm means then has noise sigma_w * sqrt(1/r_native + 1/r_reticle) (r = runs in the
mean), and the mean difference over n tasks has noise sigma_w * sqrt(sum_i (1/r_native,i + 1/r_reticle,i)) / n. A mean
difference larger than twice that is reported as detectable; the observed 2 * SD / sqrt(n) is shown beside it.

Usage (from the repo root):
  python experiments/session_harness/compare_native_c007.py [--json] [--noise-responses 1.8] [--noise-seconds 55]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import statistics
import sys
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
C007_LOG = HERE / "c007-campaign.jsonl"
C007_RUNS = ROOT / "experiments" / "p6_pilot" / "runs"
C007_LABELS = HERE / "labels" / "labels_c007_rules.jsonl"
SELECTION = HERE / "E3-calibration-007-tasks.json"
NATIVE_RUNS = HERE / "native_runs"
NATIVE_RUN = re.compile(r"^c018-(?P<task>.+)-r(?P<rollout>\d+)$")
NOISE = {"responses": 1.8, "seconds": 55.0}


def _last_jsonl(path: Path) -> Optional[dict]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return json.loads(lines[-1]) if lines else None


def load_reticle(log_path: Path = C007_LOG, runs_root: Path = C007_RUNS, labels_path: Path = C007_LABELS) -> List[dict]:
    rows = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if "run" in row:
                rows[row["run"]] = row  # the last row of a run (after any crash retry)
    first_edit = {}
    if labels_path.exists():
        for line in labels_path.read_text(encoding="utf-8").splitlines():
            label = json.loads(line) if line.strip() else {}
            if label.get("kind") == "run":
                first_edit[label["run"]] = (label.get("rule") or {}).get("first_edit_response")
    runs = []
    for name, row in rows.items():
        result = _last_jsonl(runs_root / name / "results.jsonl")
        if result is None:
            continue
        agent = result.get("agent") or {}
        consumed = ((agent.get("task_resources") or {}).get("consumed") or {})
        runs.append({"run": name, "task": result["task_id"], "rollout": row.get("rollout"),
                     "accepted": (result.get("acceptance") or {}).get("status") == "accepted",
                     "responses": agent.get("model_calls"), "turns": agent.get("model_calls"),
                     "seconds": consumed.get("active_seconds", result.get("elapsed_s")),
                     "first_edit": first_edit.get(name), "stop": result.get("stop"), "audit_clean": True})
    return runs


def load_native(record_root: Path = NATIVE_RUNS) -> List[dict]:
    runs = []
    for directory in sorted(record_root.glob("c018-*")):
        match = NATIVE_RUN.match(directory.name)
        result_path = directory / "result.json"
        if not directory.is_dir() or match is None or not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        runs.append({"run": directory.name, "task": result["task_id"], "rollout": int(match.group("rollout")),
                     "accepted": (result.get("acceptance") or {}).get("status") == "accepted",
                     "responses": result.get("responses"), "turns": result.get("turns_used"),
                     "seconds": result.get("wall_seconds"),
                     "first_edit": (result.get("first_base_file_edit") or {}).get("response"),
                     "stop": result.get("stop"), "audit_clean": bool(result.get("audit_clean"))})
    return runs


def _mean(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def arm_summary(runs: List[dict]) -> dict:
    accepted = [r for r in runs if r["accepted"]]
    return {"runs": len(runs), "accepted": len(accepted),
            "responses_to_accept": _mean(r["responses"] for r in accepted),
            "turns_to_accept": _mean(r["turns"] for r in accepted),
            "seconds_to_accept": _mean(r["seconds"] for r in accepted),
            "accepted_runs_for_means": len(accepted),
            "first_edit": _mean(r["first_edit"] for r in runs),
            "runs_with_first_edit": sum(1 for r in runs if r["first_edit"] is not None),
            "unclean_accepted": sum(1 for r in accepted if not r["audit_clean"])}


def paired(rows: List[dict], key: str) -> dict:
    diffs = [(row["task"], row["native"][key] - row["reticle"][key]) for row in rows
             if row["native"][key] is not None and row["reticle"][key] is not None]
    values = [d for _, d in diffs]
    return {"n": len(values), "mean": statistics.fmean(values) if values else None,
            "sd": statistics.stdev(values) if len(values) > 1 else None, "by_task": dict(diffs)}


def detectability(rows: List[dict], key: str, count_key: str, sigma: float, difference: dict) -> dict:
    used = [row for row in rows if row["task"] in difference["by_task"]]
    if not used:
        return {"sigma_w": sigma, "per_task_2sigma_two_runs_each": 2 * sigma, "mean_2sigma": None, "observed_2se": None,
                "detectable": None}
    inverse = [1 / row["native"][count_key] + 1 / row["reticle"][count_key] for row in used]
    mean_line = 2 * sigma * math.sqrt(sum(inverse)) / len(used)
    observed = (2 * difference["sd"] / math.sqrt(difference["n"])) if difference["sd"] is not None else None
    return {"sigma_w": sigma, "per_task_2sigma_two_runs_each": 2 * sigma,  # sqrt(1/2 + 1/2) = 1
            "mean_2sigma": mean_line, "observed_2se": observed,
            "detectable": abs(difference["mean"]) > mean_line}


def within_task_sd(runs: List[dict], key: str) -> Optional[float]:
    """Pooled SD of accepted runs around their task mean, over tasks with at least two accepted runs."""
    groups: Dict[str, list] = {}
    for run in runs:
        if run["accepted"] and run[key] is not None:
            groups.setdefault(run["task"], []).append(run[key])
    squares = sum(sum((x - statistics.fmean(v)) ** 2 for x in v) for v in groups.values() if len(v) > 1)
    freedom = sum(len(v) - 1 for v in groups.values() if len(v) > 1)
    return math.sqrt(squares / freedom) if freedom else None


def compare(reticle_runs: List[dict], native_runs: List[dict], tasks: List[str],
            noise: Dict[str, float] = NOISE) -> dict:
    rows = []
    for task in tasks:
        r = [run for run in reticle_runs if run["task"] == task]
        n = [run for run in native_runs if run["task"] == task]
        rows.append({"task": task, "reticle": arm_summary(r), "native": arm_summary(n)})
    both = [row for row in rows if row["reticle"]["runs"] and row["native"]["runs"]]
    for row in both:
        for arm in ("reticle", "native"):
            row[arm]["acceptance_rate"] = row[arm]["accepted"] / row[arm]["runs"]
    report = {
        "tasks": len(tasks), "tasks_with_native_runs": len(both),
        "totals": {arm: {"runs": sum(row[arm]["runs"] for row in both),
                         "accepted": sum(row[arm]["accepted"] for row in both)} for arm in ("reticle", "native")},
        "native_runs_total": len(native_runs),
        "native_unclean_accepted": sum(1 for run in native_runs if run["accepted"] and not run["audit_clean"]),
        "rows": rows,
        "acceptance": paired(both, "acceptance_rate"),
        "responses_to_accept": paired(both, "responses_to_accept"),
        "seconds_to_accept": paired(both, "seconds_to_accept"),
        "first_edit": paired(both, "first_edit"),
        "within_task_sd": {arm: {key: within_task_sd(runs, key) for key in ("responses", "seconds")}
                           for arm, runs in (("reticle", reticle_runs), ("native", native_runs))},
    }
    outcomes = [row["native"]["acceptance_rate"] - row["reticle"]["acceptance_rate"] for row in both]
    report["acceptance"]["native_better"] = sum(1 for d in outcomes if d > 0)
    report["acceptance"]["reticle_better"] = sum(1 for d in outcomes if d < 0)
    report["acceptance"]["equal"] = sum(1 for d in outcomes if d == 0)
    report["detectability"] = {
        "responses": detectability(both, "responses_to_accept", "accepted_runs_for_means", noise["responses"],
                                   report["responses_to_accept"]),
        "seconds": detectability(both, "seconds_to_accept", "accepted_runs_for_means", noise["seconds"],
                                 report["seconds_to_accept"]),
    }
    return report


def _fmt(value, digits=1) -> str:
    return "-" if value is None else (f"{value:.{digits}f}" if isinstance(value, float) else str(value))


def render(report: dict) -> str:
    lines = ["# Native arm (card 018) vs Reticle incumbent (card 007)", "",
             f"Tasks with native runs: {report['tasks_with_native_runs']} of {report['tasks']} "
             f"({report['native_runs_total']} native runs; accepted but audit not clean: "
             f"{report['native_unclean_accepted']}).", "",
             "| Task | Reticle acc | Native acc | R resp | N resp (turns) | d resp | R s | N s | d s | R 1st edit | "
             "N 1st edit |", "|---|:-:|:-:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for row in report["rows"]:
        r, n = row["reticle"], row["native"]
        d_resp = report["responses_to_accept"]["by_task"].get(row["task"])
        d_sec = report["seconds_to_accept"]["by_task"].get(row["task"])
        native_accepted = f"{n['accepted']}/{n['runs']}" if n["runs"] else "-"
        lines.append(
            f"| {row['task']} | {r['accepted']}/{r['runs']} | {native_accepted} | "
            f"{_fmt(r['responses_to_accept'])} | {_fmt(n['responses_to_accept'])} ({_fmt(n['turns_to_accept'])}) | "
            f"{_fmt(d_resp)} | {_fmt(r['seconds_to_accept'], 0)} | {_fmt(n['seconds_to_accept'], 0)} | "
            f"{_fmt(d_sec, 0)} | {_fmt(r['first_edit'])} | {_fmt(n['first_edit'])} |")
    totals = report["totals"]
    lines += ["", f"Accepted on the tasks with native runs: Reticle {totals['reticle']['accepted']}/"
                  f"{totals['reticle']['runs']}, native {totals['native']['accepted']}/{totals['native']['runs']}.",
              "",
              "| Paired difference (native - Reticle) | n tasks | mean | SD | 2-sigma line (mean) | observed 2 SE | "
                  "detectable |", "|---|--:|--:|--:|--:|--:|:-:|"]
    acceptance = report["acceptance"]
    lines.append(f"| acceptance rate | {acceptance['n']} | {_fmt(acceptance['mean'], 3)} | {_fmt(acceptance['sd'], 3)} "
                 f"| - | - | native better on {acceptance['native_better']}, Reticle on "
                 f"{acceptance['reticle_better']}, equal {acceptance['equal']} |")
    for key, label, digits in (("responses", "responses to accept", 2), ("seconds", "seconds to accept", 1)):
        difference, line = report[f"{key}_to_accept"], report["detectability"][key]
        lines.append(f"| {label} | {difference['n']} | {_fmt(difference['mean'], digits)} | "
                     f"{_fmt(difference['sd'], digits)} | {_fmt(line.get('mean_2sigma'), digits)} | "
                     f"{_fmt(line.get('observed_2se'), digits)} | "
                     f"{'-' if line.get('detectable') is None else ('yes' if line['detectable'] else 'no')} |")
    first = report["first_edit"]
    lines.append(f"| first-edit index | {first['n']} | {_fmt(first['mean'], 2)} | {_fmt(first['sd'], 2)} | - | - | - |")
    sd = report["within_task_sd"]
    lines += ["", f"Within-task noise used: {_noise_text(report)}. "
                  "Pooled within-task SD of accepted runs, from the data: "
                  f"Reticle {_fmt(sd['reticle']['responses'], 2)} responses, {_fmt(sd['reticle']['seconds'], 0)} s; "
                  f"native {_fmt(sd['native']['responses'], 2)} responses, {_fmt(sd['native']['seconds'], 0)} s.",
              "Responses: Reticle counts model responses; native counts distinct assistant messages (the CLI's "
              "num_turns in parentheses). Seconds: Reticle active seconds; native CLI wall seconds."]
    return "\n".join(lines) + "\n"


def _noise_text(report: dict) -> str:
    detect = report["detectability"]
    return (f"sigma_w = {_fmt(detect['responses']['sigma_w'])} responses and {_fmt(detect['seconds']['sigma_w'], 0)} s "
            "per run (card 007 efficiency baseline)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--noise-responses", type=float, default=NOISE["responses"])
    parser.add_argument("--noise-seconds", type=float, default=NOISE["seconds"])
    args = parser.parse_args(argv)
    tasks = sorted(json.loads(SELECTION.read_text(encoding="utf-8"))["task_ids"])
    report = compare(load_reticle(), load_native(), tasks,
                     {"responses": args.noise_responses, "seconds": args.noise_seconds})
    sys.stdout.write(json.dumps(report, indent=2) + "\n" if args.json else render(report))


if __name__ == "__main__":
    main()
