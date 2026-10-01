"""Card 022's question bank: fetch public series, cut them at each forecast date, keep history-only candidates, draw.

  python experiments/forecast_tasks/build_bank.py --fetch     fetch the raw responses that are not cached yet
                                                              (sequential, one request every --pause seconds), then build
  python experiments/forecast_tasks/build_bank.py             build from the cache only (no network)

Inputs: sources.json (the series), the raw cache (default .runtime/forecast-022/raw/, with manifest.json recording each
response's URL, sha256 and size; the raw responses hold data after every forecast date and never enter a workspace).

The frozen selection rule, v2 (design section 4 as amended by section 10, Q6, 2026-09-29; SELECTION_RULE below is the
text recorded in the manifest):
1. Candidates: every (series, forecast date T, template, horizon) the series' kind allows, T the Mondays 2026-07-06 to
   2026-08-24, horizons 7/14/28 days (count: 7). The snapshot is the series' rows dated on or after history_start and
   before T.
2. Base-rate filter: the true resolver (resolvers.py) over the weekly past windows that end before T, on the snapshot
   only; keep a candidate when there are at least 52 such windows and the frequency of YES is in [0.2, 0.8]. Nothing
   after T is read, and outcomes are computed only after the draw.
3. A candidate whose window reaches past the fetched data is dropped (it could not resolve).
4. Series-disjoint splits: every group (a city's two weather series, otherwise one series) belongs wholly to one of
   calibration, sealed and reserve. With random.Random(22): shuffle each source's groups, interleave the sources
   round-robin, and give each group to the split furthest below its share of the series (40:120:40), ties in the
   order calibration, sealed, reserve.
5. Seeded draw, same generator, split by split (calibration 40, sealed 120, reserve 40): shuffle the split's pool,
   group it by (source, template), shuffle the group order, and take round-robin across groups, skipping a candidate
   whose series already has 4 questions or one whose window [T, T+h) overlaps a window already taken for its series
   (so at most one question per (series, T)).
6. Recall-probe positive control: the same filter at the Mondays 2025-07-07 to 2025-08-25 (before the model's training
   cutoff), 20 questions, at most one per series, drawn round-robin over (source, template) with
   random.Random("22:recall"). They are statements only (no workspace), for probe_recall.py.

Outputs (all written with LF line endings; hashes are of those bytes):
- tasks.forecast.json   the tasks (kind "forecast"): statement, question.md and data/README.md text, snapshot paths and
                        sha256; no outcome
- splits.json           the task ids per split (a card's task sets refer to it), and the series of each split
- recall_control.json   the 20 positive-control statements; no outcome
- snapshots/<T>/<series>.csv   one per (T, series) a task needs: rows dated before T only
- bank_manifest.json    rule, seed, dates, counts, diagnostics, raw-response and output sha256s, and the sealed
                        resolutions' sha256
- <sealed>/resolutions.json    (default ~/harness-sealed/022/; outside the checkout) each task's and each control
                        question's outcome and the window values it was resolved from. Its sha256 is pinned in the card
                        before any run.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import datetime
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import resolvers  # noqa: E402

SOURCES = HERE / "sources.json"
DEFAULT_RAW = ROOT / ".runtime" / "forecast-022" / "raw"
DEFAULT_SEALED = Path.home() / "harness-sealed" / "022"
BUILDER_VERSION = "forecast-bank-v2"
SEED = 22
FORECAST_DATES = tuple(datetime.date(2026, 7, 6) + datetime.timedelta(days=7 * k) for k in range(8))
RECALL_CONTROL_DATES = tuple(datetime.date(2025, 7, 7) + datetime.timedelta(days=7 * k) for k in range(8))
RECALL_CONTROL_COUNT = 20
HORIZONS = (7, 14, 28)
COUNT_HORIZON = 7
BASE_RATE_RANGE = (0.2, 0.8)
MIN_WINDOWS = 52
SERIES_CAP = 4  # questions per series, in every split, with windows that do not overlap
SPLITS = (("calibration", 40), ("sealed", 120), ("reserve", 40))
USER_AGENT = "harnessExperiment-forecast-bank/1 (research; github.com/grantprater)"
USGS_YEARS_PER_REQUEST = 1
SELECTION_RULE = (
    "v2. Candidates: every (series, T, template, horizon) the series kind allows; T = the Mondays 2026-07-06..2026-08-24; "
    "horizons 7/14/28 (count: 7). Keep a candidate when the true resolver over the weekly past windows ending before T, "
    "on rows dated history_start..T-1 only, has >= 52 windows and a YES frequency in [0.2, 0.8], and its window lies "
    "within the fetched data. Splits are series-disjoint: with random.Random(22), shuffle each source's groups (a "
    "city's two weather series, else one series), interleave the sources round-robin, give each group to the split "
    "furthest below its share of the series (40:120:40). Then, same generator, splits in order calibration (40), sealed "
    "(120), reserve (40): shuffle the split's pool, group by (source, template), shuffle the groups, take round-robin; "
    "at most 4 questions per series, whose windows [T, T+h) do not overlap. Recall positive control: the same filter "
    "at the Mondays 2025-07-07..2025-08-25, 20 questions, one per series, random.Random('22:recall')."
)
TEMPLATES_BY_KIND = {
    "level": ("direction", "touch", "window_mean"),
    "wet_days": ("count", "window_mean"),
    "events": ("count", "window_mean"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lf_sha256(path: Path) -> str:
    """sha256 with CRLF folded to LF: the bytes git stores, whatever core.autocrlf wrote to this checkout."""
    return sha256_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def write_lf(path: Path, text: str) -> str:
    """Write text with LF line endings; return the sha256 of the bytes written."""
    data = text.replace("\r\n", "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def dumps(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def parse_day(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text[:10])


# ---------------------------------------------------------------------------------------------------------------
# Fetching (network only here, only with --fetch)
# ---------------------------------------------------------------------------------------------------------------

def requests_for(config: dict):
    """[(cache key, url, series names)] for every raw response the series need, in a fixed order."""
    start, end = config["history_start"], config["fetch_end"]
    sources, cities = config["sources"], config.get("cities", {})
    planned, seen = [], set()
    for series in config["series"]:
        source = series["source"]
        template = sources[source]["url"]
        if source == "fred":
            key = f"fred-{series['id']}.csv"
            url = template.format(id=series["id"]) + f"&cosd={start}&coed={end}"
            items = [(key, url)]
        elif source == "open-meteo":
            city = cities[series["city"]]
            key = f"open-meteo-{series['city']}.json"
            url = template.format(latitude=city["latitude"], longitude=city["longitude"], start=start, end=end)
            items = [(key, url)]
        elif source == "usgs":
            box = "".join(f"&{name}={value}" for name, value in sorted((series.get("box") or {}).items()))
            items = []
            first, last = parse_day(start).year, parse_day(end).year
            for year in range(first, last + 1, USGS_YEARS_PER_REQUEST):
                chunk_start = max(parse_day(start), datetime.date(year, 1, 1))
                chunk_end = min(parse_day(end), datetime.date(year + USGS_YEARS_PER_REQUEST, 1, 1))
                items.append((f"usgs-{series['name']}-{year}.csv", template.format(
                    start=chunk_start.isoformat(), end=chunk_end.isoformat(),
                    minmagnitude=series["minmagnitude"], box=box)))
        elif source == "wikimedia":
            key = f"wikimedia-{series['name']}.json"
            url = template.format(article=series["article"], start_compact=start.replace("-", ""),
                                  end_compact=end.replace("-", ""))
            items = [(key, url)]
        else:
            raise ValueError(f"unknown source {source!r}")
        for key, url in items:
            if key not in seen:
                seen.add(key)
                planned.append((key, url, [series["name"]]))
            else:
                next(p for p in planned if p[0] == key)[2].append(series["name"])
    return planned


def read_manifest(raw_dir: Path) -> dict:
    path = raw_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fetch_missing(config: dict, raw_dir: Path, pause: float, opener=urllib.request.urlopen, sleep=time.sleep,
                  out=print) -> dict:
    """Fetch every planned response not in the cache, one at a time with a pause; record URL, sha256 and size."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(raw_dir)
    fetched = 0
    for key, url, names in requests_for(config):
        if key in manifest and (raw_dir / key).exists():
            continue
        if fetched:
            sleep(pause)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=120) as response:
            data = response.read()
            status = getattr(response, "status", 200)
        if status != 200 or not data:
            raise RuntimeError(f"{url}: HTTP {status}, {len(data)} bytes")
        (raw_dir / key).write_bytes(data)
        manifest[key] = {"url": url, "sha256": sha256_bytes(data), "bytes": len(data), "series": names,
                         "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        (raw_dir / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
        fetched += 1
        out(f"fetched {key}: {len(data)} bytes")
    return manifest


# ---------------------------------------------------------------------------------------------------------------
# Parsing: every series becomes sorted (date, float) rows
# ---------------------------------------------------------------------------------------------------------------

def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def parse_series(config: dict, raw_dir: Path) -> dict:
    """{series name: sorted [(date, float)]} from the cache; checks each cached file against its recorded sha256."""
    manifest = read_manifest(raw_dir)
    by_series: dict = {s["name"]: {} for s in config["series"]}
    meta = {s["name"]: s for s in config["series"]}
    usgs_days: dict = {}
    for key, _, names in requests_for(config):
        path = raw_dir / key
        if key not in manifest or not path.exists():
            raise FileNotFoundError(f"raw response {key} is not cached; run build_bank.py --fetch")
        data = path.read_bytes()
        if sha256_bytes(data) != manifest[key]["sha256"]:
            raise ValueError(f"raw response {key} does not match its recorded sha256")
        text = data.decode("utf-8-sig")
        for name in names:
            series = meta[name]
            rows = by_series[name]
            if series["source"] == "fred":
                reader = csv.reader(io.StringIO(text))
                next(reader)
                for record in reader:
                    if len(record) >= 2 and _number(record[1]) is not None:
                        rows[parse_day(record[0])] = _number(record[1])
            elif series["source"] == "open-meteo":
                daily = json.loads(text)["daily"]
                for day, value in zip(daily["time"], daily[series["variable"]]):
                    if _number(value) is not None:
                        rows[parse_day(day)] = _number(value)
            elif series["source"] == "usgs":
                counts = usgs_days.setdefault(name, {})
                for record in csv.DictReader(io.StringIO(text)):
                    if record.get("type", "earthquake") != "earthquake":  # quarry blasts, landslides, eruptions
                        continue
                    day = parse_day(record["time"])
                    counts[day] = counts.get(day, 0) + 1
            elif series["source"] == "wikimedia":
                for item in json.loads(text)["items"]:
                    stamp = item["timestamp"]
                    rows[datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))] = float(item["views"])
    start, end = parse_day(config["history_start"]), parse_day(config["fetch_end"])
    for name, counts in usgs_days.items():  # every day in the requested range, 0 when nothing happened
        day = start
        while day < end:  # the last request's endtime is fetch_end 00:00, so fetch_end itself is not covered
            by_series[name][day] = float(counts.get(day, 0))
            day += datetime.timedelta(days=1)
    return {name: sorted(rows.items()) for name, rows in by_series.items()}


