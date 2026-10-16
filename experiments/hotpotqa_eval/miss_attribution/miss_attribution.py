"""Offline miss attribution and "fetch more" replay over existing HotpotQA routing logs.

Zero model calls. Reads only runs/*/results.jsonl, runs/*/calls.jsonl, and (for gold titles of
the run without an oracle arm) the local dataset cache corpus_cache/hotpotqa_validation_0_100.json.
No network access of any kind.

Where the fields come from (established by reading run_eval.py and the logs):
- routed doc titles: results.jsonl, route arm, `selected_titles` (parsed from `route_reply`).
  The router is asked for exactly 2 titles; no scores or ranking over the other docs are logged.
- gold doc titles: not stored in results.jsonl. Recovered from (1) the oracle arm's answer prompt in
  calls.jsonl (the `=== Title ===` headers, d50 run only) and (2) the dataset cache's
  `supporting_facts.title`. Both are checked against the logged `route_gold_recall`.
- answers: results.jsonl `prediction`, `gold`, `em`, `f1`; F1 is recomputed with hotpotqa_scoring.f1.
- all doc texts shown to the model: the full arm's answer prompt in calls.jsonl.

Usage (from the repo root):
  python experiments/hotpotqa_eval/miss_attribution/miss_attribution.py [--cache PATH]
Writes experiments/hotpotqa_eval/miss_attribution/analysis_output.md and prints the same text.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parents[1]
sys.path.insert(0, str(EVAL))

from hotpotqa_scoring import bootstrap_ci, f1  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

RUNS = ["meta-llama_llama-3.1-8b-instruct_n50_seed0", "meta-llama_llama-3.1-8b-instruct_n50_seed0_d50"]
CLASSES = {
    "a": "both gold routed, answer correct (EM=1)",
    "b": "both gold routed, answer wrong (answer miss)",
    "c": "one gold routed",
    "d": "no gold routed (routing miss)",
}
# Frozen-rule selection criterion, fixed in code before the replay table was read:
# on the d50 run (60 docs, the setting a live run would use), take the rule with the most
# questions having both gold docs among routed + fetched docs, subject to a mean of at most
# MAX_MEAN_EXTRA extra docs per question; ties go to fewer extra docs.
MAX_MEAN_EXTRA = 1.0
SELECTION_RUN = RUNS[1]

HEADER_RE = re.compile(r"^=== (.+) ===$", re.MULTILINE)


# ---------------------------------------------------------------- parsing helpers (unit-tested)

def parse_docs(prompt: str) -> dict[str, str]:
    """Title -> text for the `=== Title ===` blocks of an answer prompt, in prompt order."""
    end = prompt.rfind("\n\nQuestion: ")
    body = prompt if end < 0 else prompt[:end]
    heads = list(HEADER_RE.finditer(body))
    docs = {}
    for i, h in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        docs[h.group(1)] = body[h.end():stop].strip()
    return docs


def link_key(title: str) -> str | None:
    """Casefolded title without a trailing disambiguator such as ' (film)'; None if too short to match."""
    key = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().casefold()
    return key if len(key) >= 4 else None


def mention_pos(text: str, title: str) -> int | None:
    """Position of the first whole-word mention of `title` (disambiguator dropped) in `text`."""
    key = link_key(title)
    if key is None:
        return None
    m = re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", text.casefold())
    return m.start() if m else None


def link_candidates(routed: list[str], docs: dict[str, str], direction: str = "both") -> list[str]:
    """Unrouted docs title-linked to a routed doc, best first.

    forward link: a routed doc's text mentions the candidate's title (the HotpotQA bridge pattern).
    back link:    the candidate's text mentions a routed doc's title.
    Order: forward links before back-only links; within forward, earlier mention first;
    remaining ties keep the prompt order. Uses only what a live system would see.
    """
    out = []
    for order, (title, text) in enumerate(docs.items()):
        if title in routed:
            continue
        fwd = [p for r in routed if r in docs for p in [mention_pos(docs[r], title)] if p is not None]
        back = any(mention_pos(text, r) is not None for r in routed)
        if direction == "forward":
            back = False
        if fwd:
            out.append(((0, min(fwd), order), title))
        elif back:
            out.append(((1, 0, order), title))
    return [t for _, t in sorted(out)]


def pair_linked(routed: list[str], docs: dict[str, str]) -> bool:
    """True if the two routed docs mention each other's title (either direction)."""
    if len(routed) != 2 or any(r not in docs for r in routed):
        return False
    a, b = routed
    return mention_pos(docs[a], b) is not None or mention_pos(docs[b], a) is not None


