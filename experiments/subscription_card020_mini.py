"""One-task, paired subscription integration slice of active card 020.

Controls gate the live runs. Each live arm keeps the card's 20-response budget,
with no inference retries. Execution is local OCI, not the original cloud VM.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "c020-subscription-mini-20261001"
OUTPUT = ROOT / "experiments" / "session_harness" / "subscription_mini" / PREFIX
TASK_FILE = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
TASK_HASH = "fa185723735d56e7ff6858b7188bd603ed8f2ee0170637273fcaa71038db1daa"
IMAGE = "localhost/reticle-p6-task:py313-v1"
IMAGE_ID = "8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b"
MODEL = "gpt-5.6-sol"


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def arguments(client, arm):
    name = f"{PREFIX}-001-r1-{arm}"
    args = [sys.executable, str(ROOT / "experiments/p6_pilot/run_pilot.py"),
            "--client", client, "--backend", "oci", "--oci-image", IMAGE,
            "--arm", "pressure-recent-v3", "--tasks", str(TASK_FILE), "sqlparse-mut-001",
            "--run-name", name, "--max-calls-per-run", "20", "--max-attempts-per-run", "20",
            "--elapsed-cap-seconds", "1200", "--max-context-bytes", "80000", "--pytest-timeout", "600"]
    if client == "chatgpt-subscription":
        args += ["--models", MODEL, "--max-total-calls", "20"]
    if arm != "incumbent":
        args += ["--oracle", "hidden-tests:3"]
    return name, args


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {"source_card": "E4-cloud-check-oracle-020", "purpose": "subscription integration check",
            "task": "sqlparse-mut-001", "rollouts": 1, "policy": "pressure-recent-v3",
            "model": MODEL, "client": "chatgpt-subscription", "task_file_sha256_lf": TASK_HASH,
            "image": IMAGE, "image_id": IMAGE_ID, "max_live_requests": 40,
            "differences_from_card020": ["one task, one rollout instead of eight tasks with two rollouts",
                "GPT-5.6-Sol via subscription Responses instead of Claude Sonnet 5 via CLI",
                "local network-isolated OCI instead of cloud VM trusted-local",
                "20 attempts per arm with no automatic inference retries instead of 24 attempts",
                "output-token cap unavailable on the subscription preview",
                "Claude-specific reply recovery omitted"],
            "arm_order": ["incumbent", "check-oracle"], "oracle_limit": 3,
            "acceptance": "original hidden fail-to-pass and pass-to-pass evaluator",
            "interpretation": "pipeline integration check; no treatment-effect or campaign claim"}
    existing = OUTPUT / "plan.json"
    if existing.exists() and json.loads(existing.read_text()) != plan:
        raise RuntimeError("Stored mini-run plan differs")
    save(existing, plan)
    state = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
             "completed": [], "current": None}
    try:
        actual_hash = hashlib.sha256(TASK_FILE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual_hash != TASK_HASH:
            raise RuntimeError("Mutation task bank differs from the source card")
        inspected = subprocess.check_output(["podman", "image", "inspect", "--format", "{{.Id}}", IMAGE], text=True).strip()
        if inspected != IMAGE_ID:
            raise RuntimeError("Task image differs from the pinned image")
        for client, arm, expected in [("gold", "gold", "accepted"), ("noop", "noop", "rejected"),
                                       ("chatgpt-subscription", "incumbent", None),
                                       ("chatgpt-subscription", "check-oracle", None)]:
            name, args = arguments(client, arm)
            state["current"] = name
            save(OUTPUT / "status.json", state)
            print("Starting " + name, flush=True)
            with (OUTPUT / (arm + ".log")).open("w", encoding="utf-8") as log:
                process = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            if process.returncode:
                raise RuntimeError(f"{arm} runner exited {process.returncode}; see {arm}.log")
            run_root = ROOT / "experiments/p6_pilot/runs" / name
            records = [json.loads(line) for line in (run_root / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
            if len(records) != 1:
                raise RuntimeError("Expected exactly one task result")
            record = records[0]
            status = record["acceptance"]["status"]
            if expected and status != expected:
                raise RuntimeError(f"{arm} control expected {expected}, got {status}")
            if status not in ("accepted", "rejected"):
                raise RuntimeError(f"{arm} evaluator did not return a usable decision: {status}")
            if record.get("totals", {}).get("provider_attempts", 0) > 20:
                raise RuntimeError("Attempt budget violation")
            if record["agent"].get("error"):
                raise RuntimeError(f"{arm} model/provider error; stopping before further requests")
            checks = (record.get("treatments", {}).get("oracle") or {}).get("results", [])
            state["completed"].append({"arm": arm, "acceptance": status, "stop": record["stop"],
                "responses": record["totals"]["model_calls"], "provider_attempts": record["totals"]["provider_attempts"],
                "tool_calls": record["totals"]["tool_calls"], "elapsed_s": record["elapsed_s"],
                "checks": checks, "reported_cost_usd": record.get("reported_cost_usd"), "run_dir": str(run_root)})
            save(OUTPUT / "status.json", state)
            print(f"{arm}: {status}", flush=True)
        state.update(status="completed", current=None, finished_at=datetime.now(timezone.utc).isoformat())
        rows = ["# Card 020 subscription mini-run", "", "Integration check: one task, one rollout per arm.", "",
                "| Arm | Accepted | Responses | Attempts | Tools | Seconds |", "|---|---|---:|---:|---:|---:|"]
        for row in state["completed"]:
            rows.append(f"| {row['arm']} | {row['acceptance']} | {row['responses']} | {row['provider_attempts']} | {row['tool_calls']} | {row['elapsed_s']} |")
        rows += ["", "See plan.json for protocol differences and status.json for check counts and evidence paths.",
                 "This small integration test does not estimate treatment effects or update card 020's campaign."]
        (OUTPUT / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    except Exception as exc:
        state.update(status="stopped", error=str(exc), finished_at=datetime.now(timezone.utc).isoformat())
        save(OUTPUT / "status.json", state)
        raise
    save(OUTPUT / "status.json", state)
    print("Completed; report: " + str(OUTPUT / "report.md"), flush=True)


if __name__ == "__main__":
    main()
