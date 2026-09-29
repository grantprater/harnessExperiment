"""claude-cli reply recovery (adapter v3, --cli-reply-recovery): lenient JSON for an unparsed StructuredOutput input,
one CLI-fed second turn otherwise, the tool guard, and default-off requests byte-identical to v2. Stub CLI only."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import claude_cli  # noqa: E402
import run_card  # noqa: E402
import run_pilot  # noqa: E402
from reticle.context import PressureRecentContextPolicyV3  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError  # noqa: E402
from test_claude_cli_client import (  # noqa: E402
    ClaudeCliTestCase, assistant_event, direct, init_event, ok, result_event, tool,
)

RECOVERY = claude_cli.REPLY_RECOVERY
CARDS = ROOT / "experiments" / "session_harness" / "cards"
V3_KEYS = {"cli_model_messages", "structured_output_repair", "structured_output_retries",
           "structured_output_rejections"}
# Unparseable even leniently: cut off inside a string (the CLI's error names the full size).
TRUNCATED = '{"content": "The fix is complete. The bug was an inverted condition in `_split_kwds` — exac'
# Parseable only leniently: a literal newline inside the content string.
CONTROL = '{"content": "Fixed.\nThe guard was inverted.", "tool_calls": [{"id": "c1", "name": "finish", "arguments": {"summary": "done"}}]}'


def unparsed_use(raw, use_id):
    return {"type": "tool_use", "id": use_id, "name": "StructuredOutput",
            "input": {claude_cli.UNPARSED_INPUT_KEY: {"raw": raw}}}


def tool_result(use_id, content, is_error):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": content, "is_error": is_error}]}}


def refused(use_id, raw):
    return tool_result(use_id, "<tool_use_error>InputValidationError: StructuredOutput was called with input that "
                               "could not be parsed as JSON.\nYou sent (first 200 of "
                               f"{len(raw.encode('utf-8'))} bytes): {raw[:200]}", True)


def stream(*messages, final=None, subtype="success"):
    """A --max-turns 2 stream: each message is (blocks, the CLI's tool results after it)."""
    events = [init_event()]
    for position, (blocks, results) in enumerate(messages, 1):
        events.extend(assistant_event(block, message_id=f"msg_{position}") for block in blocks)
        events.extend(results)
    events.append(result_event(final, is_error=subtype != "success", subtype=subtype))
    return {"events": events, "exit": 0 if subtype == "success" else 1}


def valid_use(use_id, *calls, content=None):
    return {"type": "tool_use", "id": use_id, "name": "StructuredOutput",
            "input": {"content": content, "tool_calls": list(calls)}}


class RecoveryTestCase(ClaudeCliTestCase):
    def recovery_client(self, model="sonnet"):
        return claude_cli.ClaudeCliClient(model, self.calls_path, "run-1", run_pilot.CallBudget(100, 0),
                                          backoff_seconds=0, workdir=self.root / "cli-cwd",
                                          max_turns=claude_cli.RECOVERY_MAX_TURNS, reply_recovery=RECOVERY)

    def run_recovery_agent(self, client, calls=6):
        task = TaskEnvelope("cli-task", "Read a.txt, then finish.",
                            budgets={"model_responses": 5, "model_attempts": 5})
        return AgentController(self.runtime, task, self.tools, run_pilot.GuardedClient(client, self.tools),
                               AgentLimits(calls, 100_000), policy=PressureRecentContextPolicyV3()).run()

    def rows(self):
        return run_pilot.read_jsonl(self.calls_path)


class ReplyRecoveryTests(RecoveryTestCase):
    def test_malformed_then_valid_uses_the_second_message(self):
        second = valid_use("toolu_2", tool("finish", summary="done"), content="Fixed.")
        self.replies(stream(([unparsed_use(TRUNCATED, "toolu_1")], [refused("toolu_1", TRUNCATED)]),
                            ([second], [tool_result("toolu_2", "Structured output provided successfully", False)]),
                            final=second["input"]))
        client = self.recovery_client()
        result = self.run_recovery_agent(client)
        self.assertEqual(result.stop_reason, "finish_requested")
        self.assertEqual((result.model_calls, result.provider_attempts), (1, 1), "no adapter retry was spent")
        self.assertEqual(self.outcomes(), ["response"])
        row = self.rows()[0]
        self.assertEqual((row["structured_output_repair"], row["structured_output_retries"],
                          row["cli_model_messages"]), (None, 1, 2))
        [rejection] = row["structured_output_rejections"]
        self.assertEqual((rejection["kind"], rejection["message"], rejection["raw"], rejection["strict_json"]),
                         ("unparsed", 1, TRUNCATED, False))
        self.assertEqual(rejection["raw_bytes"], rejection["cli_reported_bytes"])
        self.assertEqual(row["response"]["choices"][0]["message"]["content"], "Fixed.")
        self.assertEqual(row["request"]["adapter_version"], "claude-cli-adapter-v3")
        # The stream's accounting is kept as before: usage and the list-price estimate from the result event.
        self.assertEqual(row["cli_result"]["total_cost_usd"], 0.0123)
        self.assertEqual(client.recovery_summary(), {
            "replies": 1, "lenient_json": 0, "second_turn": 1, "unrecovered_attempts": 0,
            "rejected_structured_output": 1, "discarded_model_messages": 0})

    def test_a_leniently_parseable_raw_input_is_the_reply(self):
        later = valid_use("toolu_2", tool("read_file", path="a.txt"), content="not used")
        self.replies(stream(([unparsed_use(CONTROL, "toolu_1")], [refused("toolu_1", CONTROL)]),
                            ([later], [tool_result("toolu_2", "Structured output provided successfully", False)]),
                            final=later["input"]))
        client = self.recovery_client()
        response = client.complete([{"role": "user", "content": "go"}], [])
        self.assertEqual(response.message["content"], "Fixed.\nThe guard was inverted.")
        self.assertEqual([c["function"]["name"] for c in response.message["tool_calls"]], ["finish"])
        self.assertEqual((response.metadata["structured_output_repair"], response.metadata["structured_output_retries"],
                          response.metadata["cli_model_messages"]), ("lenient-json", 0, 2))
        self.assertEqual(response.usage, {"prompt_tokens": 110, "completion_tokens": 20})
        row = self.rows()[0]
        self.assertEqual(row["structured_output_repair"], "lenient-json")
        [rejection] = row["structured_output_rejections"]
        self.assertEqual((rejection["repaired"], rejection["strict_json"], rejection["raw"]),
                         ("lenient-json", False, CONTROL))
        self.assertEqual(client.recovery_summary()["lenient_json"], 1)
        self.assertEqual(client.recovery_summary()["discarded_model_messages"], 1)

    def test_an_unrecoverable_raw_input_still_fails_as_before(self):
        second_raw = TRUNCATED + " again"
        self.replies(stream(([unparsed_use(TRUNCATED, "toolu_1")], [refused("toolu_1", TRUNCATED)]),
                            ([unparsed_use(second_raw, "toolu_2")], [refused("toolu_2", second_raw)]),
                            subtype="error_max_turns"))
        client = self.recovery_client()
        result = self.run_recovery_agent(client)
        self.assertEqual(result.stop_reason, "model_error")
        self.assertEqual(self.outcomes(), ["invalid_reply"] * 3)
        self.assertTrue(run_pilot.is_provider_stop(result.to_dict()))
        for row in self.rows():
            self.assertEqual(row["failure"], "invalid_reply")
            self.assertEqual([(r["message"], r["raw"]) for r in row["structured_output_rejections"]],
                             [(1, TRUNCATED), (2, second_raw)])
        self.assertEqual(client.recovery_summary()["unrecovered_attempts"], 3)

    def test_a_second_message_without_structured_output_is_not_a_reply(self):
        self.replies(stream(([unparsed_use(TRUNCATED, "toolu_1")], [refused("toolu_1", TRUNCATED)]),
                            ([{"type": "tool_use", "id": "toolu_2", "name": "finish", "input": {"summary": "x"}}],
                             [tool_result("toolu_2", "<tool_use_error>Error: No such tool available: finish"
                                                     "</tool_use_error>", True)]),
                            subtype="error_max_turns"))
        with self.assertRaises(ModelClientError):
            self.recovery_client().complete([{"role": "user", "content": "go"}], [])
        self.assertEqual([row["failure"] for row in self.rows()], ["invalid_reply"] * 3)

    def test_a_first_message_v2_can_use_is_the_reply_and_later_turns_are_discarded(self):
        reply = direct(("read_file", {"path": "a.txt"}), text="Reading.")
        reply["events"].insert(-1, assistant_event(
            valid_use("toolu_late", tool("write_file", path="a.txt", content="x")), message_id="msg_2"))
        self.replies(reply, ok(tool("finish", summary="done")))
        result = self.run_recovery_agent(self.recovery_client())
        self.assertEqual((result.stop_reason, result.tool_calls), ("finish_requested", 2))
        self.assertEqual((self.workspace / "a.txt").read_text(encoding="utf-8"), "alpha\n")
        first, second = self.rows()
        self.assertEqual((first["reply_channel"], first["structured_output_retries"], first["cli_model_messages"]),
                         ("direct_tool_use", 0, 2))
        self.assertEqual((second["reply_channel"], second["structured_output_rejections"]), ("structured_output", []))

    def test_a_tool_the_cli_ran_fails_the_attempt_without_retry(self):
        self.replies(stream(([unparsed_use(TRUNCATED, "toolu_1")], [refused("toolu_1", TRUNCATED)]),
                            ([{"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "ls"}},
                              valid_use("toolu_3", tool("finish", summary="done"))],
                             [tool_result("toolu_2", "a.txt", False)])))
        with self.assertRaises(ModelClientError):
            self.recovery_client().complete([{"role": "user", "content": "go"}], [])
        [row] = self.rows()
        self.assertEqual(row["failure"], "tool_isolation_violation")
        self.assertEqual(len(self.stub_calls()), 1)
        self.assertNotIn("response", row)

    def test_the_cli_runs_at_two_turns_with_the_same_isolation(self):
        self.replies(ok(tool("finish", summary="done")))
        self.recovery_client().complete([{"role": "user", "content": "go"}], [])
        argv = self.stub_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--max-turns") + 1], "2")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        for flag in claude_cli.ISOLATION_ARGUMENTS:
            self.assertIn(flag, argv)


class DefaultOffTests(RecoveryTestCase):
    def v2_client(self):
        return claude_cli.ClaudeCliClient("sonnet", self.calls_path, "run-1", run_pilot.CallBudget(100, 0),
                                          backoff_seconds=0, workdir=self.root / "cli-cwd")

    def test_default_off_requests_are_v2_byte_for_byte(self):
        self.replies(ok(tool("finish", summary="done")))
        messages = [{"role": "user", "content": "go"}]
        response = self.v2_client().complete(messages, [])
        call = self.stub_calls()[0]
        system_file = call["argv"][call["argv"].index("--system-prompt-file") + 1]
        self.assertEqual(call["argv"], [
            "-p", "--model", "sonnet", "--output-format", "stream-json", "--verbose", "--max-turns", "1",
            "--safe-mode", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--tools", "",
            "--json-schema", json.dumps(claude_cli.REPLY_SCHEMA, separators=(",", ":")),
            "--system-prompt-file", system_file])
        self.assertEqual(call["prompt"], claude_cli.render_conversation(messages))
        row = self.rows()[0]
        expected = hashlib.sha256(json.dumps(
            {"model": "sonnet", "system": claude_cli.render_system_prompt([]), "prompt": call["prompt"],
             "adapter": "claude-cli-adapter-v2"}, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(row["request_sha256"], expected)
        self.assertEqual(row["request"]["adapter_version"], "claude-cli-adapter-v2")
        self.assertFalse(V3_KEYS & set(row))
        self.assertFalse(V3_KEYS & set(response.metadata))

    def test_default_off_never_repairs_an_unparsed_input(self):
        self.replies(stream(([unparsed_use(CONTROL, "toolu_1")], [refused("toolu_1", CONTROL)]),
                            subtype="error_max_turns"))
        with self.assertRaises(ModelClientError):
            self.v2_client().complete([{"role": "user", "content": "go"}], [])
        self.assertEqual([row["failure"] for row in self.rows()], ["invalid_reply"] * 3)
        self.assertFalse(any(V3_KEYS & set(row) for row in self.rows()))
        self.assertIsNone(self.v2_client().recovery_summary())


class ContractTests(unittest.TestCase):
    def test_off_the_contract_is_v2_and_on_it_is_v3(self):
        v2 = claude_cli.cli_contract("claude-sonnet-5", max_turns=1, timeout=300, version="v")
        self.assertEqual(v2, claude_cli.cli_contract("claude-sonnet-5", max_turns=1, timeout=300, version="v",
                                                     reply_recovery=None))
        self.assertEqual(run_pilot.cli_routing_contract("claude-sonnet-5", "v", {}), v2)
        self.assertEqual((v2["adapter_version"], "reply_recovery" in v2), ("claude-cli-adapter-v2", False))
        v3 = run_pilot.cli_routing_contract("claude-sonnet-5", "v", {"reply_recovery": RECOVERY})
        self.assertEqual(v3["adapter_version"], "claude-cli-adapter-v3")
        self.assertEqual(v3["arguments"][v3["arguments"].index("--max-turns") + 1], "2")
        self.assertEqual(v3["reply_recovery"]["name"], RECOVERY)
        self.assertEqual(set(v3) - set(v2), {"reply_recovery"})
        execution = {"backend": "trusted-local"}
        self.assertNotEqual(run_pilot.protocol_hash("pressure-recent-v3", {"m": v2}, execution, {}),
                            run_pilot.protocol_hash("pressure-recent-v3", {"m": v3}, execution, {}))

    def test_the_rules_are_checked(self):
        with self.assertRaises(ValueError):
            claude_cli.cli_contract("m", max_turns=1, timeout=300, version="v", reply_recovery=RECOVERY)
        with self.assertRaises(ValueError):
            claude_cli.cli_contract("m", max_turns=2, timeout=300, version="v", reply_recovery="guess-json")
        with self.assertRaises(ValueError):
            claude_cli.ClaudeCliClient("m", Path("unused.jsonl"), "r", None, reply_recovery=RECOVERY)

    def test_the_flag_is_a_client_option_not_a_treatment(self):
        argv = ["--oracle", "hidden-tests:3", "--cli-reply-recovery", RECOVERY]
        self.assertEqual(run_pilot.client_options_from_args(argv), {"reply_recovery": RECOVERY})
        self.assertEqual(set(run_pilot.treatments_from_args(argv)), {"oracle"})
        self.assertEqual(run_pilot.client_options_from_args(["--oracle", "hidden-tests:3"]), {})
        self.assertIn("--cli-reply-recovery", run_pilot.CLIENT_FLAGS)


class CardPlanTests(unittest.TestCase):
    def test_card_020_hashes_the_option_in_both_arms_and_not_in_its_controls(self):
        card = run_card.load_card(CARDS / "020.json")
        plan = run_card.build_plan(card, CARDS / "020.json")
        stripped = copy.deepcopy(card)
        for arm in stripped["arms"]:
            arm["extra_args"] = [a for a in arm["extra_args"] if a not in ("--cli-reply-recovery", RECOVERY)]
        base = run_card.build_plan(stripped, CARDS / "020.json")
        for arm in card["arms"]:
            self.assertEqual(arm["extra_args"][-2:], ["--cli-reply-recovery", RECOVERY])
        planned = {inv.run_name: inv for inv in plan.invocations}
        for inv in base.invocations:
            if inv.kind == "run":
                self.assertNotEqual(planned[inv.run_name].expected_hash, inv.expected_hash)
                routing = planned[inv.run_name].expected_config["provider_routing"]["claude-sonnet-5"]
                self.assertEqual(routing["adapter_version"], "claude-cli-adapter-v3")
            else:  # scripted controls take the arm's extra_args and ignore the client option
                self.assertEqual(planned[inv.run_name].expected_hash, inv.expected_hash)
        plan_019 = run_card.build_plan(run_card.load_card(CARDS / "019.json"), CARDS / "019.json")
        hash_019 = {inv.task_ids[0]: inv.expected_hash for inv in plan_019.runs}
        for inv in base.runs:  # without the option, the incumbent is still card 019's protocol
            if inv.name == "incumbent":
                self.assertEqual(inv.expected_hash, hash_019[inv.task_ids[0]])


if __name__ == "__main__":
    unittest.main()