def classify(n_gold_routed: int, n_gold: int, em: float) -> str:
    if n_gold_routed >= n_gold:
        return "a" if em == 1.0 else "b"
    return "c" if n_gold_routed > 0 else "d"


# ---------------------------------------------------------------- data loading

def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(run: str, cache: dict) -> dict:
    run_dir = EVAL / "runs" / run
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    results = {}
    for r in load_jsonl(run_dir / "results.jsonl"):
        results[(r["qid"], r["arm"])] = r  # last record wins, as in run_eval.load_results
    calls = defaultdict(dict)
    for c in load_jsonl(run_dir / "calls.jsonl"):
        if "error" not in c:
            calls[(c["qid"], c["arm"])][c["step"]] = c  # last successful call per step
    questions = []
    for qid in config["question_ids"]:
        full_call = calls[(qid, "full")]["answer"]
        docs = parse_docs(full_call["prompt"])
        gold_cache = list(dict.fromkeys(cache[qid]["supporting_facts"]["title"]))
        gold_oracle = None
        if "oracle" in config["arms"]:
            gold_oracle = list(parse_docs(calls[(qid, "oracle")]["answer"]["prompt"]))
        route = results[(qid, "route")]
        questions.append({
            "qid": qid, "type": route["type"], "gold_answer": route["gold"], "docs": docs,
            "gold_titles": gold_oracle or gold_cache, "gold_cache": gold_cache, "gold_oracle": gold_oracle,
            "tok_per_char": full_call["prompt_tokens"] / len(full_call["prompt"]),
            "route": route, "full": results[(qid, "full")], "oracle": results.get((qid, "oracle")),
        })
    return {"run": run, "config": config, "questions": questions}


# ---------------------------------------------------------------- analysis

def check_run(data: dict) -> list[str]:
    """Consistency checks; any failure aborts the analysis."""
    problems = []
    for q in data["questions"]:
        gold, sel = q["gold_titles"], q["route"]["selected_titles"]
        if q["gold_oracle"] is not None and set(q["gold_oracle"]) != set(q["gold_cache"]):
            problems.append(f"{q['qid']}: oracle-prompt gold titles differ from dataset cache")
        if any(g not in q["docs"] for g in gold):
            problems.append(f"{q['qid']}: gold title missing from the full-arm prompt")
        recall = len(set(gold) & set(sel)) / len(gold)
        if abs(recall - q["route"]["route_gold_recall"]) > 1e-9:
            problems.append(f"{q['qid']}: recomputed recall {recall} != logged {q['route']['route_gold_recall']}")
        for arm in ("full", "route", "oracle"):
            r = q[arm]
            if r is not None and abs(f1(r.get("prediction", ""), r["gold"]) - r["f1"]) > 1e-9:
                problems.append(f"{q['qid']} {arm}: recomputed F1 differs from logged")
    return problems


