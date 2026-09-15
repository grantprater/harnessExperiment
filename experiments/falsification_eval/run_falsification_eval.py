"""Multi-turn repair on hard Exercism tasks: does automated falsification extraction help?

Arms share the system prompt, the task prompt, and the test feedback; every reply must start
with an `APPROACH:` line.
- transcript:   one growing conversation; each failure appends the reply and the test result.
- last_failure: blank slate each turn with the task, current code, and latest test result.
- ledger:       last_failure plus the dead-end ledger from reticle.cognitive.falsification,
                and a notice when the code repeats an already-failed attempt.

Every API call is appended to calls.jsonl and every finished (task, arm) to results.jsonl as
it completes, so a crash loses nothing and a rerun resumes. REPORT.md is built only from
results.jsonl. Model-written code runs locally in a temporary directory with a timeout; this is
not a sandbox.

Usage (from the repo root):
  python experiments/falsification_eval/run_falsification_eval.py --dry-run
  python experiments/falsification_eval/run_falsification_eval.py --arms last_failure --max-turns 1 --max-calls 23
  python experiments/falsification_eval/run_falsification_eval.py --max-calls 276
  python experiments/falsification_eval/run_falsification_eval.py --report-only
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "exercism_bench"))

import exercism_loader
from run_aider_bench import extract_python_code
from reticle.cognitive.falsification import DeadEndLedger, code_fingerprint, parse_approach, parse_unittest_output


def _load_hotpotqa_runner():
    spec = importlib.util.spec_from_file_location("hotpotqa_run_eval", ROOT / "experiments" / "hotpotqa_eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_hotpotqa = _load_hotpotqa_runner()
chat, ApiError, append_jsonl, load_openrouter_key = (
    _hotpotqa.chat, _hotpotqa.ApiError, _hotpotqa.append_jsonl, _hotpotqa.load_openrouter_key)

exercism_loader.TASKS_DIR = HERE / "tasks"

DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct"
ARMS = ("transcript", "last_failure", "ledger")
# Exercism Python practice exercises rated difficulty 5-9. paasio is excluded: its tests import a
# test_utils helper the loader does not fetch, so no attempt could pass.
TASKS = (
    "binary-search-tree", "bowling", "camicia", "custom-set", "dot-dsl", "forth", "knapsack",
    "rational-numbers", "relative-distance", "zebra-puzzle", "affine-cipher", "alphametics",
    "bank-account", "react", "two-bucket", "word-search", "zipper", "book-store", "dominoes",
    "satellite", "sgf-parsing", "rest-api", "pov",
)
TEST_TIMEOUT_S = 10
FEEDBACK_CHARS = 2500

SYSTEM_PROMPT = """You are an expert Python engineer implementing a programming exercise so that its unit tests pass.
Every reply must have exactly this form:
APPROACH: <one sentence describing the implementation strategy of this attempt>
```python
<the complete contents of the solution file>
```"""

TASK_PROMPT = """# Exercise: {slug}

## Instructions
{instructions}

## Starting stub ({snake}.py)
```python
{stub}
```"""

FIRST_PROMPT = """{task}

Implement the complete {snake}.py. Reply with the APPROACH line and the complete file."""

RETRY_PROMPT = """{task}

## Your current implementation ({snake}.py)
```python
{code}
```

## Latest test result
{feedback}
{ledger}
Fix the implementation. Reply with the APPROACH line and the complete {snake}.py."""

TRANSCRIPT_RETRY_PROMPT = """## Latest test result
{feedback}

