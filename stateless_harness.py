"""Stateless Blank-Slate Epistemic Harness (Reticle Core).

Implements the "Notes-as-State, Tools-as-Opcodes" cognitive architecture:
1. Blank-Slate Calls: Each model invocation receives a freshly synthesized
   epistemic packet instead of an append-only conversational transcript.
2. Falsification Ledger: Explicit negative knowledge (what failed and why)
   monotonically prunes search trees and prevents circular attempts.
3. Grounding Pointers: Holds addresses (file:lines, AST symbols, bounding boxes)
   rather than lossy sensory caricatures.
4. Dynamic Tool Synthesizer: Allows the agent to write and register ad-hoc
   Python tools at runtime, converting probabilistic reasoning into
   deterministic execution.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from perception import extract_outline, extract_symbol, inspect_region


# ============================================================================
# 1. Epistemic Ledgers (Negative Knowledge, Grounding Pointers, Tools)
# ============================================================================

@dataclass
class FalsificationRecord:
    id: str
    hypothesis: str
    action_taken: str
    rejection_evidence: str
    step: int


class FalsificationLedger:
    """Records falsified paths, failed actions, and negative hypothesis tests."""

    def __init__(self):
        self.records: List[FalsificationRecord] = []

    def record(self, hypothesis: str, action_taken: str, rejection_evidence: str, step: int) -> FalsificationRecord:
        rec_id = f"f_{len(self.records) + 1:02d}"
        rec = FalsificationRecord(
            id=rec_id,
            hypothesis=hypothesis.strip(),
            action_taken=action_taken.strip(),
            rejection_evidence=rejection_evidence.strip(),
            step=step
        )
        self.records.append(rec)
        return rec

    def render_view(self) -> str:
        if not self.records:
            return "No falsified paths recorded yet."
        lines = [
            "| ID | Step | Falsified Hypothesis | Action Attempted | Rejection Evidence |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ]
        for r in self.records:
            ev = r.rejection_evidence.replace("\n", " ")[:60]
            lines.append(f"| `{r.id}` | {r.step} | {r.hypothesis} | `{r.action_taken}` | {ev} |")
        return "\n".join(lines)


@dataclass
class GroundingPointer:
    id: str
    target: str          # e.g. "sample_calculator.py"
    locator: str         # e.g. "L8-L15" or "def calculate_discount"
    description: str     # e.g. "Percentage calculation defect"
    verified: bool = True


class GroundingLedger:
    """Maintains precise spatial/symbolic coordinates into the raw environment."""

    def __init__(self):
        self.pointers: List[GroundingPointer] = []

    def record_pointer(self, target: str, locator: str, description: str, verified: bool = True) -> GroundingPointer:
        # Deduplicate or update existing target+locator
        for p in self.pointers:
            if p.target == target and p.locator == locator:
                p.description = description
                p.verified = verified
                return p
        ptr_id = f"ptr_{len(self.pointers) + 1:02d}"
        ptr = GroundingPointer(
            id=ptr_id,
            target=target.strip(),
            locator=locator.strip(),
            description=description.strip(),
            verified=verified
        )
        self.pointers.append(ptr)
        return ptr

    def render_view(self) -> str:
        if not self.pointers:
            return "No grounding pointers established yet."
        lines = [
            "| ID | Target File / Entity | Locator (Lines/Symbol) | Semantic Role | Verified |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ]
        for p in self.pointers:
            lines.append(f"| `{p.id}` | `{p.target}` | `{p.locator}` | {p.description} | {'Yes' if p.verified else 'No'} |")
        return "\n".join(lines)


# ============================================================================
# 2. Dynamic Tool Synthesizer (Executable Notes)
# ============================================================================

class DynamicToolRegistry:
    """Enables runtime synthesis and execution of ad-hoc Python tools."""

    def __init__(self):
        self.tools: Dict[str, Callable[..., Any]] = {}
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.tool_sources: Dict[str, str] = {}

    def register_tool(
        self,
        name: str,
        code: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """Compile and register an ad-hoc Python tool."""
        # 1. Syntactic validation via Python AST compiler
        try:
            parsed = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError in synthesized tool code: {e}"

        # Ensure function with given name exists in the code
        fn_nodes = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        matching_nodes = [node for node in fn_nodes if node.name == name]
        if not matching_nodes:
            available = [n.name for n in fn_nodes]
            return False, f"Code does not define top-level function '{name}'. Found: {available}"

        # 2. Execution environment sandbox
        local_scope: Dict[str, Any] = {}
        try:
            # Provide standard modules
            safe_globals = {
                "__builtins__": __builtins__,
                "os": os,
                "sys": sys,
                "json": json,
                "Path": Path,
                "re": __import__("re"),
                "math": __import__("math")
            }
            exec(code, safe_globals, local_scope)
        except Exception as e:
            return False, f"Evaluation error during tool registration: {e}"

        fn = local_scope.get(name)
        if not callable(fn):
            return False, f"Target '{name}' is not callable."

        # 3. Store callable and construct schema
        self.tools[name] = fn
        self.tool_sources[name] = code

        schema_params = parameters or {
            "type": "object",
            "properties": {},
            "required": []
        }
        self.schemas[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": f"[Synthesized Tool] {description}",
                "parameters": schema_params
            }
        }
        return True, f"Successfully registered dynamic tool '{name}'."

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Execute a registered ad-hoc tool."""
        if name not in self.tools:
            return f"Error: Synthesized tool '{name}' not found in registry."
        try:
            fn = self.tools[name]
            result = fn(**args)
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2)
            return str(result)
        except Exception as e:
            return f"Error executing tool '{name}': {type(e).__name__}: {e}"

    def get_schemas(self) -> List[Dict[str, Any]]:
        return list(self.schemas.values())

    def render_view(self) -> str:
        if not self.schemas:
            return "No synthesized tools registered."
        lines = [
            "| Tool Name | Description | Parameters |",
            "| :--- | :--- | :--- |"
        ]
        for name, s in self.schemas.items():
            desc = s["function"]["description"]
            props = list(s["function"]["parameters"].get("properties", {}).keys())
            lines.append(f"| `{name}` | {desc} | `{', '.join(props) if props else 'none'}` |")
        return "\n".join(lines)


