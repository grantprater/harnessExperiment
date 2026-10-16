"""Card 022's memorisation probe (design section 3): does the model already know how the questions resolved?

One isolated question per bank question and per positive-control question (T in 2025, before the model's training
cutoff): the statement, no data, and the instruction to give the outcome only if it is known. Built; the live path runs
only with --live and has not been run.

  python experiments/forecast_tasks/probe_recall.py --print fc-0706-beijing-tmax-touch-h7     show one prompt
  python experiments/forecast_tasks/probe_recall.py --run --live --out DIR [--model claude-sonnet-5] [--limit N]
                                                    ask every question (bank, then positive control); ledger.jsonl
  python experiments/forecast_tasks/probe_recall.py --score DIR/ledger.jsonl --resolutions FILE --resolutions-sha256 X

Scoring (pre-registered in the design):
- An answer "names" an outcome when its OUTCOME line is YES or NO; UNKNOWN, a missing line or an unparseable reply does
  not. A named answer's probability is its PROBABILITY line (clipped to [0, 1]), else 1 or 0 for YES or NO.
- Leak rule, on the post-cutoff bank: stop and treat the bank as leaked when the model names an outcome for more than
  10% of questions AND its Brier on the named questions is lower than gold's (the history-only base rate) on the same
  questions.
- Sensitivity, on the positive control: the probe can detect recall only if the model names some control outcomes
  and is right more often than chance (more than half of the named ones) with a Brier below gold's there; otherwise
  the report says the probe is insensitive and no "no leakage" claim may be made.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import score_forecasts  # noqa: E402

PROMPT_VERSION = "recall-v1"
PROMPT = (
    "This is a memory check, not a forecast. The yes/no question below was asked on {forecast_date} and has "
    "already resolved. If you know or remember how it resolved, give the outcome and your probability that it "
    "resolved YES. If you do not know the outcome, answer UNKNOWN; do not estimate it from the question itself.\n\n"
    "{title}\n\n{criteria}\n\n"
    "End your reply with exactly these two lines:\n"
    "OUTCOME: YES, NO or UNKNOWN\n"
    "PROBABILITY: your probability from 0 to 1 that it resolved YES (0.5 if UNKNOWN)"
)
OUTCOME = re.compile(r"^\s*\**OUTCOME\**\s*:\s*\**\s*(YES|NO|UNKNOWN)\b", re.IGNORECASE | re.MULTILINE)
PROBABILITY = re.compile(r"^\s*\**PROBABILITY\**\s*:\s*\**\s*([0-9]*\.?[0-9]+)\s*(%?)", re.IGNORECASE | re.MULTILINE)
LEAK_NAMED_RATE = 0.10


def prompt(question: dict) -> str:
    return PROMPT.format(forecast_date=question["forecast_date"], title=question["title"],
                         criteria=question["criteria"])


def parse(reply: str) -> dict:
    """{"named": bool, "outcome": True/False/None, "probability": float or None} from the last OUTCOME and
    PROBABILITY lines."""
    outcomes = OUTCOME.findall(reply or "")
    label = outcomes[-1].upper() if outcomes else None
    if label not in ("YES", "NO"):
        return {"named": False, "outcome": None, "probability": None}
    probability = None
    found = PROBABILITY.findall(reply or "")
    if found:
        number, percent = found[-1]
        probability = min(1.0, max(0.0, float(number) / (100.0 if percent else 1.0)))
    if probability is None:
        probability = 1.0 if label == "YES" else 0.0
    return {"named": True, "outcome": label == "YES", "probability": probability}


def questions(tasks_path: Path, control_path: Path) -> list:
    """[(set, question)]: the bank (post-cutoff), then the positive control (2025)."""
    bank = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
    control = json.loads(control_path.read_text(encoding="utf-8"))["questions"]
    return [("bank", q) for q in bank] + [("control", q) for q in control]


def summarise(entries, outcomes: dict) -> dict:
    """entries: [{"task_id", "parsed", "base_rate"}]; outcomes: {task_id: bool}."""
    named = [e for e in entries if e["parsed"]["named"]]
    summary = {"questions": len(entries), "named": len(named),
               "named_rate": len(named) / len(entries) if entries else 0.0}
    if named:
        truth = [outcomes[e["task_id"]] for e in named]
        summary["named_correct"] = sum(e["parsed"]["outcome"] == t for e, t in zip(named, truth))
        summary["named_brier"] = sum(score_forecasts.brier(e["parsed"]["probability"], t)
                                     for e, t in zip(named, truth)) / len(named)
        summary["gold_brier_same_questions"] = sum(score_forecasts.brier(e["base_rate"], t)
                                                   for e, t in zip(named, truth)) / len(named)
    return summary


def verdict(bank: dict, control: dict) -> dict:
    leaked = (bank["named_rate"] > LEAK_NAMED_RATE and bank.get("named_brier", 1.0)
              < bank.get("gold_brier_same_questions", 0.0))
    sensitive = (control["named"] > 0 and control.get("named_correct", 0) > control["named"] / 2
                 and control.get("named_brier", 1.0) < control.get("gold_brier_same_questions", 0.0))
    if leaked:
        text = "leaked: stop the card and treat the bank as known to the model"
    elif sensitive:
        text = "no leakage detected by a probe that detects recall on the positive control"
    else:
        text = "probe insensitive (no recall shown on the positive control): no claim about leakage either way"
    return {"leaked": leaked, "sensitive": sensitive, "verdict": text}


def score(ledger_path: Path, outcomes: dict, control_outcomes: dict) -> dict:
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sets = {"bank": [], "control": []}
    for row in rows:
        sets[row["set"]].append({"task_id": row["task_id"], "parsed": parse(row.get("reply", "")),
                                 "base_rate": row["base_rate"]})
    bank = summarise(sets["bank"], outcomes)
    control = summarise(sets["control"], control_outcomes)
    return {"bank": bank, "control": control, **verdict(bank, control)}


def load_outcomes(path: Path, expected_sha256: str):
    """(bank outcomes, control outcomes) from the sealed file, after checking its pinned sha256."""
    actual = score_forecasts.lf_sha256(path)
    if actual != expected_sha256:
        raise SystemExit(f"{path}: sha256 {actual} is not the pinned {expected_sha256}; nothing scored")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ({k: bool(v["outcome"]) for k, v in data["resolutions"].items()},
            {k: bool(v["outcome"]) for k, v in data.get("recall_control", {}).items()})


def run(out_dir: Path, model: str, limit=None, executable: str = "claude") -> Path:
    """Ask every question once (live). Resumes: questions already in the ledger are skipped."""
    import cli_ask
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "ledger.jsonl"
    done = {json.loads(line)["task_id"] for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()} if ledger.exists() else set()
    items = questions(HERE / "tasks.forecast.json", HERE / "recall_control.json")[:limit]
    budget = cli_ask.AttemptBudget(cli_ask.MAX_ATTEMPTS * len(items))
    for which, question in items:
        if question["task_id"] in done:
            continue
        text = prompt(question)
        answer = cli_ask.ask(text, model=model, calls_path=out_dir / "calls.jsonl",
                             run_id=f"recall-{question['task_id']}", budget=budget, executable=executable)
        row = {"set": which, "task_id": question["task_id"], "base_rate": question["base_rate"],
               "prompt_version": PROMPT_VERSION, "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), **answer,
               "parsed": parse(answer["reply"])}
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return ledger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", metavar="TASK_ID")
    group.add_argument("--run", action="store_true")
    group.add_argument("--score", type=Path, metavar="LEDGER")
    parser.add_argument("--live", action="store_true", help="required with --run: it calls the model")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resolutions", type=Path)
    parser.add_argument("--resolutions-sha256")
    args = parser.parse_args(argv)
    if args.print:
        found = {q["task_id"]: q for _, q in questions(HERE / "tasks.forecast.json", HERE / "recall_control.json")}
        print(prompt(found[args.print]))
    elif args.run:
        if not args.live or not args.out:
            raise SystemExit("--run calls the model: pass --live and --out DIR")
        print(run(args.out, args.model, args.limit))
    else:
        if not args.resolutions or not args.resolutions_sha256:
            raise SystemExit("--score needs --resolutions and --resolutions-sha256")
        print(json.dumps(score(args.score, *load_outcomes(args.resolutions, args.resolutions_sha256)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
