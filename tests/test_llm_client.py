"""Unit tests for Reticle LLMClient and token efficiency telemetry."""

from __future__ import annotations

import unittest
from reticle.cognitive.llm_client import LLMClient, StepMetric, MODEL_PRICING


class TestLLMClientTelemetry(unittest.TestCase):

    def setUp(self):
        # Explicit mock mode to isolate unit test
        self.client = LLMClient(api_key="mock_key", model="gemini-3.6-flash")

    def test_mock_chat_completion_telemetry(self):
        messages = [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello world from unit test."}
        ]
        res = self.client.chat_completion(messages)
        self.assertIn("content", res)
        self.assertIn("usage", res)
        self.assertGreater(res["usage"]["prompt_tokens"], 0)
        self.assertGreater(res["usage"]["completion_tokens"], 0)

        metrics = self.client.get_efficiency_metrics()
        self.assertEqual(metrics["total_turns"], 1)
        self.assertEqual(metrics["total_tokens"], res["usage"]["total_tokens"])
        self.assertGreater(metrics["total_cost_usd"], 0.0)

    def test_cost_estimation(self):
        prompt_tokens = 1_000_000
        comp_tokens = 1_000_000
        cost = self.client._estimate_cost(prompt_tokens, comp_tokens)
        # gemini-3.6-flash is $0.10 / 1M prompt and $0.40 / 1M completion => $0.50
        self.assertAlmostEqual(cost, 0.50, places=2)

    def test_growth_gradient_calculation(self):
        # Manually record 3 flatline turns
        client = LLMClient(api_key="mock_key")
        client._record_turn(prompt_tokens=500, completion_tokens=50, latency_s=0.5)
        client._record_turn(prompt_tokens=500, completion_tokens=60, latency_s=0.6)
        client._record_turn(prompt_tokens=500, completion_tokens=40, latency_s=0.4)

        metrics = client.get_efficiency_metrics()
        self.assertEqual(metrics["total_turns"], 3)
        self.assertEqual(metrics["context_growth_gradient"], 0.0)
        self.assertEqual(metrics["context_stability_index"], 1.0)

    def test_compounding_growth_gradient(self):
        # Record turns that grow linearly (conversational drift)
        client = LLMClient(api_key="mock_key")
        client._record_turn(prompt_tokens=1000, completion_tokens=100, latency_s=0.5)
        client._record_turn(prompt_tokens=2000, completion_tokens=100, latency_s=0.5)
        client._record_turn(prompt_tokens=3000, completion_tokens=100, latency_s=0.5)

        metrics = client.get_efficiency_metrics()
        self.assertGreater(metrics["context_growth_gradient"], 900.0)
        self.assertGreater(metrics["context_stability_index"], 1.5)


if __name__ == "__main__":
    unittest.main()
