"""Replay a run's model requests and price them under provider prefix caching. No model calls.

Each request is compared with the previous one in provider render order: tool schemas first, then the
messages (Anthropic renders tools -> system -> messages; chat templates also put the schemas ahead of the
conversation). Per turn:

- bytes: the materialized request as the context manifest records it, the canonical JSON of
  {"messages", "tools"};
- LCP: the longest common byte prefix with the previous request, in render order;
- cacheable: the LCP rounded down to a unit boundary (the tool block is one unit, each message one);
- the leading messages identical to the previous request, the first differing message and the byte
  offset inside it, and every previous message that does not reappear byte-identical in this request;
- relative cost with tokens = bytes / 4 and an uncached input price of 1.0 per token:
  (a) no caching: tokens; (b) Anthropic-style 5-minute caching: 0.10 x cacheable tokens (read) plus
  1.25 x the remaining tokens (written, because each request is cached for the next one).

Idealised: a cache breakpoint sits at the read boundary (at most two explicit breakpoints in either
layout), no entry expires (the calls are seconds apart), and tokens are bytes / 4.

--policy selects where the requests come from:
  recorded            the bodies in calls.jsonl, as sent. Checked against request_sha256 and, when the
                      session is present, against the context manifests and the journal's call chain.
  pressure-recent-v2  rebuilt from the session journal with the package's policy class
  pressure-recent-v3  as above, with v3's status wording
  append-only         rebuilt from the journal: the opening, then every transcript unit rendered in full
                      and never reduced, omitted or reordered, then the resource status as the LAST message
--status-last moves a rebuilt pressure-recent request's status to the end, keeping its omissions and budget fit.

A rebuild copies sessions/<run_id>/session to a temporary directory, because building a context writes
request artifacts. Each turn's resource status is taken from the recorded request of the same call
(parsed back into the controller's status mapping), since the journal replay does not recompute
controller state; the rest of each request is rebuilt from the journal.

Usage: python experiments/session_harness/cache_replay.py RUN_DIR [--policy NAME] [--budget BYTES] [--status-last]
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.context import (  # noqa: E402
    PressureRecentContextPolicy,
    PressureRecentContextPolicyV2,
    PressureRecentContextPolicyV3,
    TranscriptStore,
    render_resource_status,
)
from reticle.context.baseline import RESOURCE_STATUS_PREFIX, _RESOURCE_LABELS, _encoded  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402

BYTES_PER_TOKEN = 4
READ_PRICE = 0.10   # cache read, relative to uncached input
WRITE_PRICE = 1.25  # 5-minute cache write, relative to uncached input
POLICIES = ("recorded", "pressure-recent-v2", "pressure-recent-v3", "append-only")


class AppendOnlyReplayPolicy(PressureRecentContextPolicy):
    """Replay-only layout: the pressure-recent opening and full unit rendering, but no older unit is
    ever reduced, omitted or reordered, and the per-turn resource status is the last message."""

    policy_version = "append-only-replay"
    renders_resource_status = True

    def __init__(self, labeled_limits: bool = False):
        super().__init__()
        self.labeled_limits = labeled_limits

    def build(self, runtime, task, transcript, tools, max_context_bytes, diagnostics=None, resource_status=None):
        messages, selected = self._opening(task)
        for index, unit in enumerate(self._paired_units(transcript)):
            rendered, items = self._render_unit(unit, index)
            messages.extend(rendered)
            selected.extend(items)
        text = render_resource_status(resource_status or {}, labeled_limits=self.labeled_limits)
        if text:
            messages.append({"role": "system", "content": text, "_context_id": "resource-status"})
            selected.append({"kind": "resource_status", "rendering": "full"})
        return self._record(runtime, task, messages, tools, max_context_bytes, selected, [], list(diagnostics or []))


# ---------------------------------------------------------------- prefix and message boundaries

def render_order(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Tuple[bytes, List[int]]:
    """The request with the tool block first, as providers render it for caching.

    Returns the bytes and the unit boundaries: 0, the end of the tool block, then the end of each
    message. The length equals the canonical {"messages", "tools"} JSON the manifests record."""
    head = b'{"tools":' + _encoded(tools) + b',"messages":['
    parts, boundaries = [head], [0, len(head)]
    for index, message in enumerate(messages):
        raw = (b"," if index else b"") + _encoded(message)
        parts.append(raw)
        boundaries.append(boundaries[-1] + len(raw))
    parts.append(b"]}")
    return b"".join(parts), boundaries


def common_prefix(a: bytes, b: bytes) -> int:
    limit, low, step = min(len(a), len(b)), 0, 1 << 12
    while step:
        while low + step <= limit and a[low:low + step] == b[low:low + step]:
            low += step
        step >>= 1
    return low


def cacheable_prefix(lcp: int, boundaries: List[int]) -> Tuple[int, int]:
    """The LCP rounded down to a unit boundary: (bytes, complete leading units; 1 = the tool block)."""
    units = bisect_right(boundaries, lcp) - 1
    return boundaries[units], units


def leading_identical(previous: List[Dict[str, Any]], current: List[Dict[str, Any]]) -> int:
    count = 0
    for old, new in zip(previous, current):
        if _encoded(old) != _encoded(new):
            break
        count += 1
    return count


def label(message: Dict[str, Any]) -> str:
    role, content = message.get("role"), message.get("content")
    text = content if isinstance(content, str) else ""
    if role == "system":
        for prefix, name in (("Reticle runtime contract", "contract"), (RESOURCE_STATUS_PREFIX, "status"),
                             ("Context pressure omitted", "omission-marker"), ("Pinned scratch", "pin"),
                             ("PIN OVERFLOW", "pin")):
            if text.startswith(prefix):
                return name
        return "system"
    if role == "assistant":
        names = [call.get("function", {}).get("name", "?") for call in message.get("tool_calls") or []]
        return f"assistant({','.join(names)})" if names else "assistant"
    return str(role)


@dataclass
class Turn:
    turn: int
    request_bytes: int
    messages: int
    lcp_bytes: int = 0
    cacheable_bytes: int = 0
    leading_messages: int = 0
    tools_identical: bool = False
    break_at: str = ""  # first differing message, with the byte offset inside it
    break_detail: str = ""
    not_reused: List[str] = field(default_factory=list)
    uncached_cost: float = 0.0
    cached_cost: float = 0.0
    over_budget: bool = False
    provider_cached_tokens: Optional[int] = None
    provider_prompt_tokens: Optional[int] = None

    @property
    def cached_fraction(self) -> float:
        return self.cacheable_bytes / self.request_bytes if self.request_bytes else 0.0


def price(request_bytes: int, cacheable_bytes: int) -> Tuple[float, float]:
    tokens, cached = request_bytes / BYTES_PER_TOKEN, cacheable_bytes / BYTES_PER_TOKEN
    return tokens, READ_PRICE * cached + WRITE_PRICE * (tokens - cached)


def analyse(requests: List[Dict[str, Any]]) -> List[Turn]:
    """requests: [{"messages", "tools", optional "over_budget", "usage"}] in dispatch order."""
    turns: List[Turn] = []
    previous: Optional[Tuple[bytes, List[Dict[str, Any]], List[Dict[str, Any]]]] = None
    for number, request in enumerate(requests, 1):
        messages, tools = request["messages"], request["tools"]
        raw, boundaries = render_order(messages, tools)
        if len(raw) != len(_encoded({"messages": messages, "tools": tools})):
            raise AssertionError("render-order bytes differ in length from the canonical request")
        turn = Turn(number, len(raw), len(messages), over_budget=bool(request.get("over_budget")))
        usage = request.get("usage") or {}
        if usage:
            turn.provider_prompt_tokens = usage.get("prompt_tokens")
            turn.provider_cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        if previous is not None:
            old_raw, old_messages, old_tools = previous
            turn.lcp_bytes = common_prefix(old_raw, raw)
            turn.cacheable_bytes, units = cacheable_prefix(turn.lcp_bytes, boundaries)
            turn.tools_identical = _encoded(old_tools) == _encoded(tools)
            turn.leading_messages = max(0, units - 1)
            if turn.tools_identical and turn.leading_messages != leading_identical(old_messages, messages):
                raise AssertionError("boundary rounding disagrees with the message comparison")
            turn.break_at, turn.break_detail = describe_break(old_raw, raw, turn.lcp_bytes, boundaries, units,
                                                              old_messages, messages)
            present = {_encoded(message) for message in messages}
            turn.not_reused = ([] if turn.tools_identical else ["tools"]) + [
                f"m{index} {label(message)}" for index, message in enumerate(old_messages)
                if _encoded(message) not in present
            ]
        turn.uncached_cost, turn.cached_cost = price(turn.request_bytes, turn.cacheable_bytes)
        turns.append(turn)
        previous = (raw, messages, tools)
    return turns


def describe_break(old_raw: bytes, raw: bytes, lcp: int, boundaries: List[int], units: int,
                   old_messages: List[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    def snippet(value: bytes) -> str:
        return json.dumps(value[max(0, lcp - 16):lcp + 24].decode("utf-8", errors="replace"), ensure_ascii=False)

    detail = f"prefix ends at byte {lcp}: previous {snippet(old_raw)} / this {snippet(raw)}"
    if units == 0:
        return f"tools +{lcp}", detail
    index = units - 1
    if index >= len(messages):
        return "none (request is a prefix of the previous one)", detail
    if index >= len(old_messages):
        return f"m{index} appended", detail
    start = boundaries[units] + (1 if index else 0)  # skip the separating comma
    old_label, new_label = label(old_messages[index]), label(messages[index])
    name = old_label if old_label == new_label else f"{old_label}->{new_label}"
    return f"m{index} {name} +{lcp - start}", detail


# ---------------------------------------------------------------- sources

def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def recorded_calls(run_dir: Path, run_id: Optional[str]) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """One entry per call index (the last attempt), in dispatch order, with body-hash checks."""
    rows = read_jsonl(run_dir / "calls.jsonl")
    run_ids = sorted({row["run_id"] for row in rows})
    if run_id is None:
        if len(run_ids) != 1:
            raise SystemExit(f"calls.jsonl holds runs {run_ids}; choose one with --run-id")
        run_id = run_ids[0]
    rows = [row for row in rows if row["run_id"] == run_id]
    by_call: Dict[int, Dict[str, Any]] = {}
    hashes_ok = 0
    for row in rows:
        body = row["request"]
        if hashlib.sha256(json.dumps(body, ensure_ascii=False).encode("utf-8")).hexdigest() == row["request_sha256"]:
            hashes_ok += 1
        by_call[row["call_index"]] = {**row, "attempts": by_call.get(row["call_index"], {}).get("attempts", 0) + 1}
    calls = [by_call[index] for index in sorted(by_call)]
    notes = [f"calls.jsonl: {len(rows)} attempts, {len(calls)} calls; request_sha256 recomputed from the "
             f"recorded body matches {hashes_ok}/{len(rows)}"]
    retried = [call["call_index"] for call in calls if call["attempts"] > 1]
    if retried:
        notes.append(f"calls with retries (priced once, last attempt): {retried}")
    return run_id, calls, notes


def session_dir(run_dir: Path, run_id: str) -> Path:
    return run_dir / "sessions" / run_id / "session"


def journal_links(events: List[Dict[str, Any]]) -> Tuple[List[Tuple[int, Dict[str, Any]]], Dict[str, int], Dict[int, set]]:
    """Manifests in order, manifest hash -> call index, call index -> dispatched body hashes."""
    manifests = [(event["sequence"], event["payload"]["manifest"]) for event in events if event["kind"] == "context_manifest"]
    call_of_hash: Dict[str, int] = {}
    attempt_call: Dict[str, int] = {}
    for event in events:
        if event["kind"] == "model_request_intent":
            call_of_hash[event["payload"]["request_hash"]] = event["payload"]["call_index"]
            attempt_call[event["payload"]["attempt_id"]] = event["payload"]["call_index"]
    bodies: Dict[int, set] = {}
    for event in events:
        if event["kind"] == "provider_attempt_started" and event["payload"].get("request_id") in attempt_call:
            call = attempt_call[event["payload"]["request_id"]]
            bodies.setdefault(call, set()).add((event["payload"].get("metadata") or {}).get("request_sha256"))
    return manifests, call_of_hash, bodies


def check_recorded_against_session(run_dir: Path, run_id: str, calls: List[Dict[str, Any]]) -> List[str]:
    events_path = session_dir(run_dir, run_id) / "events.jsonl"
    if not events_path.exists():
        return [f"no session journal at {events_path}: manifest checks skipped"]
    manifests, call_of_hash, bodies = journal_links(read_jsonl(events_path))  # read-only
    by_hash = {manifest["materialized_request_hash"]: manifest for _, manifest in manifests}
    hash_ok = bytes_ok = chain_ok = 0
    for call in calls:
        body = call["request"]
        materialized = _encoded({"messages": body["messages"], "tools": body["tools"]})
        digest = hashlib.sha256(materialized).hexdigest()
        manifest = by_hash.get(digest)
        hash_ok += manifest is not None
        bytes_ok += manifest is not None and manifest["request_bytes"] == len(materialized)
        chain_ok += (call_of_hash.get(digest) == call["call_index"]
                     and call["request_sha256"] in bodies.get(call["call_index"], set()))
    return [f"session manifests: {len(manifests)}; recorded body -> manifest hash {hash_ok}/{len(calls)}, "
            f"manifest request_bytes {bytes_ok}/{len(calls)}, journal chain manifest->call_index->request_sha256 "
            f"{chain_ok}/{len(calls)}"]


_STATUS_V2 = re.compile(r"^(?P<label>[^:]+): (?P<remaining>[-\d.]+) of (?P<limit>[-\d.]+)$")
_STATUS_V3 = re.compile(r"^(?P<label>[^:]+): (?P<remaining>[-\d.]+) remaining \(limit (?P<limit>[-\d.]+)\)"
                        r"(?:, after charging (?P<unknown>\d+) attempt\(s\) .*)?$")


def parse_resource_status(text: str) -> Tuple[Dict[str, Any], bool]:
    """Invert render_resource_status: (status mapping, labeled_limits)."""
    if not text.startswith(RESOURCE_STATUS_PREFIX):
        raise ValueError("not a resource status line")
    keys = {name: key for key, name, _ in _RESOURCE_LABELS}
    status: Dict[str, Any] = {}
    labeled = False
    for part in text[len(RESOURCE_STATUS_PREFIX):].rstrip(".").split("; "):
        if part.startswith("each model attempt first reserves $"):
            status["attempt_cost_reservation_usd"] = float(part.rsplit("$", 1)[1])
            continue
        match = _STATUS_V3.match(part)
        labeled = labeled or match is not None
        match = match or _STATUS_V2.match(part)
        if match is None or match["label"] not in keys:
            raise ValueError(f"unrecognised status part: {part!r}")
        status[keys[match["label"]]] = {"remaining": float(match["remaining"]), "limit": float(match["limit"])}
        if match.groupdict().get("unknown"):
            status["cost_unknown_billing_attempts"] = int(match["unknown"])
    return status, labeled


def recorded_status(body: Dict[str, Any]) -> Optional[str]:
    return next((m["content"] for m in body["messages"] if m.get("role") == "system"
                 and isinstance(m.get("content"), str) and m["content"].startswith(RESOURCE_STATUS_PREFIX)), None)


def move_status_last(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same messages with the resource status moved to the end (same bytes, so the same budget fit)."""
    status = [m for m in messages if label(m) == "status"]
    return [m for m in messages if label(m) != "status"] + status


