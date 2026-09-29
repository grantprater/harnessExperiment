"""Card 022's question bank: the true resolvers, the builder (fetch, parse, frozen selection rule, determinism, no
outcome read before the draw), and properties of the committed bank. Offline: the raw responses are the trimmed
fixtures in tests/fixtures/forecast (5 series from 2024-06-01) and the committed snapshots; no network."""

import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "experiments" / "forecast_tasks"
FIXTURES = ROOT / "tests" / "fixtures" / "forecast"
sys.path.insert(0, str(FORECAST))

import build_bank  # noqa: E402
import resolvers  # noqa: E402

D = datetime.date


def daily(start, values):
    return [(start + datetime.timedelta(days=i), float(v)) for i, v in enumerate(values)]


def lf_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class ResolverTests(unittest.TestCase):
    T = D(2026, 7, 6)

    def test_direction_compares_the_windows_last_value_with_the_last_before_T(self):
        rows = daily(D(2026, 7, 1), [1, 2, 3, 4, 5, 9, 1, 2])  # T = 07-06 has 9
        self.assertTrue(resolvers.direction(rows, self.T, 1))  # window [07-06]: 9 > 5
        self.assertFalse(resolvers.direction(rows, self.T, 2))  # window ends 07-07 at 1
        self.assertFalse(resolvers.direction(rows, self.T, 3))  # ends 07-08 at 2; the reference is 5 (07-05)
        self.assertTrue(resolvers.direction(rows[:5] + [(D(2026, 7, 9), 6.0)], self.T, 4))  # holidays: last is 07-09

    def test_empty_windows_resolve_no(self):
        rows = daily(D(2026, 6, 1), range(35))  # ends 07-05, nothing on or after T
        for template in ("direction", "touch", "window_mean"):
            self.assertFalse(resolvers.resolve(template, rows, self.T, 7))
        self.assertFalse(resolvers.direction([], self.T, 7))

    def test_windows_are_half_open(self):
        rows = daily(D(2026, 7, 6), [0] * 7 + [100])  # 07-13 = T + 7 is outside a 7-day window
        self.assertFalse(resolvers.touch([(D(2026, 7, 1), 50.0), *rows], self.T, 7))
        self.assertTrue(resolvers.touch([(D(2026, 7, 1), 50.0), *rows], self.T, 8))

    def test_touch_level_is_the_max_of_the_90_days_before_T(self):
        rows = [(self.T - datetime.timedelta(days=91), 1000.0), (self.T - datetime.timedelta(days=90), 10.0),
                (self.T - datetime.timedelta(days=1), 5.0), (self.T, 10.0), (self.T + datetime.timedelta(days=1), 10.5)]
        self.assertEqual(resolvers.touch_level(rows, self.T), 10.0)  # T-91 is outside the lookback
        self.assertFalse(resolvers.touch(rows, self.T, 1))  # 10 is not strictly above 10
        self.assertTrue(resolvers.touch(rows, self.T, 2))

    def test_window_mean(self):
        rows = daily(self.T - datetime.timedelta(days=3), [1, 2, 3, 2, 2, 2.1])
        self.assertTrue(resolvers.window_mean(rows, self.T, 3))  # 2.033 > 2
        self.assertFalse(resolvers.window_mean(daily(self.T - datetime.timedelta(days=3), [1, 2, 3, 2, 2, 2]),
                                               self.T, 3))

    def test_count_k_is_the_rounded_up_median_of_52_blocks(self):
        start = self.T - datetime.timedelta(days=7 * 52)
        weeks = [[1] * (i % 4) + [0] * (7 - i % 4) for i in range(52)]  # wet days per week: 0,1,2,3,0,1,...
        rows = daily(start, [v for week in weeks for v in week])
        self.assertEqual(resolvers.count_k(rows, self.T, 7, "days", 1.0), 2)  # median of 13x(0,1,2,3) = 1.5 -> 2
        after = daily(self.T, [1, 1, 0, 0, 0, 0, 0])
        self.assertTrue(resolvers.count(rows + after, self.T, 7, "days", 1.0))
        self.assertFalse(resolvers.count(rows + daily(self.T, [1, 0, 0, 0, 0, 0, 0]), self.T, 7, "days", 1.0))
        sums = daily(start, [3] * 364)  # 21 per week
        self.assertEqual(resolvers.count_k(sums, self.T, 7, "sum", 0.0), 21)
        self.assertTrue(resolvers.count(sums + daily(self.T, [3] * 7), self.T, 7, "sum", 0.0))

    def test_past_windows_end_before_T_and_respect_the_lookback(self):
        dates = resolvers.past_forecast_dates(self.T, 14, "touch", D(2026, 1, 1))
        self.assertEqual(dates[0], self.T - datetime.timedelta(days=14))  # T-7 would end on T+6
        self.assertTrue(all(d + datetime.timedelta(days=14) <= self.T for d in dates))
        self.assertTrue(all(d - datetime.timedelta(days=90) >= D(2026, 1, 1) for d in dates))
        self.assertTrue(all((self.T - d).days % 7 == 0 for d in dates))

    def test_base_rate_reads_only_rows_before_T(self):
        rows = daily(D(2025, 1, 1), [i % 5 for i in range(600)])
        before = resolvers.base_rate(rows, self.T, 7, "direction")
        changed = [(d, v if d < self.T else -v) for d, v in rows]
        self.assertEqual(resolvers.base_rate(changed, self.T, 7, "direction"), before)


class BuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
        cls.series = build_bank.parse_series(cls.config, FIXTURES / "raw")

    def build(self, series=None):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        out, sealed = Path(scratch.name) / "bank", Path(scratch.name) / "sealed"
        manifest = build_bank.build(self.config, series or self.series, out, sealed,
                                    build_bank.read_manifest(FIXTURES / "raw"), FIXTURES / "sources.json")
        return out, sealed, manifest

    def test_parse_is_sorted_daily_and_counts_earthquakes_only(self):
        quakes = self.series["quakes_california_m25"]
        days = [d for d, _ in quakes]
        self.assertEqual(days, sorted(days))
        self.assertEqual(days[0], D(2024, 6, 1))
        self.assertEqual(len(days), (days[-1] - days[0]).days + 1)  # zero-filled every day
        self.assertIn(0.0, [v for _, v in quakes])
        raw = "".join((FIXTURES / "raw" / f"usgs-quakes_california_m25-{y}.csv").read_text(encoding="utf-8")
                      for y in (2024, 2025, 2026))
        earthquakes = sum(1 for line in raw.splitlines() if line.endswith(",earthquake")
                          and line[:10] < build_bank.parse_day(self.config["fetch_end"]).isoformat())
        self.assertEqual(sum(v for _, v in quakes), earthquakes)
        self.assertIn(",quarry blast", raw)  # present in the raw data, excluded from the counts
        self.assertEqual(self.series["DGS10"][0][0], D(2024, 6, 3))  # FRED: business days only

    def test_a_tampered_raw_response_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch)
            for path in (FIXTURES / "raw").iterdir():
                (raw / path.name).write_bytes(path.read_bytes())
            (raw / "fred-DGS10.csv").write_bytes((raw / "fred-DGS10.csv").read_bytes() + b"2026-09-28,9.99\n")
            with self.assertRaisesRegex(ValueError, "sha256"):
                build_bank.parse_series(self.config, raw)

    def test_build_is_deterministic(self):
        first, sealed_a, manifest_a = self.build()
        second, sealed_b, manifest_b = self.build()
        files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file()))
        for relative in files:
            if relative.name != "bank_manifest.json":  # it names the sealed file's (temporary) path
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes(), relative)
        self.assertEqual((sealed_a / "resolutions.json").read_bytes(), (sealed_b / "resolutions.json").read_bytes())
        self.assertEqual(manifest_a["tasks_file"], manifest_b["tasks_file"])

    def test_frozen_rule(self):
        out, sealed, manifest = self.build()
        tasks = json.loads((out / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(manifest["split_counts"], {"calibration": 20, "sealed": 10, "reserve": 0})
        cells = [(t["series"], t["forecast_date"]) for t in tasks]
        self.assertEqual(len(cells), len(set(cells)))  # at most one question per (series, T)
        capped = [t["series"] for t in tasks if t["split"] in ("sealed", "reserve")]
        self.assertTrue(all(capped.count(s) <= build_bank.SERIES_CAP for s in capped))
        for task in tasks:
            self.assertTrue(0.2 <= task["base_rate"] <= 0.8 and task["base_rate_windows"] >= 52)
            month = D.fromisoformat(task["forecast_date"]).month
            self.assertEqual(month, 7 if task["split"] == "calibration" else 8)
            self.assertIn(D.fromisoformat(task["forecast_date"]), build_bank.FORECAST_DATES)
        splits = json.loads((out / "splits.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(len(v) for v in splits.values()), len(tasks))

    def test_no_outcome_in_the_checkout_outputs(self):
        out, sealed, manifest = self.build()
        resolutions = json.loads((sealed / "resolutions.json").read_text(encoding="utf-8"))["resolutions"]
        self.assertFalse((out / "resolutions.json").exists())
        self.assertEqual(manifest["resolutions"]["sha256"], lf_sha(sealed / "resolutions.json"))
        tasks = json.loads((out / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(set(resolutions), {t["task_id"] for t in tasks})
        for task in tasks:
            self.assertFalse({"outcome", "resolution"} & set(task))
            for item in task["snapshot"].values():
                last = (out / item["path"]).read_text(encoding="utf-8").splitlines()[-1][:10]
                self.assertLess(last, task["forecast_date"])

    def test_selection_never_reads_data_on_or_after_T(self):
        """Changing every value dated on or after 2026-07-27 (the last July T) leaves the calibration draw and its
        statements unchanged; only outcomes may differ."""
        cut = D(2026, 7, 27)
        changed = {name: [(d, v if d < cut else v * 3 + 7) for d, v in rows] for name, rows in self.series.items()}
        out_a, _, _ = self.build()
        out_b, _, _ = self.build(changed)
        load = lambda out: [t for t in json.loads((out / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]
                            if t["split"] == "calibration"]  # noqa: E731
        self.assertEqual(load(out_a), load(out_b))

    def test_fetch_is_sequential_polite_and_cached(self):
        requests, sleeps = [], []

        class Response:
            status = 200

            def __init__(self, url):
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return f"payload for {self.url}".encode()

        def opener(request, timeout):
            requests.append((request.full_url, request.get_header("User-agent")))
            return Response(request.full_url)

        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch)
            manifest = build_bank.fetch_missing(self.config, raw, 2.0, opener=opener, sleep=sleeps.append,
                                                out=lambda *_: None)
            planned = build_bank.requests_for(self.config)
            self.assertEqual([url for url, _ in requests], [url for _, url, _ in planned])
            self.assertEqual(sleeps, [2.0] * (len(planned) - 1))
            self.assertTrue(all(agent == build_bank.USER_AGENT for _, agent in requests))
            for key, url, _ in planned:
                self.assertEqual(manifest[key]["sha256"], hashlib.sha256(f"payload for {url}".encode()).hexdigest())
            build_bank.fetch_missing(self.config, raw, 2.0, opener=opener, sleep=sleeps.append, out=lambda *_: None)
            self.assertEqual(len(requests), len(planned))  # everything cached: no second request


class CommittedBankTests(unittest.TestCase):
    """The bank card 022 pins: every snapshot matches its hash and ends before its forecast date."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((FORECAST / "bank_manifest.json").read_text(encoding="utf-8"))
        cls.tasks = json.loads((FORECAST / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]

    def test_manifest_pins_the_committed_files(self):
        self.assertEqual(lf_sha(FORECAST / "tasks.forecast.json"), self.manifest["tasks_file"]["sha256"])
        self.assertEqual(lf_sha(FORECAST / "splits.json"), self.manifest["splits_file"]["sha256"])
        self.assertEqual(lf_sha(FORECAST / "resolvers.py"), self.manifest["resolvers_sha256"])
        self.assertEqual(lf_sha(FORECAST / "sources.json"), self.manifest["sources_sha256"])
        for relative, digest in self.manifest["snapshots"].items():
            self.assertEqual(lf_sha(FORECAST / relative), digest, relative)
        card = json.loads((ROOT / "experiments" / "session_harness" / "cards" / "022.json").read_text(encoding="utf-8"))
        self.assertEqual(card["tasks"]["file_sha256"], self.manifest["tasks_file"]["sha256"])
        self.assertIn(self.manifest["resolutions"]["sha256"], " ".join(card["stop_rules"]["manual"]))

    def test_every_snapshot_row_is_before_its_forecast_date(self):
        checked = 0
        for task in self.tasks:
            self.assertFalse({"outcome", "resolution"} & set(task))
            for name, item in task["snapshot"].items():
                lines = (FORECAST / item["path"]).read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[0], "date,value")
                self.assertEqual(len(lines) - 1, item["rows"])
                self.assertTrue(all(line[:10] < task["forecast_date"] for line in lines[1:]), (task["task_id"], name))
                checked += 1
        self.assertGreater(checked, 100)

    def test_counts_are_what_the_frozen_rule_gives(self):
        self.assertEqual(self.manifest["split_counts"], {"calibration": 40, "sealed": 60, "reserve": 0})
        self.assertEqual(self.manifest["cells_with_a_kept_candidate"], {"july": 120, "august": 120})
        self.assertEqual(len(self.tasks), 100)


if __name__ == "__main__":
    unittest.main()
