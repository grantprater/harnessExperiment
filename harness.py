"""Cognitive Harness (Reticle Prototype).

Implements:
1. Macro/Foveated Perception (AST Outlines -> Saccade Region Inspection).
2. Two-Phase Operational Loop:
   - Phase 1: Generative ('Make it work') until validation passes.
   - Phase 2: Compaction ('Make it elegant') to prune boilerplate and enforce taste.
3. Predictive Coding: Pre-action prediction commitment and zero-surprise evaporation.
4. Episodic Tracing: Structured JSON logging to ./traces/ for future CLS consolidation.
5. Zero-dependency HTTP client compatible with OpenAI, Gemini (OpenAI compat), Ollama, Groq.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from perception import extract_outline, extract_symbol, inspect_region, list_symbols


MAX_INLINE_RESULT_CHARS = 8_000


def _inline_preview(value: str, limit: int = MAX_INLINE_RESULT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n[truncated: {len(value) - limit} characters omitted]"


# ============================================================================
# 1. Epistemic Trace & State Dataclasses
# ============================================================================

@dataclass
class ToolCallRecord:
    tool: str
    args: Dict[str, Any]
    result_preview: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class EpisodicTrace:
    trace_id: str
    task: str
    timestamp: float
    total_steps: int
    actions: List[Dict[str, Any]]
    success: bool
    phase1_steps: int
    phase2_executed: bool
    phase2_succeeded: Optional[bool] = None
    rollback_succeeded: Optional[bool] = None
    notes: str = ""

    def save(self, trace_dir: str | Path = "traces"):
        path = Path(trace_dir)
        path.mkdir(parents=True, exist_ok=True)
        out_file = path / f"{self.trace_id}.json"
        out_file.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        print(f"[Trace] Episodic trace logged to {out_file.name}")


# ============================================================================
# 2. Tool Environment & Actuation
# ============================================================================

class Environment:
    def __init__(self, root_dir: str | Path = "."):
        self.root = Path(root_dir).resolve()

    def outline(self, file_path: str, mode: str = "semantic") -> str:
        return extract_outline(self.root / file_path, mode=mode)

    def symbol(self, file_path: str, symbol_name: str) -> str:
        return extract_symbol(self.root / file_path, symbol_name)

    def saccade(self, file_path: str, start_line: int, end_line: int) -> str:
        return inspect_region(self.root / file_path, start_line, end_line)

    def replace_lines(
        self, file_path: str, start_line: int, end_line: int, new_content: str
    ) -> str:
        path = self.root / file_path
        if not path.exists():
            return f"Error: {file_path} does not exist."
        
        lines = path.read_text(encoding="utf-8").splitlines()
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            return f"Error: Invalid line range {start_line}-{end_line} (total lines: {len(lines)})."

        # Auto-indent guard: If the original line has leading indentation and
        # replacement line is completely unindented, preserve base indentation.
        target_orig = lines[start_line - 1]
        orig_indent = len(target_orig) - len(target_orig.lstrip())

        raw_replacement = new_content.splitlines()
        replacement = []
        for r_line in raw_replacement:
            if r_line.strip() and (len(r_line) - len(r_line.lstrip())) == 0 and orig_indent > 0:
                replacement.append(" " * orig_indent + r_line)
            else:
                replacement.append(r_line)

        new_lines = lines[:start_line - 1] + replacement + lines[end_line:]
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return f"Success: Replaced lines {start_line}-{end_line} in {file_path} ({len(replacement)} lines written)."

    def run_command(self, cmd: str) -> Dict[str, Any]:
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "passed": res.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "Timeout expired (30s)", "passed": False}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e), "passed": False}


def load_dotenv(paths=(".env", "../../.env", "../.env")):
    for p_str in paths:
        p = Path(p_str)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("$env:"):
                        k = k[5:]
                    elif k.startswith("export "):
                        k = k[7:]
                    os.environ[k.strip()] = v.strip().strip("\"'")
            break

load_dotenv()


# ============================================================================
# 3. Minimal OpenAI-Compatible HTTP Client (Zero Dependencies)
# ============================================================================

class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().replace("$env:", "")
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or "mock_key"
        )
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENROUTER_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta/openai/"
        ).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("MODEL") or "gemini-3.6-flash"
        self.mock_mode = (self.api_key == "mock_key")

    def chat_completion(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if self.mock_mode:
            return {
                "content": "Mock mode: LLM_API_KEY not configured. Simulating response.",
                "tool_calls": []
            }

        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/grant/reticle",
            "X-Title": "Reticle-Cognitive-Harness"
        }

        max_retries = 4
        for attempt in range(max_retries):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if "choices" not in data:
                        err_msg = json.dumps(data)
                        if ("502" in err_msg or "overloaded" in err_msg or "rate-limited" in err_msg) and attempt < max_retries - 1:
                            wait_sec = (attempt + 1) * 3
                            print(f"  [Retry {attempt+1}/{max_retries}] Upstream busy, waiting {wait_sec}s...")
                            time.sleep(wait_sec)
                            continue
                        raise RuntimeError(f"OpenRouter/LLM error response: {err_msg}")
                    choice = data["choices"][0]["message"]
                    return {
                        "content": choice.get("content") or "",
                        "tool_calls": choice.get("tool_calls") or []
                    }
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                if e.code in (502, 503, 429) and attempt < max_retries - 1:
                    wait_sec = (attempt + 1) * 3
                    print(f"  [Retry {attempt+1}/{max_retries}] HTTP {e.code}, waiting {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                raise RuntimeError(f"HTTP Error {e.code}: {err_body}")
            except Exception as e:
                if attempt < max_retries - 1 and ("502" in str(e) or "overloaded" in str(e)):
                    wait_sec = (attempt + 1) * 3
                    print(f"  [Retry {attempt+1}/{max_retries}] Network busy, waiting {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                raise RuntimeError(f"API/Network error: {e}")
        raise RuntimeError("Max retries exceeded.")


# ============================================================================
# 4. Tool Definitions Schema
# ============================================================================

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "outline",
            "description": "Macro Sensor: View compressed symbol outline (classes, functions, line numbers) of a file. Automatically inlines full source for small files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to file."},
                    "mode": {"type": "string", "enum": ["semantic", "bare", "folded"], "description": "Outline detail level (default: semantic)."}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_symbol",
            "description": "Mesoscopic Sensor: Inspect the exact definition of a named class or function (e.g. 'calculate_tax' or 'Calculator.add') with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to file."},
                    "symbol_name": {"type": "string", "description": "Name of the class, function, or method to inspect."}
                },
                "required": ["file_path", "symbol_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "saccade",
            "description": "Foveated Saccade: Inspect a precise line range of a file with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to file."},
                    "start_line": {"type": "integer", "description": "Start line (1-indexed)."},
                    "end_line": {"type": "integer", "description": "End line (1-indexed)."}
                },
                "required": ["file_path", "start_line", "end_line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "Actuation: Replace a range of lines with new content.",
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
            "description": "Run shell verification command (e.g. pytest or python script).",
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


# ============================================================================
# 5. Cognitive Loop Engine
# ============================================================================

class CognitiveHarness:
    def __init__(self, env: Environment, client: Optional[LLMClient] = None):
        self.env = env
        self.client = client or LLMClient()

    def _dispatch_tool(
        self,
        fn_name: str,
        args: Dict[str, Any],
        target_file: Optional[str],
        verify_cmd: str
    ) -> Tuple[str, bool]:
        """Dispatch tool call to environment and return (result_preview, is_solved)."""
        target = args.get("file_path", target_file)
        if fn_name == "outline":
            return self.env.outline(target, mode=args.get("mode", "semantic")), False
        if fn_name in ("view_symbol", "symbol"):
            return self.env.symbol(target, args.get("symbol_name", "")), False
        if fn_name == "saccade":
            return self.env.saccade(target, args.get("start_line", 1), args.get("end_line", 20)), False
        if fn_name == "replace_lines":
            return self.env.replace_lines(target, args.get("start_line", 1), args.get("end_line", 1), args.get("new_content", "")), False
        if fn_name == "run_command":
            cmd = args.get("cmd", verify_cmd)
            cmd_res = self.env.run_command(cmd)
            stdout = _inline_preview(cmd_res["stdout"]) or "(empty)"
            stderr = _inline_preview(cmd_res["stderr"]) or "(empty)"
            return (
                f"Exit: {cmd_res['exit_code']}\nStdout:\n{stdout}\nStderr:\n{stderr}",
                cmd_res["passed"] and cmd == verify_cmd,
            )
        return f"Unknown tool: {fn_name}", False

    def run(
        self,
        task: str,
        verify_cmd: str,
        target_file: Optional[str] = None,
        project_dir: Optional[str] = None,
        max_phase1_steps: int = 8,
        editorial_pass: bool = False,
    ) -> EpisodicTrace:
        trace_id = f"tr_{int(time.time() * 1000) % 1000000:06d}"
        actions_log: List[Dict[str, Any]] = []

        print(f"\n[Cognitive Harness] Starting Task [{trace_id}]: {task}")
        print(f"[Verification Target]: {verify_cmd}")

        # Multi-File Peripheral Perception: Generate outlines across all relevant files
        outlines = []
        if project_dir:
            p_path = self.env.root / project_dir
            py_files = sorted([f for f in p_path.glob("*.py") if not f.name.startswith("test_")])
            for f in py_files:
                rel = str(f.relative_to(self.env.root)).replace("\\", "/")
                outlines.append(f"--- Macro Outline: {rel} ---\n" + self.env.outline(rel))
            initial_outline = "\n\n".join(outlines)
        elif target_file:
            initial_outline = self.env.outline(target_file)
        else:
            initial_outline = "No target file specified. Use 'outline' tool to inspect files."

        system_prompt = (
            "You are an elite, parsimonious software engineer. Follow these cognitive rules:\n"
            "1. Coarse-to-fine perception: Use macro outlines to orient across files, and 'saccade' to zoom into specific lines.\n"
            "2. Predictive coding: State your hypothesis briefly before modifying files or running commands.\n"
            "3. Economy: Solve tasks with the minimum code required. Do not inspect files that are clearly irrelevant.\n"
            "4. Code formatting: Preserve exact required indentation (e.g. 4 spaces for function bodies) when modifying lines."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Task: {task}\n"
                    f"Verification Command: {verify_cmd}\n\n"
                    f"Macro Outlines of Project:\n{initial_outline}\n\n"
                    "Identify the file and function causing the issue, inspect it with 'saccade', apply the fix with 'replace_lines', and verify with 'run_command'."
                )
            }
        ]

        # ================================================================
        # PHASE 1: GENERATIVE ("Make It Work")
        # ================================================================
        print("\n--- PHASE 1: GENERATIVE (Make It Work) ---")
        phase1_solved = False
        step = 0

        while step < max_phase1_steps and not phase1_solved:
            step += 1
            print(f"\n[Step {step}/{max_phase1_steps}] Calling LLM...")
            
            if self.client.mock_mode:
                print("  [Mock Mode] Demonstrating perception and verification flow.")
                actions_log.append({"step": step, "type": "mock", "detail": "Simulation step"})
                phase1_solved = True
                break

            response = self.client.chat_completion(messages, tools=TOOL_SCHEMAS)
            content = response["content"]
            tool_calls = response["tool_calls"]

            if content:
                print(f"  [Model Thought]: {content[:140]}...")

            if not tool_calls:
                # Check if verification command passes
                verify_res = self.env.run_command(verify_cmd)
                if verify_res["passed"]:
                    print("  [Verification]: PASSED!")
                    phase1_solved = True
                    break
                else:
                    messages.append({"role": "assistant", "content": content or "Verifying..."})
                    messages.append({"role": "user", "content": f"Tests failing:\n{verify_res['stderr'] or verify_res['stdout']}"})
                    continue

            # Sort tool calls so multiple replace_lines on the same file run bottom-to-top
            # (prevents top insertions from shifting line offsets for lower replacements)
            def tool_sort_key(tc):
                if tc.get("function", {}).get("name") == "replace_lines":
                    try:
                        t_args = json.loads(tc["function"]["arguments"])
                        return (0, t_args.get("file_path", ""), -t_args.get("start_line", 0))
                    except Exception:
                        pass
                return (1, "", 0)

            tool_calls = sorted(tool_calls, key=tool_sort_key)

            # Append the assistant message with all tool calls
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            # Process and append each tool result
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                print(f"  -> Actuating Tool: {fn_name}({args})")

                result_str, call_solved = self._dispatch_tool(fn_name, args, target_file, verify_cmd)
                if call_solved:
                    phase1_solved = True

                actions_log.append({"tool": fn_name, "args": args, "result_preview": result_str[:100]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", "call_default"),
                    "content": result_str
                })

            # A verification earlier in a batch cannot certify later mutations.
            batch_verification = self.env.run_command(verify_cmd)
            phase1_solved = batch_verification["passed"]
            if not phase1_solved:
                messages.append({
                    "role": "user",
                    "content": (
                        "Final verification for this action batch failed:\n"
                        f"{batch_verification['stderr'] or batch_verification['stdout']}"
                    ),
                })

        # ================================================================
        # PHASE 2: COMPACTION ("Make It Elegant / Taste Pass")
        # ================================================================
        final_res = self.env.run_command(verify_cmd)
        phase1_solved = final_res["passed"]
        phase2_executed = False
        phase2_succeeded: Optional[bool] = None
        rollback_succeeded: Optional[bool] = None
        trace_notes = ""
        if editorial_pass and phase1_solved and not self.client.mock_mode:
            phase2_executed = True
            print("\n--- PHASE 2: COMPACTION (Taste / Editorial Refactor) ---")
            compaction_prompt = (
                "The task is functionally solved and verified. Now perform the EDITORIAL TASTE PASS:\n"
                "1. Inspect your changes. Can any lines, temporary variables, or verbose abstractions be pruned?\n"
                "2. Make the code more idiomatic and parsimonious.\n"
                "3. Re-run verification to ensure tests remain 100% green."
            )
            messages.append({"role": "user", "content": compaction_prompt})
            
            refactor_resp = self.client.chat_completion(messages, tools=TOOL_SCHEMAS)
            snapshots: Dict[Path, Optional[bytes]] = {}
            if refactor_resp["tool_calls"]:
                for tc in refactor_resp["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    if fn_name == "replace_lines":
                        target = (self.env.root / args["file_path"]).resolve()
                        if target not in snapshots:
                            snapshots[target] = target.read_bytes() if target.exists() else None
                        self.env.replace_lines(args["file_path"], args["start_line"], args["end_line"], args["new_content"])
                        actions_log.append({"phase": 2, "tool": fn_name, "args": args})

            # Final verification
            final_res = self.env.run_command(verify_cmd)
            phase2_succeeded = final_res["passed"]
            if not phase2_succeeded:
                rollback_errors: List[str] = []
                for target, content in snapshots.items():
                    try:
                        if content is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_bytes(content)
                    except Exception as exc:
                        rollback_errors.append(f"{target}: {exc}")
                rollback_check = self.env.run_command(verify_cmd)
                rollback_succeeded = not rollback_errors and rollback_check["passed"]
                final_res = rollback_check
                if rollback_errors:
                    trace_notes = "Editorial rollback failed: " + "; ".join(rollback_errors)
                elif not rollback_check["passed"]:
                    trace_notes = "Editorial files restored, but verification after rollback failed."
            print(f"  [Phase 2 Verification]: {'Green (Preserved)' if phase2_succeeded else 'Failed (Rolled Back)'}")

        final_success = final_res["passed"]

        # ================================================================
        # EPISODIC LOGGING (Save to /traces/)
        # ================================================================
        trace = EpisodicTrace(
            trace_id=trace_id,
            task=task,
            timestamp=time.time(),
            total_steps=step,
            actions=actions_log,
            success=final_success,
            phase1_steps=step,
            phase2_executed=phase2_executed,
            phase2_succeeded=phase2_succeeded,
            rollback_succeeded=rollback_succeeded,
            notes=trace_notes,
        )
        trace.save(self.env.root / "traces")
        return trace


# ============================================================================
# 6. CLI Entrypoint & Demo Runner
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cognitive Harness Runner")
    parser.add_argument(
        "--experiment",
        choices=["greenfield", "multi", "sample"],
        default="greenfield",
        help="Experiment to run: 'greenfield' (infill from skeleton), 'multi' (billing bug), 'sample' (toy calculator)"
    )
    parser.add_argument("--steps", type=int, default=10, help="Max steps for phase 1")
    args = parser.parse_args()

    current_dir = Path(__file__).parent
    env = Environment(root_dir=current_dir)
    harness = CognitiveHarness(env=env)

    if args.experiment == "greenfield":
        task = (
            "Greenfield Implementation: Implement the missing methods marked with 'raise NotImplementedError' "
            "in greenfield_bench/models.py and greenfield_bench/engine.py. "
            "Follow the docstring contracts, use 'saccade' to inspect the stubs, use 'replace_lines' to implement them, "
            "and verify that all 5 unit tests pass."
        )
        verify_cmd = f"{sys.executable} -m unittest greenfield_bench/test_suite.py"
        trace = harness.run(
            task=task,
            verify_cmd=verify_cmd,
            project_dir="greenfield_bench",
            max_phase1_steps=args.steps
        )
    elif args.experiment == "multi":
        task = (
            "In the billing pipeline, sales tax is being incorrectly computed on the pre-discount "
            "subtotal instead of the post-discount taxable amount when promo codes are used. "
            "Find the bug across the project files, fix it, and ensure all 6 unit tests pass."
        )
        verify_cmd = f"{sys.executable} -m unittest project_bench/test_suite.py"
        trace = harness.run(
            task=task,
            verify_cmd=verify_cmd,
            project_dir="project_bench",
            max_phase1_steps=args.steps
        )
    else:
        task = "Fix the discount calculation bug in calculate_discount() so price with discount_percent calculates properly."
        verify_cmd = f"{sys.executable} test_calculator.py"
        trace = harness.run(
            task=task,
            verify_cmd=verify_cmd,
            target_file="sample_calculator.py",
            max_phase1_steps=args.steps
        )

    print(f"\n[Done] Experiment '{args.experiment}' completed.")