# ---------------------------------------------------------------------------------------------------------------
# Candidates, draw, statements
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Candidate:
    series: str
    source: str
    kind: str
    template: str
    horizon: int
    T: datetime.date
    params: dict
    base_rate: float
    windows: int

    @property
    def task_id(self) -> str:
        prefix = f"fc-{self.T:%m%d}" if self.T.year == 2026 else f"rc-{self.T:%Y%m%d}"
        return f"{prefix}-{self.series.lower().replace('_', '-')}-{self.template.replace('_', '-')}-h{self.horizon}"

    @property
    def window_end(self) -> datetime.date:
        return self.T + datetime.timedelta(days=self.horizon - 1)


def template_plan(series: dict):
    """[(template, horizon, params)] a series' kind allows."""
    plan = []
    for template in TEMPLATES_BY_KIND[series["kind"]]:
        if template == "count":
            mode = "sum" if series["kind"] == "events" else "days"
            params = {"mode": mode, "threshold": float(series.get("threshold", 0.0))}
            plan.append((template, COUNT_HORIZON, params))
        else:
            plan.extend((template, horizon, {}) for horizon in HORIZONS)
    return plan


def snapshot_rows(rows, T, first_day):
    return [(day, value) for day, value in rows if first_day <= day < T]


def resolvable(rows, window_end: datetime.date, source: str) -> bool:
    """The fetched data reach the window's end (FRED has no weekend rows, so up to 3 days of slack there)."""
    if not rows:
        return False
    slack = 3 if source == "fred" else 0
    return rows[-1][0] >= window_end - datetime.timedelta(days=slack)