def attribution(data: dict) -> list[str]:
    qs = data["questions"]
    n = len(qs)
    has_oracle = qs[0]["oracle"] is not None
    for q in qs:
        k = len(set(q["gold_titles"]) & set(q["route"]["selected_titles"]))
        q["n_gold_routed"] = k
        q["cls"] = classify(k, len(q["gold_titles"]), q["route"]["em"])
    lines = [f"### Miss attribution: `{data['run']}` ({len(qs[0]['docs'])} docs per question)", "",
             "| Class | Meaning | n | route F1 | full F1 | " + ("oracle F1 | " if has_oracle else "") + "route EM |",
             "| :-- | :-- | --: | --: | --: | " + ("--: | " if has_oracle else "") + "--: |"]
    for c, meaning in CLASSES.items():
        sub = [q for q in qs if q["cls"] == c]
        if not sub:
            lines.append(f"| {c} | {meaning} | 0 | - | - | " + ("- | " if has_oracle else "") + "- |")
            continue
        mean = lambda arm, key="f1": statistics.mean(q[arm][key] for q in sub)  # noqa: E731
        lines.append(f"| {c} | {meaning} | {len(sub)} | {mean('route'):.3f} | {mean('full'):.3f} | "
                     + (f"{mean('oracle'):.3f} | " if has_oracle else "") + f"{mean('route', 'em'):.3f} |")
    lines.append(f"| all | | {n} | {statistics.mean(q['route']['f1'] for q in qs):.3f} | "
                 f"{statistics.mean(q['full']['f1'] for q in qs):.3f} | "
                 + (f"{statistics.mean(q['oracle']['f1'] for q in qs):.3f} | " if has_oracle else "")
                 + f"{statistics.mean(q['route']['em'] for q in qs):.3f} |")
    fails = sum(1 for q in qs if not q["route"]["route_format_ok"])
    lines += ["", f"- Both gold routed: {sum(1 for q in qs if q['cls'] in 'ab')}/{n}; "
              f"routing replies naming no valid title: {fails}/{n} (these fall in class d, F1 0, no answer call).",
              f"- Mean gold-document recall of the router: {statistics.mean(q['route']['route_gold_recall'] for q in qs):.3f}"]

    # Gap decomposition: mean(A - B) over all questions = sum over classes of (1/n) * sum_class(A - B).
    pairs = [("oracle", "full"), ("oracle", "route")] if has_oracle else [("full", "route")]
    lines += ["", "Gap decomposition (each cell = the class's share of the overall mean F1 gap, "
              "i.e. sum over the class of the per-question difference, divided by n; cells add up to the total):", "",
              "| Gap | total | " + " | ".join(f"class {c}" for c in CLASSES) + " | total 95% CI |",
              "| :-- | --: | " + " | ".join("--: " for _ in CLASSES) + "| :-- |"]
    for hi, lo in pairs:
        diffs = [q[hi]["f1"] - q[lo]["f1"] for q in qs]
        ci = bootstrap_ci(diffs)
        parts = [sum(q[hi]["f1"] - q[lo]["f1"] for q in qs if q["cls"] == c) / n for c in CLASSES]
        lines.append(f"| {hi} - {lo} | {sum(diffs) / n:+.3f} | " + " | ".join(f"{p:+.3f}" for p in parts)
                     + f" | [{ci[1]:+.3f}, {ci[2]:+.3f}] |")
        if hi == "oracle" and lo == "route":
            split = (f"- `oracle - route` split: routing misses (c+d) {parts[2] + parts[3]:+.3f}, "
                     f"answer misses (b) {parts[1]:+.3f}, both-routed-and-correct (a) {parts[0]:+.3f}.")
    lines.append("")
    if has_oracle:
        lines += [split, "- Class labels come from the route arm, so for `oracle - full` they say which questions "
                  "the router struggles with, not anything the full arm did."]
    else:
        lines.append("- No oracle arm in this run, so only `full - route` can be decomposed.")
    return lines


RULES = [("none", 0, "both", False)]
for _m in (1, 2, 3, 99):
    for _dir in ("forward", "both"):
        for _cond in (False, True):
            RULES.append((f"link{'' if _m == 99 else _m}{'-all' if _m == 99 else ''}-{_dir}"
                          f"{'-if-pair-unlinked' if _cond else ''}", _m, _dir, _cond))


