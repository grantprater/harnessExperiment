"""claude-cli client: rendering, isolation checks, and per-attempt accounting against a stub `claude` on PATH (no live call)."""

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import claude_cli  # noqa: E402
import run_pilot  # noqa: E402
from reticle.context import PressureRecentContextPolicyV3  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.budgets import TaskBudgetLedger  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits  # noqa: E402

STUB = r'''
import json, os, sys
from pathlib import Path
state = Path(os.environ["STUB_CLAUDE_STATE"])
if sys.argv[1:] == ["--version"]:
    print("0.0.0 (stub)")
    sys.exit(0)
prompt = sys.stdin.buffer.read().decode("utf-8")
n = len(list(state.glob("call-*.json"))) + 1
(state / f"call-{n:03d}.json").write_text(json.dumps({
    "argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
    "present": sorted(k for k in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID") if k in os.environ)}),
    encoding="utf-8")
replies = json.loads((state / "replies.json").read_text(encoding="utf-8"))
reply = replies[min(n, len(replies)) - 1]
for event in reply["events"]:
    print(json.dumps(event))
sys.exit(reply.get("exit", 0))
'''


def init_event(tools=("StructuredOutput",), api_key_source="none", mcp=()):
    return {"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": list(mcp),
            "apiKeySource": api_key_source, "model": "claude-stub", "claude_code_version": "0.0.0"}


def result_event(structured=None, is_error=False, text="", subtype="success"):
    event = {"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": 2, "result": text,
             "session_id": "stub-session", "stop_reason": "tool_use", "total_cost_usd": 0.0123,
             "usage": {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 7,
                       "output_tokens": 20}}
    if structured is not None:
        event["structured_output"] = structured
    return event


def assistant_event(*blocks, message_id="msg_1"):
    return {"type": "assistant", "message": {"id": message_id, "role": "assistant", "content": list(blocks)}}


def structured_use(structured):
    return {"type": "tool_use", "id": "toolu_s", "name": "StructuredOutput", "input": structured}


def ok(*calls, content=None):
    """The CLI's structured-output path: the first message is one StructuredOutput call."""
    structured = {"content": content, "tool_calls": list(calls)}
    return {"events": [init_event(), assistant_event({"type": "thinking", "thinking": ""}),
                       assistant_event(structured_use(structured)),
                       {"type": "user", "message": {"content": [
                           {"type": "tool_result", "tool_use_id": "toolu_s", "content": "Structured output provided"}]}},
                       result_event(structured)]}


