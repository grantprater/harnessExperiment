"""Label every assistant response of recorded runs by rules, Claude, or Jev, and measure their agreement.

Rules: `weakness_mining.label_trajectory`; `label --labeller rules` writes them to a file (one record per response
with the rule phase and the two rule facts Jev's yes/no questions are scored against, and one run record per run with
the run labels and the failure signature), rewriting the file since the rules are deterministic.

Claude (`--labeller claude`, the default): the local CLI in headless mode (subscription login, no API key, no
tools, no settings), one call per response, with the fixed system prompt `labels/claude_phase_prompt.md` and a user
message holding the task statement, a one-line summary of each earlier response, and the response's text, calls, and
results. Claude calls are serialised and run under the shared
live-run lock (`.runtime/locks/live-run.lock` in the main checkout), so they never overlap a live harness run.

Jev (`--labeller jev`, see `jev_labeller.py`): OpenRouter's decisions endpoint, one serialised call per response
with the same rendered user message as its state and three questions (phase, edited_existing_source,
verified_after_edit). It reads the key from `OPENROUTER_API_KEY` in the environment. Its records go to a separate
file, `labels/labels_jev.jsonl` by default, keyed by (run, response), so the held-out `labels.jsonl` is never
rewritten; each record also carries the rule-derived facts the two yes/no questions are scored against.

`label` (Claude or Jev) appends one record per response to the labels file and skips responses already labelled, so
an interrupted pass resumes. `agreement` prints per-phase agreement between the rules and Claude and, where gold labels
exist, each method's agreement with them, then every disagreement. `agreement --labeller jev` prints Jev against
gold, the rules, and Claude, its confidence calibration, the yes/no questions against the rule facts, cost and time,
and, given `--repeat`, the determinism of a second identical pass. `develop` compares Jev with the rules on a
development set that has no gold phases (card 007 and later): per-phase agreement and the confusion matrix, the yes/no
questions against the rule facts, every response whose Jev diagnose probability reaches a threshold (0.3 by default,
fixed before the card-007 pass), and, given an adjudicated diagnose file, Jev's diagnose precision and recall.

Usage:
  python experiments/session_harness/label_phases.py label RUN_DIR [RUN_DIR ...] [--labels FILE] [--model sonnet]
  python experiments/session_harness/label_phases.py label RUN_DIR [RUN_DIR ...] --labeller jev [--labels FILE]
  python experiments/session_harness/label_phases.py agreement [--labels FILE]
  python experiments/session_harness/label_phases.py agreement --labeller jev [--jev FILE] [--repeat FILE]
  python experiments/session_harness/label_phases.py label RUN_DIR [RUN_DIR ...] --labeller rules --labels FILE
  python experiments/session_harness/label_phases.py develop --rules FILE --jev FILE [--devset FILE] [--threshold 0.3]
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
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

import jev_labeller as jev  # noqa: E402
import weakness_mining as wm  # noqa: E402
from claude_cli import ISOLATION_ARGUMENTS, child_environment, resolve_executable  # noqa: E402

LABELS = HERE / "labels" / "labels.jsonl"
LABELS_JEV = HERE / "labels" / "labels_jev.jsonl"
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


def rule_facts(trajectory: wm.Trajectory) -> Dict[int, Dict[str, object]]:
    """Per response: the rule phase and the journal-derived answers to Jev's two yes/no questions."""
    rules = wm.label_trajectory(trajectory)
    edited = {edit["response"] for edit in rules.base_edits}
    return {response.index: {"rule_phase": phase, "rule_edited_existing_source": response.index in edited,
                             "rule_verified_after_edit": response.index in rules.verify_responses}
            for response, phase in zip(trajectory.responses, rules.phases)}