def replay(data: dict) -> tuple[list[str], dict]:
    qs = data["questions"]
    n = len(qs)
    rows, stats = [], {}
    for name, m, direction, cond in RULES:
        both = rec = extra = tok = trig = 0
        for q in qs:
            routed = q["route"]["selected_titles"]
            fetched = []
            if m and routed and not (cond and pair_linked(routed, q["docs"])):
                fetched = link_candidates(routed, q["docs"], direction)[:m]
                trig += bool(fetched)
            have = set(routed) | set(fetched)
            gold = set(q["gold_titles"])
            both += gold <= have
            rec += len(gold & have) / len(gold)
            extra += len(fetched)
            tok += sum(len(f"=== {t} ===\n{q['docs'][t]}\n\n") for t in fetched) * q["tok_per_char"]
        stats[name] = {"both": both, "recall": rec / n, "extra": extra / n, "tok": tok / n, "trig": trig}
        rows.append(f"| `{name}` | {trig}/{n} | {both}/{n} | {rec / n:.3f} | {extra / n:.2f} | {tok / n:.0f} |")
    # Random-fetch baseline (expected value, analytic): add m uniformly random unrouted docs.
    for m in (1, 2):
        both = rec = 0.0
        for q in qs:
            pool = len(q["docs"]) - len(q["route"]["selected_titles"])
            g = len(q["gold_titles"]); miss = g - q["n_gold_routed"]
            rec += (q["n_gold_routed"] + m * miss / pool) / g
            both += 1.0 if miss == 0 else (m / pool if miss == 1 else math.comb(m, 2) / math.comb(pool, 2))
        rows.append(f"| random {m} (expected) | {n}/{n} | {both:.1f}/{n} | {rec / n:.3f} | {m:.2f} | ~{m} doc |")
    lines = [f"### Fetch-more replay: `{data['run']}`", "",
             "| Rule | Triggered | Both gold in context | Mean gold recall | Mean extra docs | Mean extra prompt tokens (est.) |",
             "| :-- | --: | --: | --: | --: | --: |"] + rows
    lines.append("")
    lines.append("Extra tokens = characters of the fetched `=== Title ===` blocks times this question's "
                 "API-reported tokens/character in the full-arm prompt.")
    return lines, stats


def lower_priority() -> None:
    """Run at idle priority: the machine's CPU is shared with long-running jobs."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)  # IDLE
        else:
            import os
            os.nice(19)
    except Exception:
        pass


def main():
    lower_priority()
    ap =argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "corpus_cache" / "hotpotqa_validation_0_100.json"),
                    help="local HotpotQA cache (the worktree may lack it; point at the main checkout)")
    args = ap.parse_args()
    cache_path = Path(args.cache)
    if not cache_path.exists():
        sys.exit(f"Dataset cache not found: {cache_path} (pass --cache; this script never downloads).")
    cache = {r["id"]: r for r in json.loads(cache_path.read_text(encoding="utf-8"))}

    out = ["# Miss attribution and fetch-more replay: generated output", "",
           "Generated by `miss_attribution.py` from existing logs. Zero model calls.", ""]
    all_stats = {}
    for run in RUNS:
        data = load_run(run, cache)
        problems = check_run(data)
        if problems:
            sys.exit("Consistency check failed:\n" + "\n".join(problems))
        out.append(f"Consistency checks passed for `{run}`: recomputed recall and F1 match the logs"
                   + ("; oracle-prompt gold titles match the dataset cache." if data["questions"][0]["oracle"] else "."))
        out.append("")
        out += attribution(data) + [""]
        lines, stats = replay(data)
        out += lines + [""]
        all_stats[run] = stats

    sel = all_stats[SELECTION_RUN]
    eligible = [(-s["both"], s["extra"], name) for name, s in sel.items() if s["extra"] <= MAX_MEAN_EXTRA]
    _, _, frozen = min(eligible)
    out += ["### Frozen rule (selected by the criterion fixed in code)", "",
            f"Criterion: most both-gold questions on `{SELECTION_RUN}` with mean extra docs <= {MAX_MEAN_EXTRA}; "
            "ties to fewer extra docs.", "", f"Selected: `{frozen}`", ""]
    for run in RUNS:
        s, base = all_stats[run][frozen], all_stats[run]["none"]
        out.append(f"- `{run}`: both gold {base['both']} -> {s['both']}/50, mean recall {base['recall']:.3f} -> "
                   f"{s['recall']:.3f}, triggered {s['trig']}/50, mean extra docs {s['extra']:.2f}, "
                   f"mean extra prompt tokens ~{s['tok']:.0f}")
    text = "\n".join(out) + "\n"
    (HERE / "analysis_output.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
