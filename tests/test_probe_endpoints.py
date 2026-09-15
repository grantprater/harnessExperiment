"""Endpoint probe: classification, route pricing, and summary eligibility (mocked HTTP, no API calls)."""

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import probe_endpoints  # noqa: E402


def tool_response(name="list_files", arguments='{"path": "."}'):
    return {"provider": "Stub", "usage": {"cost": 0.0001}, "choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}]}}]}


class ClassifyTests(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual(probe_endpoints.classify(tool_response()), ("valid_tool_call", "list_files"))
        self.assertEqual(probe_endpoints.classify(tool_response(arguments={"path": "."}))[0], "valid_tool_call")
        self.assertEqual(probe_endpoints.classify(tool_response(name="rm_rf"))[0], "invalid_tool_call")
        self.assertEqual(probe_endpoints.classify(tool_response(arguments="{not json"))[0], "invalid_tool_arguments")
        self.assertEqual(probe_endpoints.classify(tool_response(arguments='["x"]'))[0], "invalid_tool_call")
        text = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "hmm"}}]}
        self.assertEqual(probe_endpoints.classify(text), ("no_tool_call", "length"))
        self.assertEqual(probe_endpoints.classify({"error": {"message": "overloaded"}})[0], "error_body")


class EndpointPlanTests(unittest.TestCase):
    def catalog(self, endpoints):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps({"data": {"endpoints": endpoints}}).encode())
        return mock.patch.object(probe_endpoints.urllib.request, "urlopen", return_value=response)

    def endpoint(self, tag, prompt, completion, parameters=probe_endpoints.REQUIRED_PARAMETERS):
        return {"tag": tag, "quantization": "fp8", "status": 0, "uptime_last_1d": 99.9,
                "pricing": {"prompt": str(prompt / 1e6), "completion": str(completion / 1e6)},
                "supported_parameters": list(parameters)}

    def test_worst_case_uses_the_most_expensive_compatible_matching_endpoint(self):
        endpoints = [
            self.endpoint("vendor/fp8", 0.10, 0.40),
            self.endpoint("vendor/turbo", 0.50, 2.00, parameters=("tools", "max_tokens")),  # filtered out
            self.endpoint("vendor/eu", 0.20, 0.60),
            self.endpoint("other", 9.0, 9.0),
        ]
        with self.catalog(endpoints):
            plan = probe_endpoints.endpoint_plan("m/x", "vendor", 3_000, 1_000)
        self.assertEqual(plan["endpoint_tags"], ["vendor/fp8", "vendor/eu"])
        self.assertAlmostEqual(plan["worst_case_usd_per_request"], (1_000 * 0.20 + 1_000 * 0.60) / 1e6)

    def test_missing_or_incompatible_routes_stop_before_any_request(self):
        with self.catalog([self.endpoint("other", 0.1, 0.1)]), self.assertRaises(SystemExit):
            probe_endpoints.endpoint_plan("m/x", "vendor", 3_000, 1_000)
        with self.catalog([self.endpoint("vendor", 0.1, 0.1, parameters=("tools",))]), self.assertRaises(SystemExit):
            probe_endpoints.endpoint_plan("m/x", "vendor", 3_000, 1_000)


class SummaryTests(unittest.TestCase):
    def test_eligibility_requires_every_planned_request_to_return_a_valid_tool_call(self):
        with tempfile.TemporaryDirectory() as name:
            run_dir = Path(name)
            plans = [{"model": "m/a", "slug": "good"}, {"model": "m/b", "slug": "limited"}, {"model": "m/c", "slug": "short"}]
            (run_dir / "card.json").write_text(json.dumps({"rounds": 2, "endpoints": plans}), encoding="utf-8")
            rows = [
                {"model": "m/a", "slug": "good", "http_status": 200, "latency_s": 1.0, "outcome": "valid_tool_call", "response": tool_response()},
                {"model": "m/a", "slug": "good", "http_status": 200, "latency_s": 2.0, "outcome": "valid_tool_call", "response": tool_response()},
                {"model": "m/b", "slug": "limited", "http_status": 200, "latency_s": 1.0, "outcome": "valid_tool_call", "response": tool_response()},
                {"model": "m/b", "slug": "limited", "http_status": 429, "latency_s": 0.2, "outcome": "http_429", "error": "rate limited"},
                {"model": "m/c", "slug": "short", "http_status": 200, "latency_s": 1.0, "outcome": "valid_tool_call", "response": tool_response()},
            ]
            (run_dir / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with mock.patch("builtins.print"):
                summary = {item["slug"]: item for item in probe_endpoints.summarize(run_dir)}
        self.assertTrue(summary["good"]["eligible"])
        self.assertAlmostEqual(summary["good"]["reported_cost_usd"], 0.0002)
        self.assertFalse(summary["limited"]["eligible"])
        self.assertEqual(summary["limited"]["outcomes"], {"valid_tool_call": 1, "http_429": 1})
        self.assertFalse(summary["short"]["eligible"])


if __name__ == "__main__":
    unittest.main()
