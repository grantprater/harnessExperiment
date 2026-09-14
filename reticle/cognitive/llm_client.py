"""LLM Client with token accounting and efficiency telemetry for Reticle."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Pricing per 1M tokens: (prompt_price_usd, completion_price_usd)
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    # Google AI Studio / Gemini models
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-flash-8b": (0.0375, 0.15),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-3.6-flash": (0.10, 0.40),
    # OpenAI models
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3-mini": (1.10, 4.40),
}
DEFAULT_PRICING = (0.10, 0.40)


@dataclass
class StepMetric:
    step: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_s: float
    cost_usd: float
    model: str


class LLMClient:
    """Robust OpenAI/Google Studio compatible client with token telemetry.
    
    Automatically handles:
    1. Google AI Studio OpenAI-compatible endpoints
    2. Exact token accounting via response usage metadata
    3. Cost estimation based on model pricing
    4. Context growth gradient calculation (verifying flatline token dynamics)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self._load_dotenv_if_present()

        # Resolve API key from arguments or common environment variables
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or "mock_key"
        )

        # Base URL resolution
        default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENROUTER_BASE_URL")
            or default_base_url
        ).rstrip("/")

        # Model resolution
        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("MODEL")
            or "gemini-3.6-flash"
        )
        self.mock_mode = (self.api_key == "mock_key")

        # Telemetry records
        self.step_metrics: List[StepMetric] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    @staticmethod
    def _load_dotenv_if_present() -> None:
        """Parse local .env file if available in working directory."""
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().replace("$env:", "")
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD based on model pricing table."""
        prompt_rate, completion_rate = MODEL_PRICING.get(self.model, DEFAULT_PRICING)
        cost = (prompt_tokens / 1_000_000.0) * prompt_rate + (completion_tokens / 1_000_000.0) * completion_rate
        return round(cost, 6)

    def _record_turn(self, prompt_tokens: int, completion_tokens: int, latency_s: float) -> StepMetric:
        """Record turn telemetry and update aggregates."""
        total = prompt_tokens + completion_tokens
        cost = self._estimate_cost(prompt_tokens, completion_tokens)
        step_num = len(self.step_metrics) + 1

        metric = StepMetric(
            step=step_num,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            latency_s=round(latency_s, 3),
            cost_usd=cost,
            model=self.model
        )
        self.step_metrics.append(metric)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total
        self.total_cost_usd = round(self.total_cost_usd + cost, 6)
        return metric

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Execute chat completion with retry, token extraction, and telemetry."""
        t0 = time.time()

        if self.mock_mode:
            # Synthetic simulation when no live API key is present
            prompt_chars = sum(len(m.get("content", "")) for m in messages)
            mock_prompt_tokens = max(10, prompt_chars // 4)
            mock_completion_tokens = 35
            latency = time.time() - t0
            self._record_turn(mock_prompt_tokens, mock_completion_tokens, latency)

            return {
                "content": "Mock mode: simulated response (no live API key provided).",
                "tool_calls": [],
                "usage": {
                    "prompt_tokens": mock_prompt_tokens,
                    "completion_tokens": mock_completion_tokens,
                    "total_tokens": mock_prompt_tokens + mock_completion_tokens
                }
            }

        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/grant/reticle",
            "X-Title": "Reticle-Cognitive-Harness"
        }

        max_retries = 4
        for attempt in range(max_retries):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    latency = time.time() - t0
                    data = json.loads(resp.read().decode("utf-8"))

                    if "choices" not in data:
                        err_msg = json.dumps(data)
                        if ("502" in err_msg or "overloaded" in err_msg or "rate-limited" in err_msg) and attempt < max_retries - 1:
                            wait_sec = (attempt + 1) * 3
                            time.sleep(wait_sec)
                            continue
                        raise RuntimeError(f"Upstream LLM error response: {err_msg}")

                    choice = data["choices"][0]["message"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens") or (sum(len(m.get("content", "")) for m in messages) // 4)
                    c_tok = usage.get("completion_tokens") or (len(choice.get("content") or "") // 4)
                    self._record_turn(p_tok, c_tok, latency)

                    return {
                        "content": choice.get("content") or "",
                        "tool_calls": choice.get("tool_calls") or [],
                        "usage": {
                            "prompt_tokens": p_tok,
                            "completion_tokens": c_tok,
                            "total_tokens": p_tok + c_tok
                        }
                    }

            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                if e.code in (502, 503, 429) and attempt < max_retries - 1:
                    wait_sec = (attempt + 1) * 3
                    time.sleep(wait_sec)
                    continue
                raise RuntimeError(f"HTTP Error {e.code}: {err_body}")
            except Exception as e:
                if attempt < max_retries - 1 and ("502" in str(e) or "overloaded" in str(e)):
                    wait_sec = (attempt + 1) * 3
                    time.sleep(wait_sec)
                    continue
                raise RuntimeError(f"API/Network error: {e}")

        raise RuntimeError("Max retries exceeded.")

    def get_efficiency_metrics(self) -> Dict[str, Any]:
        """Compute full token efficiency and context stability telemetry."""
        turns = len(self.step_metrics)
        if turns == 0:
            return {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "total_turns": 0,
                "mean_tokens_per_step": 0.0,
                "context_growth_gradient": 0.0,
                "context_stability_index": 1.0,
                "total_latency_s": 0.0,
                "mean_latency_s": 0.0,
                "step_history": []
            }

        prompt_history = [m.prompt_tokens for m in self.step_metrics]
        total_lat = sum(m.latency_s for m in self.step_metrics)

        # Context growth gradient: simple linear slope of prompt tokens across steps
        # Flatline / Stateless => gradient ~ 0.0
        # Compounding / Conversational => gradient > 0.0
        if turns > 1:
            n = turns
            xs = list(range(1, n + 1))
            ys = prompt_history
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            denom = sum((x - mean_x) ** 2 for x in xs)
            if denom > 0:
                gradient = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / denom
            else:
                gradient = 0.0
            stability_index = round(max(ys) / max(1, min(ys)), 2)
        else:
            gradient = 0.0
            stability_index = 1.0

        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_turns": turns,
            "mean_tokens_per_step": round(self.total_tokens / turns, 1),
            "context_growth_gradient": round(gradient, 2),
            "context_stability_index": stability_index,
            "total_latency_s": round(total_lat, 2),
            "mean_latency_s": round(total_lat / turns, 2),
            "step_history": [asdict(m) for m in self.step_metrics]
        }
