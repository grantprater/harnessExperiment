"""Post-hoc scorer for card 022 (design section 6): Brier and log score per question, paired arm differences, the
cluster bootstrap over series, the pre-registered verdict, calibration and reading agreement.

Runs after a campaign, never during one: it needs the sealed resolutions, whose sha256 must equal the value pinned in
the card (--resolutions-sha256); a mismatch stops before anything is scored.

  python experiments/forecast_tasks/score_forecasts.py --resolutions ~/harness-sealed/022/resolutions.json \\
      --resolutions-sha256 <pinned> --split sealed \\
      --arm incumbent=experiments/p6_pilot/runs/c022-* --arm treatment=... --baseline incumbent [--json]

Rules (fixed here, as pre-registered):
- Brier (p - o)^2; log loss -ln(p) or -ln(1 - p) with p clipped to [0.01, 0.99] (pastcast clips when it parses);
  lower is better for both.
- A question with no committed forecast in an arm is scored at p = 0.5 and counts as not committed.
- An arm's forecast for a question is its first run for that question in the order given (rollout 1).
- D = mean over the set's questions of (score_treatment - score_baseline); negative favours the treatment.
- 95% interval: cluster bootstrap over series, 10,000 resamples, random.Random(22); the one-sided 95% upper bound is
  the 95th percentile of the resampled D and the lower bound the 5th (linear interpolation). A two-way bootstrap over
  series x forecast date is reported as a sensitivity analysis.
- Verdict, first matching row: "transfers, with gain" if upper < 0; "transfers, no harm" if upper < margin (Brier
  0.01, log 0.04) and the treatment's commitment rate is at most 5 points lower; "harms" if lower > 0; else
  "inconclusive". The report also says when "no harm" holds with the lower bound above 0 (inside the margin, but
  worse).
- Vacuity: a treatment that fired in fewer than 20% of its runs gets "not exercised" instead of a verdict.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
SEED = 22
RESAMPLES = 10_000
CLIP = (0.01, 0.99)
MARGINS = {"brier": 0.01, "log": 0.04}
COMMIT_DROP = 0.05
VACUITY_MIN = 0.20


def brier(p: float, outcome: bool) -> float:
    return (p - (1.0 if outcome else 0.0)) ** 2


def log_loss(p: float, outcome: bool) -> float:
    p = min(CLIP[1], max(CLIP[0], p))
    return -math.log(p if outcome else 1 - p)


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_resolutions(path: Path, expected_sha256: str) -> dict:
    """{task_id: outcome}; refuses a file whose sha256 differs from the card's pin."""
    actual = lf_sha256(path)
    if actual != expected_sha256:
        raise SystemExit(f"{path}: sha256 {actual} is not the pinned {expected_sha256}; nothing scored")
    data = json.loads(Path(path).read_text(encoding="utf-8"))["resolutions"]
    return {task_id: bool(item["outcome"]) for task_id, item in data.items()}


def run_records(run_dirs) -> list:
    records = []
    for run_dir in run_dirs:
        path = Path(run_dir) / "results.jsonl"
        if path.exists():
            records += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return records


def arm_forecasts(records) -> dict:
    """{task_id: {"probability": p or None, "committed": bool, "record": the run record}}, first run per task."""
    forecasts = {}
    for record in records:
        if record["task_id"] in forecasts:
            continue
        details = (record.get("acceptance") or {}).get("forecast") or {}
        committed = (record.get("acceptance") or {}).get("status") == "accepted" and bool(details.get("committed"))
        forecasts[record["task_id"]] = {"probability": details.get("probability") if committed else None,
                                        "committed": committed, "record": record}
    return forecasts


def question_scores(task_ids, forecasts: dict, resolutions: dict) -> dict:
    """{task_id: {p, committed, outcome, brier, log}}; a missing or uncommitted forecast is scored at 0.5."""
    scores = {}
    for task_id in task_ids:
        entry = forecasts.get(task_id) or {}
        p = entry.get("probability")
        committed = p is not None
        p = float(p) if committed else 0.5
        outcome = resolutions[task_id]
        scores[task_id] = {"p": p, "committed": committed, "outcome": outcome, "brier": brier(p, outcome),
                           "log": log_loss(p, outcome)}
    return scores


