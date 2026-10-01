"""Card 021 host smoke: one live reply to the commitment nudge on a stubbed mid-run transcript.

The transcript is built by hand, not by a run: the task prompt the runner gives (INSTRUCTIONS with the task's
statement), one earlier read_file call over the mutated function's region of the task's pre-edit tree (with its real
content, the situation the observation audit found in 17 of 22 hard rejections), and the commitment nudge's harness
message. The request goes through the runner's claude-cli client (adapter v3, reply recovery as in card 021's arms)
with the verifier-commit arm's tool list, one attempt. The reply's tool calls are then dispatched against a
CommitmentTools suite on a scratch copy of the tree, so a malformed commitment is visible as a rejection, and the
committed file and function are compared with the mutation offline.

Usage: python experiments/session_harness/smoke021_commit_reply.py --out DIR --task sqlparse-mut-057 \\
           --repos .runtime/bug-mining/repos --model claude-sonnet-5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(HERE))

import repro_verifiers  # noqa: E402
import run_pilot  # noqa: E402
from claude_cli import REPLY_RECOVERY, ClaudeCliClient  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.nudges import commit_nudge_text  # noqa: E402
from reticle.tools import ToolSuite  # noqa: E402
from reticle.tools.commitment import CommitmentLog, CommitmentTools  # noqa: E402
from score_commitments import function_matches  # noqa: E402

TREATMENT_ARGS = ["--verifier", "repro-test:3", "--verifier-manifest",
                  "experiments/session_harness/verifiers/021/manifest.json", "--nudge", "commit"]


def transcript(task: dict, tree: Path, window: int = 30) -> list:
    path = task["mutation_file"]
    lines = (tree / path).read_text(encoding="utf-8").splitlines()
    start = max(1, int(task["mutation_line"]) - window)
    end = min(len(lines), int(task["mutation_line"]) + window)
    shown = "\n".join(f"{number:>5}  {lines[number - 1]}" for number in range(start, end + 1))
    return [
        {"role": "user", "content": run_pilot.INSTRUCTIONS.format(repo=task["repo"], repo_url=task["repo_url"],
                                                                  statement=task["statement"])},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "read_file", "arguments": json.dumps({"path": path, "start_line": start, "end_line": end})}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": f"{path} lines {start}-{end} of {len(lines)}:\n{shown}"},
        {"role": "system", "content": commit_nudge_text(0.5)},
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-file", default="experiments/mutation_tasks/tasks.mutations.json")
    parser.add_argument("--repos", type=Path, default=run_pilot.REPOS)
    parser.add_argument("--model", required=True)
    parser.add_argument("--label", default="v1", help="names this attempt's files (the nudge text version)")
    args = parser.parse_args(argv)
    _, tasks = run_pilot.load_tasks([args.tasks_file, args.task])
    task = tasks[0]
    args.out.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="smoke021-"))
    try:
        tree = repro_verifiers.materialize(task, args.repos, temp / "workspace")
        messages = transcript(task, tree)
        tools = run_pilot.model_tool_schemas(run_pilot.treatments_from_args(TREATMENT_ARGS))
        calls_path = args.out / f"calls-{args.task}-{args.label}.jsonl"
        client = ClaudeCliClient(args.model, calls_path, f"smoke021-{args.task}",
                                 run_pilot.CallBudget(1, 0), max_attempts=1, timeout=300, max_turns=1,
                                 reply_recovery=REPLY_RECOVERY)
        reply = client.complete(messages, tools).message
        runtime = LocalRuntime(temp / "session", tree)
        suite = type("CommitSuite", (CommitmentTools, ToolSuite), {})(runtime, interpreter=sys.executable,
                                                                      commitment=CommitmentLog(runtime))
        outcomes = []
        for call in reply.get("tool_calls") or []:
            name = call["function"]["name"]
            if name in ("commit_hypothesis", "record_observation"):
                outcome = suite.dispatch(name, call["function"]["arguments"], call["id"])
                outcomes.append({"tool": name, "status": outcome.status, "content": outcome.content})
            else:
                outcomes.append({"tool": name, "status": "not dispatched (smoke)"})
        commits = [json.loads(c["function"]["arguments"]) for c in reply.get("tool_calls") or []
                   if c["function"]["name"] == "commit_hypothesis"]
        last = commits[-1] if commits else {}
        attempts = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        record = {
            "task_id": task["task_id"], "model": args.model, "nudge": commit_nudge_text(0.5),
            "messages": messages, "reply": reply, "dispatched": outcomes,
            "committed": bool(commits),
            "located_file": last.get("file") == task["mutation_file"],
            "located_function": function_matches(last.get("function"), task.get("mutated_function")),
            "line_distance": abs(int(last["line"]) - int(task["mutation_line"])) if isinstance(last.get("line"), int)
            else None,
            "cli_list_price_estimate_usd": sum(((a.get("cli_result") or {}).get("total_cost_usd") or 0)
                                               for a in attempts),
            "reported_model": [a.get("reported_model") for a in attempts],
        }
        (args.out / f"commit-reply-{task['task_id']}-{args.label}.json").write_text(json.dumps(record, indent=2) + "\n",
                                                                     encoding="utf-8", newline="\n")
        print(json.dumps({key: record[key] for key in ("task_id", "committed", "located_file", "located_function",
                                                        "line_distance", "cli_list_price_estimate_usd")}))
        print(json.dumps(outcomes)[:1500])
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