# ============================================================================
# 3. The Epistemic Note Board
# ============================================================================

class EpistemicNoteBoard:
    """The central state packet rendered for each blank-slate model invocation."""

    def __init__(self, goal: str, invariants: List[str]):
        self.goal = goal
        self.invariants = invariants
        self.falsifications = FalsificationLedger()
        self.grounding = GroundingLedger()
        self.tools = DynamicToolRegistry()
        self.last_delta: Optional[str] = None
        self.current_step: int = 0

    def render_packet(self) -> str:
        """Render the complete stateless state packet."""
        invariants_text = "\n".join(f"- [ ] {inv}" for inv in self.invariants)
        delta_text = self.last_delta if self.last_delta else "Initial state. No actions executed yet."

        packet = f"""# EPISTEMIC STATE BOARD (Step {self.current_step})

## 1. GOAL & INVARIANTS (ACCEPTANCE CRITERIA)
**Goal:** {self.goal}
**Invariants to Satisfy:**
{invariants_text}

## 2. FALSIFICATION LEDGER (REJECTED PATHS - DO NOT REPEAT)
{self.falsifications.render_view()}

## 3. GROUNDING POINTERS (EXACT LOCATIONS IN RAW ENVIRONMENT)
{self.grounding.render_view()}

## 4. SYNTHESIZED RUNTIME TOOLS (COMPOUNDED CAPABILITIES)
{self.tools.render_view()}

## 5. LAST ACTION DELTA (IMMEDIATE FEEDBACK)
{delta_text}
"""
        return packet.strip()


# ============================================================================
# 4. Base Environment & Tool Schemas
# ============================================================================

class StatelessEnvironment:
    """Environment with base macro/foveated sensors, file actuators, and verification."""

    def __init__(self, root_dir: str | Path = "."):
        self.root = Path(root_dir).resolve()

    def outline(self, file_path: str, mode: str = "semantic") -> str:
        return extract_outline(self.root / file_path, mode=mode)

    def symbol(self, file_path: str, symbol_name: str) -> str:
        return extract_symbol(self.root / file_path, symbol_name)

    def saccade(self, file_path: str, start_line: int, end_line: int) -> str:
        return inspect_region(self.root / file_path, start_line, end_line)

    def replace_lines(self, file_path: str, start_line: int, end_line: int, new_content: str) -> str:
        target = self.root / file_path
        if not target.exists():
            return f"Error: File {file_path} not found."

        try:
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            total = len(lines)
            if start_line < 1 or end_line > total or start_line > end_line:
                return f"Error: Invalid line range [{start_line}, {end_line}] for file with {total} lines."

            repl_lines = [l if l.endswith("\n") else l + "\n" for l in new_content.splitlines()]
            if not repl_lines and new_content == "":
                repl_lines = []

            modified = lines[:start_line - 1] + repl_lines + lines[end_line:]
            new_text = "".join(modified)

            # Invariant check: ensure file compiles if it's Python
            if file_path.endswith(".py"):
                try:
                    ast.parse(new_text)
                except SyntaxError as e:
                    return f"Error: replacement causes SyntaxError: {e}. Change rejected."

            target.write_text(new_text, encoding="utf-8")
            return f"Successfully replaced lines {start_line}-{end_line} in {file_path} ({len(repl_lines)} lines inserted)."
        except Exception as e:
            return f"Error updating {file_path}: {e}"

    def run_command(self, cmd: str) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip()
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "passed": False, "stdout": "", "stderr": "Command timed out after 30s."}
        except Exception as e:
            return {"exit_code": -1, "passed": False, "stdout": "", "stderr": str(e)}


