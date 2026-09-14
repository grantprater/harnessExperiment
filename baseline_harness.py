"""Baseline (Unfoveated) Agent Harness.

Provides standard, non-foveated tools:
- read_file(file_path): Dumps the entire file contents at once.
- replace_lines(...)
- run_command(...)

Used as the control experiment to compare against the Foveated (outline+saccade) harness.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness import Environment, LLMClient


BASELINE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the entire contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to file."}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "Replace a range of lines with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to file."},
                    "start_line": {"type": "integer", "description": "Start line (inclusive)."},
                    "end_line": {"type": "integer", "description": "End line (inclusive)."},
                    "new_content": {"type": "string", "description": "Exact replacement string."}
                },
                "required": ["file_path", "start_line", "end_line", "new_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run shell verification command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command line."}
                },
                "required": ["cmd"]
            }
        }
    }
]


def run_baseline(task: str, verify_cmd: str, max_steps: int = 6):
    env = Environment(root_dir=Path(__file__).parent)
    client = LLMClient() # Loads liquid/lfm-2.5-2.6b:free from .env

    print(f"\n[Baseline Harness - Unfoveated] Model: {client.model}")
    print(f"Task: {task}")
    print(f"Verification: {verify_cmd}\n")

    system_prompt = (
        "You are a software engineer. Fix bugs by using read_file to inspect files, "
        "replace_lines to edit code, and run_command to verify."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Task: {task}\n"
                f"Verification Command: {verify_cmd}\n"
                "Project files: project_bench/models.py, project_bench/pricing.py, project_bench/checkout.py\n\n"
                "Inspect files using read_file, fix the bug, and verify with run_command."
            )
        }
    ]

    solved = False
    step = 0
    total_tokens_approx = 0

    while step < max_steps and not solved:
        step += 1
        print(f"[Step {step}/{max_steps}] Calling LLM...")

        resp = client.chat_completion(messages, tools=BASELINE_TOOLS)
        content = resp["content"]
        tool_calls = resp["tool_calls"]

        if content:
            print(f"  [Thought]: {content[:120]}...")

        if not tool_calls:
            res = env.run_command(verify_cmd)
            if res["passed"]:
                print("  [Verification]: Passed!")
                solved = True
                break
            else:
                messages.append({"role": "assistant", "content": content or "Checking..."})
                messages.append({"role": "user", "content": f"Failing:\n{res['stderr'] or res['stdout']}"})
                continue

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}
            print(f"  -> Actuating Tool: {fn}({args})")

            if fn == "read_file":
                p = env.root / args.get("file_path", "")
                if p.exists():
                    out = p.read_text(encoding="utf-8")
                else:
                    out = f"Error: {p} not found."
            elif fn == "replace_lines":
                out = env.replace_lines(
                    args.get("file_path", ""),
                    args.get("start_line", 1),
                    args.get("end_line", 1),
                    args.get("new_content", "")
                )
            elif fn == "run_command":
                cmd_res = env.run_command(args.get("cmd", verify_cmd))
                out = f"Exit: {cmd_res['exit_code']}\nStdout: {cmd_res['stdout']}\nStderr: {cmd_res['stderr']}"
                if cmd_res["passed"] and args.get("cmd") == verify_cmd:
                    solved = True
            else:
                out = f"Unknown tool {fn}"

            print(f"     [Result preview]: {out[:80]}... ({len(out)} chars)")
            messages.append({"role": "tool", "tool_call_id": tc.get("id", "call_1"), "content": out})

    print(f"\n[Baseline Result]: Solved: {solved} in {step} steps.")
    return solved


if __name__ == "__main__":
    task = (
        "In the billing pipeline in project_bench, sales tax is being incorrectly computed on the "
        "pre-discount subtotal instead of the post-discount taxable amount when promo codes are used. "
        "Find the bug across the project files, fix it, and ensure all 6 unit tests pass."
    )
    cmd = f"{sys.executable} -m unittest project_bench/test_suite.py"
    run_baseline(task, cmd)