def rebuilt_requests(run_dir: Path, run_id: str, calls: List[Dict[str, Any]], policy_name: str,
                     budget: int, recorded_budget: int, status_last: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
    source = session_dir(run_dir, run_id)
    if not (source / "events.jsonl").exists():
        raise SystemExit(f"--policy {policy_name} rebuilds from the session journal; {source} is missing")
    calls_by_index = {call["call_index"]: call for call in calls}
    with tempfile.TemporaryDirectory(prefix="cache-replay-") as temporary:
        copy, workspace = Path(temporary) / "session", Path(temporary) / "workspace"
        shutil.copytree(source, copy, ignore=shutil.ignore_patterns("writer.lock"))
        workspace.mkdir()
        configuration = json.loads((copy / "session.json").read_text(encoding="utf-8"))
        configuration["workspace_root"] = str(workspace)
        (copy / "session.json").write_text(json.dumps(configuration), encoding="utf-8")
        runtime = LocalRuntime(copy)
        events = [event.to_dict() for event in runtime.journal.read_all()]
        task = TaskEnvelope(**next(e["payload"]["task"] for e in events if e["kind"] == "task_contract"))
        manifests, call_of_hash, _ = journal_links(events)
        status_texts = [recorded_status(call["request"]) for call in calls]
        round_trip = sum(1 for text in status_texts if text is not None
                         and render_resource_status(*parse_resource_status(text)) == text)
        labeled = any(parse_resource_status(text)[1] for text in status_texts if text)
        if policy_name == "append-only":
            policy = AppendOnlyReplayPolicy(labeled_limits=labeled)
        else:
            policy = {"pressure-recent-v2": PressureRecentContextPolicyV2,
                      "pressure-recent-v3": PressureRecentContextPolicyV3}[policy_name]()
        store = TranscriptStore(runtime)
        requests: List[Dict[str, Any]] = []
        hash_ok = bytes_ok = same_messages = 0
        for sequence, manifest in manifests:
            call = calls_by_index.get(call_of_hash.get(manifest["materialized_request_hash"]))
            if call is None:
                continue  # the context was built but no provider request followed
            text = recorded_status(call["request"])
            status = None
            if text is not None:
                status = parse_resource_status(text)[0]
                if policy_name == "pressure-recent-v3":
                    earlier = [c for c in calls if c["call_index"] < call["call_index"]]
                    status["cost_unknown_billing_attempts"] = sum(
                        1 for c in earlier if ((c.get("response") or {}).get("usage") or {}).get("cost") is None)
            built = policy.build(runtime, task, store.load(as_of_sequence=sequence), manifest["selected_tool_schemas"],
                                 budget, resource_status=status)
            materialized = _encoded({"messages": built.messages, "tools": built.tools})
            hash_ok += hashlib.sha256(materialized).hexdigest() == manifest["materialized_request_hash"]
            bytes_ok += len(materialized) == manifest["request_bytes"]
            recorded = call["request"]
            same_messages += _encoded(built.messages) == _encoded(recorded["messages"])
            messages = move_status_last(built.messages) if status_last else built.messages
            requests.append({"messages": messages, "tools": built.tools, "over_budget": built.over_budget,
                             "omitted_units": len(built.manifest.omitted_items)})
    expected = policy_name == "pressure-recent-v2" and budget == recorded_budget  # rebuilt before any move
    notes = [
        f"rebuilt {len(requests)} requests with {policy.policy_version} at budget {budget} "
        f"(run: {recorded_budget}) from a temporary copy of {source.relative_to(run_dir).as_posix()}",
        f"status lines re-rendered identically after parsing: {round_trip}/{sum(t is not None for t in status_texts)}",
        f"rebuilt vs session manifests: hash {hash_ok}/{len(requests)}, request_bytes {bytes_ok}/{len(requests)}; "
        f"messages identical to the recorded request {same_messages}/{len(requests)}"
        + ("" if expected else " (differences are expected: this is not the run's policy and budget)")
        + (" (checked before the status move)" if status_last else ""),
    ]
    omitted = [r["omitted_units"] for r in requests]
    if any(omitted):
        notes.append(f"transcript units omitted per turn: {omitted}")
    return requests, notes


# ---------------------------------------------------------------- report

def table(turns: List[Turn], show_provider: bool) -> str:
    header = ["#", "bytes", "LCP", "cacheable", "same lead msgs", "first break (msg, byte in msg)",
              "previous msgs not reused", "cost no cache", "cost cached", "cached %"]
    if show_provider:
        header.append("provider cached / prompt tok")
    lines = ["| " + " | ".join(header) + " |", "|" + "---:|" * 5 + "---|---|" + "---:|" * (len(header) - 7)]
    for turn in turns:
        not_reused = ", ".join(turn.not_reused[:4]) + (f" (+{len(turn.not_reused) - 4})" if len(turn.not_reused) > 4 else "")
        cells = [str(turn.turn), f"{turn.request_bytes:,}" + (" (over)" if turn.over_budget else ""),
                 f"{turn.lcp_bytes:,}", f"{turn.cacheable_bytes:,}", str(turn.leading_messages),
                 turn.break_at or "(first request)", not_reused or "-", f"{turn.uncached_cost:,.0f}",
                 f"{turn.cached_cost:,.0f}", f"{100 * turn.cached_fraction:.1f}"]
        if show_provider:
            cells.append(f"{turn.provider_cached_tokens} / {turn.provider_prompt_tokens}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def totals(turns: List[Turn]) -> Dict[str, float]:
    request = sum(t.request_bytes for t in turns)
    cacheable = sum(t.cacheable_bytes for t in turns)
    uncached = sum(t.uncached_cost for t in turns)
    cached = sum(t.cached_cost for t in turns)
    return {"turns": len(turns), "request_bytes": request, "cacheable_bytes": cacheable,
            "cost_no_cache": uncached, "cost_cached": cached, "cached_over_uncached": cached / uncached if uncached else 0.0,
            "cached_fraction": cacheable / request if request else 0.0}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--policy", choices=POLICIES, default="recorded")
    parser.add_argument("--budget", type=int, help="context bytes for a rebuilt policy (default: the run's)")
    parser.add_argument("--status-last", action="store_true",
                        help="with a rebuilt pressure-recent policy, move its resource status to the end")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    config = json.loads((args.run_dir / "config.json").read_text(encoding="utf-8"))
    recorded_budget = int(config["max_context_bytes"])
    if args.policy == "recorded" and args.budget is not None:
        parser.error("--budget applies to rebuilt policies; recorded requests were built at the run's budget")
    if args.status_last and not args.policy.startswith("pressure-recent"):
        parser.error("--status-last applies to the rebuilt pressure-recent policies")
    run_id, calls, notes = recorded_calls(args.run_dir, args.run_id)
    if args.policy == "recorded":
        notes += check_recorded_against_session(args.run_dir, run_id, calls)
        requests = [{"messages": c["request"]["messages"], "tools": c["request"]["tools"],
                     "usage": (c.get("response") or {}).get("usage")} for c in calls]
        policy_label, budget = f"recorded ({config.get('arm')})", recorded_budget
    else:
        budget = args.budget or recorded_budget
        requests, rebuilt_notes = rebuilt_requests(args.run_dir, run_id, calls, args.policy, budget, recorded_budget,
                                                   status_last=args.status_last)
        notes += rebuilt_notes
        policy_label = args.policy + (" with the status moved last" if args.status_last else "")
    turns = analyse(requests)
    summary = totals(turns)
    print(f"# cache replay: {run_id}, policy {policy_label}, budget {budget}")
    print(f"tokens = bytes/{BYTES_PER_TOKEN}; uncached input 1.0/token; cache read {READ_PRICE}, write {WRITE_PRICE}; "
          "prefix in render order (tools, then messages), rounded down to a message boundary")
    for note in notes:
        print(f"- {note}")
    print()
    print(table(turns, show_provider=args.policy == "recorded"))
    print()
    print("Where each prefix ends:")
    for turn in turns[1:]:
        print(f"- turn {turn.turn}: {turn.break_at}; {turn.break_detail}")
    print()
    print(f"TOTAL {summary['turns']} turns: {summary['request_bytes']:,} bytes; cost no cache {summary['cost_no_cache']:,.0f}; "
          f"cost cached {summary['cost_cached']:,.0f} ({summary['cached_over_uncached']:.3f} x no cache); "
          f"cacheable fraction {100 * summary['cached_fraction']:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