def percentile(sorted_values, q: float) -> float:
    """Linear interpolation between order statistics (numpy's default)."""
    if not sorted_values:
        return float("nan")
    position = (len(sorted_values) - 1) * q
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def cluster_bootstrap(diffs, clusters, resamples=RESAMPLES, seed=SEED) -> list:
    """Sorted resampled means: draw as many clusters as there are, with replacement; a draw's mean is the sum of its
    clusters' differences over their question count."""
    totals: dict = {}
    for diff, cluster in zip(diffs, clusters):
        total, count = totals.get(cluster, (0.0, 0))
        totals[cluster] = (total + diff, count + 1)
    keys = sorted(totals)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        total = count = 0
        for _ in keys:
            cluster_total, cluster_count = totals[keys[rng.randrange(len(keys))]]
            total += cluster_total
            count += cluster_count
        means.append(total / count)
    return sorted(means)


def two_way_bootstrap(diffs, rows, cols, resamples=RESAMPLES, seed=SEED) -> list:
    """Sorted resampled means with series (rows) and forecast dates (cols) resampled independently; a question's weight
    is the product of its series' and its date's draw counts. A draw with zero total weight is drawn again."""
    row_keys, col_keys = sorted(set(rows)), sorted(set(cols))
    rng = random.Random(seed)
    means = []
    while len(means) < resamples:
        row_weight = {key: 0 for key in row_keys}
        col_weight = {key: 0 for key in col_keys}
        for _ in row_keys:
            row_weight[row_keys[rng.randrange(len(row_keys))]] += 1
        for _ in col_keys:
            col_weight[col_keys[rng.randrange(len(col_keys))]] += 1
        weights = [row_weight[r] * col_weight[c] for r, c in zip(rows, cols)]
        total = sum(weights)
        if total:
            means.append(sum(w * d for w, d in zip(weights, diffs)) / total)
    return sorted(means)


def verdict(upper: float, lower: float, commit_delta: float, margin: float) -> str:
    if upper < 0:
        return "transfers, with gain"
    if upper < margin and commit_delta >= -COMMIT_DROP - 1e-12:
        return "transfers, no harm"
    if lower > 0:
        return "harms"
    return "inconclusive"


def fired(record: dict) -> bool:
    """Whether any treatment acted in a run: the nudge was delivered, the finish guard triggered, check() was called."""
    for state in (record.get("treatments") or {}).values():
        if state.get("fired") or state.get("guard_triggered") or (state.get("calls") or 0) > 0:
            return True
    return False


def paired_comparison(task_ids, tasks: dict, baseline: dict, treatment: dict, treatment_records=(),
                      resamples=RESAMPLES) -> dict:
    """D per score with both bootstraps, the verdicts, and the vacuity check. tasks: {task_id: task} for clusters."""
    series = [tasks[t]["series"] for t in task_ids]
    dates = [tasks[t]["forecast_date"] for t in task_ids]
    commit_delta = (sum(treatment[t]["committed"] for t in task_ids)
                    - sum(baseline[t]["committed"] for t in task_ids)) / len(task_ids)
    result = {"questions": len(task_ids), "series": len(set(series)), "commit_rate_delta": commit_delta}
    for score in ("brier", "log"):
        diffs = [treatment[t][score] - baseline[t][score] for t in task_ids]
        one = cluster_bootstrap(diffs, series, resamples)
        two = two_way_bootstrap(diffs, series, dates, resamples)
        lower, upper = percentile(one, 0.05), percentile(one, 0.95)
        result[score] = {
            "D": sum(diffs) / len(diffs), "sd_d": _sd(diffs),
            "lower_95_one_sided": lower, "upper_95_one_sided": upper,
            "two_way": {"lower_95_one_sided": percentile(two, 0.05), "upper_95_one_sided": percentile(two, 0.95)},
            "verdict": verdict(upper, lower, commit_delta, MARGINS[score]),
            "no_harm_but_lower_bound_above_zero": upper < MARGINS[score] and lower > 0,
        }
    records = list(treatment_records)
    if records:
        rate = sum(fired(r) for r in records) / len(records)
        result["treatment_fired_rate"] = rate
        if rate < VACUITY_MIN:
            for score in ("brier", "log"):
                result[score]["verdict"] = "not exercised"
    return result


