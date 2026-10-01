"""True resolvers for card 022's forecast templates (standard library only).

Shared by the bank builder (history-only base rates and, after the draw, the sealed resolutions), the in-run evaluator
(reading agreement on past windows), and the scripted `gold`/`constant`/`peeker` controls, whose resolve.py is this
file's source followed by an `outcome` wrapper (standalone_resolve_py). One function per template, each generic in the
forecast date, so the same code gives a question's outcome and its base rate over past windows.

Conventions (the question statements say the same in words):
- rows: the target series as (datetime.date, float) pairs sorted by date; at resolution time it holds every published
  row, at forecast time only rows dated before T.
- The window of a question with forecast date T and horizon h days is the h dates T, T+1, ..., T+h-1 ([T, T+h)).
  The snapshot a forecaster sees ends the day before T, so no date is in both.
- A window with no row resolves NO (market holidays can empty a short window; a whole-week gap never occurs in the
  bank's series, and the builder refuses a question whose window lies beyond the fetched data).
"""

from __future__ import annotations

from bisect import bisect_left
import datetime
import math

TOUCH_LOOKBACK_DAYS = 90
COUNT_HISTORY_WEEKS = 52


def _index(rows, day):
    """The number of rows dated before day (rows are sorted by date)."""
    return bisect_left(rows, day, key=lambda row: row[0])


def _window(rows, start, end):
    """Values dated in [start, end)."""
    return [value for _, value in rows[_index(rows, start):_index(rows, end)]]


def _last_before(rows, day):
    position = _index(rows, day)
    return rows[position - 1][1] if position else None


def direction(rows, T, horizon):
    """YES if the last value dated in [T, T+h) is strictly greater than the last value dated before T."""
    reference = _last_before(rows, T)
    window = _window(rows, T, T + datetime.timedelta(days=horizon))
    return reference is not None and bool(window) and window[-1] > reference


def touch_level(rows, T):
    """The maximum over the 90 dates before T ([T-90, T)); None without a row there."""
    history = _window(rows, T - datetime.timedelta(days=TOUCH_LOOKBACK_DAYS), T)
    return max(history) if history else None


def touch(rows, T, horizon):
    """YES if any value dated in [T, T+h) is strictly greater than the maximum over the 90 dates before T."""
    level = touch_level(rows, T)
    window = _window(rows, T, T + datetime.timedelta(days=horizon))
    return level is not None and any(value > level for value in window)


def window_mean(rows, T, horizon):
    """YES if the mean over [T, T+h) is strictly greater than the mean over the h dates before T ([T-h, T))."""
    step = datetime.timedelta(days=horizon)
    after, before = _window(rows, T, T + step), _window(rows, T - step, T)
    return bool(after) and bool(before) and sum(after) / len(after) > sum(before) / len(before)


def _week_total(rows, start, horizon, mode, threshold):
    values = _window(rows, start, start + datetime.timedelta(days=horizon))
    if mode == "sum":
        return sum(values)
    return sum(1 for value in values if value >= threshold)


def count_k(rows, T, horizon, mode, threshold):
    """k: the median of the totals of the 52 consecutive h-day blocks before T, rounded up to a whole number."""
    totals = sorted(_week_total(rows, T - datetime.timedelta(days=horizon * j), horizon, mode, threshold)
                    for j in range(1, COUNT_HISTORY_WEEKS + 1))
    middle = len(totals) // 2
    median = totals[middle] if len(totals) % 2 else (totals[middle - 1] + totals[middle]) / 2
    return int(math.ceil(median - 1e-9))


def count(rows, T, horizon, mode, threshold):
    """YES if the window's total is at least k (count_k). mode "sum" adds the values (daily event counts); mode
    "days" counts the dates whose value is at least threshold (wet days)."""
    return _week_total(rows, T, horizon, mode, threshold) >= count_k(rows, T, horizon, mode, threshold)


RESOLVERS = {"direction": direction, "touch": touch, "window_mean": window_mean, "count": count}


def resolve(template, rows, T, horizon, params=None):
    """The true outcome of one template on rows, as a bool."""
    return bool(RESOLVERS[template](rows, T, horizon, **(params or {})))


def lookback_days(template, horizon):
    """How many dates before T a template reads; a past window needs this much history inside the snapshot."""
    if template == "touch":
        return TOUCH_LOOKBACK_DAYS
    if template == "count":
        return horizon * COUNT_HISTORY_WEEKS
    if template == "window_mean":
        return horizon
    return 7  # direction: the last value before T (a week covers any market holiday)


def past_forecast_dates(T, horizon, template, first_day):
    """Weekly past forecast dates T' = T - 7k whose whole window ends before T and whose lookback starts on or after
    first_day, newest first."""
    dates, k = [], 1
    while True:
        past = T - datetime.timedelta(days=7 * k)
        k += 1
        if past + datetime.timedelta(days=horizon) > T:
            continue
        if past - datetime.timedelta(days=lookback_days(template, horizon)) < first_day:
            return dates
        dates.append(past)


def base_rate(rows, T, horizon, template, params=None, first_day=None):
    """(history-only frequency of YES over past windows, number of windows). Uses only rows dated before T."""
    history = [(day, value) for day, value in rows if day < T]
    if not history:
        return None, 0
    first_day = first_day or history[0][0]
    dates = past_forecast_dates(T, horizon, template, first_day)
    if not dates:
        return None, 0
    outcomes = [resolve(template, history, past, horizon, params) for past in dates]
    return sum(outcomes) / len(outcomes), len(outcomes)
