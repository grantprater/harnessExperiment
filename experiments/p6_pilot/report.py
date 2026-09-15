"""Build REPORT.md for one pilot run directory from its saved JSONL files only.

Usage: python experiments/p6_pilot/report.py experiments/p6_pilot/runs/<run-name>

Numbers only: per-run outcomes, calls, provider-reported tokens and cost, calls without
reported usage, and provider errors. No conclusions are written.
"""

from collections import defaultdict
import json
from pathlib import Path
import sys


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def usage_totals(calls):
    totals = {"attempts": 0, "http_errors": 0, "responses": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "reasoning_tokens": 0, "cost": 0.0, "responses_missing_usage": 0, "responses_missing_cost": 0}
    for call in calls:
        totals["attempts"] += 1
        if "response" not in call:
            totals["http_errors"] += 1
            continue
        totals["responses"] += 1
        usage = call["response"].get("usage")
        if not isinstance(usage, dict):
            totals["responses_missing_usage"] += 1
            totals["responses_missing_cost"] += 1
            continue
        totals["prompt_tokens"] += usage.get("prompt_tokens") or 0
        totals["completion_tokens"] += usage.get("completion_tokens") or 0
        totals["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        if isinstance(usage.get("cost"), (int, float)):
            totals["cost"] += usage["cost"]
        else:
            totals["responses_missing_cost"] += 1
    return totals


def main() -> None:
    run_dir = Path(sys.argv[1])
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    results = read_jsonl(run_dir / "results.jsonl")
    calls_by_run = defaultdict(list)
    for call in read_jsonl(run_dir / "calls.jsonl"):
        calls_by_run[call["run_id"]].append(call)

    lines = [
        f"# P6 pilot run: {run_dir.name}",
        "",
        f"- Arm: `{config['arm']}`; protocol `{config['protocol_hash']}`; source `{config['source_revision']}`",
        f"- Models: {', '.join(config['models'])}",
        f"- Tasks: {', '.join(config['tasks'])}",
        f"- Limits: {config['max_calls_per_run']} model calls/run, {config['max_context_bytes']} context bytes, "
        f"{config['max_tokens']} max output tokens, total HTTP attempt cap {config.get('max_total_calls')}",
        f"- Runs recorded: {len(results)} of {len(config['models']) * len(config['tasks'])} planned",
        "",
        "## Runs",
        "",
        "| task | model | stop | model calls | tool calls | acceptance | fail-to-pass | pass-to-pass | failing f2p/p2p | "
        "HTTP attempts | HTTP errors | prompt tok | completion tok | cost (reported) | missing usage |",
        "|---|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        usage = usage_totals(calls_by_run[result["run_id"]])
        agent, acceptance = result["agent"], result["acceptance"]
        criteria = acceptance.get("criteria") or {}
        failing = "/".join(str(len((criteria.get(name) or {}).get("failing", []))) for name in ("fail-to-pass", "pass-to-pass"))
        outcomes = acceptance["criterion_outcomes"]
        lines.append(
            f"| {result['task_id']} | {result['model']} | {agent.get('stop_reason')} | {agent.get('model_calls', '')} | "
            f"{agent.get('tool_calls', '')} | {acceptance['status']} | {outcomes.get('fail-to-pass')} | "
            f"{outcomes.get('pass-to-pass')} | {failing} | {usage['attempts']} | {usage['http_errors']} | "
            f"{usage['prompt_tokens']} | {usage['completion_tokens']} | ${usage['cost']:.4f} | "
            f"{usage['responses_missing_usage']} |"
        )

    lines += ["", "## Totals by model", "",
              "| model | runs | accepted | rejected | other | HTTP attempts | HTTP errors | prompt tok | completion tok | "
              "reasoning tok | cost (reported) | responses missing cost |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for model in config["models"]:
        model_results = [r for r in results if r["model"] == model]
        usage = usage_totals([c for r in model_results for c in calls_by_run[r["run_id"]]])
        statuses = [r["acceptance"]["status"] for r in model_results]
        lines.append(
            f"| {model} | {len(model_results)} | {statuses.count('accepted')} | {statuses.count('rejected')} | "
            f"{len(statuses) - statuses.count('accepted') - statuses.count('rejected')} | {usage['attempts']} | "
            f"{usage['http_errors']} | {usage['prompt_tokens']} | {usage['completion_tokens']} | "
            f"{usage['reasoning_tokens']} | ${usage['cost']:.4f} | {usage['responses_missing_cost']} |"
        )

    errors = [(c["run_id"], c.get("http_status"), (c.get("error") or "")[:160])
              for calls in calls_by_run.values() for c in calls if "response" not in c]
    lines += ["", "## Provider errors", ""]
    lines += [f"- {run_id}: HTTP {status}: {message}" for run_id, status, message in errors] or ["- none"]
    lines += ["", "Generated by `report.py` from config.json, calls.jsonl, and results.jsonl only.", ""]
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
