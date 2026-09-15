"""Diagnostic: replay one saved pilot request that produced an empty reply.

Question: does the empty reply (tool-call markup inside reasoning, nothing parsed) depend on
temperature or on the serving provider? The request body is copied exactly from the pilot's
calls.jsonl; only temperature and provider routing change. Conditions are interleaved
round-robin. One HTTP attempt per call, no retries, hard cap on total calls. Every call is
appended to calls.jsonl as it completes; the summary is computed from that file only.

Usage: python experiments/p6_pilot/diagnose_empty_reply.py [--dry-run]
"""

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_pilot import BASE_URL, load_openrouter_key  # noqa: E402

SOURCE = HERE / "runs" / "pilot1-transcript" / "calls.jsonl"
SOURCE_RUN, SOURCE_CALL, SOURCE_ATTEMPT = "tomlkit-549__qwen_qwen3.5-9b", 2, 1
OUT = HERE / "runs" / "diag-qwen-empty-reply"
TEMPERATURES = (0, 0.6)
PROVIDERS = ("siliconflow", "venice")
REPETITIONS = 5
MAX_CALLS = 20
MARKUP = re.compile(r"<tool_call>|<function=")


def classify(response: dict) -> str:
    message = (response.get("choices") or [{}])[0].get("message") or {}
    if message.get("tool_calls"):
        return "tool_calls_parsed"
    if MARKUP.search(message.get("reasoning") or ""):
        return "markup_in_reasoning_unparsed"
    if MARKUP.search(message.get("content") or ""):
        return "markup_in_content_unparsed"
    if (message.get("content") or "").strip():
        return "text_only"
    return "empty_other"


def summarize(rows):
    table = {}
    for row in rows:
        key = f"temperature={row['temperature']} provider={row['provider_requested']}"
        cell = table.setdefault(key, {})
        label = row["classification"]
        cell[label] = cell.get(label, 0) + 1
        served = f"served_by:{row.get('provider_served')}"
        cell[served] = cell.get(served, 0) + 1
    return table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = next(
        json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines()
        if (lambda r: r["run_id"] == SOURCE_RUN and r["call_index"] == SOURCE_CALL and r["attempt"] == SOURCE_ATTEMPT)(json.loads(line))
    )
    original = source["request"]
    print(f"source: {SOURCE_RUN} call {SOURCE_CALL}; original classification: {classify(source['response'])}; "
          f"original provider: {source['response'].get('provider')}")
    plan = [(t, p) for _ in range(REPETITIONS) for t in TEMPERATURES for p in PROVIDERS]
    print(f"planned calls: {len(plan)} (cap {MAX_CALLS})")
    if len(plan) > MAX_CALLS:
        raise SystemExit("plan exceeds cap")
    if args.dry_run:
        return

    OUT.mkdir(parents=True, exist_ok=True)
    calls_path = OUT / "calls.jsonl"
    if calls_path.exists():
        raise SystemExit(f"{calls_path} already exists; refusing to add calls to a completed diagnostic")
    (OUT / "config.json").write_text(json.dumps({
        "source": {"file": str(SOURCE.relative_to(HERE)), "run_id": SOURCE_RUN, "call_index": SOURCE_CALL,
                   "attempt": SOURCE_ATTEMPT, "request_sha256": source["request_sha256"]},
        "temperatures": TEMPERATURES, "providers": PROVIDERS, "repetitions": REPETITIONS, "max_calls": MAX_CALLS,
        "routing": {"allow_fallbacks": False, "require_parameters": True}, "retries": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")

    api_key = load_openrouter_key()
    rows = []
    for index, (temperature, provider) in enumerate(plan, 1):
        body = copy.deepcopy(original)
        body["temperature"] = temperature
        body["provider"] = {"order": [provider], "allow_fallbacks": False, "require_parameters": True}
        row = {"index": index, "temperature": temperature, "provider_requested": provider,
               "time": datetime.now(timezone.utc).isoformat()}
        started = time.time()
        try:
            request = urllib.request.Request(f"{BASE_URL}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                             method="POST", headers={"Authorization": f"Bearer {api_key}",
                                                                     "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.load(response)
            row["response"] = data
            row["provider_served"] = data.get("provider")
            row["classification"] = classify(data) if data.get("choices") else "error_in_body"
        except urllib.error.HTTPError as exc:
            row.update(http_status=exc.code, error=exc.read().decode("utf-8", "replace")[:1_000], classification="http_error")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            row.update(error=repr(exc), classification="transport_error")
        row["latency_s"] = round(time.time() - started, 2)
        with calls_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        usage = (row.get("response") or {}).get("usage") or {}
        print(f"{index:2d} T={temperature} {provider:11s} -> {row['classification']} "
              f"(served {row.get('provider_served')}, cost {usage.get('cost')})", flush=True)

    saved = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    total_cost = sum(((r.get("response") or {}).get("usage") or {}).get("cost") or 0 for r in saved)
    print(json.dumps({"calls": len(saved), "reported_cost_usd": round(total_cost, 6), "by_condition": summarize(saved)}, indent=2))


if __name__ == "__main__":
    main()
