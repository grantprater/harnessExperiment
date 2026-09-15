"""E2 history retrieval: can a model discover and use evidence that has left its context?

Fixture `changed-file` (the plan's first E2 fixture), seeded through the real tools and journal:
the agent read service.cfg, service.cfg was then rewritten, and a large log read followed. Under
pressure-recent-v1 at the fixed context budget, the original read is omitted from the request.
The task asks for release_code as it was before the change.

Decision rule, fixed before any run: accepted iff answer.txt, stripped, equals the original value
exactly. A preflight aborts with zero model calls unless the first request is within budget, omits
earlier units, and does not contain the original value.

Isolation: file, note, output, and history tools only; `run` is removed from the schemas and
rejected if called. Every provider attempt is appended to calls.jsonl as it completes and the
attempt's outcome to results.jsonl.

Stops: model calls, HTTP attempts (--max-total-calls), elapsed time, reported cost, and a
diagnostic termination after three identical observation calls without a workspace change.

Clients:
  openrouter  live; requires --model and --max-total-calls
  gold        retrieves with search_history and writes the value it surfaced (pipeline check, no API)
  live-file   answers from the current service.cfg (must be rejected, no API)
  noop        finishes immediately (must be rejected, no API)

Usage (from the repo root):
  python experiments/session_harness/run_e2.py --client gold --run-name e2-gold
  python experiments/session_harness/run_e2.py --client openrouter --model qwen/qwen3.5-9b \\
      --provider venice --run-name e2-qwen --max-total-calls 12 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402  (OpenRouter client, attempt budget, pricing, raw-log helpers)
from reticle.context import PressureRecentContextPolicy, TranscriptStore  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError, ModelResponse  # noqa: E402
from reticle.tools import TOOL_SCHEMAS, ToolSuite  # noqa: E402
from reticle.tools.primitives import ToolOutcome  # noqa: E402

RUNNER_VERSION = 1
FIXTURE = "changed-file"
ORIGINAL_CODE = "K7Q-4821"
CHANGED_CODE = "K7Q-9035"
CODE_PATTERN = re.compile(r"K7Q-\d{4}")
CONFIG = "# billing-sync service configuration\nservice = billing-sync\nrelease_code = {code}\nregion = eu-west\n"
LOG = "".join(
    f"2026-09-14T12:{i // 60:02d}:{i % 60:02d}Z worker-{i % 7} processed batch {i:04d} status=ok\n"
    for i in range(400)
)
TASK = (
    "Earlier in this session you read service.cfg, and the file has since been changed. "
    "Write the value that release_code had before that change to answer.txt (the value only, "
    "nothing else), then call finish."
)
MAX_CONTEXT_BYTES = 12_000
MAX_MODEL_CALLS = 8
SEED = [
    ("seed-read-config", "read_file", {"path": "service.cfg"}),
    ("seed-update-config", "write_file", {"path": "service.cfg", "content": CONFIG.format(code=CHANGED_CODE)}),
    ("seed-read-log", "read_file", {"path": "logs/worker.log"}),
]
OBSERVATION_TOOLS = {
    "list_files", "read_file", "outline", "search", "read_output", "search_output",
    "history", "search_history", "read_artifact", "read_note",
}
RETRIEVAL_TOOLS = {"history", "search_history", "read_artifact", "read_output", "search_output"}
FIXTURE_SCHEMAS = [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] != "run"]


class FixtureTools(ToolSuite):
    """File, note, output, and history tools only; flags repeated identical observations."""

    def __init__(self, runtime: LocalRuntime):
        super().__init__(runtime, interpreter=sys.executable)
        self.seen: dict = {}
        self.diagnostic = None

    def schemas(self):
        return json.loads(json.dumps(FIXTURE_SCHEMAS))

    def _dispatch(self, name, arguments, call_id):
        if name == "run":
            return self._journaled(call_id, name, {"disabled": True}, lambda: ToolOutcome(
                "ERROR: run is not available in this fixture; use the file and history tools.", "rejected"))
        return super()._dispatch(name, arguments, call_id)

    def dispatch(self, name, arguments, call_id):
        outcome = super().dispatch(name, arguments, call_id)
        if name in OBSERVATION_TOOLS:
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed = arguments
            key = json.dumps([name, parsed, self.runtime.workspace.revision()], sort_keys=True, default=str)
            self.seen[key] = self.seen.get(key, 0) + 1
            if self.seen[key] >= 3 and self.diagnostic is None:
                self.diagnostic = f"three identical {name} calls without a workspace change"
        return outcome


class GuardedClient:
    """Applies the repetition, elapsed, cost, and attempt stops before each model call."""

    def __init__(self, inner, tools: FixtureTools, elapsed_cap_seconds: float, cost_ceiling_usd: float):
        self.inner, self.tools = inner, tools
        self.deadline = time.time() + elapsed_cap_seconds
        self.cost_ceiling, self.cost = cost_ceiling_usd, 0.0

    def complete(self, messages, tools) -> ModelResponse:
        if self.tools.diagnostic:
            raise ModelClientError(f"diagnostic_termination: {self.tools.diagnostic}")
        if time.time() > self.deadline:
            raise ModelClientError("elapsed_cap_reached")
        if self.cost >= self.cost_ceiling:
            raise ModelClientError(f"cost_ceiling_reached: ${self.cost:.4f}")
        try:
            response = self.inner.complete(messages, tools)
        except run_pilot.BudgetExceeded as exc:
            raise ModelClientError(f"attempt_cap_reached: {exc}") from None
        cost = (response.usage or {}).get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            self.cost += cost
        return response


def _call(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class ScriptedClient:
    """Pipeline checks. gold writes the original value only if its retrieval surfaced it."""

    def __init__(self, kind: str):
        self.kind, self.calls = kind, 0

    def complete(self, messages, tools) -> ModelResponse:
        self.calls += 1
        if self.kind == "noop" or self.calls >= 3:
            calls = [_call("finish", {"summary": f"{self.kind} scripted finish"}, f"{self.kind}-finish")]
        elif self.calls == 1:
            calls = ([_call("search_history", {"query": "release_code"}, "gold-search")] if self.kind == "gold"
                     else [_call("read_file", {"path": "service.cfg"}, "live-read")])
        else:
            latest = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "tool"), "")
            codes = CODE_PATTERN.findall(latest)
            if self.kind == "gold":
                value = ORIGINAL_CODE if ORIGINAL_CODE in codes else "NOT-FOUND"
            else:
                value = codes[-1] if codes else "NOT-FOUND"
            calls = [_call("write_file", {"path": "answer.txt", "content": value + "\n"}, f"{self.kind}-write")]
        return ModelResponse({"role": "assistant", "content": None, "tool_calls": calls})


def task_envelope() -> TaskEnvelope:
    return TaskEnvelope(
        "e2-changed-file", TASK,
        authority={"tools": "file, note, output, and history tools; no command execution"},
        budgets={"model_calls": MAX_MODEL_CALLS, "context_bytes": MAX_CONTEXT_BYTES},
    )


def build_fixture(root: Path):
    workspace = root / "workspace"
    (workspace / "logs").mkdir(parents=True)
    (workspace / "service.cfg").write_bytes(CONFIG.format(code=ORIGINAL_CODE).encode("utf-8"))
    (workspace / "logs" / "worker.log").write_bytes(LOG.encode("utf-8"))
    runtime = LocalRuntime(root / "session", workspace)
    tools = FixtureTools(runtime)
    transcript = TranscriptStore(runtime)
    for call_id, name, arguments in SEED:
        transcript.append({"role": "assistant", "content": None, "tool_calls": [_call(name, arguments, call_id)]})
        outcome = tools.dispatch(name, json.dumps(arguments), call_id)
        if outcome.status != "success":
            raise SystemExit(f"fixture seed {call_id} failed: {outcome.content[:300]}")
        transcript.append({"role": "tool", "tool_call_id": call_id, "content": outcome.content,
                           "_reticle_output": {"handle": outcome.handle, "tool": name, "status": outcome.status}})
    tools.seen.clear()
    return runtime, tools, transcript, workspace


def preflight(runtime: LocalRuntime, tools: FixtureTools, transcript: TranscriptStore, workspace: Path) -> dict:
    built = PressureRecentContextPolicy().build(
        runtime, task_envelope(), transcript.load(), tools.schemas(), MAX_CONTEXT_BYTES
    )
    request = runtime.artifacts.read(built.manifest.materialized_request_artifact_id)
    checks = {
        "within_budget": not built.over_budget,
        "earlier_units_omitted": bool(built.manifest.omitted_items),
        "original_value_absent_from_first_request": ORIGINAL_CODE.encode() not in request,
        "live_file_holds_changed_value": CHANGED_CODE in (workspace / "service.cfg").read_text(encoding="utf-8"),
    }
    return {"request_bytes": built.manifest.request_bytes, "omitted_items": built.manifest.omitted_items,
            "checks": checks, "passed": all(checks.values())}


def protocol_hash(routing: dict) -> str:
    return hashlib.sha256(json.dumps({
        "runner_version": RUNNER_VERSION, "fixture": FIXTURE, "task": TASK, "config": CONFIG,
        "codes": [ORIGINAL_CODE, CHANGED_CODE], "log_sha256": hashlib.sha256(LOG.encode()).hexdigest(),
        "seed": SEED, "tools": FIXTURE_SCHEMAS, "policy": PressureRecentContextPolicy.policy_version,
        "max_context_bytes": MAX_CONTEXT_BYTES, "max_model_calls": MAX_MODEL_CALLS, "routing": routing,
    }, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def grade(runtime: LocalRuntime, workspace: Path) -> dict:
    answer_path = workspace / "answer.txt"
    answer = answer_path.read_text(encoding="utf-8").strip() if answer_path.exists() else None
    if answer == ORIGINAL_CODE:
        outcome = "accepted"
    elif answer == CHANGED_CODE:
        outcome = "answered_changed_value"
    elif answer is None:
        outcome = "no_answer"
    else:
        outcome = "wrong_value"
    seeded = {call_id for call_id, _, _ in SEED}
    events = runtime.journal.read_all()
    tool_calls = [
        {
            "call_id": event.payload.get("call_id"),
            "tool": event.payload.get("tool"),
            "result_contains_original_value": ORIGINAL_CODE.encode() in runtime.artifacts.read(event.payload["artifact_id"]),
        }
        for event in events
        if event.kind == "tool_output" and event.payload.get("call_id") not in seeded
    ]
    requests = [
        {
            "call_index": event.payload.get("call_index"),
            "request_bytes": len(runtime.artifacts.read(event.payload["request_artifact_id"])),
            "contains_original_value": ORIGINAL_CODE.encode() in runtime.artifacts.read(event.payload["request_artifact_id"]),
        }
        for event in events
        if event.kind == "model_call"
    ]
    return {
        "answer": answer, "outcome": outcome, "accepted": outcome == "accepted",
        "tool_calls": tool_calls,
        "retrieval_calls": sum(1 for call in tool_calls if call["tool"] in RETRIEVAL_TOOLS),
        "requests": requests,
        "first_request_contains_original_value": bool(requests and requests[0]["contains_original_value"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client", required=True, choices=["openrouter", "gold", "live-file", "noop"])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--model")
    parser.add_argument("--provider", help="pin one OpenRouter provider, no fallbacks")
    parser.add_argument("--max-total-calls", type=int, help="HTTP attempts, retries included")
    parser.add_argument("--max-tokens", type=int, default=4_096)
    parser.add_argument("--elapsed-cap-seconds", type=float, default=900)
    parser.add_argument("--cost-ceiling-usd", type=float, default=0.25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    live = args.client == "openrouter"
    if live and not args.model:
        raise SystemExit("--model is required for the openrouter client")
    model = args.model if live else f"{args.client}-client"
    routing = {}
    if live:
        routing = ({"order": [args.provider.lower()], "allow_fallbacks": False, "require_parameters": True}
                   if args.provider else dict(run_pilot.UNPINNED_ROUTING))
    card = {
        "experiment": "E2", "fixture": FIXTURE, "runner_version": RUNNER_VERSION,
        "protocol_hash": protocol_hash(routing), "client": args.client, "model": model,
        "provider_routing": routing, "policy_version": PressureRecentContextPolicy.policy_version,
        "attempts": 1, "max_model_calls": MAX_MODEL_CALLS, "max_context_bytes": MAX_CONTEXT_BYTES,
        "max_tokens": args.max_tokens, "temperature": 0, "max_total_calls": args.max_total_calls,
        "max_attempts_per_call": run_pilot.MAX_ATTEMPTS, "elapsed_cap_seconds": args.elapsed_cap_seconds,
        "cost_ceiling_usd": args.cost_ceiling_usd,
        "decision_rule": "accepted iff answer.txt, stripped, equals the original release_code",
        "task": TASK,
    }

    scratch = Path(tempfile.mkdtemp(prefix="e2-preflight-"))
    try:
        card["preflight"] = preflight(*build_fixture(scratch))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(card["preflight"], indent=1))
    if not card["preflight"]["passed"]:
        raise SystemExit("Preflight failed; no model calls made.")

    api_key = None
    if live:
        pricing = (run_pilot.endpoint_pricing(model, args.provider.lower()) if args.provider
                   else run_pilot.model_pricing(run_pilot.fetch_catalog(), [model])[model])
        if args.provider and not pricing["tools"]:
            raise SystemExit(f"Pinned endpoint {args.provider} for {model} does not list tool support")
        card["pricing_at_plan_time"] = pricing
        attempts = args.max_total_calls or MAX_MODEL_CALLS * run_pilot.MAX_ATTEMPTS
        per_attempt = (MAX_CONTEXT_BYTES / 3 * pricing["prompt_usd_per_mtok"]
                       + args.max_tokens * pricing["completion_usd_per_mtok"]) / 1e6
        print(f"E2 {FIXTURE}, protocol {card['protocol_hash']}: 1 attempt with {model} "
              f"({'pinned to ' + args.provider if args.provider else 'unpinned routing'})")
        print(f"  <= {MAX_MODEL_CALLS} model calls, <= {attempts} HTTP attempts; "
              f"${pricing['prompt_usd_per_mtok']:.3f}/M in, ${pricing['completion_usd_per_mtok']:.3f}/M out; "
              f"worst case <= ${per_attempt * attempts:.4f}; stop at reported ${args.cost_ceiling_usd:.2f}")
        if args.dry_run:
            return
        if args.max_total_calls is None:
            raise SystemExit("--max-total-calls is required for live runs")
        api_key = run_pilot.load_openrouter_key()
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")
    elif args.dry_run:
        print(f"{args.client} client; no API calls")
        return

    run_dir = HERE / "e2_runs" / args.run_name
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; use a new --run-name")
    run_dir.mkdir(parents=True)
    card.update(source_revision=run_pilot.source_revision(), started_at=run_pilot.utc_now())
    (run_dir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    runtime, tools, _, workspace = build_fixture(run_dir)
    run_id = f"{FIXTURE}__{run_pilot.slug(model)}"
    inner = (run_pilot.OpenRouterClient(api_key, model, run_dir / "calls.jsonl", run_id,
                                        run_pilot.CallBudget(args.max_total_calls, 0), args.max_tokens, routing)
             if live else ScriptedClient(args.client))
    client = GuardedClient(inner, tools, args.elapsed_cap_seconds, args.cost_ceiling_usd)
    started = time.time()
    result = AgentController(
        runtime, task_envelope(), tools, client, AgentLimits(MAX_MODEL_CALLS, MAX_CONTEXT_BYTES),
        policy=PressureRecentContextPolicy(),
    ).run()
    error = result.error or ""
    stop = ("diagnostic_termination" if error.startswith("diagnostic_termination")
            else error.split(":", 1)[0] if error.endswith("_reached") or "_reached:" in error
            else result.stop_reason)
    record = {
        "time": run_pilot.utc_now(), "run_id": run_id, "protocol_hash": card["protocol_hash"],
        "client": args.client, "model": model, "stop": stop, "agent_result": result.to_dict(),
        "http_attempts": len(run_pilot.read_jsonl(run_dir / "calls.jsonl")),
        "reported_cost_usd": client.cost, "elapsed_s": round(time.time() - started, 1),
        **grade(runtime, workspace),
    }
    run_pilot.append_jsonl(run_dir / "results.jsonl", record)
    print(json.dumps({key: record[key] for key in (
        "outcome", "answer", "stop", "http_attempts", "reported_cost_usd", "retrieval_calls",
        "first_request_contains_original_value")} | {"model_calls": result.model_calls}, indent=1))


if __name__ == "__main__":
    main()