BASE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "outline",
            "description": "Macro Sensor: View compressed symbol outline (classes, functions, line numbers) of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file relative to repo root."},
                    "mode": {"type": "string", "enum": ["semantic", "bare", "folded"], "description": "Outline detail level."}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "saccade",
            "description": "Foveated Saccade: Inspect a precise line range of a file at 1:1 fidelity with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file relative to repo root."},
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
            "name": "view_symbol",
            "description": "Inspect definition of a named class or function with exact line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file relative to repo root."},
                    "symbol_name": {"type": "string", "description": "Function or class name."}
                },
                "required": ["file_path", "symbol_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "Actuation: Replace a range of lines with new content (verified by AST parse).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file relative to repo root."},
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
            "description": "Execute a shell command (e.g. pytest or python script) to verify invariants.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Command string to execute."}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_grounding_pointer",
            "description": "Note-taking: Record or update an exact address/locator in the grounding ledger for future turns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Target file or component."},
                    "locator": {"type": "string", "description": "Line span, AST symbol, or entity coordinate."},
                    "description": {"type": "string", "description": "Semantic role or summary of what is located here."}
                },
                "required": ["target", "locator", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "synthesize_tool",
            "description": "Synthesize a new executable Python tool that becomes an available opcode on all subsequent turns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Python function name."},
                    "code": {"type": "string", "description": "Complete Python code containing the function definition."},
                    "description": {"type": "string", "description": "Clear explanation of what the tool computes or checks."},
                    "parameters": {"type": "object", "description": "JSON Schema object describing function arguments."}
                },
                "required": ["name", "code", "description"]
            }
        }
    }
]


# ============================================================================
# 5. Blank-Slate Cognitive Harness Execution Loop
# ============================================================================

