"""Parsing and scoring for the HotpotQA evaluation.

Exact match and F1 follow the official HotpotQA evaluation script (hotpot_evaluate_v1.py).
"""

from __future__ import annotations

import json
import random
import re
import string
from collections import Counter
from typing import List, Optional, Sequence, Tuple


def normalize_answer(s: str) -> str:
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def exact_match(prediction: str, gold: str) -> float:
    return float(normalize_answer(prediction) == normalize_answer(gold))


def f1(prediction: str, gold: str) -> float:
    pred, ref = normalize_answer(prediction), normalize_answer(gold)
    special = ("yes", "no", "noanswer")
    if (pred in special or ref in special) and pred != ref:
        return 0.0
    pred_tokens, ref_tokens = pred.split(), ref.split()
    num_same = sum((Counter(pred_tokens) & Counter(ref_tokens)).values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


ANSWER_RE = re.compile(r"answer\s*:\s*(.+)", re.IGNORECASE)


def parse_answer(reply: str) -> Tuple[str, bool]:
    """Return (answer, format_ok). Without an 'Answer:' line the whole reply is kept and format_ok is False."""
    matches = ANSWER_RE.findall(reply)
    if not matches:
        return reply.strip(), False
    answer = matches[-1].strip().strip("*_`\"' ").rstrip(".").strip()
    return answer, True


ROUTE_PARSER_VERSION = 3  # 2: bare comma-separated titles; 3: bare titles inside unquoted brackets


def parse_titles(reply: str, titles: Sequence[str], limit: int = 2) -> List[str]:
    """Return up to `limit` document titles the reply names exactly (case-insensitive).

    Accepts a JSON list, double-quoted titles, or bare comma/newline-separated titles.
    No substring matching: every candidate must equal a whole title, so a reply that names
    no exact title yields [] and is counted as a routing failure by the caller.
    """
    by_key = {t.strip().casefold(): t for t in titles}
    candidates: List[str] = []
    m = re.search(r"\[.*?\]", reply, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            candidates = [c for c in parsed if isinstance(c, str)]
        except json.JSONDecodeError:
            pass
    if not candidates:
        candidates = re.findall(r'"([^"\n]+)"', reply)
    if not candidates:
        # Bare list such as "Documents: Title A, Title B". Joining up to 3 consecutive
        # comma-separated parts lets titles that themselves contain commas still match exactly;
        # the longest match wins and its parts are not reused.
        body = re.sub(r"documents\s*:", "", reply, flags=re.IGNORECASE)
        parts = [p.strip().strip("[]").strip().strip("\"'").lstrip("-*• ").strip() for p in re.split(r"[,\n]", body)]
        i = 0
        while i < len(parts):
            for j in range(min(len(parts), i + 3), i, -1):
                joined = ", ".join(parts[i:j])
                if joined.casefold() in by_key or joined.casefold().rstrip(".") in by_key:
                    candidates.append(joined)
                    i = j
                    break
            else:
                i += 1
    selected: List[str] = []
    for c in candidates:
        key = c.strip().casefold()
        title = by_key.get(key) or by_key.get(key.rstrip("."))
        if title and title not in selected:
            selected.append(title)
        if len(selected) == limit:
            break
    return selected


def bootstrap_ci(diffs: Sequence[float], n_resamples: int = 10000, seed: int = 0) -> Optional[Tuple[float, float, float]]:
    """Mean and 95% percentile bootstrap interval of paired per-question differences."""
    if len(diffs) < 2:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples))
    return sum(diffs) / n, means[int(0.025 * n_resamples)], means[int(0.975 * n_resamples) - 1]
