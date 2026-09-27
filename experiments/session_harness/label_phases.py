"""Label every assistant response of recorded runs two ways, rules and Claude, and measure their agreement.

Rules: `weakness_mining.label_trajectory`. Claude: the local CLI in headless mode (subscription login, no API key,
no tools, no settings), one call per response, with the fixed system prompt `labels/claude_phase_prompt.md` and a
user message holding the task statement, a one-line summary of each earlier response, and the response's text,
calls, and results. Calls are serialised and run under the shared live-run lock
(`.runtime/locks/live-run.lock` in the main checkout), so they never overlap a live harness run.

`label` appends one record per response to the labels file and skips responses already labelled, so an
interrupted pass resumes. `agreement` prints per-phase agreement between the rules and Claude and, where gold labels
exist, each method's agreement with them, then every disagreement.

Usage:
  python experiments/session_harness/label_phases.py label RUN_DIR [RUN_DIR ...] [--labels FILE] [--model sonnet]
  python experiments/session_harness/label_phases.py agreement [--labels FILE]
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, Iterator, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import weakness_mining as wm  # noqa: E402
from claude_cli import ISOLATION_ARGUMENTS, child_environment, resolve_executable  # noqa: E402

LABELS = HERE / "labels" / "labels.jsonl"
PROMPT = HERE / "labels" / "claude_phase_prompt.md"
RESULT_CHARS, ARGUMENT_CHARS, STATEMENT_CHARS = 1500, 1500, 1500


def _short(value: str, limit: int) -> str:
    value = value.replace("\r\n", "\n")
    return value if len(value) <= limit else value[:limit] + f"... [{len(value) - limit} more chars]"


def _summary_arguments(arguments) -> str:
    if isinstance(arguments, dict):
        arguments = {key: (_short(value, 60) if isinstance(value, str) else value) for key, value in arguments.items()}
    return _short(json.dumps(arguments, ensure_ascii=False), 160)


def render_request(trajectory: wm.Trajectory, response: wm.Response) -> str:
    history = []
    for earlier in trajectory.responses[:response.index - 1]:
        parts = [f"{call.tool} {_summary_arguments(call.arguments)} -> {call.status}: "
                 f"{_short((call.content.strip().splitlines() or [''])[0], 80)}" for call in earlier.calls]
        history.append(f"#{earlier.index} " + ("; ".join(parts) if parts else "(no tool call) "
                                                + _short(earlier.text.strip(), 120)))
    calls = []
    for number, call in enumerate(response.calls, 1):
        calls.append(f"[{number}] {call.tool} {_short(json.dumps(call.arguments, ensure_ascii=False), ARGUMENT_CHARS)}\n"
                     f"    result ({call.status}):\n{_short(call.content, RESULT_CHARS)}")
    return "\n".join([
        "Task statement:", _short(trajectory.statement.strip(), STATEMENT_CHARS), "",
        "Earlier responses in this run:", *(history or ["(none)"]), "",
        f"Response to label: {response.index} of {len(trajectory.responses)}", "",
        "Text:", response.text.strip() or "(no text)", "",
        "Tool calls and results:", *(calls or ["(no tool call)"]),
    ])


def parse_reply(text: str) -> Dict[str, str]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    value = json.loads(match.group(0))
    phase = str(value.get("phase", "")).strip().lower()
    if phase not in wm.PHASES:
        raise ValueError(f"unknown phase {phase!r}")
    return {"phase": phase, "mechanism": str(value.get("mechanism", "")).strip()}


def ask_claude(request: str, model: str, workdir: Path, timeout: int = 300) -> Dict[str, object]:
    executable = resolve_executable("claude")
    if executable is None:
        raise SystemExit("claude is not on PATH")
    arguments = [executable, "-p", "--model", model, "--output-format", "json", "--max-turns", "1",
                 *ISOLATION_ARGUMENTS, "--system-prompt-file", str(PROMPT)]
    environment, _ = child_environment()
    last_error = ""
    for attempt in (1, 2):
        started = time.time()
        try:
            completed = subprocess.run(arguments, input=request.encode("utf-8"), capture_output=True,
                                       cwd=str(workdir), env=environment, timeout=timeout)
            output = json.loads(completed.stdout.decode("utf-8", errors="replace"))
            reply = parse_reply(output.get("result") or "")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
            last_error = repr(exc)[:300]
            continue
        return {**reply, "model": sorted((output.get("modelUsage") or {}).keys()), "attempts": attempt,
                "latency_s": round(time.time() - started, 1),
                "cli_list_price_estimate_usd": output.get("total_cost_usd")}
    raise RuntimeError(f"labelling call failed twice: {last_error}")


def main_checkout() -> Path:
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


@contextmanager
def live_run_lock(owner: str, wait_seconds: float = 7200) -> Iterator[Path]:
    path = main_checkout() / ".runtime" / "locks" / "live-run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    token = json.dumps({"owner": owner, "pid": os.getpid(), "since": datetime.now(timezone.utc).isoformat()})
    deadline = time.time() + wait_seconds
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() > deadline:
                raise SystemExit(f"live-run lock still held after {wait_seconds} s: {path}")
            print(f"waiting for {path}: {path.read_text(encoding='utf-8', errors='replace')[:200]}", flush=True)
            time.sleep(30)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(token)
        break
    try:
        yield path
    finally:
        if path.exists() and path.read_text(encoding="utf-8") == token:
            path.unlink()


def read_labels(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def label(run_dirs: List[Path], labels_path: Path, model: str) -> None:
    done = {(r["run"], r["response"]) for r in read_labels(labels_path)
            if r.get("kind") == "response" and r.get("claude_phase")}
    prompt_sha = hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    workdir = Path(tempfile.mkdtemp(prefix="reticle-labelling-"))
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    with live_run_lock("s6b-mining: label_phases.py (Claude CLI labelling)"):
        for run_dir in run_dirs:
            trajectory = wm.load_run(run_dir)
            rules = wm.label_trajectory(trajectory)
            for response, rule_phase in zip(trajectory.responses, rules.phases):
                if (trajectory.run, response.index) in done:
                    continue
                request = render_request(trajectory, response)
                reply = ask_claude(request, model, workdir)
                record = {
                    "kind": "response", "run": trajectory.run, "task_id": trajectory.task_id,
                    "response": response.index, "rule_phase": rule_phase,
                    "claude_phase": reply["phase"], "claude_mechanism": reply["mechanism"],
                    "claude": {"cli_model": model, "model_ids": reply["model"], "attempts": reply["attempts"],
                               "latency_s": reply["latency_s"],
                               "cli_list_price_estimate_usd": reply["cli_list_price_estimate_usd"],
                               "prompt_sha256": prompt_sha,
                               "request_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest()},
                    "gold_phase": None, "gold_source": None, "note": None,
                }
                with labels_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"{trajectory.run} #{response.index}: rule={rule_phase} claude={reply['phase']} "
                      f"({reply['latency_s']} s) {reply['mechanism']}", flush=True)


def agreement_tables(records: List[dict]) -> str:
    rows = [r for r in records if r.get("kind") == "response" and r.get("claude_phase")]
    if not rows:
        return "no labelled responses"
    lines = [f"Responses: {len(rows)}; rule = Claude on {sum(r['rule_phase'] == r['claude_phase'] for r in rows)} "
             f"({100 * sum(r['rule_phase'] == r['claude_phase'] for r in rows) / len(rows):.1f}%); "
             f"Cohen's kappa {kappa([r['rule_phase'] for r in rows], [r['claude_phase'] for r in rows]):.2f}.", ""]
    gold = [r for r in rows if r.get("gold_phase")]
    header = "| Phase | Rule | Claude | Both | Specific agreement |"
    rule_line = "|---|---:|---:|---:|---:|"
    if gold:
        header += " Gold | Rule = gold | Claude = gold |"
        rule_line += "---:|---:|---:|"
    lines += [header, rule_line]
    for phase in wm.PHASES:
        n_rule = sum(r["rule_phase"] == phase for r in rows)
        n_claude = sum(r["claude_phase"] == phase for r in rows)
        both = sum(r["rule_phase"] == phase == r["claude_phase"] for r in rows)
        if not (n_rule or n_claude or any(r.get("gold_phase") == phase for r in gold)):
            continue
        specific = f"{2 * both / (n_rule + n_claude):.2f}" if n_rule + n_claude else "-"
        line = f"| {phase} | {n_rule} | {n_claude} | {both} | {specific} |"
        if gold:
            in_gold = [r for r in gold if r["gold_phase"] == phase]
            line += (f" {len(in_gold)} | {sum(r['rule_phase'] == phase for r in in_gold)} | "
                     f"{sum(r['claude_phase'] == phase for r in in_gold)} |")
        lines.append(line)
    if gold:
        lines += ["", f"Against gold ({len(gold)} responses): rules {sum(r['rule_phase'] == r['gold_phase'] for r in gold)}"
                  f"/{len(gold)}, Claude {sum(r['claude_phase'] == r['gold_phase'] for r in gold)}/{len(gold)}."]
    lines += ["", "| Run | # | Rule | Claude | Gold | Claude's mechanism | Adjudication note |", "|---|---:|---|---|---|---|---|"]
    for r in rows:
        if r["rule_phase"] != r["claude_phase"]:
            lines.append(f"| {r['run']} | {r['response']} | {r['rule_phase']} | {r['claude_phase']} | "
                         f"{r.get('gold_phase') or '-'} | {r['claude_mechanism']} | {r.get('note') or ''} |")
    return "\n".join(lines)


def kappa(first: List[str], second: List[str]) -> float:
    total = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / total
    counts_a, counts_b = Counter(first), Counter(second)
    expected = sum(counts_a[k] * counts_b[k] for k in set(first) | set(second)) / (total * total)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    label_parser = sub.add_parser("label")
    label_parser.add_argument("runs", nargs="+", type=Path)
    label_parser.add_argument("--labels", type=Path, default=LABELS)
    label_parser.add_argument("--model", default="sonnet")
    agreement_parser = sub.add_parser("agreement")
    agreement_parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args(argv)
    if args.command == "label":
        label(args.runs, args.labels, args.model)
    else:
        print(agreement_tables(read_labels(args.labels)))


if __name__ == "__main__":
    main()