def candidates(config: dict, series_rows: dict, dates=FORECAST_DATES):
    """(kept candidates, diagnostics). Reads only rows dated before each T, except the resolvability check, which
    reads only the last fetched date."""
    first_day = parse_day(config["history_start"])
    kept, counts = [], {"generated": 0, "too_few_windows": 0, "outside_base_rate_range": 0, "not_resolvable": 0}
    for series in config["series"]:
        rows = series_rows[series["name"]]
        for T in dates:
            history = snapshot_rows(rows, T, first_day)
            for template, horizon, params in template_plan(series):
                counts["generated"] += 1
                if not resolvable(rows, T + datetime.timedelta(days=horizon - 1), series["source"]):
                    counts["not_resolvable"] += 1
                    continue
                rate, windows = resolvers.base_rate(history, T, horizon, template, params, first_day=first_day)
                if windows < MIN_WINDOWS:
                    counts["too_few_windows"] += 1
                    continue
                if not BASE_RATE_RANGE[0] <= rate <= BASE_RATE_RANGE[1]:
                    counts["outside_base_rate_range"] += 1
                    continue
                kept.append(Candidate(series["name"], series["source"], series["kind"], template, horizon, T,
                                      params, rate, windows))
    counts["kept"] = len(kept)
    return kept, counts