class BlankSlateHarness:
    """Executes goal-directed iterations via stateless note-board transitions."""

    def __init__(
        self,
        env: StatelessEnvironment,
        client: Optional[Any] = None,
        max_steps: int = 10
    ):
        self.env = env
        self.client = client
        self.max_steps = max_steps

    def _dispatch_tool(
        self,
        fn_name: str,
        args: Dict[str, Any],
        board: EpistemicNoteBoard,
        step: int,
        verify_cmd: str
    ) -> Tuple[str, bool]:
        """Dispatch a single tool call to sensory sensors, actuators, or dynamic tools."""
        solved = False

        if fn_name == "outline":
            res = self.env.outline(args.get("file_path", ""), mode=args.get("mode", "semantic"))
            return f"Outline of {args.get('file_path')}: {len(res.splitlines())} lines rendered.", False

        if fn_name == "saccade":
            res = self.env.saccade(args.get("file_path", ""), args.get("start_line", 1), args.get("end_line", 20))
            return f"Saccade on {args.get('file_path')}:{args.get('start_line')}-{args.get('end_line')}:\n{res}", False

        if fn_name == "view_symbol":
            res = self.env.symbol(args.get("file_path", ""), args.get("symbol_name", ""))
            return f"Symbol {args.get('symbol_name')}:\n{res}", False

        if fn_name == "replace_lines":
            res = self.env.replace_lines(
                args.get("file_path", ""),
                args.get("start_line", 1),
                args.get("end_line", 1),
                args.get("new_content", "")
            )
            if "Error:" in res:
                board.falsifications.record(
                    hypothesis=f"Edit lines {args.get('start_line')}-{args.get('end_line')} in {args.get('file_path')}",
                    action_taken=f"replace_lines({args.get('file_path')}, {args.get('start_line')}, {args.get('end_line')})",
                    rejection_evidence=res,
                    step=step
                )
            return res, False

        if fn_name == "run_command":
            cmd = args.get("cmd", verify_cmd)
            cmd_res = self.env.run_command(cmd)
            if not cmd_res["passed"]:
                board.falsifications.record(
                    hypothesis=f"Verification via '{cmd}'",
                    action_taken=f"run_command({cmd})",
                    rejection_evidence=cmd_res["stderr"] or cmd_res["stdout"] or "Non-zero exit code",
                    step=step
                )
            elif cmd == verify_cmd:
                solved = True
            return f"Command '{cmd}': exit {cmd_res['exit_code']}", solved

        if fn_name == "record_grounding_pointer":
            ptr = board.grounding.record_pointer(args.get("target", ""), args.get("locator", ""), args.get("description", ""))
            return f"Recorded Grounding Pointer {ptr.id} -> {ptr.target}:{ptr.locator}", False

        if fn_name == "synthesize_tool":
            ok, msg = board.tools.register_tool(
                name=args.get("name", ""),
                code=args.get("code", ""),
                description=args.get("description", ""),
                parameters=args.get("parameters")
            )
            if not ok:
                board.falsifications.record(
                    hypothesis=f"Tool synthesis for '{args.get('name')}'",
                    action_taken=f"synthesize_tool({args.get('name')})",
                    rejection_evidence=msg,
                    step=step
                )
            return f"Synthesize tool '{args.get('name')}': {msg}", False

        if fn_name in board.tools.tools:
            tool_res = board.tools.execute_tool(fn_name, args)
            return f"Dynamic tool '{fn_name}' output:\n{tool_res}", False

        return f"Unknown tool: {fn_name}", False

    def run(
        self,
        goal: str,
        verify_cmd: str,
        invariants: Optional[List[str]] = None,
        initial_pointers: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        board = EpistemicNoteBoard(
            goal=goal,
            invariants=invariants or [f"Command '{verify_cmd}' exits with code 0"]
        )

        if initial_pointers:
            for p in initial_pointers:
                board.grounding.record_pointer(p["target"], p["locator"], p["description"])

        solved = False
        step = 0
        execution_history: List[Dict[str, Any]] = []

        system_instruction = (
            "You are a stateless epistemic agent. You have NO conversational memory; each turn is a blank slate.\n"
            "All knowledge of previous steps is preserved strictly in the Epistemic State Board.\n"
            "Cognitive Rules:\n"
            "1. NEVER repeat an action or hypothesis recorded in the Falsification Ledger.\n"
            "2. Use Grounding Pointers to target saccades directly at known coordinates without re-scanning.\n"
            "3. If an invariant can be computed deterministically, use 'synthesize_tool' to create a dedicated probe.\n"
            "4. Preserving minimal state: do not write narrative summaries; update the ledger with precise pointers."
        )

        while step < self.max_steps and not solved:
            step += 1
            board.current_step = step

            # 1. Stateless prompt & schemas
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": board.render_packet()}
            ]
            all_tools = BASE_TOOL_SCHEMAS + board.tools.get_schemas()

            if self.client is None:
                verify_res = self.env.run_command(verify_cmd)
                if verify_res["passed"]:
                    solved = True
                    break
                board.last_delta = f"Verification failed:\n{verify_res['stderr'] or verify_res['stdout']}"
                continue

            response = self.client.chat_completion(messages, tools=all_tools)
            tool_calls = response.get("tool_calls") or []
            content = response.get("content") or ""

            if not tool_calls:
                verify_res = self.env.run_command(verify_cmd)
                if verify_res["passed"]:
                    solved = True
                    board.last_delta = "Goal verified: All invariants satisfied."
                    break
                rejection = verify_res["stderr"] or verify_res["stdout"] or "Tests still failing."
                board.falsifications.record(
                    hypothesis=content or "Model assumed task was complete without action",
                    action_taken="no_op",
                    rejection_evidence=rejection,
                    step=step
                )
                board.last_delta = f"No action taken, but verification failed:\n{rejection[:200]}"
                continue

            # 2. Dispatch tool calls modularly
            deltas: List[str] = []
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name", "")
                try:
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    args = {}

                delta, call_solved = self._dispatch_tool(fn_name, args, board, step, verify_cmd)
                deltas.append(delta)
                if call_solved:
                    solved = True

                execution_history.append({"step": step, "tool": fn_name, "args": args, "preview": delta[:120]})

            # 3. Re-verify invariants
            check = self.env.run_command(verify_cmd)
            if check["passed"]:
                solved = True
                deltas.append("Verification check passed.")

            board.last_delta = "\n".join(deltas)

        # Collect efficiency and token telemetry if client supports it
        efficiency_metrics = {}
        total_token_spend = 0
        if self.client is not None and hasattr(self.client, "get_efficiency_metrics"):
            efficiency_metrics = self.client.get_efficiency_metrics()
            total_token_spend = efficiency_metrics.get("total_tokens", 0)

        return {
            "solved": solved,
            "total_steps": step,
            "board": board,
            "falsifications_count": len(board.falsifications.records),
            "grounding_pointers_count": len(board.grounding.pointers),
            "synthesized_tools_count": len(board.tools.schemas),
            "execution_history": execution_history,
            "total_token_spend": total_token_spend,
            "efficiency_metrics": efficiency_metrics
        }

