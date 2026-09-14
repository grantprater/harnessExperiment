"""Trial execution of Autonomous Refactoring Meta-Loop on stateless_harness.py."""

import ast
from pathlib import Path
from refactoring_meta_loop import AutonomousRefactoringMetaLoop, ComplexityProfiler

ROOT = Path(__file__).resolve().parent

def run_trial():
    meta = AutonomousRefactoringMetaLoop(ROOT)
    candidates = ComplexityProfiler.scan_codebase(ROOT)

    # Pick candidate: stateless_harness.py [run]
    target_c = next((c for c in candidates if "stateless_harness" in c.file_path and c.function_name == "run"), None)
    if not target_c:
        print("Candidate not found!")
        return

    print(f"Target Candidate: {target_c.file_path}:{target_c.start_line} [{target_c.function_name}]")
    print(f"Pre-refactor Metrics: {target_c.metrics.total_lines} lines, {target_c.metrics.branch_count} branches, score {target_c.metrics.complexity_score}")

    # The refactored run method and extracted _dispatch_tool_call
    refactored_code = '''    def _dispatch_tool(
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
            return f"Saccade on {args.get('file_path')}:{args.get('start_line')}-{args.get('end_line')}:\\n{res}", False

        if fn_name == "view_symbol":
            res = self.env.symbol(args.get("file_path", ""), args.get("symbol_name", ""))
            return f"Symbol {args.get('symbol_name')}:\\n{res}", False

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
            return f"Dynamic tool '{fn_name}' output:\\n{tool_res}", False

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
            "You are a stateless epistemic agent. You have NO conversational memory; each turn is a blank slate.\\n"
            "All knowledge of previous steps is preserved strictly in the Epistemic State Board.\\n"
            "Cognitive Rules:\\n"
            "1. NEVER repeat an action or hypothesis recorded in the Falsification Ledger.\\n"
            "2. Use Grounding Pointers to target saccades directly at known coordinates without re-scanning.\\n"
            "3. If an invariant can be computed deterministically, use 'synthesize_tool' to create a dedicated probe.\\n"
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
                board.last_delta = f"Verification failed:\\n{verify_res['stderr'] or verify_res['stdout']}"
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
                board.last_delta = f"No action taken, but verification failed:\\n{rejection[:200]}"
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

            board.last_delta = "\\n".join(deltas)

        return {
            "solved": solved,
            "total_steps": step,
            "board": board,
            "falsifications_count": len(board.falsifications.records),
            "grounding_pointers_count": len(board.grounding.pointers),
            "synthesized_tools_count": len(board.tools.schemas),
            "execution_history": execution_history
        }'''

    res = meta.execute_refactor(
        candidate=target_c,
        refactored_code=refactored_code,
        refactoring_intent="Decompose monolithic tool routing cascade into modular _dispatch_tool method"
    )

    print("\nResult:")
    print(f"Success: {res['success']}")


if __name__ == "__main__":
    run_trial()
