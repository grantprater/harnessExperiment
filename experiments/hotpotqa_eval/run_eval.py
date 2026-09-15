"""HotpotQA distractor evaluation: all 10 documents vs. route-then-answer.

Arms share the same answer prompt; only the documents shown differ.
- full:   all 10 documents (1 call).
- route:  call 1 picks 2 documents from titles + first sentences; call 2 answers from them (2 calls).
          A routing reply naming no valid title is scored as wrong and counted, with no fallback.
- oracle: the gold supporting documents (1 call). Upper bound for routing; optional.

Every API call is appended to calls.jsonl and every finished (question, arm) to results.jsonl
as soon as it completes, so a crash loses nothing and a rerun resumes. REPORT.md is built only
from results.jsonl.

Usage (from the repo root):
  python experiments/hotpotqa_eval/run_eval.py --dry-run
  python experiments/hotpotqa_eval/run_eval.py --max-calls 150
  python experiments/hotpotqa_eval/run_eval.py --report-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import public_corpus_loader as pcl
from hotpotqa_scoring import ROUTE_PARSER_VERSION, bootstrap_ci, exact_match, f1, parse_answer, parse_titles

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct"
POOL_SIZE = 100  # questions are sampled from the first POOL_SIZE validation rows
ARMS = ("full", "route", "oracle")
CALLS_PER_ARM = {"full": 1, "route": 2, "oracle": 1}

ANSWER_PROMPT = """Answer the question using the documents below.

{documents}

Question: {question}
Give the shortest possible answer (for example a name, date, number, or yes/no). Reply in exactly this form:
Answer: <answer>"""

ROUTE_PROMPT = """Below are {count} documents, each shown by its title and first sentence.

{catalog}

