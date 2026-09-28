"""A stand-in for experiments/p6_pilot/run_pilot.py in tests/test_run_card.py: no model, no container.

It exposes the names run_card.RunnerAdapter reads (protocol_hash, resolve_execution, cli_contract, ...),
accepts the flags run_card emits, prints the protocol line on --dry-run, and otherwise writes
config.json, calls.jsonl, and results.jsonl under runs/<run-name>/ next to itself, as run_pilot.py does.

It follows run_pilot.py after S6a: --tasks [FILE.json] [TASK_ID ...], a task contract (here: tasks with a
mutation_patch) enters the protocol hash, and config.json records task_file and task_contracts.

Behaviour comes from the JSON file named by CARD_STUB_BEHAVIOUR:
  {"log": PATH, "attempts": N, "runs": {RUN_NAME: BEHAVIOUR}}
where BEHAVIOUR is accept (default for live clients and gold), reject (default for noop), model_error,
crash (exit 1, no record), silent (exit 0, no record), wrong_hash, over_budget, or model_pin (a model_error
whose error is a model_pin_violation), or a list of those used in turn by reruns of the same run name.
With "cost_per_attempt": X, each attempt record carries cli_result.total_cost_usd X; with "sleep_seconds": S,
each non-dry-run invocation first sleeps S seconds.
Each non-dry-run invocation appends its run name to PATH.
CARD_STUB_CLI_VERSION overrides the reported CLI version.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
RUNNER_VERSION = 1
TOOLSET_VERSION = "stub-tools-v1"
ARMS = {"stub-policy-a": object, "stub-policy-b": object}
CLI_MAX_TURNS = 1
CLI_TIMEOUT_SECONDS = 300
UNPINNED_ROUTING = {"require_parameters": True}
DEFAULT_OCI_IMAGE = "localhost/stub:1"


def cli_contract(model, *, max_turns, timeout, version):
    return {"client": "claude-cli", "cli_version": version, "model": model, "max_turns": max_turns,
            "timeout_seconds": timeout}


def cli_version():
    return os.environ.get("CARD_STUB_CLI_VERSION", "9.9.9 (stub)")


class IsolatedOCIBackend:
    def __init__(self, image, engine=None):
        self.image = image
        self.engine = engine or "podman"

    def availability(self):
        return True, "available"

    def user_arguments(self):
        return ["--userns", "keep-id"] if "podman" in self.engine else ["--user", "65534:65534"]


def resolve_execution(backend_name, image):
    if backend_name == "trusted-local":
        return None, {"backend": "trusted-local", "guest_python": "stub-python", "authority": "trusted-local"}
    engine = IsolatedOCIBackend(image).engine
    inspected = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", image],
                               capture_output=True, text=True)
    image_id = inspected.stdout.strip()
    backend = IsolatedOCIBackend(image_id, engine=engine)
    available, detail = backend.availability()
    if not available:
        raise SystemExit(detail)
    return backend, {"backend": "isolated-oci", "image": image, "image_id": image_id,
                     "container_user_arguments": backend.user_arguments()}


DEFAULT_TASK_FILE = HERE / "tasks.json"


def protocol_hash(arm, routing, execution, guards, task_contracts=()):
    inputs = {"runner_version": RUNNER_VERSION, "arm": arm, "provider_routing": routing, "execution": execution,
              "guards": guards, "toolset_version": TOOLSET_VERSION}
    if task_contracts:
        inputs["task_contracts"] = sorted(task_contracts, key=lambda contract: contract["task_id"])
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def load_tasks(selection=None):
    """--tasks [FILE.json] [TASK_ID ...], as run_pilot.py: a .json argument names the task file."""
    selection = list(selection or [])
    files = [item for item in selection if item.lower().endswith(".json")]
    path = Path(files[0]) if files else DEFAULT_TASK_FILE
    tasks = json.loads(path.read_text(encoding="utf-8"))["tasks"]
    wanted = [item for item in selection if item not in files]
    if wanted:
        tasks = [t for t in tasks if t["task_id"] in wanted]
    return path.resolve(), tasks


def task_file_record(path):
    return {"path": str(path), "sha256_lf": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def task_contract(task):
    if not task.get("mutation_patch"):
        return None
    return {"task_id": task["task_id"], "materializer": "stub-v1",
            "mutation_patch_sha256": hashlib.sha256(task["mutation_patch"].encode("utf-8")).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--backend", default="trusted-local", choices=["trusted-local", "oci"])
    parser.add_argument("--oci-image", default=DEFAULT_OCI_IMAGE)
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument("--max-calls-per-run", type=int, default=25)
    parser.add_argument("--max-context-bytes", type=int, default=80_000)
    parser.add_argument("--max-tokens", type=int, default=8_192)
    parser.add_argument("--max-total-calls", type=int, default=None)
    parser.add_argument("--pytest-timeout", type=int, default=600)
    parser.add_argument("--max-attempts-per-run", type=int, default=None)
    parser.add_argument("--max-tool-actions-per-run", type=int, default=None)
    parser.add_argument("--elapsed-cap-seconds", type=float, default=None)
    parser.add_argument("--cost-ceiling-usd", type=float, default=None)
    parser.add_argument("--attempt-cost-reservation-usd", type=float, default=None)
    parser.add_argument("--resume-after-provider-stop", type=int, default=0)
    parser.add_argument("--resume-wait-seconds", type=float, default=300.0)
    parser.add_argument("--stop-on-repeats", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    task_file, tasks = load_tasks(args.tasks)
    task_ids = [t["task_id"] for t in tasks]
    contracts = [c for c in (task_contract(t) for t in tasks) if c is not None]
    live = args.client in ("openrouter", "claude-cli")
    models = args.models if live else [f"{args.client}-client"]
    if args.client == "claude-cli":
        routing = {m: cli_contract(m, max_turns=CLI_MAX_TURNS, timeout=CLI_TIMEOUT_SECONDS, version=cli_version())
                   for m in models}
    else:
        routing = {m: dict(UNPINNED_ROUTING) for m in models}
    _, execution = resolve_execution(args.backend, args.oci_image)
    guards = {"stop_on_repeats": args.stop_on_repeats, "resume_after_provider_stop": args.resume_after_provider_stop,
              "resume_wait_seconds": args.resume_wait_seconds if args.resume_after_provider_stop else None}
    arm_hash = protocol_hash(args.arm, routing, execution, guards, contracts)

    behaviour_path = os.environ.get("CARD_STUB_BEHAVIOUR")
    behaviour = json.loads(Path(behaviour_path).read_text(encoding="utf-8")) if behaviour_path else {}
    default = "reject" if args.client == "noop" else "accept"
    mode = behaviour.get("runs", {}).get(args.run_name, default)
    if isinstance(mode, list):  # one entry per earlier invocation of this run name (a rerun in place)
        log = Path(behaviour["log"]) if behaviour.get("log") else None
        earlier = log.read_text(encoding="utf-8").split().count(args.run_name) if log and log.exists() else 0
        mode = mode[min(earlier, len(mode) - 1)] if not args.dry_run else default
    if mode == "wrong_hash":
        arm_hash = "deadbeef0000"
    print(f"{len(task_ids)} runs, arm {args.arm}, protocol {arm_hash}")
    if args.dry_run:
        return 0
    if behaviour.get("log"):
        with open(behaviour["log"], "a", encoding="utf-8") as handle:
            handle.write(args.run_name + "\n")
    if mode == "crash":
        return 1
    if behaviour.get("sleep_seconds"):
        import time
        time.sleep(behaviour["sleep_seconds"])

    budgets = {"model_responses": args.max_calls_per_run, "context_bytes": args.max_context_bytes}
    optional = {"model_attempts": args.max_attempts_per_run, "tool_actions": args.max_tool_actions_per_run,
                "active_seconds": args.elapsed_cap_seconds, "cost_usd": args.cost_ceiling_usd,
                "model_attempt_cost_reservation": args.attempt_cost_reservation_usd if args.cost_ceiling_usd else None}
    budgets.update({k: v for k, v in optional.items() if v is not None})
    config = {
        "runner_version": RUNNER_VERSION, "protocol_hash": arm_hash, "arm": args.arm, "client": args.client,
        "models": models, "provider_routing": routing, "tasks": task_ids, "max_calls_per_run": args.max_calls_per_run,
        "max_context_bytes": args.max_context_bytes, "max_tokens": args.max_tokens,
        "pytest_timeout_seconds": args.pytest_timeout, "max_total_calls": args.max_total_calls,
        "toolset_version": TOOLSET_VERSION, "execution": execution, "guards": guards,
        "budgets_per_run": {model: budgets for model in models},
        "task_file": task_file_record(task_file), "task_contracts": contracts,
    }
    run_dir = HERE / "runs" / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    if mode == "silent":
        return 0
    attempts = behaviour.get("attempts", 2) if live else 0
    for task_id in task_ids:
        with (run_dir / "calls.jsonl").open("a", encoding="utf-8") as handle:
            for index in range(attempts):
                row = {"run_id": task_id, "attempt": index + 1}
                if behaviour.get("cost_per_attempt") is not None:
                    row["cli_result"] = {"total_cost_usd": behaviour["cost_per_attempt"]}
                handle.write(json.dumps(row) + "\n")
        responses = args.max_calls_per_run + 1 if mode == "over_budget" else min(3, args.max_calls_per_run)
        accepted = mode in ("accept", "over_budget", "wrong_hash")
        stop = "model_error" if mode in ("model_error", "model_pin") else "finish_requested"
        error = {"model_error": "failed after 3 attempts: stub outage",
                 "model_pin": "model_pin_violation: requested 'claude-x', the CLI reported ['claude-y']"}.get(mode)
        record = {
            "run_id": f"{task_id}__{models[0]}", "task_id": task_id, "model": models[0], "client": args.client,
            "arm": args.arm, "protocol_hash": arm_hash, "stop": stop,
            "agent": {"stop_reason": stop, "error": error,
                      "task_resources": {"consumed": {"active_seconds": 1.5}},
                      "usage_reported": {"prompt_tokens": 100.0, "completion_tokens": 10.0}},
            "totals": {"model_calls": responses if live else 2, "provider_attempts": attempts, "tool_calls": 2},
            "acceptance": {"status": "accepted" if accepted else "rejected",
                           "criterion_outcomes": {"fail-to-pass": "pass" if accepted else "fail"}},
            "elapsed_s": 2.0,
        }
        with (run_dir / "results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
