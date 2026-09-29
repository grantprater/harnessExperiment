"""Fixed in-run evaluator for one card-022 forecast task, run by AcceptanceRunner on a candidate snapshot copy.

Usage: evaluate_forecast.py <bundle_dir> <candidate_dir>

The bundle (outside the agent's workspace) holds task.json, resolvers.py (the true resolvers) and data/<series>.csv
(the target series' snapshot: rows dated before the forecast date only). No outcome exists anywhere at run time, so
the only acceptance criterion is "committed":

- forecast.json is a JSON object whose "probability" is a real number in [0, 1] and which holds no other number
  (not {"probability": 1.7}, not two numbers, not a bare number or a list), and
- resolve.py defines outcome(rows, T, horizon) that, run on the snapshot for the most recent past window (a weekly past
  forecast date whose window ends before T), returns a bool (True/False, not 0/1) within the time limit.

resolve.py is the agent's code, so nothing it does may reach the verdict except outcome()'s return values:
- the true outcomes, the snapshot rows and the past dates are computed in this process before any agent code runs;
- the agent's code runs in a child process (python -I) in a fresh temporary directory that holds only copies of the
  candidate's top-level .py files, with no argument that names the bundle, the candidate or any output file;
- the child reads its inputs (the rows, the dates and a random nonce) from stdin before it imports resolve.py, then
  points its stdout and stderr at the null device, keeps a private duplicate of the pipe, and writes one line, the
  nonce and the results, to that duplicate when every call has returned; os._exit then ends it, so no atexit hook or
  thread of the agent's code can write after it;
- this process accepts exactly one line that starts with the nonce, and nothing else from the child.
A resolve.py can still forge its results only by deliberately inspecting the checker process (its frames or file
descriptors); the post-run leakage audit (audit_forecast_runs.py) flags code that does.

As a diagnostic outside acceptance, the same child runs outcome() on up to 52 past windows and the report counts where
it agrees with the true resolver there (reading agreement: the forecasting counterpart of a wrong fix). Only a JSON
report is printed to stdout.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

REPORT_PROBLEMS_LIMIT = 10
CHILD = r'''
import datetime, importlib.util, json, os, sys
request = json.loads(sys.stdin.read())
rows = [(datetime.date.fromisoformat(day), value) for day, value in request["rows"]]
dates = [datetime.date.fromisoformat(day) for day in request["dates"]]
nonce, horizon = request["nonce"], request["horizon"]
channel = os.dup(1)
null = os.open(os.devnull, os.O_WRONLY)
os.dup2(null, 1)
os.dup2(null, 2)
del request


def report(value):
    os.write(channel, (nonce + " " + json.dumps(value) + "\n").encode("utf-8"))
    os._exit(0)


try:
    sys.path.insert(0, os.getcwd())
    spec = importlib.util.spec_from_file_location("resolve", os.path.join(os.getcwd(), "resolve.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outcome = getattr(module, "outcome")
except BaseException as exc:
    report({"load_error": f"{type(exc).__name__}: {exc}"[:300]})
results = []
for day in dates:
    try:
        value = outcome(list(rows), day, horizon)
        results.append(value if isinstance(value, bool) else f"not a bool: {type(value).__name__}")
    except BaseException as exc:
        results.append(f"error: {type(exc).__name__}: {exc}"[:200])
report({"results": results})
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


def run_resolver(candidate: Path, rows, dates, horizon: int, timeout: float):
    """(results per date or None, problem or None): the agent's outcome() on the snapshot, in an isolated child."""
    if not (candidate / "resolve.py").is_file():
        return None, "resolve.py is missing"
    nonce = secrets.token_hex(16)
    request = json.dumps({"rows": [[day.isoformat(), value] for day, value in rows],
                          "dates": [day.isoformat() for day in dates], "horizon": horizon, "nonce": nonce})
    with tempfile.TemporaryDirectory(prefix="resolver-") as scratch:
        for source in candidate.glob("*.py"):  # resolve.py and any helper module it imports
            shutil.copyfile(source, Path(scratch) / source.name)
        (Path(scratch) / "_checker.py").write_text(CHILD, encoding="utf-8")
        try:
            completed = subprocess.run([sys.executable, "-I", "_checker.py"], input=request.encode("utf-8"),
                                       cwd=scratch, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return None, f"resolve.py did not finish within {timeout:g} s"
    lines = [line for line in completed.stdout.decode("utf-8", "replace").splitlines() if line.startswith(nonce + " ")]
    if len(lines) != 1:
        return None, ("resolve.py stopped the checker before it reported" if not lines
                      else "the checker reported more than once; its output is not trusted")
    report = json.loads(lines[0][len(nonce) + 1:])
    if "load_error" in report:
        return None, f"resolve.py does not load or has no outcome(): {report['load_error']}"
    if len(report.get("results", [])) != len(dates):
        return None, "the checker reported the wrong number of results"
    return report["results"], None


def main() -> int:
    bundle, candidate = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    spec = json.loads((bundle / "task.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(bundle))
    import resolvers  # the bundle's copy of the true resolvers

    # Everything the verdict compares against is fixed here, before any agent code runs.
    T = datetime.date.fromisoformat(spec["forecast_date"])
    horizon, template, params = spec["horizon_days"], spec["template"], spec["params"]
    rows = []
    for line in (bundle / "data" / f"{spec['series']}.csv").read_text(encoding="utf-8").splitlines()[1:]:
        day, value = line.split(",")
        rows.append((datetime.date.fromisoformat(day), float(value)))
    first_day = datetime.date.fromisoformat(spec["history_start"])
    dates = resolvers.past_forecast_dates(T, horizon, template, first_day)[:spec["agreement_windows"]]
    truth = [resolvers.resolve(template, rows, day, horizon, params) for day in dates]

    probability, problems = check_forecast(candidate / "forecast.json")
    results, resolver_problem = run_resolver(candidate, rows, dates, horizon, spec["resolver_timeout_seconds"])
    resolver_valid = bool(results) and isinstance(results[0], bool)
    if resolver_problem:
        problems.append(resolver_problem)
    elif not resolver_valid:
        problems.append(f"resolve.py on the most recent past window ({dates[0]}): {results[0] if results else 'no result'}")
    agreement = None
    if results is not None:
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