def group_of(series: dict) -> str:
    return series.get("group", series["name"])


def assign_splits(config: dict, rng: random.Random, splits=SPLITS) -> dict:
    """{series name: split}: series-disjoint, by group (module docstring, step 4)."""
    members: dict = {}
    for series in config["series"]:
        members.setdefault((series["source"], group_of(series)), []).append(series["name"])
    by_source: dict = {}
    for source, group in sorted(members):
        by_source.setdefault(source, []).append(group)
    for source in sorted(by_source):
        rng.shuffle(by_source[source])
    order, position = [], 0
    while any(position < len(groups) for groups in by_source.values()):
        order += [(source, groups[position]) for source, groups in sorted(by_source.items()) if position < len(groups)]
        position += 1
    total_series, total_questions = len(config["series"]), sum(count for _, count in splits)
    target = {split: total_series * count / total_questions for split, count in splits}
    assigned = {split: 0 for split, _ in splits}
    split_of = {}
    for key in order:
        split = max((split for split, _ in splits), key=lambda name: target[name] - assigned[name])
        assigned[split] += len(members[key])
        for name in members[key]:
            split_of[name] = split
    return split_of


def overlaps(candidate, taken) -> bool:
    """Whether candidate's window [T, T+h) overlaps any of taken's windows."""
    start, end = candidate.T, candidate.T + datetime.timedelta(days=candidate.horizon)
    return any(start < other.T + datetime.timedelta(days=other.horizon) and other.T < end for other in taken)