def direct(*uses, text=None):
    """The model calls harness tools directly; the CLI rejects them and stops at --max-turns 1."""
    blocks = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": arguments}
        for i, (name, arguments) in enumerate(uses, 1)]
    events = [init_event(), assistant_event({"type": "thinking", "thinking": ""})]
    for block in blocks:
        events.append(assistant_event(block))
        if block["type"] == "tool_use":
            events.append({"type": "user", "message": {"content": [{
                "type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                "content": f"<tool_use_error>Error: No such tool available: {block['name']}</tool_use_error>"}]}})
    events.append(result_event(is_error=True, subtype="error_max_turns"))
    return {"events": events, "exit": 1}


def tool(name, **arguments):
    return {"id": "call_1", "name": name, "arguments": arguments}


FAILED = {"events": [init_event(), result_event(is_error=True, text="API Error: 529 overloaded", subtype="success")],
          "exit": 1}


class ClaudeCliTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.state = self.root / "stub-state"
        self.state.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "stub_claude.py").write_text(STUB, encoding="utf-8")
        if os.name == "nt":
            (bin_dir / "claude.cmd").write_text(
                f'@"{sys.executable}" "{bin_dir / "stub_claude.py"}" %*\r\n', encoding="utf-8")
        else:
            launcher = bin_dir / "claude"
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_dir / "stub_claude.py"}" "$@"\n',
                                encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        # PATH holds only the stub, so no test can reach a real CLI.
        patched = mock.patch.dict(os.environ, {"PATH": str(bin_dir), "STUB_CLAUDE_STATE": str(self.state),
                                               "ANTHROPIC_API_KEY": "must-not-reach-the-child",
                                               "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "parent"})
        patched.start()
        self.addCleanup(patched.stop)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "a.txt").write_text("alpha\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", self.workspace)
        self.tools = run_pilot.RepeatGuardTools(self.runtime, interpreter=sys.executable)
        self.calls_path = self.root / "calls.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def replies(self, *replies):
        (self.state / "replies.json").write_text(json.dumps(list(replies)), encoding="utf-8")

    def stub_calls(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.state.glob("call-*.json"))]

    def client(self, campaign_cap=100):
        inner = claude_cli.ClaudeCliClient("sonnet", self.calls_path, "run-1", run_pilot.CallBudget(campaign_cap, 0),
                                           backoff_seconds=0, workdir=self.root / "cli-cwd")
        return run_pilot.GuardedClient(inner, self.tools)

    def run_agent(self, budgets, calls=6):
        task = TaskEnvelope("cli-task", "Read a.txt, then finish.", budgets=budgets)
        return AgentController(self.runtime, task, self.tools, self.client(), AgentLimits(calls, 100_000),
                               policy=PressureRecentContextPolicyV3()).run()

    def outcomes(self):
        return [e.payload["outcome"] for e in self.runtime.journal.read_all() if e.kind == "provider_attempt_finished"]


class ClaudeCliClientTests(ClaudeCliTestCase):
    def test_tool_calls_are_converted_and_the_cli_runs_isolated(self):
        self.replies(ok(tool("read_file", path="a.txt"), tool("glob_files", glob="*.txt")),
                     ok(tool("finish", summary="done")))
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.provider_attempts, result.tool_calls), (2, 2, 3))

        first, second = self.stub_calls()
        argv = first["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertNotIn("--bare", argv)  # --bare refuses the subscription login
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), claude_cli.REPLY_SCHEMA)
        system = Path(argv[argv.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("### read_file\nRead a text file", system)
        self.assertEqual(Path(first["cwd"]).resolve(), (self.root / "cli-cwd").resolve())
        self.assertEqual(first["present"], [], "session links and API credentials must not reach the child")
        # Stateless: the second request carries the first exchange, rendered with its results.
        self.assertIn("Read a.txt, then finish.", first["prompt"])
        self.assertIn("tool call cli_1_1: read_file {\"path\": \"a.txt\"}", second["prompt"])
        self.assertIn("tool result for call cli_1_1 (read_file)", second["prompt"])
        self.assertIn("alpha", second["prompt"])

        rows = run_pilot.read_jsonl(self.calls_path)
        self.assertEqual(len(rows), 2)
        message = rows[0]["response"]["choices"][0]["message"]
        self.assertEqual([c["id"] for c in message["tool_calls"]], ["cli_1_1", "cli_1_2"])
        self.assertEqual(json.loads(message["tool_calls"][1]["function"]["arguments"]), {"glob": "*.txt"})
        self.assertEqual(rows[0]["cli_init"]["tools"], ["StructuredOutput"])
        self.assertEqual(rows[0]["billing"], "unknown")
        self.assertEqual(result.calls_missing_usage["cost"], 2)

    def test_attempts_are_reserved_and_reconciled_with_unknown_billing(self):
        self.replies(ok(tool("finish", summary="done")))
        budgets = {"model_responses": 3, "model_attempts": 3, "cost_usd": 1.0, "model_attempt_cost_reservation": 0.1}
        result = self.run_agent(budgets)
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual(self.outcomes(), ["response"])
        ledger = TaskBudgetLedger(self.runtime, "cli-task", budgets)
        self.assertEqual(ledger.unknown_billing_count(), 1)
        self.assertEqual(result.task_resources["pending"], {})
        started = [e.payload["provider_attempt_id"] for e in self.runtime.journal.read_all()
                   if e.kind == "provider_attempt_started"]
        self.assertEqual([r["provider_attempt_id"] for r in run_pilot.read_jsonl(self.calls_path)], started)

    def test_cli_errors_are_retried_at_most_twice(self):
        self.replies(FAILED, FAILED, ok(tool("finish", summary="done")))
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.provider_attempts, len(self.stub_calls())), (1, 3, 3))
        self.assertEqual(self.outcomes(), ["cli_error", "cli_error", "response"])

        self.replies(FAILED)
        again = claude_cli.ClaudeCliClient("sonnet", self.calls_path, "run-2", run_pilot.CallBudget(100, 0),
                                           backoff_seconds=0, workdir=self.root / "cli-cwd")
        with self.assertRaisesRegex(run_pilot.ModelClientError, "failed after 3 attempts"):
            again.complete([{"role": "user", "content": "x"}], [])

    def test_a_cli_that_exposes_tools_is_never_used(self):
        for init in (init_event(tools=("StructuredOutput", "Bash")), init_event(api_key_source="ANTHROPIC_API_KEY"),
                     init_event(mcp=({"name": "docs", "status": "connected"},))):
            with self.subTest(init=init):
                for path in self.state.glob("call-*.json"):
                    path.unlink()
                reply = ok(tool("finish", summary="done"))
                reply["events"][0] = init
                self.replies(reply)
                client = claude_cli.ClaudeCliClient("sonnet", self.calls_path, "run-x", run_pilot.CallBudget(100, 0),
                                                    backoff_seconds=0, workdir=self.root / "cli-cwd")
                with self.assertRaises(run_pilot.ModelClientError):
                    client.complete([{"role": "user", "content": "x"}], [])
                self.assertEqual(len(self.stub_calls()), 1, "an isolation failure is not retried")
                self.assertEqual(run_pilot.read_jsonl(self.calls_path)[-1]["failure"], "tool_isolation_violation")

    def test_malformed_structured_output_is_retried_then_stops(self):
        malformed = ok()
        malformed["events"][2]["message"]["content"][0]["input"] = {"content": None, "tool_calls": [{"name": "run"}]}
        self.replies(malformed)
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "model_error")
        self.assertEqual(self.outcomes(), ["invalid_reply"] * 3)
        self.assertTrue(run_pilot.is_provider_stop(result.to_dict()))

    def test_direct_calls_in_the_first_message_are_the_reply(self):
        self.replies(direct(("search_text", {"query": "def get_real_name"}), ("glob_files", {"glob": "*.py"}),
                            text="Looking for the function."),
                     ok(tool("finish", summary="done")))
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.provider_attempts, result.tool_calls), (2, 2, 3))
        self.assertEqual(self.outcomes(), ["response", "response"])
        first, second = run_pilot.read_jsonl(self.calls_path)
        self.assertEqual((first["reply_channel"], second["reply_channel"]), ("direct_tool_use", "structured_output"))
        message = first["response"]["choices"][0]["message"]
        self.assertEqual(message["content"], "Looking for the function.")
        self.assertEqual([(c["id"], c["function"]["name"]) for c in message["tool_calls"]],
                         [("cli_1_1", "search_text"), ("cli_1_2", "glob_files")])
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"query": "def get_real_name"})
        # The CLI's own rejection stays in the log and never reaches the next request.
        self.assertTrue(any("No such tool" in (t.get("tool_result") or "") for t in first["cli_turns"]))
        next_prompt = self.stub_calls()[1]["prompt"]
        self.assertNotIn("No such tool", next_prompt)
        self.assertIn("tool result for call cli_1_1 (search_text)", next_prompt)

    def test_structured_output_wins_over_direct_calls_in_the_same_message(self):
        structured = {"content": None, "tool_calls": [tool("finish", summary="done")]}
        self.replies({"events": [init_event(), assistant_event(
            {"type": "tool_use", "id": "toolu_d", "name": "run", "input": {"command": "pytest"}},
            structured_use(structured)), result_event(structured)]})
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual((result.stop_reason, result.tool_calls), ("finish_requested", 1))
        self.assertEqual(run_pilot.read_jsonl(self.calls_path)[0]["ignored_direct_calls"], ["run"])

    def test_only_the_first_message_counts(self):
        reply = direct(("read_file", {"path": "a.txt"}))
        reply["events"].insert(-1, assistant_event(
            {"type": "tool_use", "id": "toolu_late", "name": "write_file", "input": {"path": "a.txt", "content": "x"}},
            message_id="msg_2"))
        self.replies(reply, ok(tool("finish", summary="done")))
        result = self.run_agent({"model_responses": 5, "model_attempts": 5})
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual((self.workspace / "a.txt").read_text(encoding="utf-8"), "alpha\n")

    def test_campaign_cap_stops_without_a_phantom_attempt(self):
        self.replies(FAILED)
        task = TaskEnvelope("cli-task", "x", budgets={"model_responses": 5, "model_attempts": 5})
        result = AgentController(self.runtime, task, self.tools, self.client(campaign_cap=1),
                                 AgentLimits(5, 100_000), policy=PressureRecentContextPolicyV3()).run()
        self.assertEqual(run_pilot.guard_stop_label(result.to_dict()), "attempt_cap_reached")
        self.assertEqual(len(self.stub_calls()), 1)
        self.assertEqual(result.task_resources["pending"], {})

    def test_contract_is_part_of_the_protocol(self):
        contract = claude_cli.cli_contract("sonnet", max_turns=3, timeout=300, version=claude_cli.cli_version())
        self.assertEqual(contract["cli_version"], "0.0.0 (stub)")
        self.assertEqual(contract["arguments"][contract["arguments"].index("--tools") + 1], "")
        execution = {"backend": "trusted-local"}
        other = dict(contract, model="opus")
        self.assertNotEqual(run_pilot.protocol_hash("pressure-recent-v3", {"sonnet": contract}, execution, {}),
                            run_pilot.protocol_hash("pressure-recent-v3", {"sonnet": other}, execution, {}))


class RenderTests(unittest.TestCase):
    def test_every_message_role_is_rendered_in_order_with_call_names(self):
        prompt = claude_cli.render_conversation([
            {"role": "system", "content": "contract"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "looking", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\": \"x\"}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "file body"},
            {"role": "system", "content": "2 responses remaining"},
        ])
        order = ["##### [1] system\ncontract", "##### [2] user\ntask",
                 "##### [3] assistant (your earlier reply)\nlooking\ntool call c1: read_file {\"path\": \"x\"}",
                 "##### [4] tool result for call c1 (read_file)\nfile body",
                 "##### [5] system\n2 responses remaining", "##### end of conversation"]
        positions = [prompt.index(part) for part in order]
        self.assertEqual(positions, sorted(positions))

    def test_reply_without_calls_is_plain_text(self):
        message, ids = claude_cli.reply_message({"content": "thinking", "tool_calls": []}, 4)
        self.assertEqual(message, {"role": "assistant", "content": "thinking"})
        self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main()
