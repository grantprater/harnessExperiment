"""Live subscription control: Reticle writes and verifies a file in a fresh workspace.

Run with --model set to a slug from chatgpt_auth models. At most five requests.
All session evidence stays in the ignored .runtime directory.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.cognitive.chatgpt_subscription import ChatGPTSubscriptionClient
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits
from reticle.tools import ToolSuite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    runtime_root = ROOT / ".runtime"
    runtime_root.mkdir(exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="subscription-smoke-", dir=runtime_root))
    workspace = run_root / "workspace"
    workspace.mkdir()
    runtime = LocalRuntime(run_root / "session", workspace)
    task = TaskEnvelope(
        task_id="subscription-smoke",
        description='Write ready.txt with exactly "subscription-ok\\n", read it back to verify the contents, '
                    'then call finish. Use write_file, read_file, and finish only.',
        criteria=[{"id": "ready-file", "kind": "executable", "visibility": "visible"}],
        budgets={"model_responses": 5, "model_attempts": 5, "tool_actions": 8},
    )
    client = ChatGPTSubscriptionClient(args.model, calls_path=run_root / "calls.jsonl", run_id="subscription-smoke")
    tools = ToolSuite(runtime, interpreter=sys.executable)
    result = AgentController(runtime, task, tools, client, AgentLimits(5, 60_000)).run()
    candidate = workspace / "ready.txt"
    passed = (result.stop_reason == "finish_requested" and candidate.exists()
              and candidate.read_bytes() == b"subscription-ok\n")
    report = {"passed": passed, "model": args.model, "run_dir": str(run_root), "agent": asdict(result)}
    (run_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