def round_robin(pool, rng: random.Random, count: int, accept) -> list:
    """Shuffle the pool, group it by (source, template), shuffle the groups, and take round-robin across them, each
    group offering its next candidate that accept(candidate, taken) allows, until count are taken."""
    pool = list(pool)
    rng.shuffle(pool)
    groups: dict = {}
    for candidate in pool:
        groups.setdefault((candidate.source, candidate.template), []).append(candidate)
    keys = sorted(groups)
    rng.shuffle(keys)
    taken, positions = [], {key: 0 for key in keys}
    while len(taken) < count and any(positions[key] < len(groups[key]) for key in keys):
        for key in keys:
            if len(taken) >= count:
                break
            group = groups[key]
            while positions[key] < len(group):
                candidate = group[positions[key]]
                positions[key] += 1
                if accept(candidate, taken):
                    taken.append(candidate)
                    break
    return taken


def draw(pool_all, split_of: dict, rng: random.Random, splits=SPLITS, cap=SERIES_CAP) -> dict:
    """{split: [Candidate]} by the frozen rule (module docstring, step 5)."""
    ordered = sorted(pool_all, key=lambda c: c.task_id)
    by_series: dict = {}
    chosen = {}

    def accept(candidate, taken):
        mine = by_series.setdefault(candidate.series, [])
        if len(mine) >= cap or overlaps(candidate, mine):
            return False
        mine.append(candidate)
        return True

    for split, count in splits:
        chosen[split] = round_robin([c for c in ordered if split_of[c.series] == split], rng, count, accept)
    return chosen


def draw_recall_control(pool_all, seed=SEED, count=RECALL_CONTROL_COUNT) -> list:
    """The recall probe's positive control (module docstring, step 6)."""
    rng = random.Random(f"{seed}:recall")
    return round_robin(sorted(pool_all, key=lambda c: c.task_id), rng, count,
                       lambda candidate, taken: all(other.series != candidate.series for other in taken))


def fmt(value: float) -> str:
    return f"{value:.10g}"


def statement_parts(candidate: Candidate, series: dict, history) -> dict:
    """Title, resolution criteria and fine print; any number they state is computed from the snapshot."""
    T, end, h, name = candidate.T, candidate.window_end, candidate.horizon, series["name"]
    day = datetime.timedelta(days=1)
    window = f"dated on or after {T} and on or before {end}"
    shown = {}
    if candidate.template == "direction":
        title = f"Will {series['title']} ({name}) end the {h} days from {T} to {end} higher than it ended the days before {T}?"
        criteria = (f"Resolves YES if the last value of {name} {window} is strictly greater than the last value of "
                    f"{name} dated before {T}. Resolves NO otherwise, including when no value is dated in that window.")
    elif candidate.template == "touch":
        level = resolvers.touch_level(history, T)
        shown["level_at_T"] = level
        title = (f"Will {series['title']} ({name}) go above {fmt(level)}, its maximum over the 90 days before {T}, "
                 f"on any date from {T} to {end}?")
        criteria = (f"Resolves YES if any value of {name} {window} is strictly greater than the maximum of the values "
                    f"of {name} dated on or after {T - 90 * day} and before {T} (that maximum is {fmt(level)}). "
                    f"Resolves NO otherwise.")
    elif candidate.template == "window_mean":
        title = (f"Will the mean of {series['title']} ({name}) from {T} to {end} be higher than its mean from "
                 f"{T - h * day} to {T - day}?")
        criteria = (f"Resolves YES if the mean of the values of {name} {window} is strictly greater than the mean of "
                    f"the values of {name} dated on or after {T - h * day} and on or before {T - day}. Resolves NO "
                    f"otherwise, including when either window has no value.")
    else:
        mode, threshold = candidate.params["mode"], candidate.params["threshold"]
        k = resolvers.count_k(history, T, h, mode, threshold)
        shown["k_at_T"] = k
        blocks = (f"each of the 52 consecutive 7-day blocks before {T} (the latest is {T - 7 * day} to {T - day})")
        if mode == "days":
            title = (f"Will {series['title']} ({name}) be at least {fmt(threshold)} mm on at least {k} of the "
                     f"{h} days from {T} to {end}?")
            criteria = (f"Resolves YES if at least k of the dates on or after {T} and on or before {end} have a value "
                        f"of {name} of at least {fmt(threshold)}, where k is the median, rounded up to a whole number, "
                        f"of the number of such dates in {blocks}; k = {k}. Resolves NO otherwise.")
        else:
            title = (f"Will the {series['title'].lower()} ({name}) add up to at least {k} over the {h} days from {T} "
                     f"to {end}?")
            criteria = (f"Resolves YES if the sum of the values of {name} {window} is at least k, where k is the "
                        f"median, rounded up to a whole number, of the sums over {blocks}; k = {k}. Resolves NO "
                        f"otherwise.")
    fine_print = (f"Dates are UTC calendar dates. The target series is data/{name}.csv (columns date,value; "
                  f"{series['units']}); its rows are as published by the source, and the question resolves on the rows "
                  f"published for the window's dates. resolve.py's outcome(rows, T, horizon) is called with rows = "
                  f"the (datetime.date, float) pairs of the complete {name} series sorted by date, T = "
                  f"datetime.date({T.year}, {T.month}, {T.day}) and horizon = {h}.")
    return {"title": title, "criteria": criteria, "fine_print": fine_print, "shown": shown}