Fix the implementation. Reply with the APPROACH line and the complete {snake}.py."""

PROMPT_HASH = hashlib.sha256(
    (SYSTEM_PROMPT + TASK_PROMPT + FIRST_PROMPT + RETRY_PROMPT + TRANSCRIPT_RETRY_PROMPT).encode("utf-8")).hexdigest()[:10]
DECISION_RULE = ("On pass rate within the turn budget, an arm is called better than another only if the exact "
                 "McNemar test on paired task outcomes gives p < 0.05. Repeat rates and token use are descriptive.")


class BudgetExceeded(Exception):
    pass


def run_tests(task, code: str):
    """Run the task's unittest suite against `code`; returns (RunReport, raw output)."""
    snake = task["snake_name"]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        (tmp / f"{snake}.py").write_text(code, encoding="utf-8")
        (tmp / f"{snake}_test.py").write_text(task["test_code"], encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, "-B", "-m", "unittest", f"{snake}_test.py"], cwd=tmp,
                                  capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
            output, timed_out = proc.stdout + proc.stderr, False
        except subprocess.TimeoutExpired:
            output, timed_out = "", True
    return parse_unittest_output(output, timed_out=timed_out), output


def format_feedback(report, output: str) -> str:
    """Test feedback shown to every arm."""
    if report.passed:
        return "All tests passed."
    if report.collection_error:
        tail = output[-FEEDBACK_CHARS:].strip()
        return f"The tests could not run: {report.collection_error}" + (f"\n```\n{tail}\n```" if tail else "")
    return f"{len(report.failures)} of {report.ran} tests failing.\n```\n{output[:FEEDBACK_CHARS].strip()}\n```"


def task_text(task) -> str:
    return TASK_PROMPT.format(slug=task["slug"], instructions=task["instructions"].strip(),
                              snake=task["snake_name"], stub=task["stub"].rstrip())


class Runner:
    def __init__(self, api_key: str, model: str, run_dir: Path, max_calls: int):
        self.api_key, self.model, self.run_dir, self.max_calls = api_key, model, run_dir, max_calls
        self.calls_made = 0

    def call(self, rec: dict, turn: int, messages):
        if self.calls_made >= self.max_calls:
            raise BudgetExceeded(f"--max-calls {self.max_calls} reached")
        self.calls_made += 1
        t0 = time.time()
        entry = {"time": datetime.now(timezone.utc).isoformat(), "slug": rec["slug"], "arm": rec["arm"],
                 "turn": turn, "model": self.model, "messages": messages}
        try:
            content, p_tok, c_tok, attempts = chat(self.api_key, self.model, messages)
            entry.update(response=content, prompt_tokens=p_tok, completion_tokens=c_tok, attempts=attempts)
        except ApiError as e:
            entry.update(error=str(e))
            raise
        finally:
            entry["latency_s"] = round(time.time() - t0, 2)
            append_jsonl(self.run_dir / "calls.jsonl", entry)
        for field, value in (("prompt_tokens", p_tok), ("completion_tokens", c_tok)):
            if value is None:
                rec["tokens_missing"] = True
            else:
                rec[field] += value
        return content, p_tok, c_tok

    def run_task_arm(self, task, arm: str, max_turns: int) -> dict:
        snake = task["snake_name"]
        rec = {"slug": task["slug"], "arm": arm, "model": self.model, "prompt_hash": PROMPT_HASH,
               "max_turns": max_turns, "passed": False, "turns": [], "prompt_tokens": 0, "completion_tokens": 0}
        text = task_text(task)
        ledger = DeadEndLedger() if arm == "ledger" else None
        transcript = [{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": FIRST_PROMPT.format(task=text, snake=snake)}]
        code = feedback = repeat_notice = ""
        first_seen = {}
        previous_signature = None
        try:
            for turn in range(1, max_turns + 1):
                if turn == 1 or arm == "transcript":
                    messages = transcript
                else:
                    ledger_section = ""
                    if ledger is not None:
                        ledger_section = f"\n## Dead ends so far\n{ledger.render()}\n" + (f"{repeat_notice}\n" if repeat_notice else "")
                    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": RETRY_PROMPT.format(
                                    task=text, snake=snake, code=code, feedback=feedback, ledger=ledger_section)}]
                reply, p_tok, _ = self.call(rec, turn, messages)
                code = extract_python_code(reply)
                approach, approach_found = parse_approach(reply)
                fingerprint = code_fingerprint(code)
                repeat_of_turn = first_seen.get(fingerprint)
                first_seen.setdefault(fingerprint, turn)
                repeat_notice = ""
                if ledger is not None:
                    match = ledger.find_repeat(code)
                    if match:
                        repeat_notice = ("Note: your last attempt was identical (ignoring comments and formatting) "
                                         f"to code that already failed as {match.dead_end_id}.")
                report, output = run_tests(task, code)
                feedback = format_feedback(report, output)
                if ledger is not None:
                    ledger.record_attempt(turn, approach, code, report)
                rec["turns"].append({
                    "turn": turn, "approach": approach, "approach_found": approach_found,
                    "fingerprint": fingerprint, "repeat_of_turn": repeat_of_turn, "signature": report.signature,
                    "same_signature_as_previous": (not report.passed) and report.signature == previous_signature,
                    "passed": report.passed, "ran": report.ran, "failing": len(report.failures),
                    "collection_error": report.collection_error, "prompt_tokens": p_tok,
                    "prompt_chars": sum(len(m["content"]) for m in messages)})
                previous_signature = report.signature
                if report.passed:
                    rec["passed"] = True
                    break
                if arm == "transcript":
                    transcript = transcript + [
                        {"role": "assistant", "content": reply},
                        {"role": "user", "content": TRANSCRIPT_RETRY_PROMPT.format(feedback=feedback, snake=snake)}]
        except ApiError as e:
            rec["error"] = str(e)
        rec["turns_used"] = len(rec["turns"])
        if ledger is not None:
            rec["ledger"] = ledger.to_dict()
            rec["ledger_render"] = ledger.render()
        return rec


