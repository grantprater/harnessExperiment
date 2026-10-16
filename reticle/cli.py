"""Unified CLI for the Reticle Cognitive Harness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reticle import __version__
from reticle.adapters.blender_engine import verify_blender_installed, get_blender_path
from reticle.adapters.code_ast import parse_and_inspect_code


def cmd_version(args):
    print(f"Reticle Cognitive Harness v{__version__}")


def cmd_blender_info(args):
    installed = verify_blender_installed()
    path = get_blender_path()
    print(f"Blender Installed: {installed}")
    print(f"Blender Path: {path if path else 'Not found'}")


def cmd_verify_ast(args):
    fpath = Path(args.file)
    if not fpath.exists():
        print(f"Error: File not found: {fpath}")
        sys.exit(1)
    code = fpath.read_text(encoding="utf-8")
    res = parse_and_inspect_code(code)
    if res.valid:
        print(f"SUCCESS: Valid Python syntax in {fpath}")
        print(f"Functions ({len(res.functions)}): {res.functions}")
        print(f"Classes ({len(res.classes)}): {res.classes}")
        print(f"Imports ({len(res.imports)}): {res.imports}")
    else:
        print(f"SYNTAX ERROR on line {res.error_line}: {res.syntax_error}")
        sys.exit(1)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    legacy = {'version', 'blender-info', 'verify-ast', 'run', 'login', 'models', 'knowledge', 'usage'}
    if not argv or argv[0] not in legacy | {'--help', '-h'}:
        from reticle.interactive import add_arguments, launch
        chat = argparse.ArgumentParser(prog='reticle', description='Interactive Reticle coding harness')
        add_arguments(chat)
        args = chat.parse_args(argv[1:] if argv and argv[0] == 'chat' else argv)
        try:
            sys.exit(launch(args))
        except (ValueError, OSError, RuntimeError) as exc:
            chat.exit(1, f'Error: {exc}\n')
    parser = argparse.ArgumentParser(
        prog="reticle",
        description="Reticle: Cognitive Harness for AI Agents"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    from reticle.interactive import add_arguments
    p_chat = subparsers.add_parser('chat', help='Start an interactive coding session (also the default)')
    add_arguments(p_chat)

    p_login = subparsers.add_parser('login', help='Connect your ChatGPT subscription to Reticle')
    p_login.add_argument('--new-account', action='store_true')
    p_login.add_argument('--no-browser', action='store_true')
    p_login.set_defaults(func=cmd_login)
    p_models = subparsers.add_parser('models', help='List models available through your subscription')
    p_models.set_defaults(func=cmd_models)
    p_knowledge = subparsers.add_parser('knowledge', help='Export evidence, inspect a snapshot, or propose experiments')
    p_knowledge.add_argument('action', choices=['export', 'inspect', 'propose'])
    p_knowledge.add_argument('path', help='Source session for export; snapshot file for inspect/propose')
    p_knowledge.add_argument('--library', default='.reticle/knowledge')
    p_knowledge.set_defaults(func=cmd_knowledge)
    p_usage = subparsers.add_parser('usage', help='Export saved session token measurements as JSON')
    p_usage.add_argument('session', help='Saved session directory')
    p_usage.add_argument('--output', help='Write JSON to this file instead of stdout')
    p_usage.set_defaults(func=cmd_usage)

    # version
    p_ver = subparsers.add_parser("version", help="Show Reticle version")
    p_ver.set_defaults(func=cmd_version)

    # blender-info
    p_blend = subparsers.add_parser("blender-info", help="Check local Blender installation")
    p_blend.set_defaults(func=cmd_blender_info)

    # verify-ast
    p_ast = subparsers.add_parser("verify-ast", help="Validate Python syntax via AST compiler")
    p_ast.add_argument("file", help="Python source file to inspect")
    p_ast.set_defaults(func=cmd_verify_ast)

    # run (Stateless Cognitive Harness)
    p_run = subparsers.add_parser("run", help="Execute goal-directed tasks with Stateless Cognitive Harness")
    p_run.add_argument("--goal", "-g", required=True, help="Goal description for the agent")
    p_run.add_argument("--verify", "-v", required=True, help="Verification command that must return exit code 0")
    p_run.add_argument("--invariants", "-i", nargs="*", help="Optional explicit invariant assertions")
    p_run.add_argument("--model", "-m", default="gemini-3.6-flash", help="Model name (default: gemini-3.6-flash)")
    p_run.add_argument("--api-key", "-k", default=None, help="Google Studio or OpenAI API key (or set GEMINI_API_KEY)")
    p_run.add_argument("--base-url", default=None, help="API Base URL (default: Google AI Studio OpenAI endpoint)")
    p_run.add_argument("--max-steps", "-s", type=int, default=10, help="Maximum execution steps (default: 10)")
    p_run.add_argument("--dir", "-d", default=".", help="Working directory for execution (default: current)")
    p_run.add_argument("--json", action="store_true", help="Print execution results as JSON")
    p_run.add_argument("--report", default=None, help="Optional path to export execution telemetry report")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


def cmd_run(args):
    """Execute goal-directed tasks using the Stateless Blank-Slate Harness."""
    import json
    import time
    from reticle.cognitive.llm_client import LLMClient
    from reticle.cognitive.stateless_harness import StatelessEnvironment, BlankSlateHarness

    target_dir = Path(args.dir).resolve()
    if not target_dir.exists():
        print(f"Error: Target directory does not exist: {target_dir}")
        sys.exit(1)

    print("=" * 80)
    print("RETICLE COGNITIVE HARNESS: STATELESS BLANK-SLATE RUNNER")
    print("=" * 80)
    print(f"Directory:    {target_dir}")
    print(f"Goal:         {args.goal}")
    print(f"Verify Cmd:   {args.verify}")
    print(f"Model:        {args.model}")

    client = LLMClient(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model
    )

    if client.mock_mode:
        print("[Notice] Running in MOCK / SIMULATION mode.")
        print("         To connect to Google AI Studio, provide --api-key or export GEMINI_API_KEY.")
    else:
        print(f"[Connected] Live endpoint configured for model '{client.model}'")

    print("-" * 80)

    t0 = time.time()
    env = StatelessEnvironment(target_dir)
    harness = BlankSlateHarness(env=env, client=client, max_steps=args.max_steps)

    invariants = args.invariants if args.invariants else [f"Command '{args.verify}' exits with code 0"]
    result = harness.run(
        goal=args.goal,
        verify_cmd=args.verify,
        invariants=invariants
    )
    elapsed = time.time() - t0

    metrics = result.get("efficiency_metrics", {})
    solved = result.get("solved", False)
    status_str = "SUCCESS (All Invariants Satisfied)" if solved else "INCOMPLETE (Max Steps Reached)"

    if args.json:
        serializable_res = {
            "solved": solved,
            "total_steps": result.get("total_steps"),
            "elapsed_seconds": round(elapsed, 2),
            "goal": args.goal,
            "verify_cmd": args.verify,
            "falsifications_count": result.get("falsifications_count"),
            "grounding_pointers_count": result.get("grounding_pointers_count"),
            "synthesized_tools_count": result.get("synthesized_tools_count"),
            "total_token_spend": result.get("total_token_spend"),
            "efficiency_metrics": metrics
        }
        print(json.dumps(serializable_res, indent=2))
        return

    print("\n" + "=" * 80)
    print("EXECUTION TELEMETRY & EFFICIENCY REPORT")
    print("=" * 80)
    print(f"Status:                   {status_str}")
    print(f"Steps Executed:           {result.get('total_steps')} / {args.max_steps}")
    print(f"Elapsed Time:             {elapsed:.2f}s")
    print("\n-- TOKEN SPEND & CONTEXT DYNAMICS ----------------------------------------------")
    print(f"Total Prompt Tokens:      {metrics.get('total_prompt_tokens', 0):,}")
    print(f"Total Completion Tokens:  {metrics.get('total_completion_tokens', 0):,}")
    print(f"Total Tokens Consumed:    {metrics.get('total_tokens', 0):,}")
    print(f"Estimated Cost (USD):     ${metrics.get('total_cost_usd', 0.0):.6f}")
    print(f"Mean Tokens / Step:       {metrics.get('mean_tokens_per_step', 0.0)} tok")
    print(f"Context Growth Gradient:  {metrics.get('context_growth_gradient', 0.0)} (0.00 = Perfect Flatline)")
    print(f"Context Stability Index:  {metrics.get('context_stability_index', 1.0)}x")
    print("\n-- EPISTEMIC ACCUMULATION ------------------------------------------------------")
    print(f"Grounding Pointers:       {result.get('grounding_pointers_count', 0)} active anchors")
    print(f"Falsifications Pruned:    {result.get('falsifications_count', 0)} negative paths")
    print(f"Synthesized Opcodes:      {result.get('synthesized_tools_count', 0)} dynamic tools")
    print("=" * 80)

    if args.report:
        rep_path = Path(args.report)
        report_content = (
            f"# Reticle Execution Report\n\n"
            f"- **Goal**: {args.goal}\n"
            f"- **Status**: {status_str}\n"
            f"- **Steps**: {result.get('total_steps')} / {args.max_steps}\n"
            f"- **Elapsed**: {elapsed:.2f}s\n"
            f"- **Total Token Spend**: {metrics.get('total_tokens', 0):,} tokens\n"
            f"- **Estimated Cost**: ${metrics.get('total_cost_usd', 0.0):.6f} USD\n"
            f"- **Context Gradient**: {metrics.get('context_growth_gradient', 0.0)}\n\n"
            f"## Final Epistemic Note Board\n\n"
            f"{result['board'].render_packet()}\n"
        )
        rep_path.write_text(report_content, encoding="utf-8")
        print(f"[Report] Saved detailed telemetry report to {rep_path}")


def cmd_login(args):
    from reticle.cognitive.chatgpt_auth import ChatGPTAuth
    try:
        ChatGPTAuth().login(new_account=args.new_account, open_browser=not args.no_browser)
    except (RuntimeError, OSError) as exc:
        raise SystemExit(str(exc)) from None


def cmd_usage(args):
    import json
    from reticle.runtime.session import LocalRuntime
    from reticle.runtime.telemetry import usage_report, write_usage_report
    if not (Path(args.session) / 'session.json').is_file():
        raise SystemExit('Saved session was not found: ' + args.session)
    runtime = LocalRuntime(args.session)
    if args.output:
        write_usage_report(runtime, args.output)
    else:
        print(json.dumps(usage_report(runtime), indent=2))


def cmd_models(args):
    import json
    from reticle.cognitive.chatgpt_auth import ChatGPTAuth
    try:
        print(json.dumps([{k: model[k] for k in ('slug', 'display_name') if k in model}
                          for model in ChatGPTAuth().models() if model.get('visibility') == 'list'], indent=2))
    except (RuntimeError, OSError) as exc:
        raise SystemExit(str(exc)) from None


def cmd_knowledge(args):
    import json
    from reticle.runtime.knowledge import KnowledgeLibrary, load_snapshot, propose_experiments
    try:
        if args.action == 'export':
            from reticle.runtime.session import LocalRuntime
            from reticle.runtime.reasoning import EvidenceOntology
            if not (Path(args.path) / 'session.json').is_file():
                raise ValueError('Saved session does not exist')
            runtime = LocalRuntime(args.path)
            print(KnowledgeLibrary(args.library).consolidate(runtime, EvidenceOntology(runtime, 'memory')))
        elif args.action == 'propose':
            print(json.dumps(propose_experiments(args.path), indent=2))
        else:
            data = load_snapshot(args.path)
            print(json.dumps({'version': data['version'], 'entities': len(data['entities']),
                              'relations': len(data['relations']), 'sessions': len(data['sessions']),
                              'feedback': len(data['feedback'])}, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