def label_rules(run_dirs: List[Path], labels_path: Path, task_files=wm.DEFAULT_TASK_FILES) -> None:
    """Write the rule labels of every response and the run labels of every run (the file is rewritten)."""
    gold = wm.load_gold_files(task_files)
    lines = []
    for run_dir in run_dirs:
        trajectory = wm.load_run(run_dir)
        for number, facts in rule_facts(trajectory).items():
            lines.append({"kind": "response", "run": trajectory.run, "task_id": trajectory.task_id,
                          "response": number, **facts})
        record = wm.analyse(trajectory, gold.get(trajectory.task_id))
        lines.append({"kind": "run", "run": trajectory.run, "task_id": trajectory.task_id,
                      "acceptance": record["acceptance"], "stop_class": record["stop_class"],
                      "rule": {key: record[key] for key in (
                          "first_edit_response", "verified_before_finish", "edit_in_gold_files", "edited_files",
                          "mechanism", "verifier_cause", "causal_status", "signature", "stuck_responses",
                          "refetch_calls", "rejected_calls")}})
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                           encoding="utf-8", newline="\n")
    print(f"{sum(line['kind'] == 'response' for line in lines)} responses and {len(run_dirs)} runs -> {labels_path}")


def jev_record(trajectory: wm.Trajectory, response: wm.Response, facts: Dict[str, object], request: str,
               reply: Dict[str, object], at: str) -> dict:
    return {
        "kind": "response", "run": trajectory.run, "task_id": trajectory.task_id, "response": response.index,
        **facts,
        "jev_phase": reply["phase"], "jev_probabilities": reply["probabilities"],
        "jev_confidence": reply["confidence"], "jev_edited_existing_source": reply["edited_existing_source"],
        "jev_verified_after_edit": reply["verified_after_edit"], "jev_cost": reply["cost"],
        "jev_model": reply["model"],
        "jev": {"endpoint": jev.ENDPOINT, "requested_model": jev.MODEL, "at": at, "attempts": reply["attempts"],
                "latency_s": reply["latency_s"], "input_tokens": reply["input_tokens"],
                "output_tokens": reply.get("output_tokens"),
                "questions_sha256": jev.QUESTIONS_SHA256,
                "request_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest()},
    }


def label_jev(run_dirs: List[Path], labels_path: Path, transport: jev.Transport = jev.post_json,
              key: Optional[str] = None) -> None:
    done = {(r["run"], r["response"]) for r in read_labels(labels_path) if r.get("kind") == "response"}
    key = key or jev.api_key()
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    started, calls, cost = time.time(), 0, 0.0
    for run_dir in run_dirs:
        trajectory = wm.load_run(run_dir)
        facts = rule_facts(trajectory)
        for response in trajectory.responses:
            if (trajectory.run, response.index) in done:
                continue
            request = render_request(trajectory, response)
            at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            reply = jev.ask(request, transport=transport, key=key)
            record = jev_record(trajectory, response, facts[response.index], request, reply, at)
            with labels_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            calls += reply["attempts"]
            cost += reply["cost"] or 0.0
            print(f"{trajectory.run} #{response.index}: rule={record['rule_phase']} jev={reply['phase']} "
                  f"(confidence {reply['confidence']}, edited {reply['edited_existing_source']:.2f}, "
                  f"verified {reply['verified_after_edit']:.2f}, {reply['latency_s']} s)", flush=True)
    print(f"{calls} calls, cost ${cost:.6f}, wall {time.time() - started:.1f} s", flush=True)


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


CONFIDENCE_BINS = (0.0, 0.5, 0.7, 0.9, 0.99, 1.0)  # fixed before any Jev reply was seen; the first bin includes 0
YES_NO = ("edited_existing_source", "verified_after_edit")


def _specific(first: List[str], second: List[str], phase: str) -> str:
    n_first, n_second = first.count(phase), second.count(phase)
    both = sum(a == phase == b for a, b in zip(first, second))
    return f"{2 * both / (n_first + n_second):.2f}" if n_first + n_second else "-"


def wilson_lower(successes: int, total: int, z: float = 1.96) -> Optional[float]:
    """Lower end of the Wilson 95% interval for a proportion (n/(n + z^2) when every case agrees)."""
    if not total:
        return None
    share = successes / total
    centre = share + z * z / (2 * total)
    margin = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total))
    return (centre - margin) / (1 + z * z / total)


def _wall_seconds(rows: List[dict]) -> float:
    times = sorted((datetime.fromisoformat(r["jev"]["at"]), r["jev"]["latency_s"]) for r in rows)
    return (times[-1][0] - times[0][0]).total_seconds() + times[-1][1]


def _top(probabilities: Dict[str, float], count: int = 2) -> str:
    ranked = sorted(probabilities.items(), key=lambda item: -item[1])[:count]
    return ", ".join(f"{phase} {value:.2f}" for phase, value in ranked)