def load_results(run_dir: Path) -> dict:
    """Last record per (task, arm); later records supersede earlier ones."""
    latest = {}
    path = run_dir / "results.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                latest[(r["slug"], r["arm"])] = r
    return latest


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def write_report(run_dir: Path, tasks, arms, model: str, max_turns: int) -> Path:
    results = load_results(run_dir)
    lines = [
        "# Falsification Extraction Evaluation (Exercism multi-turn repair)",
        "",
        f"- Model: `{model}` (temperature 0, via OpenRouter)",
        f"- Tasks: {len(tasks)} Exercism Python practice exercises rated difficulty 5-9 (paasio excluded: missing test helper)",
        f"- Arms: {', '.join(arms)} | up to {max_turns} turn(s) per task | prompt hash `{PROMPT_HASH}`",
        f"- Model-written code ran locally in a temporary directory with a {TEST_TIMEOUT_S}s test timeout",
        f"- Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from `results.jsonl`",
        f"- Decision rule (fixed before running): {DECISION_RULE}",
        "",
        "## Per-arm results",
        "",
        "| Arm | Completed | Errors | Missing | Passed | Cumulative passes by turn | Mean turns (passed) "
        "| Repeated code, turns 2+ | Same failure as previous turn, turns 2+ | Missing APPROACH line "
        "| Mean prompt tokens per call by turn |",
        "| :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |",
    ]
    done = {}
    for arm in arms:
        recs = [results.get((s, arm)) for s in tasks]
        ok = [r for r in recs if r and "error" not in r]
        errors = sum(1 for r in recs if r and "error" in r)
        missing = sum(1 for r in recs if r is None)
        done[arm] = {r["slug"]: r for r in ok}
        if not ok:
            lines.append(f"| {arm} | 0 | {errors} | {missing} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        passed = [r for r in ok if r["passed"]]
        by_turn = " / ".join(str(sum(1 for r in passed if r["turns_used"] <= t)) for t in range(1, max_turns + 1))
        all_turns = [t for r in ok for t in r["turns"]]
        later = [t for t in all_turns if t["turn"] >= 2]
        repeated = f"{sum(1 for t in later if t['repeat_of_turn'] is not None)}/{len(later)}" if later else "n/a"
        same = f"{sum(1 for t in later if t['same_signature_as_previous'])}/{len(later)}" if later else "n/a"
        no_approach = f"{sum(1 for t in all_turns if not t['approach_found'])}/{len(all_turns)}"
        tokens = []
        for turn in range(1, max_turns + 1):
            vals = [t["prompt_tokens"] for t in all_turns if t["turn"] == turn and t.get("prompt_tokens") is not None]
            tokens.append(f"{statistics.mean(vals):.0f}" if vals else "-")
        mean_turns = f"{statistics.mean(r['turns_used'] for r in passed):.2f}" if passed else "n/a"
        lines.append(f"| {arm} | {len(ok)} | {errors} | {missing} | {len(passed)}/{len(ok)} | {by_turn} | {mean_turns} "
                     f"| {repeated} | {same} | {no_approach} | {' / '.join(tokens)} |")

    pairs = [(a, b) for a, b in (("last_failure", "transcript"), ("ledger", "last_failure"), ("ledger", "transcript"))
             if a in arms and b in arms]
    if pairs:
        lines += ["", "## Paired pass comparisons (tasks both arms completed)", "",
                  "| Comparison | Paired tasks | Both pass | Only first passes | Only second passes | Exact McNemar p | Verdict (decision rule) |",
                  "| :-- | --: | --: | --: | --: | --: | :-- |"]
        for a, b in pairs:
            common = [s for s in tasks if s in done[a] and s in done[b]]
            both = sum(1 for s in common if done[a][s]["passed"] and done[b][s]["passed"])
            only_a = sum(1 for s in common if done[a][s]["passed"] and not done[b][s]["passed"])
            only_b = sum(1 for s in common if done[b][s]["passed"] and not done[a][s]["passed"])
            p = exact_mcnemar(only_a, only_b)
            verdict = (f"{a} better" if p < 0.05 and only_a > only_b else
                       f"{b} better" if p < 0.05 and only_b > only_a else "no detectable difference")
            lines.append(f"| {a} vs {b} | {len(common)} | {both} | {only_a} | {only_b} | {p:.3f} | {verdict} |")

    if "ledger" in arms and done.get("ledger"):
        recs = list(done["ledger"].values())
        lines += ["", "## Ledger arm", "",
                  f"- Dead ends per task: mean {statistics.mean(len(r['ledger']) for r in recs):.2f}, "
                  f"max {max(len(r['ledger']) for r in recs)}",
                  f"- Rendered ledger at the end of each task: mean "
                  f"{statistics.mean(len(r['ledger_render']) for r in recs):.0f} characters"]

    lines += ["", "## Per-task results", "", "| Task | " + " | ".join(arms) + " |",
              "| :-- | " + " | ".join(":--" for _ in arms) + " |"]
    for s in tasks:
        cells = []
        for arm in arms:
            r = results.get((s, arm))
            if r is None:
                cells.append("not run")
            elif "error" in r:
                cells.append("API error")
            elif r["passed"]:
                cells.append(f"PASS turn {r['turns_used']}")
            elif r["turns"]:
                last = r["turns"][-1]
                cells.append("fail (tests could not run)" if last["collection_error"]
                             else f"fail ({last['failing']}/{last['ran']} failing)")
            else:
                cells.append("fail (no turns)")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")

    report = run_dir / "REPORT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--arms", default=",".join(ARMS), help=f"comma-separated subset of {','.join(ARMS)}")
    ap.add_argument("--max-turns", type=int, default=4)
    ap.add_argument("--tasks", default=None, help="comma-separated subset of task slugs (default: all)")
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--max-calls", type=int, default=None, help="required for live runs; hard cap on API calls")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and example prompts; no API calls")
    ap.add_argument("--report-only", action="store_true", help="rebuild REPORT.md from results.jsonl")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if not arms or any(a not in ARMS for a in arms):
        sys.exit(f"--arms must be a subset of {ARMS}")
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else list(TASKS)
    if any(t not in TASKS for t in tasks):
        sys.exit(f"--tasks must be a subset of {TASKS}")
    run_name = args.run_name or f"{args.model.replace('/', '_').replace(':', '_')}_t{args.max_turns}"
    run_dir = HERE / "runs" / run_name

    if args.report_only:
        print(f"Report: {write_report(run_dir, tasks, arms, args.model, args.max_turns)}")
        return

    task_data = {slug: exercism_loader.load_exercise(slug) for slug in tasks}
    existing = load_results(run_dir)
    todo = [(slug, arm) for slug in tasks for arm in arms
            if not (existing.get((slug, arm)) and "error" not in existing[(slug, arm)])]
    max_calls_needed = len(todo) * args.max_turns

    first_chars = [len(SYSTEM_PROMPT) + len(FIRST_PROMPT.format(task=task_text(t), snake=t["snake_name"]))
                   for t in task_data.values()]
    print(f"Model {args.model} | {len(tasks)} tasks | arms {arms} | up to {args.max_turns} turns | prompt hash {PROMPT_HASH}")
    print(f"Run dir: {run_dir}")
    print(f"Planned API calls: at most {max_calls_needed} ({len(todo)} of {len(tasks) * len(arms)} task-arm pairs still to run)")
    print(f"Turn-1 prompt tokens (chars/4, planning only): mean {statistics.mean(first_chars) / 4:.0f}, "
          f"max {max(first_chars) / 4:.0f}; retries add the current code and up to {FEEDBACK_CHARS} characters of feedback")

    if args.dry_run:
        task = task_data[tasks[0]]
        print("\n--- Example turn-1 user prompt (truncated) ---\n"
              + FIRST_PROMPT.format(task=task_text(task), snake=task["snake_name"])[:1500] + "\n[...]")
        report, output = run_tests(task, task["stub"])
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "(example approach from the model's APPROACH line)", task["stub"], report)
        section = f"\n## Dead ends so far\n{ledger.render()}\n"
        example = RETRY_PROMPT.format(task="[task prompt as above]", snake=task["snake_name"], code="[current code]",
                                      feedback=format_feedback(report, output)[:900] + "\n[...]", ledger=section)
        print("\n--- Example ledger-arm retry prompt, using the unmodified stub's real test run ---\n" + example)
        return

    if args.max_calls is None:
        sys.exit(f"Live runs need --max-calls (this run needs at most {max_calls_needed}).")
    if max_calls_needed > args.max_calls:
        sys.exit(f"This run needs up to {max_calls_needed} calls, above --max-calls {args.max_calls}.")
    api_key = load_openrouter_key()
    if not api_key:
        sys.exit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps({
        "model": args.model, "arms": arms, "tasks": tasks, "max_turns": args.max_turns, "prompt_hash": PROMPT_HASH,
        "decision_rule": DECISION_RULE, "test_timeout_s": TEST_TIMEOUT_S, "feedback_chars": FEEDBACK_CHARS,
        "prompts": {"system": SYSTEM_PROMPT, "task": TASK_PROMPT, "first": FIRST_PROMPT, "retry": RETRY_PROMPT,
                    "transcript_retry": TRANSCRIPT_RETRY_PROMPT}}, indent=2), encoding="utf-8")

    runner = Runner(api_key, args.model, run_dir, args.max_calls)
    try:
        for i, (slug, arm) in enumerate(todo, 1):
            rec = runner.run_task_arm(task_data[slug], arm, args.max_turns)
            append_jsonl(run_dir / "results.jsonl", rec)
            if "error" in rec:
                status = f"ERROR {rec['error'][:80]}"
            else:
                repeats = sum(1 for t in rec["turns"] if t["repeat_of_turn"] is not None)
                status = f"{'PASS' if rec['passed'] else 'fail'} after {rec['turns_used']} turn(s), repeated code {repeats}"
            print(f"[{i}/{len(todo)}] {arm:12s} {slug:20s} {status}", flush=True)
    except BudgetExceeded as e:
        print(f"Stopped: {e}")
    finally:
        print(f"API calls made: {runner.calls_made}")
        print(f"Report: {write_report(run_dir, tasks, arms, args.model, args.max_turns)}")


if __name__ == "__main__":
    main()