Question: {question}
Which 2 documents are needed to answer the question? Reply in exactly this form, copying the titles exactly:
Documents: ["<title 1>", "<title 2>"]"""

PROMPT_HASH = hashlib.sha256((ANSWER_PROMPT + ROUTE_PROMPT).encode("utf-8")).hexdigest()[:10]
DECISION_RULE = ("An arm is called better or worse than `full` only if the 95% paired bootstrap interval "
                 "of its per-question F1 difference excludes 0. Otherwise: no detectable difference.")


class ApiError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def load_openrouter_key() -> str | None:
    for env_file in (ROOT / "experiments" / ".env", ROOT / ".env"):
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "OPENROUTER_API_KEY" and value.strip():
                    return value.strip().strip('"').strip("'")
    return os.environ.get("OPENROUTER_API_KEY")


def chat(api_key: str, model: str, prompt, timeout: int = 120):
    """One chat completion for a user prompt string or a full message list.

    Returns (content, prompt_tokens, completion_tokens, attempts). Token counts are exactly what
    the API reports (None if absent). Raises ApiError after 4 attempts.
    """
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode("utf-8")
    last_error = "no attempt made"
    for attempt in range(1, 5):
        req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {api_key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"
            if e.code in (408, 429, 500, 502, 503, 504):
                time.sleep(5 * attempt)
                continue
            raise ApiError(last_error)
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = repr(e)
            time.sleep(5 * attempt)
            continue
        if "error" in data or not data.get("choices"):
            last_error = json.dumps(data)[:300]
            time.sleep(5 * attempt)
            continue
        message = data["choices"][0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):  # some providers return a list of content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        usage = data.get("usage") or {}
        if not content.strip():
            # Billed output with no text would otherwise be scored as an empty answer.
            last_error = "empty content; " + json.dumps({
                "finish_reason": data["choices"][0].get("finish_reason"), "provider": data.get("provider"),
                "message_keys": sorted(message), "reasoning_chars": len(message.get("reasoning") or ""),
                "completion_tokens": usage.get("completion_tokens")})
            time.sleep(5 * attempt)
            continue
        return content, usage.get("prompt_tokens"), usage.get("completion_tokens"), attempt
    raise ApiError(last_error)


def load_questions(n: int, seed: int, distractors: int = 0):
    rows = pcl.fetch_hotpotqa_instances(split="validation", limit=POOL_SIZE, offset=0)
    # A few rows ship with fewer than 10 documents, which would make routing trivial.
    pool = [q for q in rows if len(q["documents"]) == 10]
    if len(pool) < n:
        sys.exit(f"Only {len(pool)} questions with 10 documents available, need {n}.")
    return pad_with_distractors(random.Random(seed).sample(pool, n), rows, distractors, seed)


def pad_with_distractors(questions, rows, k: int, seed: int):
    """Add k documents from other questions (titles not already present) and shuffle the order.

    Deterministic per (seed, question id); the same padded set is shown to every arm.
    """
    if k == 0:
        return questions
    all_docs = [d for row in rows for d in row["documents"]]
    padded = []
    for q in questions:
        rng = random.Random(f"{seed}:{q['id']}")
        own = {d["title"] for d in q["documents"]}
        candidates = list({d["title"]: d for d in all_docs if d["title"] not in own}.values())
        docs = list(q["documents"]) + rng.sample(candidates, k)
        rng.shuffle(docs)
        padded.append({**q, "documents": docs})
    return padded


def gold_titles(q) -> list[str]:
    return list(dict.fromkeys(q["supporting_facts"]["title"]))


def format_documents(docs) -> str:
    return "\n\n".join(f"=== {d['title']} ===\n{d['text']}" for d in docs)


def format_catalog(docs) -> str:
    return "\n".join(f"- {d['title']}: {(d['sentences'][0] if d['sentences'] else '').strip()}" for d in docs)


def build_answer_prompt(q, docs) -> str:
    return ANSWER_PROMPT.format(documents=format_documents(docs), question=q["question"])


def build_route_prompt(q) -> str:
    return ROUTE_PROMPT.format(count=len(q["documents"]), catalog=format_catalog(q["documents"]),
                               question=q["question"])


class Runner:
    def __init__(self, api_key: str, model: str, run_dir: Path, max_calls: int):
        self.api_key, self.model, self.run_dir, self.max_calls = api_key, model, run_dir, max_calls
        self.calls_made = 0

    def call(self, rec: dict, step: str, prompt: str) -> str:
        if self.calls_made >= self.max_calls:
            raise BudgetExceeded(f"--max-calls {self.max_calls} reached")
        self.calls_made += 1
        t0 = time.time()
        entry = {"time": datetime.now(timezone.utc).isoformat(), "qid": rec["qid"], "arm": rec["arm"],
                 "step": step, "model": self.model, "prompt": prompt}
        try:
            content, p_tok, c_tok, attempts = chat(self.api_key, self.model, prompt)
            entry.update(response=content, prompt_tokens=p_tok, completion_tokens=c_tok, attempts=attempts)
        except ApiError as e:
            entry.update(error=str(e))
            raise
        finally:
            entry["latency_s"] = round(time.time() - t0, 2)
            append_jsonl(self.run_dir / "calls.jsonl", entry)
        add_usage(rec, p_tok, c_tok)
        return content

    def run_arm(self, q, arm: str, saved_route_call: dict | None = None) -> dict:
        rec = {"qid": q["id"], "arm": arm, "type": q["type"], "question": q["question"], "gold": q["answer"],
               "model": self.model, "prompt_hash": PROMPT_HASH, "calls": 0, "prompt_tokens": 0,
               "completion_tokens": 0}
        docs = q["documents"]
        try:
            if arm == "full":
                shown = docs
            elif arm == "oracle":
                wanted = set(gold_titles(q))
                shown = [d for d in docs if d["title"] in wanted]
            else:
                if saved_route_call is not None:
                    # Re-parse the model's earlier routing reply instead of sampling a new one.
                    reply = saved_route_call["response"]
                    add_usage(rec, saved_route_call.get("prompt_tokens"), saved_route_call.get("completion_tokens"))
                    rec["route_reply_reused_from"] = saved_route_call["time"]
                else:
                    reply = self.call(rec, "route", build_route_prompt(q))
                selected = parse_titles(reply, [d["title"] for d in docs])
                gold = set(gold_titles(q))
                rec.update(route_reply=reply[:500], selected_titles=selected, route_format_ok=bool(selected),
                           route_parser=ROUTE_PARSER_VERSION, route_gold_recall=len(gold & set(selected)) / len(gold))
                if not selected:
                    rec.update(prediction="", answer_format_ok=None, em=0.0, f1=0.0,
                               note="routing reply named no valid title; scored as wrong, no answer call")
                    return rec
                wanted = set(selected)
                shown = [d for d in docs if d["title"] in wanted]
            reply = self.call(rec, "answer", build_answer_prompt(q, shown))
            prediction, format_ok = parse_answer(reply)
            rec.update(docs_shown=len(shown), answer_reply=reply[:500], prediction=prediction,
                       answer_format_ok=format_ok, em=exact_match(prediction, q["answer"]),
                       f1=f1(prediction, q["answer"]))
        except ApiError as e:
            rec["error"] = str(e)
        return rec


def add_usage(rec: dict, prompt_tokens, completion_tokens) -> None:
    rec["calls"] += 1
    for field, value in (("prompt_tokens", prompt_tokens), ("completion_tokens", completion_tokens)):
        if value is None:
            rec["tokens_missing"] = True
        else:
            rec[field] += value


def append_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def load_results(run_dir: Path) -> dict:
    """Last record per (qid, arm); later records supersede earlier ones (e.g. a retried error)."""
    latest = {}
    path = run_dir / "results.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                latest[(r["qid"], r["arm"])] = r
    return latest


def cell(text, width: int = 50) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1] + "…"


def write_report(run_dir: Path, questions, arms, model: str, seed: int, distractors: int = 0) -> Path:
    results = load_results(run_dir)
    qids = [q["id"] for q in questions]
    lines = [
        "# HotpotQA Distractor Evaluation",
        "",
        f"- Model: `{model}` (temperature 0, via OpenRouter)",
        f"- Questions: {len(qids)} sampled with seed {seed} from the first {POOL_SIZE} validation rows",
        f"- Documents per question: the 10 HotpotQA documents"
        + (f" + {distractors} distractors drawn from other questions in the pool, order shuffled" if distractors else ""),
        f"- Arms: {', '.join(arms)} | prompt hash `{PROMPT_HASH}`",
        f"- Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from `results.jsonl`",
        f"- Decision rule (fixed before running): {DECISION_RULE}",
        "",
        "## Per-arm results",
        "",
        "| Arm | Scored | Errors | Missing | EM | F1 | Answer format failures | Mean calls | Mean prompt tokens | Mean completion tokens |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    scored = {}
    for arm in arms:
        recs = [results.get((qid, arm)) for qid in qids]
        done = [r for r in recs if r and "error" not in r]
        errors = sum(1 for r in recs if r and "error" in r)
        missing = sum(1 for r in recs if r is None)
        scored[arm] = {r["qid"]: r for r in done}
        if done:
            em = statistics.mean(r["em"] for r in done)
            f1_mean = statistics.mean(r["f1"] for r in done)
            fmt_fail = sum(1 for r in done if r.get("answer_format_ok") is False)
            with_tokens = [r for r in done if not r.get("tokens_missing")]
            p_tok = f"{statistics.mean(r['prompt_tokens'] for r in with_tokens):.0f}" if with_tokens else "n/a"
            c_tok = f"{statistics.mean(r['completion_tokens'] for r in with_tokens):.0f}" if with_tokens else "n/a"
            lines.append(f"| {arm} | {len(done)} | {errors} | {missing} | {em:.3f} | {f1_mean:.3f} | {fmt_fail} | "
                         f"{statistics.mean(r['calls'] for r in done):.2f} | {p_tok} | {c_tok} |")
        else:
            lines.append(f"| {arm} | 0 | {errors} | {missing} | n/a | n/a | n/a | n/a | n/a | n/a |")

    if "full" in arms:
        lines += ["", "## Paired comparison against `full` (questions both arms completed)", "",
                  "| Arm | Paired n | Mean F1 diff | 95% CI | Mean EM diff | 95% CI | Verdict (decision rule) |",
                  "| :-- | --: | --: | :-- | --: | :-- | :-- |"]
        for arm in arms:
            if arm == "full":
                continue
            common = [qid for qid in qids if qid in scored["full"] and qid in scored[arm]]
            f1_ci = bootstrap_ci([scored[arm][q]["f1"] - scored["full"][q]["f1"] for q in common])
            em_ci = bootstrap_ci([scored[arm][q]["em"] - scored["full"][q]["em"] for q in common])
            if f1_ci is None:
                lines.append(f"| {arm} | {len(common)} | n/a | n/a | n/a | n/a | not enough paired questions |")
                continue
            verdict = ("better than full" if f1_ci[1] > 0 else
                       "worse than full" if f1_ci[2] < 0 else "no detectable difference")
            lines.append(f"| {arm} | {len(common)} | {f1_ci[0]:+.3f} | [{f1_ci[1]:+.3f}, {f1_ci[2]:+.3f}] | "
                         f"{em_ci[0]:+.3f} | [{em_ci[1]:+.3f}, {em_ci[2]:+.3f}] | {verdict} |")

    if "route" in arms and scored.get("route"):
        route = list(scored["route"].values())
        lines += ["", "## Routing step (`route` arm)", "",
                  f"- Replies naming no valid title (scored wrong, no answer call): "
                  f"{sum(1 for r in route if not r['route_format_ok'])}/{len(route)}",
                  f"- Picked both gold documents: {sum(1 for r in route if r['route_gold_recall'] == 1.0)}/{len(route)}",
                  f"- Mean gold-document recall: {statistics.mean(r['route_gold_recall'] for r in route):.3f}"]

    lines += ["", "## F1 by question type", "", "| Arm | " + " | ".join(("bridge", "comparison")) + " |",
              "| :-- | --: | --: |"]
    for arm in arms:
        row = []
        for qtype in ("bridge", "comparison"):
            vals = [r["f1"] for r in scored[arm].values() if r["type"] == qtype]
            row.append(f"{statistics.mean(vals):.3f} (n={len(vals)})" if vals else "n/a")
        lines.append(f"| {arm} | " + " | ".join(row) + " |")

    lines += ["", "## Per-question results", "",
              "| Question id | Type | Gold | " + " | ".join(f"{a} prediction (EM)" for a in arms) + " |",
              "| :-- | :-- | :-- | " + " | ".join(":--" for _ in arms) + " |"]
    for q in questions:
        cells = []
        for arm in arms:
            r = results.get((q["id"], arm))
            if r is None:
                cells.append("not run")
            elif "error" in r:
                cells.append("API error")
            else:
                cells.append(f"{cell(r['prediction'], 40) or '(none)'} ({r['em']:.0f})")
        lines.append(f"| `{q['id']}` | {q['type']} | {cell(q['answer'], 30)} | " + " | ".join(cells) + " |")

    report = run_dir / "REPORT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--arms", default="full,route", help=f"comma-separated subset of {','.join(ARMS)}")
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--distractors", type=int, default=0,
                    help="extra documents per question drawn from other questions (0 = the 10 HotpotQA documents)")
    ap.add_argument("--max-calls", type=int, default=None, help="required for live runs; hard cap on API calls")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and example prompts; no API calls")
    ap.add_argument("--report-only", action="store_true", help="rebuild REPORT.md from results.jsonl")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if not arms or any(a not in ARMS for a in arms):
        sys.exit(f"--arms must be a subset of {ARMS}")
    run_name = args.run_name or (f"{args.model.replace('/', '_').replace(':', '_')}_n{args.n}_seed{args.seed}"
                                 + (f"_d{args.distractors}" if args.distractors else ""))
    run_dir = HERE / "runs" / run_name
    questions = load_questions(args.n, args.seed, args.distractors)

    if args.report_only:
        print(f"Report: {write_report(run_dir, questions, arms, args.model, args.seed, args.distractors)}")
        return

    existing = load_results(run_dir)
    saved_route_calls = {}
    if (run_dir / "calls.jsonl").exists():
        for line in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            if c["arm"] == "route" and c["step"] == "route" and "error" not in c:
                saved_route_calls[c["qid"]] = c

    todo = []  # (question, arm, saved routing call to re-parse, or None)
    for q in questions:
        for a in arms:
            r = existing.get((q["id"], a))
            if r is None or "error" in r:
                todo.append((q, a, None))
            elif a == "route" and not r.get("route_format_ok") and r.get("route_parser") != ROUTE_PARSER_VERSION:
                # Routing failure under an older parser: re-parse the saved reply, no new routing call.
                todo.append((q, a, saved_route_calls.get(q["id"])))

    def planned_calls(q, arm, saved) -> int:
        if saved is None:
            return CALLS_PER_ARM[arm]
        return 1 if parse_titles(saved["response"], [d["title"] for d in q["documents"]]) else 0

    max_calls_needed = sum(planned_calls(*item) for item in todo)

    est = {"full": [len(build_answer_prompt(q, q["documents"])) // 4 for q in questions],
           "route (step 1)": [len(build_route_prompt(q)) // 4 for q in questions],
           "oracle / route (step 2, approx.)": [len(build_answer_prompt(
               q, [d for d in q["documents"] if d["title"] in set(gold_titles(q))])) // 4 for q in questions]}
    print(f"Model {args.model} | {len(questions)} questions (seed {args.seed}) | arms {arms} | prompt hash {PROMPT_HASH}")
    print(f"Run dir: {run_dir}")
    print(f"Planned API calls: at most {max_calls_needed} remaining "
          f"({len(todo)} of {len(questions) * len(arms)} question-arm pairs still to run)")
    print("Estimated prompt tokens per call (chars/4, planning only; the report uses API-reported counts):")
    for label, vals in est.items():
        print(f"  {label:34s} mean {statistics.mean(vals):6.0f}  max {max(vals):6d}")

    if args.dry_run:
        q = questions[0]
        print("\n--- Example route prompt ---\n" + build_route_prompt(q))
        print("\n--- Example answer prompt (full, truncated) ---\n" + build_answer_prompt(q, q["documents"])[:1200] + "\n[...]")
        print(f"\nGold for this example: {q['answer']!r} | gold titles {gold_titles(q)}")
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
        "model": args.model, "n": args.n, "seed": args.seed, "distractors": args.distractors, "arms": arms,
        "prompt_hash": PROMPT_HASH,
        "question_ids": [q["id"] for q in questions], "decision_rule": DECISION_RULE,
        "answer_prompt": ANSWER_PROMPT, "route_prompt": ROUTE_PROMPT}, indent=2), encoding="utf-8")

    runner = Runner(api_key, args.model, run_dir, args.max_calls)
    try:
        for i, (q, arm, saved) in enumerate(todo, 1):
            rec = runner.run_arm(q, arm, saved)
            append_jsonl(run_dir / "results.jsonl", rec)
            status = f"ERROR {rec['error'][:80]}" if "error" in rec else f"EM {rec['em']:.0f} F1 {rec['f1']:.2f}"
            print(f"[{i}/{len(todo)}] {arm:6s} {q['id']} {status} | pred {cell(rec.get('prediction', ''), 40)!r} "
                  f"| gold {q['answer']!r}", flush=True)
    except BudgetExceeded as e:
        print(f"Stopped: {e}")
    finally:
        print(f"API calls made: {runner.calls_made}")
        print(f"Report: {write_report(run_dir, questions, arms, args.model, args.seed, args.distractors)}")


if __name__ == "__main__":
    main()
