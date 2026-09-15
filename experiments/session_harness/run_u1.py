"""Usability fixtures for the coding-tool interface, with no-API controls.

U1 (pressure-recent-v2; recorded under toolset v2): a three-file package with a one-line bug. The task
does not name the function; 8-response budget.

U2 (pressure-recent-v3; toolset v3): a small package whose defect appears twice with identical text, so a
single exact replacement is ambiguous; documentation and several file types make file selection matter;
visible tests cover only one of the two defects; 12-response budget.

After the agent stops, a hidden check runs in the same isolated OCI environment. Every request's manifest
is checked for the remaining-resources line, and interface friction is computed from the saved session.
Clients: openrouter (live), gold and noop (no API).

Usage (from the repo root):
  python experiments/session_harness/run_u1.py --fixture u2 --client gold --run-name u2-gold
  python experiments/session_harness/run_u1.py --fixture u2 --client openrouter --model qwen/qwen3-coder-next \\
      --provider parasail --run-name u2-qwen-1 --max-total-calls 14 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import interface_friction  # noqa: E402
import run_pilot  # noqa: E402
from reticle.context import PressureRecentContextPolicyV2, PressureRecentContextPolicyV3  # noqa: E402
from reticle.context.baseline import RESOURCE_STATUS_PREFIX  # noqa: E402
from reticle.execution import ExecutionController, ExecutionRequest  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentLimits, ModelResponse  # noqa: E402
from reticle.tools.primitives import TOOL_SCHEMAS, TOOLSET_VERSION  # noqa: E402

HERE = Path(__file__).resolve().parent
# 2: fixture files are written as exact LF bytes; version 1 wrote them in text mode, which produced CRLF on Windows
# 3: fixture registry (u1, u2); per-fixture policy and budgets
RUNNER_VERSION = 3

U1_FILES = {
    "names/__init__.py": "",
    "names/core.py": (
        '"""Helpers for dotted names."""\n\n\n'
        "def split_parts(name):\n    return name.split(\".\")\n\n\n"
        "def first_component(name):\n    return split_parts(name)[0]\n\n\n"
        "def last_component(name):\n    parts = split_parts(name)\n"
        "    return parts[1] if len(parts) > 1 else parts[0]\n\n\n"
        "def parent_path(name):\n    return \".\".join(split_parts(name)[:-1])\n"
    ),
    "names/formatting.py": (
        '"""Display helpers."""\n\nfrom names.core import first_component, parent_path\n\n\n'
        "def quoted(name):\n    return '\"' + name + '\"'\n\n\n"
        "def describe(name):\n    parent = parent_path(name)\n"
        "    return f\"{first_component(name)} (in {parent})\" if parent else first_component(name)\n"
    ),
    "tests/test_names.py": (
        "from names.core import first_component, last_component, parent_path\n\n\n"
        "def test_first_component():\n    assert first_component(\"db.schema.table\") == \"db\"\n\n\n"
        "def test_last_component_three_parts():\n    assert last_component(\"db.schema.table\") == \"table\"\n\n\n"
        "def test_last_component_single():\n    assert last_component(\"solo\") == \"solo\"\n\n\n"
        "def test_parent_path():\n    assert parent_path(\"db.schema.table\") == \"db.schema\"\n"
    ),
}

U2_FILES = {
    "inventory/__init__.py": "",
    "inventory/pricing.py": (
        '"""Pricing helpers for order lines."""\n\nTAX_RATE = 0.08\n\n\n'
        "def subtotal(lines):\n    total = 0\n    for line in lines:\n"
        "        total += line[\"price\"] * line[\"qty\"]\n    return total\n\n\n"
        "def total_with_tax(lines):\n    total = 0\n    for line in lines:\n"
        "        total += line[\"price\"] * line[\"qty\"]\n    return round(total * (1 + TAX_RATE), 2)\n\n\n"
        "def apply_discount(amount, percent):\n"
        "    \"\"\"Reduce amount by percent (for example 10 means 10%).\"\"\"\n"
        "    return amount - amount * percent / 10\n\n\n"
        "def apply_coupon(amount, coupon):\n"
        "    \"\"\"Apply a coupon such as {\"code\": \"SPRING\", \"percent\": 20}.\"\"\"\n"
        "    percent = coupon[\"percent\"]\n"
        "    return amount - amount * percent / 10\n"
    ),
    "inventory/report.py": (
        '"""Order report formatting."""\n\nfrom inventory.pricing import apply_discount, subtotal\n\n\n'
        "def summary(lines, percent=0):\n    base = subtotal(lines)\n"
        "    return f\"subtotal={base:.2f} discounted={apply_discount(base, percent):.2f}\"\n"
    ),
    "docs/discounts.md": (
        "# Discounts\n\nA discount of `percent` reduces an amount by `amount * percent / 100`.\n"
        "Coupons carry a `percent` field and use the same rule.\n"
    ),
    "tests/test_pricing.py": (
        "from inventory.pricing import apply_discount, subtotal, total_with_tax\n\n"
        "LINES = [{\"price\": 10.0, \"qty\": 2}, {\"price\": 5.0, \"qty\": 1}]\n\n\n"
        "def test_subtotal():\n    assert subtotal(LINES) == 25.0\n\n\n"
        "def test_total_with_tax():\n    assert total_with_tax(LINES) == 27.0\n\n\n"
        "def test_discount_ten_percent():\n    assert apply_discount(200, 10) == 180\n"
    ),
}

FIXTURES = {
    "u1": {
        "name": "u1-dotted-name",
        "files": U1_FILES,
        "task": (
            "This workspace holds a small Python package, `names`. Reported problem: for a dotted name such as "
            "'db.schema.table', the function that should return the final component returns the second component "
            "instead ('schema' rather than 'table'). Find that function, fix it so it returns the last component (and "
            "the whole name when there is no dot), check your change with the tests (for example `pytest tests -q` "
            "with the run tool), and call finish. A hidden check runs on your final workspace."
        ),
        "hidden_check": (
            "from names.core import last_component as f; "
            "assert f('db.schema.table') == 'table'; assert f('a.b.c.d') == 'd'; assert f('solo') == 'solo'; "
            "print('hidden-check-passed')"
        ),
        "policy": PressureRecentContextPolicyV2,
        "gold": [
            ("replace_text", {"path": "names/core.py", "old_text": "return parts[1] if len(parts) > 1 else parts[0]",
                              "new_text": "return parts[-1]"}),
            ("run", {"command": "pytest tests -q"}),
        ],
        "budgets": {"model_responses": 8, "model_attempts": 10, "tool_actions": 16, "active_seconds": 180.0,
                    "cost_usd": 0.03},
        "context_bytes": 24_000,
    },
    "u2": {
        "name": "u2-discount-percent",
        "files": U2_FILES,
        "task": (
            "The `inventory` package applies percentage discounts ten times too strongly: a 10% discount on 200 "
            "yields 0 instead of 180. Every place that applies a percentage this way has the same defect; the "
            "documentation describes the intended rule. Fix the library, check it with the tests (for example "
            "`pytest tests -q` with the run tool), and call finish. A hidden check runs on your final workspace."
        ),
        "hidden_check": (
            "from inventory.pricing import apply_discount, apply_coupon, subtotal, total_with_tax; "
            "from inventory.report import summary; "
            "assert apply_discount(200, 10) == 180; assert apply_coupon(50, {'code': 'X', 'percent': 20}) == 40; "
            "assert subtotal([{'price': 10.0, 'qty': 2}]) == 20.0; "
            "assert total_with_tax([{'price': 10.0, 'qty': 2}, {'price': 5.0, 'qty': 1}]) == 27.0; "
            "assert summary([{'price': 200.0, 'qty': 1}], 10) == 'subtotal=200.00 discounted=180.00'; "
            "print('hidden-check-passed')"
        ),
        "policy": PressureRecentContextPolicyV3,
        "gold": [
            ("replace_text", {"path": "inventory/pricing.py", "old_text": "amount * percent / 10\n",
                              "new_text": "amount * percent / 100\n", "replace_all": True}),
            ("run", {"command": "pytest tests -q"}),
        ],
        "budgets": {"model_responses": 12, "model_attempts": 14, "tool_actions": 24, "active_seconds": 240.0,
                    "cost_usd": 0.05},
        "context_bytes": 32_000,
    },
}
SCRIPTED_RESERVATION_USD = 0.005
DECISION_RULE = (
    "pass iff the hidden check passes, every rejected tool call is followed by a non-rejected call of the same tool, "
    "and every model request contained the remaining-resources line; otherwise report which condition failed"
)


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class ScriptedClient:
    """gold: the fixture's fix, run the tests, finish. noop: finish."""

    def __init__(self, kind: str, gold_steps: list):
        self.kind, self.calls = kind, 0
        self.steps = ([] if kind == "noop" else list(gold_steps)) + [("finish", {"summary": f"{kind} client"})]

    def complete(self, messages, tools) -> ModelResponse:
        self.calls += 1
        name, arguments = self.steps[min(self.calls, len(self.steps)) - 1]
        return ModelResponse({"role": "assistant", "content": None,
                              "tool_calls": [_call(f"{self.kind}-{self.calls}", name, arguments)]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", default="u1", choices=sorted(FIXTURES))
    parser.add_argument("--client", required=True, choices=["openrouter", "gold", "noop"])
    parser.add_argument("--model")
    parser.add_argument("--provider", help="pin to one OpenRouter provider slug, no fallbacks")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--max-total-calls", type=int, help="HTTP attempts, retries included; required live")
    parser.add_argument("--max-tokens", type=int, default=4_096)
    parser.add_argument("--oci-image", default=run_pilot.DEFAULT_OCI_IMAGE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fixture = FIXTURES[args.fixture]
    context_bytes = fixture["context_bytes"]

    backend, execution = run_pilot.resolve_execution("oci", args.oci_image)
    live = args.client == "openrouter"
    routing, pricing, reservation = None, None, SCRIPTED_RESERVATION_USD
    attempts_cap = fixture["budgets"]["model_attempts"]
    if live:
        if not args.model or not args.provider:
            raise SystemExit("--model and --provider are required for the openrouter client")
        routing = {"order": [args.provider.lower()], "allow_fallbacks": False, "require_parameters": True}
        pricing = run_pilot.endpoint_pricing(args.model, args.provider.lower())
        if not pricing["tools"]:
            raise SystemExit(f"Pinned endpoint {args.provider} for {args.model} does not list tool support")
        worst = (context_bytes / 3 * pricing["prompt_usd_per_mtok"] + args.max_tokens * pricing["completion_usd_per_mtok"]) / 1e6
        reservation = math.ceil(worst * 1_000_000) / 1_000_000
        attempts = min(args.max_total_calls or attempts_cap, attempts_cap)
        print(f"{args.fixture} {args.model} @ {args.provider}: ${pricing['prompt_usd_per_mtok']:.3f}/M in, "
              f"${pricing['completion_usd_per_mtok']:.3f}/M out; reservation ${reservation:.6f}/attempt; at most "
              f"{fixture['budgets']['model_responses']} responses and {attempts} HTTP attempts; "
              f"worst case <= ${reservation * attempts:.4f}")
    budgets = {**fixture["budgets"], "model_attempt_cost_reservation": reservation, "context_bytes": context_bytes}
    policy = fixture["policy"]
    card = {
        "fixture": fixture["name"], "fixture_key": args.fixture, "runner_version": RUNNER_VERSION, "client": args.client,
        "model": args.model, "provider_routing": routing, "policy_version": policy.policy_version,
        "toolset_version": TOOLSET_VERSION,
        "tools_sha256": hashlib.sha256(json.dumps(TOOL_SCHEMAS, sort_keys=True).encode()).hexdigest(),
        "execution": execution, "budgets": budgets, "max_tokens": args.max_tokens, "temperature": 0,
        "max_total_calls": args.max_total_calls, "stop_on_repeats": True, "task": fixture["task"],
        "files": fixture["files"], "hidden_check": fixture["hidden_check"], "decision_rule": DECISION_RULE,
        "pricing_at_plan_time": pricing,
    }
    if args.dry_run:
        print(json.dumps({k: card[k] for k in ("fixture", "policy_version", "toolset_version", "budgets")}))
        return
    if live and not args.max_total_calls:
        raise SystemExit("--max-total-calls is required for live runs")
    api_key = run_pilot.load_openrouter_key() if live else None
    if live and not api_key:
        raise SystemExit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")

    run_dir = HERE / "u1_runs" / args.run_name
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; use a new --run-name")
    run_id = f"{fixture['name']}__{run_pilot.slug(args.model or args.client)}"
    session_root = run_dir / "sessions" / run_id
    workspace = session_root / "workspace"
    for relative, content in fixture["files"].items():
        (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
        (workspace / relative).write_bytes(content.encode("utf-8"))  # exact LF bytes on every platform
    card.update(source_revision=run_pilot.source_revision(), started_at=run_pilot.utc_now())
    (run_dir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    runtime = LocalRuntime(session_root / "session", workspace)
    initial_revision = runtime.workspace.revision()
    tools = run_pilot.RepeatGuardTools(runtime, interpreter="python", backend=backend,
                                       environment={"PYTHONPATH": "/workspace", "PYTHONIOENCODING": "utf-8"})
    calls_path = run_dir / "calls.jsonl"
    inner = (run_pilot.OpenRouterClient(api_key, args.model, calls_path, run_id,
                                        run_pilot.CallBudget(args.max_total_calls, 0), args.max_tokens, routing)
             if live else ScriptedClient(args.client, fixture["gold"]))
    client = run_pilot.GuardedClient(inner, tools, stop_on_repeats=True)
    envelope = TaskEnvelope(
        task_id=fixture["name"], description=fixture["task"],
        criteria=[{"id": "hidden-check", "kind": "executable", "visibility": "hidden"}],
        authority={"filesystem": "task workspace", "execution": execution["authority"], "network": "not provided"},
        budgets=budgets,
    )
    started = time.time()
    invocations = run_pilot.run_invocations(
        runtime, envelope, tools, client, AgentLimits(fixture["budgets"]["model_responses"], context_bytes), policy)
    agent = invocations[-1]
    elapsed = round(time.time() - started, 1)

    check = ExecutionController(runtime, backend).execute(ExecutionRequest(
        ["python", "-c", fixture["hidden_check"]], workspace, timeout_seconds=60,
        environment={"PYTHONPATH": "/workspace"}, mutates_workspace=False))
    passed = check.execution.status == "success" and b"hidden-check-passed" in check.execution.stdout

    manifests = [e.payload["manifest"] for e in runtime.journal.read_all() if e.kind == "context_manifest"]
    with_status = sum(
        1 for manifest in manifests
        if RESOURCE_STATUS_PREFIX in runtime.artifacts.read(manifest["materialized_request_artifact_id"]).decode("utf-8")
    )
    actions = interface_friction.actions_from_session(session_root / "session", calls_path)
    friction = interface_friction.summarize_actions(actions, set(fixture["files"]))
    recovered = all(turns is not None for turns in friction["recovery_turns"])
    record = {
        "time": run_pilot.utc_now(), "run_id": run_id, "fixture": fixture["name"], "client": args.client,
        "model": args.model, "stop": run_pilot.guard_stop_label(agent), "agent": agent,
        "hidden_check": {"status": check.execution.status, "exit_code": check.execution.exit_code,
                         "stdout": check.execution.stdout.decode("utf-8", "replace")[-500:],
                         "stderr": check.execution.stderr.decode("utf-8", "replace")[-800:]},
        "accepted": passed, "requests": len(manifests), "requests_with_resource_status": with_status,
        "all_rejections_recovered": recovered, "friction": friction,
        "workspace_changed": runtime.workspace.revision() != initial_revision,
        "http_attempts": len(run_pilot.read_jsonl(calls_path)),
        "reported_cost_usd": (agent.get("usage_reported") or {}).get("cost") if live else None,
        "elapsed_s": elapsed,
        "decision": {"pass": passed and recovered and with_status == len(manifests),
                     "hidden_check": passed, "rejections_recovered": recovered,
                     "status_in_every_request": with_status == len(manifests)},
    }
    run_pilot.append_jsonl(run_dir / "results.jsonl", record)
    print(json.dumps({k: record[k] for k in ("stop", "accepted", "requests", "requests_with_resource_status",
                                              "all_rejections_recovered", "http_attempts", "reported_cost_usd",
                                              "elapsed_s", "decision")}, indent=1))
    print(json.dumps(friction))


if __name__ == "__main__":
    main()
