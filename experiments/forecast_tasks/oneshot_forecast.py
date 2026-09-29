"""Phase A's one-shot, no-data comparator for card 022: the prompt only. Defined here, not run (slice 1 makes no model
call; the live call, through claude_cli.py's isolation and model pin with claude-sonnet-5 and 1 sample, is not built).

The prompt is metac-bot's pastcast build_prompt (the metac-bot-template binary prompt with the research left empty),
vendored verbatim below. Its provenance is pinned: PASTCAST_SOURCE names the file and commit, and
BUILD_PROMPT_SHA256 is the sha256 of the function's source with LF line endings, which a test recomputes. The
workspace question maps onto its fields: title and resolution criteria and fine print as written for the workspace
run; background says what the series is and that no data are given; today is the forecast date. The comparator sees
no data at all, so the phase A gate "the harness beats the one-shot by at least 0.02 Brier" measures what data and
process add.

  python experiments/forecast_tasks/oneshot_forecast.py --print fc-0706-dgs10-touch-h28   show one prompt
  python experiments/forecast_tasks/oneshot_forecast.py --manifest                       sha256 of every prompt
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
PASTCAST_SOURCE = {"repository": "grantprater/metac-bot", "path": "probe/pastcast.py", "commit": "f636603",
                   "file_sha256_lf": "513dbeb9c0f7786c665fbcea4a0e53d12cc7e4bc547aa6d680c1307b1b4439ed"}
BUILD_PROMPT_SHA256 = "f291dc184357ad3b7048598274195efec243f4849c374932c6032b2217cb1c7c"
MODEL = "claude-sonnet-5"
SAMPLES = 1
PROBABILITY = re.compile(r"Probability:\s*(\d+(?:\.\d+)?)\s*%")


# --- vendored verbatim from metac-bot probe/pastcast.py (see PASTCAST_SOURCE) ---
def build_prompt(q):
    # Verbatim structure of metac-bot-template main.py _run_forecast_on_binary, research left empty.
    return f"""You are a professional forecaster interviewing for a job.

Your interview question is:
{q['title']}

Question background:
{q['background']}


This question's outcome will be determined by the specific criteria below. These criteria have not yet been satisfied:
{q['criteria']}

{q.get('fine_print','')}


Your research assistant says:
{q.get('research','')}

Today is {q['today']}.

Before answering you write:
(a) The time left until the outcome to the question is known.
(b) The status quo outcome if nothing changed.
(c) A brief description of a scenario that results in a No outcome.
(d) A brief description of a scenario that results in a Yes outcome.

You write your rationale remembering that good forecasters put extra weight on the status quo outcome since the world changes slowly most of the time.


The last thing you write is your final answer as: "Probability: ZZ%", 0-100
"""
# --- end of vendored code ---


def build_prompt_sha256() -> str:
    return hashlib.sha256(inspect.getsource(build_prompt).replace("\r\n", "\n").encode("utf-8")).hexdigest()


def oneshot_question(task: dict) -> dict:
    """pastcast's question fields for a workspace task. The fine print drops the resolve.py sentence (there is no
    resolve.py in a one-shot reply)."""
    fine_print = task["fine_print"].split(" resolve.py's outcome", 1)[0]
    background = (f"The question is about the public daily time series {task['series']}. No data are provided with "
                  f"this question; answer from what you know.")
    return {"id": task["task_id"], "title": task["title"], "background": background, "criteria": task["criteria"],
            "fine_print": fine_print, "research": "", "today": task["forecast_date"]}


def oneshot_prompt(task: dict) -> str:
    return build_prompt(oneshot_question(task))


def parse_probability(reply: str):
    """pastcast's parse: the last "Probability: ZZ%", clipped to [0.01, 0.99]; None without one."""
    found = PROBABILITY.findall(reply or "")
    return max(0.01, min(0.99, float(found[-1]) / 100.0)) if found else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks.forecast.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", metavar="TASK_ID")
    group.add_argument("--manifest", action="store_true")
    args = parser.parse_args(argv)
    if build_prompt_sha256() != BUILD_PROMPT_SHA256:
        raise SystemExit("the vendored build_prompt differs from the pinned pastcast source")
    tasks = {t["task_id"]: t for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]}
    if args.print:
        print(oneshot_prompt(tasks[args.print]))
    else:
        print(json.dumps({"model": MODEL, "samples": SAMPLES, "build_prompt_sha256": BUILD_PROMPT_SHA256,
                          "pastcast_source": PASTCAST_SOURCE,
                          "prompts": {task_id: hashlib.sha256(oneshot_prompt(task).encode("utf-8")).hexdigest()
                                      for task_id, task in tasks.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