def _sd(values) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def calibration(scores: dict, bins: int = 5) -> dict:
    """Reliability by probability quintile bin ([0, .2), ..., [.8, 1]) over committed forecasts, and the ECE."""
    table = [{"bin": f"[{i / bins:.1f}, {(i + 1) / bins:.1f}{']' if i == bins - 1 else ')'}", "n": 0, "mean_p": None,
              "observed": None} for i in range(bins)]
    members = [[] for _ in range(bins)]
    for item in scores.values():
        if item["committed"]:
            members[min(bins - 1, int(item["p"] * bins))].append(item)
    total = sum(len(m) for m in members)
    ece = 0.0
    for row, items in zip(table, members):
        if items:
            row["n"] = len(items)
            row["mean_p"] = sum(i["p"] for i in items) / len(items)
            row["observed"] = sum(i["outcome"] for i in items) / len(items)
            ece += len(items) / total * abs(row["mean_p"] - row["observed"])
    return {"table": table, "ece": ece if total else None}


def reading_agreement(forecasts: dict) -> dict:
    """Mean share of past windows where resolve.py agreed with the true resolver, over runs that report it."""
    shares = []
    for entry in forecasts.values():
        agreement = (((entry.get("record") or {}).get("acceptance") or {}).get("forecast") or {}).get("reading_agreement")
        if agreement and agreement.get("windows"):
            shares.append(agreement["agree"] / agreement["windows"])
    return {"runs": len(shares), "mean_share": sum(shares) / len(shares) if shares else None}


def arm_summary(scores: dict) -> dict:
    n = len(scores)
    return {"questions": n, "committed": sum(s["committed"] for s in scores.values()),
            "brier": sum(s["brier"] for s in scores.values()) / n, "log": sum(s["log"] for s in scores.values()) / n}


def score_ledger(ledger_rows, results: dict) -> dict:
    """pastcast's score.py arithmetic (metac-bot probe/score.py): each ledger row's median against results.json's
    yes/no, rows without an outcome or a median skipped; mean Brier and mean log score (ln p of the outcome)."""
    briers, logs = [], []
    for row in ledger_rows:
        answer = results.get(str(row["id"]))
        if answer is None or row.get("median") is None:
            continue
        outcome = answer.lower() == "yes"
        briers.append(brier(row["median"], outcome))
        logs.append(-log_loss(row["median"], outcome))
    return {"n": len(briers), "brier": sum(briers) / len(briers), "log": sum(logs) / len(logs)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks.forecast.json")
    parser.add_argument("--splits", type=Path, default=HERE / "splits.json")
    parser.add_argument("--split", default="sealed")
    parser.add_argument("--resolutions", type=Path, required=True)
    parser.add_argument("--resolutions-sha256", required=True)
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=GLOB[,GLOB]",
                        help="run directories of one arm (globs allowed)")
    parser.add_argument("--baseline", help="the arm the others are compared with")
    parser.add_argument("--resamples", type=int, default=RESAMPLES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    resolutions = load_resolutions(args.resolutions, args.resolutions_sha256)
    tasks = {t["task_id"]: t for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]}
    task_ids = json.loads(args.splits.read_text(encoding="utf-8"))[args.split]
    arms, records = {}, {}
    for item in args.arm:
        name, _, patterns = item.partition("=")
        dirs = sorted({d for pattern in patterns.split(",") for d in glob.glob(pattern)})
        records[name] = run_records(dirs)
        arms[name] = arm_forecasts(records[name])
    report = {"split": args.split, "questions": len(task_ids), "arms": {}, "comparisons": {}}
    scored = {name: question_scores(task_ids, forecasts, resolutions) for name, forecasts in arms.items()}
    for name, scores in scored.items():
        report["arms"][name] = {**arm_summary(scores), "calibration": calibration(scores),
                                "reading_agreement": reading_agreement(arms[name])}
    if args.baseline:
        for name in scored:
            if name != args.baseline:
                report["comparisons"][f"{name} vs {args.baseline}"] = paired_comparison(
                    task_ids, tasks, scored[args.baseline], scored[name], records[name], args.resamples)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for name, summary in report["arms"].items():
            print(f"{name}: Brier {summary['brier']:.4f}, log {summary['log']:.4f}, committed "
                  f"{summary['committed']}/{summary['questions']}, ECE {summary['calibration']['ece']}")
        for name, comparison in report["comparisons"].items():
            for score in ("brier", "log"):
                c = comparison[score]
                print(f"{name} [{score}]: D {c['D']:+.4f}, one-sided 95% bounds [{c['lower_95_one_sided']:+.4f}, "
                      f"{c['upper_95_one_sided']:+.4f}] -> {c['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