def _confidence_bin(value: object) -> Optional[int]:
    if not isinstance(value, (int, float)):
        return None
    for number, (low, high) in enumerate(zip(CONFIDENCE_BINS, CONFIDENCE_BINS[1:])):
        if low < value <= high or (number == 0 and value == low):
            return number
    return None


def jev_agreement_tables(records: List[dict], jev_rows: List[dict], repeat_rows: Optional[List[dict]] = None,
                         threshold: float = 0.5) -> str:
    """Jev against gold, rules, and Claude on the responses present in both files; see the module docstring."""
    labelled = {(r["run"], r["response"]): r for r in records if r.get("kind") == "response"}
    rows = [{**labelled[(j["run"], j["response"])], **j} for j in jev_rows
            if j.get("kind") == "response" and (j["run"], j["response"]) in labelled]
    if not rows:
        return "no Jev-labelled responses that are also in the labels file"
    n = len(rows)
    columns = {name: [r.get(f"{name}_phase") for r in rows] for name in ("gold", "rule", "claude", "jev")}
    jev_phases = columns["jev"]

    def versus(name: str) -> str:
        same = sum(a == b for a, b in zip(jev_phases, columns[name]))
        return f"{same}/{n} ({100 * same / n:.1f}%), kappa {kappa(jev_phases, columns[name]):.2f}"

    lines = [f"Responses: {n}. Jev = gold {versus('gold')}; Jev = rules {versus('rule')}; "
             f"Jev = Claude {versus('claude')}. For reference: rules = gold "
             f"{sum(a == b for a, b in zip(columns['rule'], columns['gold']))}/{n}, Claude = gold "
             f"{sum(a == b for a, b in zip(columns['claude'], columns['gold']))}/{n}.", "",
             "| Phase | Gold | Rule | Claude | Jev | Jev = gold, of gold | 95% lower bound | Specific: Jev-gold | "
             "Jev-rule | Jev-Claude |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for phase in wm.PHASES:
        if not any(phase in column for column in columns.values()):
            continue
        in_gold = [j for j, g in zip(jev_phases, columns["gold"]) if g == phase]
        hits = sum(j == phase for j in in_gold)
        bound = wilson_lower(hits, len(in_gold))
        lines.append(f"| {phase} | {len(in_gold)} | {columns['rule'].count(phase)} | "
                     f"{columns['claude'].count(phase)} | {jev_phases.count(phase)} | {hits}/{len(in_gold)} | "
                     f"{'-' if bound is None else f'{bound:.2f}'} | "
                     f"{_specific(jev_phases, columns['gold'], phase)} | "
                     f"{_specific(jev_phases, columns['rule'], phase)} | "
                     f"{_specific(jev_phases, columns['claude'], phase)} |")

    differ = [r for r in rows if r["jev_phase"] != r.get("gold_phase")]
    lines += ["", "Every response where Jev differs from gold:" if differ else "Jev differs from gold on no response."]
    if differ:
        lines += ["", "| Run | # | Gold | Rule | Claude | Jev | Confidence | Top probabilities |",
                  "|---|---:|---|---|---|---|---:|---|"]
    for r in differ:
        lines.append(f"| {r['run']} | {r['response']} | {r.get('gold_phase')} | {r['rule_phase']} | "
                     f"{r.get('claude_phase')} | {r['jev_phase']} | {r['jev_confidence']} | "
                     f"{_top(r['jev_probabilities'])} |")

    diagnose_probability = [r["jev_probabilities"].get("diagnose", 0.0) for r in rows]
    lines += ["", f"`diagnose`: Jev chose it {jev_phases.count('diagnose')} times (Claude "
              f"{columns['claude'].count('diagnose')}, gold {columns['gold'].count('diagnose')}); Jev's diagnose "
              f"probability: mean {sum(diagnose_probability) / n:.3f}, max {max(diagnose_probability):.3f}.", "",
              "| Run | # (Claude said diagnose) | Gold | Jev | Jev's diagnose probability |", "|---|---:|---|---|---:|"]
    for r in rows:
        if r.get("claude_phase") == "diagnose":
            lines.append(f"| {r['run']} | {r['response']} | {r.get('gold_phase')} | {r['jev_phase']} | "
                         f"{r['jev_probabilities'].get('diagnose', 0.0):.3f} |")

    lines += ["", "Calibration of `jev_confidence` against gold (bins fixed in advance):", "",
              "| Confidence | Responses | Mean confidence | Jev = gold | Accuracy |", "|---|---:|---:|---:|---:|"]
    for number, (low, high) in enumerate(zip(CONFIDENCE_BINS, CONFIDENCE_BINS[1:])):
        members = [r for r in rows if _confidence_bin(r["jev_confidence"]) == number]
        label = f"[{low}, {high}]" if number == 0 else f"({low}, {high}]"
        if not members:
            lines.append(f"| {label} | 0 | - | - | - |")
            continue
        correct = sum(r["jev_phase"] == r.get("gold_phase") for r in members)
        lines.append(f"| {label} | {len(members)} | {sum(r['jev_confidence'] for r in members) / len(members):.3f} | "
                     f"{correct} | {correct / len(members):.2f} |")
    brier = sum(sum((r["jev_probabilities"].get(phase, 0.0) - (phase == r.get("gold_phase"))) ** 2
                    for phase in wm.PHASES) for r in rows) / n
    top_match = sum(r["jev_probabilities"] and isinstance(r["jev_confidence"], (int, float))
                    and abs(r["jev_confidence"] - max(r["jev_probabilities"].values())) < 1e-9 for r in rows)
    lines += ["", f"Multi-class Brier score against gold: {brier:.4f} (0 is perfect, 2 is the worst). "
              f"`jev_confidence` equals the top option's probability on {top_match}/{n} responses."]

    lines += ["", f"Yes/no questions against the rule-derived facts (yes = Jev's value >= {threshold}, "
              "fixed in advance):", "",
              "| Question | Rule yes | Jev yes when rule yes | Lowest Jev value when rule yes | Rule no | "
              "Jev yes when rule no | Highest Jev value when rule no |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in YES_NO:
        yes = [r[f"jev_{name}"] for r in rows if r[f"rule_{name}"]]
        no = [r[f"jev_{name}"] for r in rows if not r[f"rule_{name}"]]
        lines.append(f"| {name} | {len(yes)} | {sum(v >= threshold for v in yes)} | "
                     f"{f'{min(yes):.3f}' if yes else '-'} | {len(no)} | {sum(v >= threshold for v in no)} | "
                     f"{f'{max(no):.3f}' if no else '-'} |")
    misses = [r for r in rows if any((r[f"jev_{name}"] >= threshold) != bool(r[f"rule_{name}"]) for name in YES_NO)]
    if misses:
        lines += ["", "| Run | # | Rule phase | Jev phase | Jev edited | Rule edited | Jev verified | Rule verified |",
                  "|---|---:|---|---|---:|---|---:|---|"]
        for r in misses:
            lines.append(f"| {r['run']} | {r['response']} | {r['rule_phase']} | {r['jev_phase']} | "
                         f"{r['jev_edited_existing_source']:.3f} | {r['rule_edited_existing_source']} | "
                         f"{r['jev_verified_after_edit']:.3f} | {r['rule_verified_after_edit']} |")

    run_records = {r["run"]: r for r in records if r.get("kind") == "run"}
    lines += ["", "Run labels derived from Jev's per-response answers (first edit = first response with edited >= "
              "threshold; verified = verified >= threshold at or after Jev's last edit response):", "",
              "| Run | First edit: rule / adjudicated / Jev | Verified before finish: rule / adjudicated / Jev | "
              "Jev edit responses | Jev verify responses |", "|---|---|---|---|---|"]
    for run in dict.fromkeys(r["run"] for r in rows):
        mine = sorted((r for r in rows if r["run"] == run), key=lambda r: r["response"])
        edits = [r["response"] for r in mine if r["jev_edited_existing_source"] >= threshold]
        checks = [r["response"] for r in mine if r["jev_verified_after_edit"] >= threshold]
        verified = bool(edits) and any(number >= edits[-1] for number in checks)
        record = run_records.get(run) or {}
        rule, human = record.get("rule") or {}, record.get("human") or {}
        lines.append(f"| {run} | {rule.get('first_edit_response')} / {human.get('first_edit_response')} / "
                     f"{edits[0] if edits else None} | {rule.get('verified_before_finish')} / "
                     f"{human.get('verified_before_finish')} / {verified} | "
                     f"{', '.join(map(str, edits)) or '-'} | {', '.join(map(str, checks)) or '-'} |")

    passes = [("first", rows)]
    if repeat_rows:
        first = {(r["run"], r["response"]): r for r in rows}
        pairs = [(first[(r["run"], r["response"])], r) for r in repeat_rows
                 if r.get("kind") == "response" and (r["run"], r["response"]) in first]
        passes.append(("second", [second for _, second in pairs]))
        same_phase = sum(a["jev_phase"] == b["jev_phase"] for a, b in pairs)
        same_request = sum(a["jev"]["request_sha256"] == b["jev"]["request_sha256"]
                           and a["jev"]["questions_sha256"] == b["jev"]["questions_sha256"] for a, b in pairs)
        probability_gap = max(abs(a["jev_probabilities"].get(p, 0.0) - b["jev_probabilities"].get(p, 0.0))
                              for a, b in pairs for p in wm.PHASES)
        yes_no_gap = max(abs(a[f"jev_{name}"] - b[f"jev_{name}"]) for a, b in pairs for name in YES_NO)
        lines += ["", f"Determinism, second identical pass ({same_request}/{len(pairs)} with identical request and "
                  f"question hashes): identical phase {same_phase}/{len(pairs)} "
                  f"({100 * same_phase / len(pairs):.1f}%); identical confidence "
                  f"{sum(a['jev_confidence'] == b['jev_confidence'] for a, b in pairs)}/{len(pairs)}; largest "
                  f"phase-probability change {probability_gap:.4f}; largest yes/no change {yes_no_gap:.4f}; second "
                  f"pass = gold {sum(b['jev_phase'] == a.get('gold_phase') for a, b in pairs)}/{len(pairs)}."]
    lines += ["", "| Pass | Responses (attempts) | Cost (USD) | Input tokens | Sum of latencies (s) | Wall time (s) | "
              "Model |", "|---|---:|---:|---:|---:|---:|---|"]
    for name, members in passes:
        lines.append(f"| {name} | {len(members)} ({sum(r['jev']['attempts'] for r in members)}) | "
                     f"{sum(r['jev_cost'] or 0.0 for r in members):.6f} | "
                     f"{sum(r['jev']['input_tokens'] or 0 for r in members)} | "
                     f"{sum(r['jev']['latency_s'] for r in members):.1f} | {_wall_seconds(members):.1f} | "
                     f"{', '.join(sorted({str(r['jev_model']) for r in members}))} |")
    return "\n".join(lines)


DIAGNOSE_THRESHOLD = 0.3  # fixed before the card-007 Jev pass: flag a response for a human look at this probability


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} = {numerator / denominator:.2f}" if denominator else f"{numerator}/0"


def jev_development_tables(rule_rows: List[dict], jev_rows: List[dict], devset: Optional[List[dict]] = None,
                           diagnose_threshold: float = DIAGNOSE_THRESHOLD, threshold: float = 0.5) -> str:
    """Jev against the rules on a development set without gold phases; see the module docstring."""
    rules = {(r["run"], r["response"]): r for r in rule_rows if r.get("kind") == "response"}
    rows = [{**rules[(j["run"], j["response"])], **{k: v for k, v in j.items() if not k.startswith("rule_")}}
            for j in jev_rows if j.get("kind") == "response" and (j["run"], j["response"]) in rules]
    if not rows:
        return "no Jev-labelled responses that are also in the rules file"
    n = len(rows)
    rule, jev_phases = [r["rule_phase"] for r in rows], [r["jev_phase"] for r in rows]
    same = sum(a == b for a, b in zip(rule, jev_phases))
    present = [p for p in wm.PHASES if p in rule or p in jev_phases]
    lines = [f"Responses: {n} in {len({r['run'] for r in rows})} runs. Jev = rules {same}/{n} "
             f"({100 * same / n:.1f}%), Cohen's kappa {kappa(rule, jev_phases):.2f}.", "",
             "| Phase | Rule | Jev | Both | Jev = rule, of rule | Specific agreement |",
             "|---|---:|---:|---:|---:|---:|"]
    for phase in present:
        both = sum(a == phase == b for a, b in zip(rule, jev_phases))
        lines.append(f"| {phase} | {rule.count(phase)} | {jev_phases.count(phase)} | {both} | "
                     f"{both}/{rule.count(phase)} | {_specific(jev_phases, rule, phase)} |")
    lines += ["", "Confusion (rows: rule phase; columns: Jev phase):", "",
              "| Rule \\ Jev | " + " | ".join(present) + " |", "|---|" + "---:|" * len(present)]
    for phase in present:
        lines.append(f"| {phase} | " + " | ".join(
            str(sum(a == phase and b == other for a, b in zip(rule, jev_phases))) for other in present) + " |")

    lines += ["", f"Yes/no questions against the rule facts (yes = Jev's value >= {threshold}):", "",
              "| Question | Rule yes | Jev yes when rule yes | Lowest Jev value when rule yes | Rule no | "
              "Jev yes when rule no | Highest Jev value when rule no |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in YES_NO:
        yes = [r[f"jev_{name}"] for r in rows if r[f"rule_{name}"]]
        no = [r[f"jev_{name}"] for r in rows if not r[f"rule_{name}"]]
        lines.append(f"| {name} | {len(yes)} | {sum(v >= threshold for v in yes)} | "
                     f"{f'{min(yes):.3f}' if yes else '-'} | {len(no)} | {sum(v >= threshold for v in no)} | "
                     f"{f'{max(no):.3f}' if no else '-'} |")

    probability = {(r["run"], r["response"]): r["jev_probabilities"].get("diagnose", 0.0) for r in rows}
    flagged = [r for r in rows if probability[(r["run"], r["response"])] >= diagnose_threshold
               or r["jev_phase"] == "diagnose"]
    adjudicated = {(d["run"], d["response"]): d for d in devset or [] if d.get("kind") == "response"}
    note = {key: (record.get("diagnose_strength") or "") + (": " if record.get("diagnose_strength") else "")
            + (record.get("note") or "") for key, record in adjudicated.items()}
    values = sorted(probability.values())
    lines += ["", f"`diagnose`: Jev chose it {jev_phases.count('diagnose')} times; its diagnose probability has "
              f"mean {sum(values) / n:.3f}, median {values[n // 2]:.3f}, max {values[-1]:.3f}; "
              f"{len(flagged)} responses have probability >= {diagnose_threshold} or Jev's choice diagnose:", "",
              "| Run | # | Rule | Jev | Jev's diagnose probability | Adjudicated | Note |",
              "|---|---:|---|---|---:|---|---|"]
    for r in sorted(flagged, key=lambda r: -probability[(r["run"], r["response"])]):
        verdict = adjudicated.get((r["run"], r["response"])) or {}
        lines.append(f"| {r['run']} | {r['response']} | {r['rule_phase']} | {r['jev_phase']} | "
                     f"{probability[(r['run'], r['response'])]:.3f} | {verdict.get('adjudicated_phase', '-')} | "
                     f"{note.get((r['run'], r['response']), '')} |")
    if adjudicated:
        lines += ["", *diagnose_scores(rows, adjudicated, diagnose_threshold)]
    lines += ["", f"Cost: {sum(r.get('jev_cost') or 0.0 for r in rows):.6f} USD for {n} responses "
              f"({sum(r['jev']['attempts'] for r in rows)} attempts, "
              f"{sum(r['jev']['input_tokens'] or 0 for r in rows)} input tokens); models "
              f"{', '.join(sorted({str(r.get('jev_model')) for r in rows}))}."]
    return "\n".join(lines)


def diagnose_scores(rows: List[dict], adjudicated: Dict[tuple, dict], diagnose_threshold: float) -> List[str]:
    """Jev's diagnose precision and recall against an adjudicated development set.

    Each adjudicated record has `adjudicated_phase` and, for diagnose, `diagnose_strength` (`clear` or `borderline`);
    strict truth counts clear cases only, lenient truth both. Records whose `complete` is true come from runs whose
    every response was adjudicated for diagnose, so recall is measured over those runs; a response outside the file
    counts as not diagnose. Precision is over every flagged response, which must all be adjudicated.
    """
    def truth(key, strict):
        record = adjudicated.get(key) or {}
        return record.get("adjudicated_phase") == "diagnose" and (
            not strict or record.get("diagnose_strength") == "clear")

    says_rules = [("Jev's choice is diagnose", lambda r: r["jev_phase"] == "diagnose"),
                  (f"diagnose probability >= {diagnose_threshold}",
                   lambda r: r["jev_probabilities"].get("diagnose", 0.0) >= diagnose_threshold)]
    complete_runs = sorted({key[0] for key, record in adjudicated.items() if record.get("complete")})
    in_complete = [r for r in rows if r["run"] in complete_runs]
    lines = [f"Adjudicated: {len(adjudicated)} responses; {len(complete_runs)} runs adjudicated completely "
             f"({len(in_complete)} responses). True diagnose: "
             f"{sum(truth(key, True) for key in adjudicated)} clear, "
             f"{sum(truth(key, False) for key in adjudicated)} clear or borderline.", "",
             "| Truth | Jev says diagnose when | Flagged | True among flagged | Precision | Recall (complete runs) |",
             "|---|---|---:|---:|---:|---:|"]
    for strict in (True, False):
        true_complete = [r for r in in_complete if truth((r["run"], r["response"]), strict)]
        for name, says in says_rules:
            flagged = [r for r in rows if says(r)]
            missing = [r for r in flagged if (r["run"], r["response"]) not in adjudicated]
            hits = sum(truth((r["run"], r["response"]), strict) for r in flagged)
            found = sum(says(r) for r in true_complete)
            lines.append(f"| {'clear only' if strict else 'clear or borderline'} | {name} | {len(flagged)}"
                         f"{f' ({len(missing)} not adjudicated)' if missing else ''} | {hits} | "
                         f"{_ratio(hits, len(flagged) - len(missing))} | {_ratio(found, len(true_complete))} |")
    lines += ["", "| Run | # | Strength | Rule | Jev | Jev's diagnose probability | Hypothesis stated in |",
              "|---|---:|---|---|---|---:|---|"]
    by_key = {(r["run"], r["response"]): r for r in rows}
    for key, record in sorted(adjudicated.items()):
        if record.get("adjudicated_phase") != "diagnose" or key not in by_key:
            continue
        row = by_key[key]
        lines.append(f"| {key[0]} | {key[1]} | {record.get('diagnose_strength')} | {row['rule_phase']} | "
                     f"{row['jev_phase']} | {row['jev_probabilities'].get('diagnose', 0.0):.3f} | "
                     f"#{record.get('hypothesis_response')} |")
    return lines


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
    label_parser.add_argument("--labeller", choices=("claude", "jev", "rules"), default="claude")
    label_parser.add_argument("--labels", type=Path, help=f"default {LABELS.name}, or {LABELS_JEV.name} for Jev; "
                              "required for rules")
    label_parser.add_argument("--model", default="sonnet", help="Claude CLI model (Claude labeller only)")
    agreement_parser = sub.add_parser("agreement")
    agreement_parser.add_argument("--labeller", choices=("claude", "jev"), default="claude")
    agreement_parser.add_argument("--labels", type=Path, default=LABELS)
    agreement_parser.add_argument("--jev", type=Path, default=LABELS_JEV)
    agreement_parser.add_argument("--repeat", type=Path, help="a second Jev pass over the same responses")
    develop_parser = sub.add_parser("develop")
    develop_parser.add_argument("--rules", type=Path, required=True, help="a rules file from label --labeller rules")
    develop_parser.add_argument("--jev", type=Path, required=True)
    develop_parser.add_argument("--devset", type=Path,
                                help="adjudicated responses (adjudicated_phase, diagnose_strength, complete)")
    develop_parser.add_argument("--threshold", type=float, default=DIAGNOSE_THRESHOLD, help="diagnose probability")
    args = parser.parse_args(argv)
    if args.command == "develop":
        print(jev_development_tables(read_labels(args.rules), read_labels(args.jev),
                                     read_labels(args.devset) if args.devset else None, args.threshold))
    elif args.command == "label" and args.labeller == "rules":
        if args.labels is None:
            parser.error("--labels is required with --labeller rules")
        label_rules(args.runs, args.labels)
    elif args.command == "label" and args.labeller == "jev":
        label_jev(args.runs, args.labels or LABELS_JEV)
    elif args.command == "label":
        label(args.runs, args.labels or LABELS, args.model)
    elif args.labeller == "jev":
        print(jev_agreement_tables(read_labels(args.labels), read_labels(args.jev),
                                   read_labels(args.repeat) if args.repeat else None))
    else:
        print(agreement_tables(read_labels(args.labels)))


if __name__ == "__main__":
    main()
