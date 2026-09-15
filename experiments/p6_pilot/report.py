"""Build REPORT.md for one pilot run directory from its saved JSONL files only.

Usage: python experiments/p6_pilot/report.py experiments/p6_pilot/runs/<run-name>

Numbers only: per-run outcomes, calls, provider-reported tokens and cost, calls without
reported usage, paging and repeated tool calls, and provider errors. No conclusions are written.
"""

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

PAGING_TOOLS = {"read_output", "search_output"}


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


def tool_call_stats(calls):
    """Counts over model responses: paging calls, repeated identical calls, replies without tool calls."""
    seen, stats = Counter(), {"paging_calls": 0, "repeated_calls": 0, "no_tool_call_replies": 0}
    for call in calls:
        choices = (call.get("response") or {}).get("choices")
        if not choices:
            continue
        tool_calls = (choices[0].get("message") or {}).get("tool_calls") or []
        if not tool_calls:
            stats["no_tool_call_replies"] += 1
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name, arguments = function.get("name"), function.get("arguments") or ""
            try:
                arguments = json.dumps(json.loads(arguments), sort_keys=True)
            except (json.JSONDecodeError, TypeError):
                pass
            if name in PAGING_TOOLS:
                stats["paging_calls"] += 1
            if seen[(name, arguments)]:
                stats["repeated_calls"] += 1
            seen[(name, arguments)] += 1
    return stats


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
        f"- Arm: `{config['arm']}`; protocol `{config['protocol_hash']}`; runner v{config.get('runner_version')}; "
        f"source `{config['source_revision']}`",
        f"- Models: {', '.join(config['models'])}",
        f"- Provider routing: `{json.dumps(config.get('provider_routing', 'unpinned (not recorded)'))}`",
        f"- Tasks: {', '.join(config['tasks'])}",
        f"- Limits: {config['max_calls_per_run']} model calls/run, {config['max_context_bytes']} context bytes, "
        f"{config['max_tokens']} max output tokens, total HTTP attempt cap {config.get('max_total_calls')}",
        f"- Runs recorded: {len(results)} of {len(config['models']) * len(config['tasks'])} planned",
        "",
        "## Runs",
        "",
        "| task | model | stop | model calls | tool calls | acceptance | fail-to-pass | pass-to-pass | failing f2p/p2p | "
        "paging calls | repeated calls | no-tool replies | HTTP attempts | HTTP errors | prompt tok | completion tok | "
        "cost (reported) | missing usage |",
        "|---|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        calls = calls_by_run[result["run_id"]]
        usage, tools = usage_totals(calls), tool_call_stats(calls)
        agent, acceptance = result["agent"], result["acceptance"]
        criteria = acceptance.get("criteria") or {}
        failing = "/".join(str(len((criteria.get(name) or {}).get("failing", []))) for name in ("fail-to-pass", "pass-to-pass"))
        outcomes = acceptance["criterion_outcomes"]
        lines.append(
            f"| {result['task_id']} | {result['model']} | {agent.get('stop_reason')} | {agent.get('model_calls', '')} | "
            f"{agent.get('tool_calls', '')} | {acceptance['status']} | {outcomes.get('fail-to-pass')} | "
            f"{outcomes.get('pass-to-pass')} | {failing} | {tools['paging_calls']} | {tools['repeated_calls']} | "
            f"{tools['no_tool_call_replies']} | {usage['attempts']} | {usage['http_errors']} | "
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

    errors = [(c["run_id"], c.get("http_status"), (c.get("error") or json.dumps((c.get("response") or {}).get("error")))[:160])
              for calls in calls_by_run.values() for c in calls
              if "response" not in c or (c.get("response") or {}).get("error")]
    lines += ["", "## Provider errors (HTTP errors and error bodies)", ""]
    lines += [f"- {run_id}: HTTP {status}: {message}" for run_id, status, message in errors] or ["- none"]
    lines += ["", "Generated by `report.py` from config.json, calls.jsonl, and results.jsonl only.", ""]
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
