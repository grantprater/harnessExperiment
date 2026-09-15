"""Provider endpoint reliability probe (live API calls; every request is logged as it completes).

Sends one recorded agent request (by default the first request of E3 run 1: task instructions,
the full runner tool schemas, temperature 0, max_tokens 4096) to each pinned endpoint, interleaved
in a seeded round-robin order. One HTTP attempt per request: no retries and no provider fallbacks.
An endpoint is dropped after three consecutive failures (plan section 5.3). The summary is built
from the saved calls.jsonl only.

Usage (from the repo root):
  python experiments/session_harness/probe_endpoints.py --run-name probe-1 \\
      --endpoint google/gemma-4-26b-a4b-it=cloudflare --endpoint mistralai/devstral-2512=mistral \\
      --rounds 8 --dry-run
  python experiments/session_harness/probe_endpoints.py --summarize probe-1
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402
from reticle.tools.primitives import LEGACY_TOOL_NAMES  # noqa: E402

HERE = Path(__file__).resolve().parent
PROBE_VERSION = 1
PROBES = HERE / "endpoint_probes"
REQUIRED_PARAMETERS = ("tools", "tool_choice", "temperature", "max_tokens")
DEFAULT_SOURCE = ROOT / "experiments" / "p6_pilot" / "runs" / "e3-sqlparse-gemma-deepinfra-1" / "calls.jsonl"
# Legacy names stay valid: the default probe request is a recorded request that offered them.
KNOWN_TOOLS = {schema["function"]["name"] for schema in run_pilot.TOOL_SCHEMAS} | set(LEGACY_TOOL_NAMES)
CONSECUTIVE_FAILURE_STOP = 3
DECISION_RULE = (
    "An endpoint is eligible iff every one of its planned requests was sent and returned HTTP 200 with at "
    "least one tool call whose name is a runner tool and whose arguments parse as a JSON object. "
    "Choosing among eligible endpoints is reported for review, not made by this script."
)


def endpoint_plan(model: str, slug: str, request_bytes: int, max_tokens: int) -> dict:
    """Price one pinned route from the live catalog. The worst case uses the most expensive
    matching endpoint that supports every parameter the request needs (require_parameters)."""
    with urllib.request.urlopen(f"{run_pilot.BASE_URL}/models/{model}/endpoints", timeout=60) as response:
        endpoints = json.load(response)["data"]["endpoints"]
    matching = [e for e in endpoints if (e.get("tag") or "").split("/", 1)[0] == slug]
    if not matching:
        raise SystemExit(f"No '{slug}' endpoint for {model}; tags: {[e.get('tag') for e in endpoints]}")
    compatible = [
        e for e in matching
        if all(parameter in (e.get("supported_parameters") or []) for parameter in REQUIRED_PARAMETERS)
    ]
    if not compatible:
        raise SystemExit(f"No '{slug}' endpoint for {model} supports {list(REQUIRED_PARAMETERS)}")
    prompt_price = max(float((e.get("pricing") or {}).get("prompt") or 0) * 1e6 for e in compatible)
    completion_price = max(float((e.get("pricing") or {}).get("completion") or 0) * 1e6 for e in compatible)
    return {
        "model": model,
        "slug": slug,
        "endpoint_tags": [e.get("tag") for e in compatible],
        "quantizations": sorted({str(e.get("quantization")) for e in compatible}),
        "status": [e.get("status") for e in compatible],
        "uptime_last_1d": [e.get("uptime_last_1d") for e in compatible],
        "prompt_usd_per_mtok_max": prompt_price,
        "completion_usd_per_mtok_max": completion_price,
        # Planning bound only (3 bytes per token); billing uses the reported usage.cost.
        "worst_case_usd_per_request": (request_bytes / 3 * prompt_price + max_tokens * completion_price) / 1e6,
    }


def classify(data: dict) -> tuple[str, object]:
    choices = data.get("choices") or []
    if data.get("error") or not choices:
        return "error_body", json.dumps(data.get("error") or data)[:300]
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        return "no_tool_call", choices[0].get("finish_reason")
    names = []
    for call in calls:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return "invalid_tool_arguments", function.get("name")
        if function.get("name") not in KNOWN_TOOLS or not isinstance(arguments, dict):
            return "invalid_tool_call", function.get("name")
        names.append(function["name"])
    return "valid_tool_call", ",".join(names)


def send(api_key: str, body: dict, timeout: int) -> dict:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    row: dict = {"request_sha256": hashlib.sha256(raw).hexdigest()}
    started = time.time()
    try:
        request = urllib.request.Request(f"{run_pilot.BASE_URL}/chat/completions", data=raw, method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        row.update(http_status=200, response=data)
        row["outcome"], row["detail"] = classify(data)
    except urllib.error.HTTPError as exc:
        row.update(http_status=exc.code, error=exc.read().decode("utf-8", errors="replace")[:2_000])
        row["outcome"], row["detail"] = f"http_{exc.code}", None
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        row.update(error=repr(exc))
        row["outcome"], row["detail"] = "network_or_parse_error", None
    row["latency_s"] = round(time.time() - started, 2)
    return row


def summarize(run_dir: Path) -> list[dict]:
    card = json.loads((run_dir / "card.json").read_text(encoding="utf-8"))
    rows = run_pilot.read_jsonl(run_dir / "calls.jsonl")
    summary = []
    for plan in card["endpoints"]:
        mine = [r for r in rows if r["model"] == plan["model"] and r["slug"] == plan["slug"]]
        outcomes = Counter(r["outcome"] for r in mine)
        latencies = sorted(r["latency_s"] for r in mine if r.get("http_status") == 200)
        costs = [((r.get("response") or {}).get("usage") or {}).get("cost") for r in mine]
        served = Counter(((r.get("response") or {}).get("provider") or "-") for r in mine if r.get("http_status") == 200)
        summary.append({
            "model": plan["model"], "slug": plan["slug"], "planned": card["rounds"], "sent": len(mine),
            "valid_tool_calls": outcomes.get("valid_tool_call", 0), "outcomes": dict(outcomes),
            "served_by": dict(served),
            "latency_median_s": statistics.median(latencies) if latencies else None,
            "latency_p90_s": latencies[int(0.9 * (len(latencies) - 1))] if latencies else None,
            "latency_max_s": latencies[-1] if latencies else None,
            "reported_cost_usd": round(sum(c for c in costs if isinstance(c, (int, float))), 6),
            "eligible": len(mine) == card["rounds"] and outcomes.get("valid_tool_call", 0) == card["rounds"],
        })
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("| model | route | sent/planned | valid tool calls | outcomes | served by | latency median / p90 / max s | reported cost | eligible |")
    print("|---|---|---|---|---|---|---|---|---|")
    for item in summary:
        print(f"| {item['model']} | {item['slug']} | {item['sent']}/{item['planned']} | {item['valid_tool_calls']} | "
              f"{json.dumps(item['outcomes'])} | {json.dumps(item['served_by'])} | {item['latency_median_s']} / "
              f"{item['latency_p90_s']} / {item['latency_max_s']} | ${item['reported_cost_usd']:.6f} | {item['eligible']} |")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name")
    parser.add_argument("--endpoint", action="append", default=[], metavar="MODEL=SLUG")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--spacing-seconds", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-requests", type=int, default=None, help="hard cap; required for live runs")
    parser.add_argument("--source-calls", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summarize", metavar="RUN_NAME")
    args = parser.parse_args()
    if args.summarize:
        summarize(PROBES / args.summarize)
        return
    if not args.run_name or not args.endpoint:
        raise SystemExit("--run-name and at least one --endpoint are required")

    source_request = run_pilot.read_jsonl(args.source_calls)[0]["request"]
    request_bytes = len(json.dumps(source_request, ensure_ascii=False).encode("utf-8"))
    plans = []
    for item in args.endpoint:
        model, _, slug = item.partition("=")
        if not model or not slug:
            raise SystemExit(f"--endpoint {item!r} must be MODEL=SLUG")
        plans.append(endpoint_plan(model, slug.lower(), request_bytes, source_request["max_tokens"]))
    planned = args.rounds * len(plans)
    worst = args.rounds * sum(plan["worst_case_usd_per_request"] for plan in plans)
    for plan in plans:
        print(f"{plan['model']} @ {plan['slug']} {plan['endpoint_tags']} quant={plan['quantizations']} "
              f"status={plan['status']} uptime_1d={plan['uptime_last_1d']} "
              f"max ${plan['prompt_usd_per_mtok_max']:.3f}/M in, ${plan['completion_usd_per_mtok_max']:.3f}/M out; "
              f"worst case <= ${plan['worst_case_usd_per_request']:.5f}/request")
    print(f"planned requests: {planned} ({args.rounds} rounds x {len(plans)} endpoints), one attempt each, "
          f"no fallbacks; worst case <= ${worst:.4f}; request {request_bytes} bytes, max_tokens {source_request['max_tokens']}")

    card = {
        "probe_version": PROBE_VERSION, "rounds": args.rounds, "spacing_seconds": args.spacing_seconds,
        "seed": args.seed, "timeout_seconds": args.timeout, "consecutive_failure_stop": CONSECUTIVE_FAILURE_STOP,
        "source_calls": str(args.source_calls.relative_to(ROOT)), "source_request": source_request,
        "source_request_sha256": hashlib.sha256(json.dumps(source_request, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "routing": {"allow_fallbacks": False, "require_parameters": True}, "endpoints": plans,
        "planned_requests": planned, "worst_case_usd": worst, "decision_rule": DECISION_RULE,
    }
    if args.dry_run:
        return
    if args.max_requests is None or args.max_requests < planned:
        raise SystemExit(f"--max-requests is required for live runs and must be >= {planned}")
    run_dir = PROBES / args.run_name
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; use a new --run-name")
    api_key = run_pilot.load_openrouter_key()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")
    run_dir.mkdir(parents=True)
    card.update(created_at=run_pilot.utc_now(), source_revision=run_pilot.source_revision(),
                max_requests=args.max_requests)
    (run_dir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    rng = random.Random(args.seed)
    consecutive = [0] * len(plans)
    stopped: set[int] = set()
    sent = 0
    for round_index in range(1, args.rounds + 1):
        order = list(range(len(plans)))
        rng.shuffle(order)
        for index in order:
            if index in stopped:
                continue
            if sent >= args.max_requests:
                raise SystemExit(f"--max-requests {args.max_requests} reached")
            plan = plans[index]
            body = dict(source_request, model=plan["model"], provider={
                "order": [plan["slug"]], "allow_fallbacks": False, "require_parameters": True})
            row = {"time": run_pilot.utc_now(), "round": round_index, "model": plan["model"], "slug": plan["slug"],
                   **send(api_key, body, args.timeout)}
            sent += 1
            run_pilot.append_jsonl(run_dir / "calls.jsonl", row)
            print(f"round {round_index} {plan['model']} @ {plan['slug']}: HTTP {row.get('http_status')} "
                  f"{row['outcome']} {row['detail']} {row['latency_s']}s", flush=True)
            if row["outcome"] == "valid_tool_call":
                consecutive[index] = 0
            else:
                consecutive[index] += 1
                if consecutive[index] >= CONSECUTIVE_FAILURE_STOP:
                    stopped.add(index)
                    print(f"  stopping {plan['model']} @ {plan['slug']} after {CONSECUTIVE_FAILURE_STOP} consecutive failures")
            time.sleep(args.spacing_seconds)
    summarize(run_dir)


if __name__ == "__main__":
    main()
