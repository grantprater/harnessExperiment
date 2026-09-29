"""Card 022's power analysis with series as the unit (design section 4, redone for Q6's decision on 2026-09-29).

The verdict resamples series (score_forecasts.py), so questions of one series count less than independent ones. With
N questions in k series of sizes m_i, the variance of D is sigma_d^2 / N times the design effect
DE = 1 + (m_w - 1) * rho, where m_w = sum(m_i^2) / N is the size-weighted mean cluster size and rho the within-series
correlation of the paired per-question differences d. The effective N is N / DE, and the one-sided power at a true
gain Delta is Phi(Delta * sqrt(N_eff) / sigma_d - t_{0.95, k-1}) (t with k-1 degrees of freedom, since only k
clusters carry the variance).

rho is not measured for model arms (nothing has run). The estimate here is a proxy from data that no bank question
uses: historical pseudo-questions at the Mondays of 2025 on all 60 series (the bank's templates and filter, windows
ending before 2026), each series drawn like the bank (up to 4 questions with non-overlapping windows), and two
non-model forecasters that differ only in method: the full-history base rate (gold) and the base rate of the last 26
past windows. d is their paired Brier difference; rho is the one-way ANOVA intraclass correlation over series,
repeated over 200 seeded draws. It says how much a series' questions move together when a forecasting method
changes; a harness change on a model arm may correlate differently, so the table also shows 0 to 0.3.

  python experiments/forecast_tasks/power_forecast.py      writes power_forecast.json next to this file
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
import random
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_bank  # noqa: E402
import resolvers  # noqa: E402

PSEUDO_DATES = tuple(datetime.date(2025, 1, 6) + datetime.timedelta(days=14 * k) for k in range(26))
RECENT_WINDOWS = 26
DRAWS = 200
DELTA = 0.02
SIGMAS = (0.05, 0.07, 0.10)
RHOS = (0.0, 0.1, 0.2, 0.3)
Z_POWER = 0.8416  # 80% power
Z_ALPHA = 1.6449  # one-sided 0.05


def t_quantile_95(df: int) -> float:
    """Cornish-Fisher expansion of the t distribution's 0.95 quantile (exact to about 1e-3 for df >= 10)."""
    z = Z_ALPHA
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def pseudo_questions(config: dict, series_rows: dict) -> dict:
    """{series: [(T, horizon, d)]}: every 2025 pseudo-question that passes the bank's filter, with the paired Brier
    difference recent-minus-full base rate."""
    first_day = build_bank.parse_day(config["history_start"])
    out = {}
    for series in config["series"]:
        rows = series_rows[series["name"]]
        items = []
        for T in PSEUDO_DATES:
            history = [(day, value) for day, value in rows if first_day <= day < T]
            for template, horizon, params in build_bank.template_plan(series):
                past = resolvers.past_forecast_dates(T, horizon, template, first_day)
                if len(past) < build_bank.MIN_WINDOWS:
                    continue
                outcomes = [resolvers.resolve(template, history, day, horizon, params) for day in past]
                full = sum(outcomes) / len(outcomes)
                if not build_bank.BASE_RATE_RANGE[0] <= full <= build_bank.BASE_RATE_RANGE[1]:
                    continue
                recent = sum(outcomes[:RECENT_WINDOWS]) / RECENT_WINDOWS
                outcome = 1.0 if resolvers.resolve(template, rows, T, horizon, params) else 0.0
                items.append((T, horizon, (recent - outcome) ** 2 - (full - outcome) ** 2))
        out[series["name"]] = items
    return out


def draw_like_bank(items, rng: random.Random, cap: int = build_bank.SERIES_CAP) -> list:
    """Up to cap questions with non-overlapping windows, in random order."""
    pool = list(items)
    rng.shuffle(pool)
    taken = []
    for T, horizon, d in pool:
        end = T + datetime.timedelta(days=horizon)
        if all(end <= t or t + datetime.timedelta(days=h) <= T for t, h, _ in taken):
            taken.append((T, horizon, d))
        if len(taken) == cap:
            break
    return taken


def icc(groups) -> float:
    """One-way random-effects ANOVA intraclass correlation for unequal group sizes (clipped at 0 below)."""
    groups = [g for g in groups if len(g) >= 1]
    n = sum(len(g) for g in groups)
    k = len(groups)
    grand = sum(sum(g) for g in groups) / n
    ssb = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
    denominator = msb + (m0 - 1) * msw
    return max(0.0, (msb - msw) / denominator) if denominator > 0 else 0.0


def power_table(sizes, rhos=RHOS, sigmas=SIGMAS, delta=DELTA) -> list:
    n, k = sum(sizes), len(sizes)
    m_w = sum(m * m for m in sizes) / n
    critical = t_quantile_95(k - 1)
    rows = []
    for rho in rhos:
        design_effect = 1 + (m_w - 1) * rho
        n_eff = n / design_effect
        rows.append({"rho": round(rho, 4), "design_effect": round(design_effect, 3), "n_eff": round(n_eff, 1),
                     "power": {f"{sigma:.2f}": round(normal_cdf(delta * math.sqrt(n_eff) / sigma - critical), 3)
                               for sigma in sigmas}})
    return rows


def required_n(sigma: float, rho: float, m_w: float, delta: float = DELTA) -> int:
    """Questions needed for 80% power at one-sided 0.05 (normal approximation), with the design effect."""
    return math.ceil(((Z_ALPHA + Z_POWER) * sigma / delta) ** 2 * (1 + (m_w - 1) * rho))


def main() -> int:
    config = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    series_rows = build_bank.parse_series(config, build_bank.DEFAULT_RAW)
    items = pseudo_questions(config, series_rows)
    estimates = []
    for draw in range(DRAWS):
        rng = random.Random(f"22:power:{draw}")
        groups = [[d for _, _, d in draw_like_bank(items[name], rng)] for name in sorted(items)]
        estimates.append(icc([g for g in groups if g]))
    estimates.sort()
    rho_hat = statistics.median(estimates)
    splits = json.loads((HERE / "splits.json").read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t for t in json.loads((HERE / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]}
    sealed_sizes = {}
    for task_id in splits["sealed"]:
        sealed_sizes[tasks[task_id]["series"]] = sealed_sizes.get(tasks[task_id]["series"], 0) + 1
    sizes = sorted(sealed_sizes.values(), reverse=True)
    m_w = sum(m * m for m in sizes) / sum(sizes)
    report = {
        "method": __doc__.split("\n\n")[1].replace("\n", " "),
        "sealed": {"questions": sum(sizes), "series": len(sizes), "sizes": sizes, "m_weighted": round(m_w, 3)},
        "rho_proxy": {"median": round(rho_hat, 4), "p05": round(estimates[int(0.05 * DRAWS)], 4),
                      "p95": round(estimates[int(0.95 * DRAWS) - 1], 4), "draws": DRAWS,
                      "pseudo_questions": sum(len(v) for v in items.values()),
                      "sd_d_proxy": round(statistics.pstdev([d for v in items.values() for _, _, d in v]), 4)},
        "power_at_delta_0.02": power_table(sizes, sorted(set(RHOS) | {round(rho_hat, 4)})),
        "required_n_80pct": {f"sigma {sigma:.2f}, rho {rho}": required_n(sigma, rho, m_w)
                             for sigma in SIGMAS for rho in (0.0, round(rho_hat, 4), 0.2)},
        "t_critical": round(t_quantile_95(len(sizes) - 1), 4),
    }
    (HERE / "power_forecast.json").write_bytes((json.dumps(report, indent=1) + "\n").encode("utf-8"))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