def question_markdown(task: dict) -> str:
    related = ", ".join(f"data/{name}.csv" for name in task["related"]) or "none"
    return (f"# {task['title']}\n\n"
            f"Forecast date (today): {task['forecast_date']}  \n"
            f"Horizon: {task['horizon_days']} days ({task['forecast_date']} to {task['window_end']})  \n"
            f"Target series: data/{task['series']}.csv  \n"
            f"Related series: {related}\n\n"
            f"## Resolution criteria\n\n{task['criteria']}\n\n"
            f"## Fine print\n\n{task['fine_print']}\n")


def data_readme(config: dict, names, T: datetime.date) -> str:
    meta = {s["name"]: s for s in config["series"]}
    lines = [f"# Data (every row dated before {T})\n",
             "Each file has the columns date,value: one row per date with a published value, sorted by date. "
             "Dates are UTC calendar dates (ISO format). Nothing dated on or after the forecast date is included.\n"]
    for name in names:
        series = meta[name]
        source = config["sources"][series["source"]]
        lines.append(f"## {name}.csv\n\n{series['title']}. Units: {series['units']}.  \nSource: {source['title']}.  \n"
                     f"Publication: {source['publication']}\n")
    return "\n".join(lines)


def snapshot_csv(rows) -> str:
    return "date,value\n" + "".join(f"{day.isoformat()},{fmt(value)}\n" for day, value in rows)


# ---------------------------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------------------------

def resolution_record(candidate: Candidate, rows) -> dict:
    outcome = resolvers.resolve(candidate.template, rows, candidate.T, candidate.horizon, candidate.params)
    return {"outcome": outcome, "series": candidate.series, "template": candidate.template,
            "forecast_date": candidate.T.isoformat(), "horizon_days": candidate.horizon,
            "window": [[day.isoformat(), value] for day, value in rows if candidate.T <= day <= candidate.window_end]}


