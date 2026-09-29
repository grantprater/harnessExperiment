"""One isolated question to the Claude CLI, for card 022's recall probe and one-shot comparator (built; not run).

It is claude_cli.py's ClaudeCliClient with no harness tools, exactly as `claude_cli.py --probe-tools` asks its
question: the same isolation flags (no built-in tools, no MCP, no settings, no session persistence), the same child
environment (no ANTHROPIC_* credential, no session link), the same model pin (a full id such as claude-sonnet-5; a
reply from any other model is a model_pin_violation and raises), and every attempt appended to a calls.jsonl with the
CLI's list-price estimate. The answer is the reply's content text.

A live call happens only through ask(); nothing in this module or its callers runs one without an explicit --live flag.
"""

from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

from claude_cli import ClaudeCliClient, pins_model  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-5"
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 300


class AttemptBudget:
    """A cap on CLI attempts across every question of one invocation (the campaign-level cap)."""

    def __init__(self, maximum: int):
        self.maximum, self.used = maximum, 0

    def check(self):
        if self.used >= self.maximum:
            raise RuntimeError(f"attempt cap {self.maximum} reached")

    def take(self):
        self.check()
        self.used += 1


def ask(prompt: str, *, model: str, calls_path: Path, run_id: str, budget: AttemptBudget,
        executable: str = "claude") -> dict:
    """One question, one reply: {"reply", "model", "reported_model", "cli_list_price_estimate_usd", "attempts"}."""
    if not pins_model(model):
        raise SystemExit(f"--model must be a full id such as {DEFAULT_MODEL}, not the alias {model!r}")
    client = ClaudeCliClient(model, calls_path, run_id, budget, max_attempts=MAX_ATTEMPTS, timeout=TIMEOUT_SECONDS,
                             executable=executable)
    response = client.complete([{"role": "user", "content": prompt}], [])
    metadata = response.metadata or {}
    return {"reply": response.message.get("content") or "", "model": metadata.get("model"),
            "reported_model": metadata.get("reported_model"), "attempts": metadata.get("attempts"),
            "cli_list_price_estimate_usd": metadata.get("cli_list_price_estimate_usd")}
