"""Fixed in-run evaluator for one card-022 forecast task, run by AcceptanceRunner on a candidate snapshot copy.

Usage: evaluate_forecast.py <bundle_dir> <candidate_dir>

The bundle (outside the agent's workspace) holds task.json, resolvers.py (the true resolvers) and data/<series>.csv
(the target series' snapshot: rows dated before the forecast date only). No outcome exists anywhere at run time, so
the only acceptance criterion is "committed":

- forecast.json is a JSON object whose "probability" is a real number in [0, 1] and which holds no other number
  (not {"probability": 1.7}, not two numbers, not a bare number or a list), and
- resolve.py defines outcome(rows, T, horizon) that, run on the snapshot for the most recent past window (a weekly past
  forecast date whose window ends before T), returns a bool (True/False, not 0/1) within the time limit.

resolve.py is the agent's code: it runs in a child process (python -I, working directory the candidate copy) with a
timeout, and reports through a file, not stdout. As a diagnostic outside acceptance, the same child runs it on up to
52 past windows and the report counts where it agrees with the true resolver there (reading agreement: the
forecasting counterpart of a wrong fix). Only a JSON report is printed to stdout.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
import subprocess
import sys

REPORT_PROBLEMS_LIMIT = 10
CHILD = r'''
import datetime, importlib.util, json, sys
resolve_path, data_path, dates_path, horizon, out_path = sys.argv[1:6]
rows = []
with open(data_path, encoding="utf-8") as handle:
    next(handle)
    for line in handle:
        day, value = line.strip().split(",")
        rows.append((datetime.date.fromisoformat(day), float(value)))
results = []
try:
    spec = importlib.util.spec_from_file_location("resolve", resolve_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outcome = getattr(module, "outcome")
except BaseException as exc:
    json.dump({"load_error": f"{type(exc).__name__}: {exc}"[:300]}, open(out_path, "w", encoding="utf-8"))
    raise SystemExit(0)
for text in json.load(open(dates_path, encoding="utf-8")):
    try:
        value = outcome(list(rows), datetime.date.fromisoformat(text), int(horizon))
        results.append(value if isinstance(value, bool) else f"not a bool: {type(value).__name__}")
    except BaseException as exc:
        results.append(f"error: {type(exc).__name__}: {exc}"[:200])
json.dump({"results": results}, open(out_path, "w", encoding="utf-8"))
'''


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numbers_in(value) -> int:
    if is_number(value):
        return 1
    if isinstance(value, dict):
        return sum(numbers_in(item) for item in value.values())
    if isinstance(value, list):
        return sum(numbers_in(item) for item in value)
    return 0


def check_forecast(path: Path):
    """(probability or None, problems)."""
    if not path.is_file():
        return None, ["forecast.json is missing"]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"forecast.json is not JSON: {exc}"[:200]]
    if not isinstance(data, dict):
        return None, ["forecast.json is not a JSON object"]
    probability = data.get("probability")
    if not is_number(probability) or not math.isfinite(probability):
        return None, ["forecast.json has no numeric probability"]
    problems = []
    if not 0 <= probability <= 1:
        problems.append(f"probability {probability} is outside [0, 1]")
    if numbers_in(data) != 1:
        problems.append("forecast.json holds more than one number")
    return (None, problems) if problems else (float(probability), [])


def run_resolver(bundle: Path, candidate: Path, spec: dict, dates, timeout: float):
    """(results per date or None, problem or None): the agent's outcome() on the snapshot, in a child process."""
    resolve_path = candidate / "resolve.py"
    if not resolve_path.is_file():
        return None, "resolve.py is missing"
    work = bundle.parent / "resolver-check"
    work.mkdir(exist_ok=True)
    (work / "child.py").write_text(CHILD, encoding="utf-8")
    (work / "dates.json").write_text(json.dumps([d.isoformat() for d in dates]), encoding="utf-8")
    out = work / "results.json"
    command = [sys.executable, "-I", str(work / "child.py"), str(resolve_path),
               str(bundle / "data" / f"{spec['series']}.csv"), str(work / "dates.json"), str(spec["horizon_days"]),
               str(out)]
    try:
        subprocess.run(command, cwd=candidate, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, f"resolve.py did not finish within {timeout:g} s"
    if not out.is_file():
        return None, "resolve.py stopped the checker before it reported"
    report = json.loads(out.read_text(encoding="utf-8"))
    if "load_error" in report:
        return None, f"resolve.py does not load or has no outcome(): {report['load_error']}"
    return report["results"], None


def main() -> int:
    bundle, candidate = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    spec = json.loads((bundle / "task.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(bundle))
    import resolvers  # the bundle's copy of the true resolvers

    T = datetime.date.fromisoformat(spec["forecast_date"])
    horizon, template, params = spec["horizon_days"], spec["template"], spec["params"]
    rows = []
    for line in (bundle / "data" / f"{spec['series']}.csv").read_text(encoding="utf-8").splitlines()[1:]:
        day, value = line.split(",")
        rows.append((datetime.date.fromisoformat(day), float(value)))
    first_day = datetime.date.fromisoformat(spec["history_start"])
    dates = resolvers.past_forecast_dates(T, horizon, template, first_day)[:spec["agreement_windows"]]

    probability, problems = check_forecast(candidate / "forecast.json")
    results, resolver_problem = run_resolver(bundle, candidate, spec, dates, spec["resolver_timeout_seconds"])
    resolver_valid = bool(results) and isinstance(results[0], bool)
    if resolver_problem:
        problems.append(resolver_problem)
    elif not resolver_valid:
        problems.append(f"resolve.py on the most recent past window ({dates[0]}): {results[0] if results else 'no result'}")
    agreement = None
    if results is not None:
        truth = [resolvers.resolve(template, rows, day, horizon, params) for day in dates]
        answered = [(r, t) for r, t in zip(results, truth) if isinstance(r, bool)]
        agreement = {"windows": len(dates), "answered": len(answered), "agree": sum(r == t for r, t in answered),
                     "errors": sorted({r for r in results if not isinstance(r, bool)})[:3]}
    committed = probability is not None and resolver_valid
    report = {
        "criteria": {"committed": {
            "outcome": "pass" if committed else "fail", "evaluator_version": spec["evaluator_version"],
            "coverage_ids": [], "failing": problems[:REPORT_PROBLEMS_LIMIT], "missing": [], "skipped": [],
        }},
        "forecast": {"committed": committed, "probability": probability, "forecast_valid": probability is not None,
                     "resolver_valid": resolver_valid, "problems": problems[:REPORT_PROBLEMS_LIMIT],
                     "reading_agreement": agreement},
    }
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