def build(config: dict, series_rows: dict, out_dir: Path, sealed_dir: Path, raw_manifest: dict,
          sources_path: Path = SOURCES) -> dict:
    """Write the bank; return the manifest. Deterministic for the same inputs."""
    first_day = parse_day(config["history_start"])
    meta = {s["name"]: s for s in config["series"]}
    kept, counts = candidates(config, series_rows)
    rng = random.Random(SEED)
    split_of = assign_splits(config, rng)
    chosen = draw(kept, split_of, rng)
    tasks, snapshots, resolutions = [], {}, {}
    for split, _ in SPLITS:
        for candidate in sorted(chosen[split], key=lambda c: (c.T, c.task_id)):
            series = meta[candidate.series]
            history = snapshot_rows(series_rows[candidate.series], candidate.T, first_day)
            parts = statement_parts(candidate, series, history)
            names = [candidate.series, *series.get("related", [])]
            snapshot = {}
            for name in names:
                rows = snapshot_rows(series_rows[name], candidate.T, first_day)
                assert all(day < candidate.T for day, _ in rows)
                relative = f"snapshots/{candidate.T.isoformat()}/{name}.csv"
                if relative not in snapshots:
                    snapshots[relative] = write_lf(out_dir / relative, snapshot_csv(rows))
                snapshot[name] = {"path": relative, "sha256": snapshots[relative], "rows": len(rows),
                                  "first": rows[0][0].isoformat() if rows else None,
                                  "last": rows[-1][0].isoformat() if rows else None}
            task = {
                "task_id": candidate.task_id, "kind": "forecast", "split": split, "source": candidate.source,
                "series": candidate.series, "related": list(series.get("related", [])),
                "template": candidate.template, "params": candidate.params, "horizon_days": candidate.horizon,
                "forecast_date": candidate.T.isoformat(), "window_end": candidate.window_end.isoformat(),
                "history_start": config["history_start"],
                "base_rate": round(candidate.base_rate, 6), "base_rate_windows": candidate.windows,
                "shown_at_T": parts["shown"], "title": parts["title"], "criteria": parts["criteria"],
                "fine_print": parts["fine_print"], "snapshot": snapshot,
            }
            task["statement"] = f"{task['title']}\n\n{task['criteria']}\n\n{task['fine_print']}"
            task["question_md"] = question_markdown(task)
            task["data_readme"] = data_readme(config, names, candidate.T)
            tasks.append(task)
            # Outcomes only now, after the draw: the full series, window values kept for audit.
            resolutions[candidate.task_id] = resolution_record(candidate, series_rows[candidate.series])
    control_pool, control_counts = candidates(config, series_rows, RECALL_CONTROL_DATES)
    control, control_resolutions = [], {}
    for candidate in sorted(draw_recall_control(control_pool), key=lambda c: (c.T, c.task_id)):
        series = meta[candidate.series]
        parts = statement_parts(candidate, series, snapshot_rows(series_rows[candidate.series], candidate.T, first_day))
        control.append({"task_id": candidate.task_id, "source": candidate.source, "series": candidate.series,
                        "template": candidate.template, "params": candidate.params,
                        "horizon_days": candidate.horizon, "forecast_date": candidate.T.isoformat(),
                        "window_end": candidate.window_end.isoformat(), "base_rate": round(candidate.base_rate, 6),
                        "title": parts["title"], "criteria": parts["criteria"], "fine_print": parts["fine_print"]})
        control_resolutions[candidate.task_id] = resolution_record(candidate, series_rows[candidate.series])
    tasks_sha = write_lf(out_dir / "tasks.forecast.json", dumps({"schema": "forecast-tasks-v1", "tasks": tasks}))
    splits = {split: [t["task_id"] for t in tasks if t["split"] == split] for split, _ in SPLITS}
    splits["series"] = {split: sorted(name for name, owner in split_of.items() if owner == split)
                        for split, _ in SPLITS}
    splits_sha = write_lf(out_dir / "splits.json", dumps(splits))
    control_sha = write_lf(out_dir / "recall_control.json", dumps({"schema": "forecast-recall-control-v1",
                                                                   "questions": control}))
    resolutions_sha = write_lf(sealed_dir / "resolutions.json", dumps({
        "schema": "forecast-resolutions-v2", "resolutions": resolutions, "recall_control": control_resolutions}))
    per_month_cells = {}
    for candidate in kept:
        per_month_cells.setdefault(candidate.T.month, set()).add((candidate.series, candidate.T))
    per_series = {}
    for task in tasks:
        per_series[task["series"]] = per_series.get(task["series"], 0) + 1
    manifest = {
        "builder_version": BUILDER_VERSION, "seed": SEED, "selection_rule": SELECTION_RULE,
        "builder_sha256": lf_sha256(Path(__file__)), "resolvers_sha256": lf_sha256(HERE / "resolvers.py"),
        "sources_sha256": lf_sha256(sources_path),
        "forecast_dates": [d.isoformat() for d in FORECAST_DATES], "horizons": list(HORIZONS),
        "base_rate_range": list(BASE_RATE_RANGE), "min_windows": MIN_WINDOWS, "series_cap": SERIES_CAP,
        "history_start": config["history_start"], "fetch_end": config["fetch_end"],
        "series": len(config["series"]),
        "raw": {key: {"url": value["url"], "sha256": value["sha256"], "bytes": value["bytes"]}
                for key, value in sorted(raw_manifest.items())},
        "last_date_per_series": {name: rows[-1][0].isoformat() if rows else None
                                 for name, rows in sorted(series_rows.items())},
        "candidates": counts,
        "cells_with_a_kept_candidate": {("july" if month == 7 else "august"): len(cells)
                                        for month, cells in sorted(per_month_cells.items())},
        "split_targets": {split: count for split, count in SPLITS},
        "split_counts": {split: len(splits[split]) for split, _ in SPLITS},
        "split_series": {split: len(names) for split, names in splits["series"].items()},
        "questions_per_series": {split: _tally(str(per_series.get(name, 0)) for name in names)
                                 for split, names in splits["series"].items()},
        "split_by_template": {split: _tally(t["template"] for t in tasks if t["split"] == split) for split, _ in SPLITS},
        "split_by_source": {split: _tally(t["source"] for t in tasks if t["split"] == split) for split, _ in SPLITS},
        "split_by_horizon": {split: _tally(str(t["horizon_days"]) for t in tasks if t["split"] == split)
                             for split, _ in SPLITS},
        "recall_control": {"candidates": control_counts, "count": len(control),
                           "dates": [d.isoformat() for d in RECALL_CONTROL_DATES]},
        "tasks_file": {"path": "tasks.forecast.json", "sha256": tasks_sha},
        "splits_file": {"path": "splits.json", "sha256": splits_sha},
        "recall_control_file": {"path": "recall_control.json", "sha256": control_sha},
        "snapshots": dict(sorted(snapshots.items())),
        "resolutions": {"path": shown_path(sealed_dir / "resolutions.json"), "sha256": resolutions_sha,
                        "note": "outside the checkout; never written into a workspace; pinned in card 022"},
    }
    write_lf(out_dir / "bank_manifest.json", dumps(manifest))
    return manifest


def shown_path(path: Path) -> str:
    """A path under the home directory as ~/..., so the manifest does not depend on the user name."""
    try:
        return "~/" + Path(path).resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _tally(values) -> dict:
    tally: dict = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return dict(sorted(tally.items()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--fetch", action="store_true", help="fetch uncached raw responses first (network)")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between requests")
    args = parser.parse_args(argv)
    config = json.loads(args.sources.read_text(encoding="utf-8"))
    if args.fetch:
        fetch_missing(config, args.raw, args.pause)
    series_rows = parse_series(config, args.raw)
    manifest = build(config, series_rows, args.out, args.sealed, read_manifest(args.raw), args.sources)
    print(json.dumps({key: manifest[key] for key in ("candidates", "cells_with_a_kept_candidate", "split_counts")}))
    print(f"tasks {manifest['tasks_file']['sha256']}  resolutions {manifest['resolutions']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
