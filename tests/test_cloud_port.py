"""Cloud port: task-interpreter resolution, the model pin and auth rule of both claude arms, trusted-local cards with a
machine check and a spend cap, cards 019/020, and the cloud campaign wrapper. Stub CLIs and a stub runner only."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))
sys.path.insert(0, str(ROOT / "experiments" / "cloud"))

import campaign  # noqa: E402
import claude_cli  # noqa: E402
import interpreters  # noqa: E402
import native_control  # noqa: E402
import run_card  # noqa: E402
import run_pilot  # noqa: E402
from test_claude_cli_client import (  # noqa: E402
    ClaudeCliTestCase, assistant_event, init_event, result_event, structured_use, tool,
)
from test_run_card import Fixture, arm  # noqa: E402

CARDS = ROOT / "experiments" / "session_harness" / "cards"
PINNED = "claude-sonnet-5"


class TaskInterpreterTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.venv = self.root / ".runtime" / "bugs-venv"

    def make(self, *parts):
        path = self.venv.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    def test_the_variable_wins(self):
        self.make("Scripts", "python.exe")
        self.assertEqual(interpreters.task_python(self.root, {"RETICLE_TASK_PYTHON": "/opt/py/bin/python"}),
                         Path("/opt/py/bin/python"))

    def test_the_windows_interpreter_when_it_exists(self):
        windows = self.make("Scripts", "python.exe")
        self.make("bin", "python")
        self.assertEqual(interpreters.task_python(self.root, {}), windows)

    def test_the_posix_interpreter_when_only_it_exists(self):
        posix = self.make("bin", "python")
        self.assertEqual(interpreters.task_python(self.root, {}), posix)

    def test_a_missing_venv_names_this_platforms_layout(self):
        expected = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
        self.assertEqual(interpreters.task_python(self.root, {}), self.venv.joinpath(*expected))

    def test_the_runner_and_the_native_arm_use_it(self):
        if os.environ.get("RETICLE_TASK_PYTHON"):
            self.skipTest("RETICLE_TASK_PYTHON is set")
        self.assertEqual(run_pilot.TASK_PYTHON, interpreters.task_python(run_pilot.ROOT, {}))
        if os.name == "nt":  # the Windows checkout keeps the path every recorded trusted-local run hashed
            self.assertEqual(run_pilot.TASK_PYTHON, run_pilot.ROOT / ".runtime" / "bugs-venv" / "Scripts" / "python.exe")
        _, execution = run_pilot.resolve_execution("trusted-local", run_pilot.DEFAULT_OCI_IMAGE)
        self.assertEqual(execution["guest_python"], str(run_pilot.TASK_PYTHON))
        self.assertEqual(native_control.task_interpreter().name, run_pilot.TASK_PYTHON.name)


class RecordedHashTests(unittest.TestCase):
    def test_card_007_still_plans_its_recorded_hash(self):
        plan = run_card.build_plan(run_card.load_card(CARDS / "007.json"), CARDS / "007.json")
        planned = {inv.run_name: inv.expected_hash for inv in plan.invocations}
        crlf = b"\r\n" in (ROOT / "experiments" / "p6_pilot" / "evaluate_task.py").read_bytes()
        if crlf:  # the Windows checkout the recorded runs hashed
            self.assertEqual(planned["c007-sqlparse-mut-001-r1"], "b0fda8c921ad")
            self.assertEqual((planned["s6a-control-gold-mut-v2"], planned["s6a-control-noop-mut-v2"]),
                             ("f825e41bc259", "58dfdf928e0b"))
        else:  # an LF checkout (Linux): the same protocol, with the recorded CRLF evaluator bytes, gives it too
            self.assertEqual(planned["c007-sqlparse-mut-001-r1"], "412a440aaa43")
            self.assertEqual(plan.line_ending_hashes["incumbent"], ("CRLF", "b0fda8c921ad"))

    def test_an_alias_contract_is_unchanged_and_a_full_id_is_pinned(self):
        alias = claude_cli.cli_contract("sonnet", max_turns=1, timeout=300, version="v")
        self.assertNotIn("model_pin", alias)
        pinned = claude_cli.cli_contract(PINNED, max_turns=1, timeout=300, version="v")
        self.assertEqual(pinned["model_pin"]["requested"], PINNED)
        self.assertEqual(set(pinned) - set(alias), {"model_pin"})


def pinned_reply(model, *calls, init_model=None, usage_model=None):
    structured = {"content": None, "tool_calls": list(calls)}
    message = assistant_event(structured_use(structured))
    message["message"]["model"] = model
    init = dict(init_event(), model=init_model or model)
    result = result_event(structured)
    result["modelUsage"] = {usage_model or model: {"costUSD": 0.01}}
    return {"events": [init, message, result]}


class ModelPinTests(ClaudeCliTestCase):
    def pinned_client(self, model=PINNED):
        return claude_cli.ClaudeCliClient(model, self.calls_path, "run-1", run_pilot.CallBudget(10, 0),
                                          backoff_seconds=0, workdir=self.root / "cli-cwd")

    def test_the_full_id_reaches_the_cli_unchanged_and_the_reported_model_is_recorded(self):
        self.replies(pinned_reply(PINNED, tool("finish", summary="done")))
        response = self.pinned_client().complete([{"role": "user", "content": "go"}], [])
        argv = self.stub_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], PINNED)
        self.assertEqual(response.metadata["reported_model"],
                         {"init": PINNED, "messages": [PINNED], "result": [PINNED]})
        row = run_pilot.read_jsonl(self.calls_path)[0]
        self.assertEqual(row["reported_model"]["init"], PINNED)
        self.assertNotIn("failure", row)

    def test_another_model_is_refused_before_its_reply_is_used(self):
        for reply in (pinned_reply("claude-sonnet-5-5", tool("run", command=["rm", "-rf", "."])),
                      pinned_reply(PINNED, tool("finish", summary="x"), init_model="claude-sonnet-5-5"),
                      pinned_reply(PINNED, tool("finish", summary="x"), usage_model="claude-sonnet-5-5")):
            with self.subTest(reply=reply["events"][0]["model"]):
                self.calls_path.unlink(missing_ok=True)
                for old in self.state.glob("call-*.json"):
                    old.unlink()
                self.replies(reply)
                with self.assertRaises(run_pilot.ModelClientError) as caught:
                    self.pinned_client().complete([{"role": "user", "content": "go"}], [])
                self.assertIn("model_pin_violation", str(caught.exception))
                rows = run_pilot.read_jsonl(self.calls_path)
                # integration/2026-10: one guard; its failure kind is model_mismatch, its message names both
                self.assertEqual([r["failure"] for r in rows], [claude_cli.MODEL_MISMATCH])  # not retried
                self.assertEqual(rows[0]["model_mismatch"]["expected"], PINNED)
                self.assertNotIn("response", rows[0])
                self.assertEqual(len(self.stub_calls()), 1)

    def test_a_refused_model_dispatches_no_tool_in_an_agent_run(self):
        self.replies(pinned_reply("claude-sonnet-5-5", tool("read_file", path="a.txt")))
        inner = self.pinned_client()
        client = run_pilot.GuardedClient(inner, self.tools)
        from reticle.context import PressureRecentContextPolicyV3
        from reticle.runtime.contracts import TaskEnvelope
        from reticle.runtime.controller import AgentController, AgentLimits
        task = TaskEnvelope("cli-task", "Read a.txt, then finish.", budgets={"model_responses": 3, "model_attempts": 3})
        result = AgentController(self.runtime, task, self.tools, client, AgentLimits(3, 100_000),
                                 policy=PressureRecentContextPolicyV3()).run()
        self.assertEqual(result.tool_calls, 0)
        self.assertIn("model_pin_violation", result.error)

    def test_an_alias_is_not_checked(self):
        self.replies(pinned_reply("claude-sonnet-5-5", tool("finish", summary="done")))
        response = self.pinned_client("sonnet").complete([{"role": "user", "content": "go"}], [])
        self.assertEqual(response.metadata["reported_model"]["init"], "claude-sonnet-5-5")


class AuthSourceTests(ClaudeCliTestCase):
    def client_for(self):
        return claude_cli.ClaudeCliClient("sonnet", self.calls_path, "run-1", run_pilot.CallBudget(10, 0),
                                          backoff_seconds=0, workdir=self.root / "cli-cwd")

    def reply_with_source(self, source):
        reply = pinned_reply("claude-stub", tool("finish", summary="done"))
        reply["events"][0]["apiKeySource"] = source
        return reply

    def test_a_login_other_than_none_is_accepted_and_recorded(self):
        for source in ("none", "claude.ai", "/login managed key", None):
            with self.subTest(source=source):
                self.replies(self.reply_with_source(source))
                response = self.client_for().complete([{"role": "user", "content": "go"}], [])
                self.assertEqual(response.metadata["api_key_source"], source)
                self.assertEqual(run_pilot.read_jsonl(self.calls_path)[-1]["cli_init"]["apiKeySource"], source)

    def test_an_environment_key_or_token_is_refused(self):
        for source in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "apiKeyHelper"):
            with self.subTest(source=source):
                self.replies(self.reply_with_source(source))
                with self.assertRaises(run_pilot.ModelClientError):
                    self.client_for().complete([{"role": "user", "content": "go"}], [])
                self.assertEqual(run_pilot.read_jsonl(self.calls_path)[-1]["failure"], "tool_isolation_violation")

    def test_anthropic_variables_are_always_stripped_and_named_session_variables_kept(self):
        with mock.patch.dict(os.environ, {"RETICLE_CLI_PASS_ENV": "CLAUDE_CODE_SESSION_ID, ANTHROPIC_API_KEY",
                                          "ANTHROPIC_BASE_URL": "https://example.invalid"}):
            environment, removed = claude_cli.child_environment()
            self.assertIn("CLAUDE_CODE_SESSION_ID", environment)
            self.assertNotIn("ANTHROPIC_API_KEY", environment)
            self.assertNotIn("ANTHROPIC_BASE_URL", environment)
            self.assertNotIn("CLAUDECODE", environment)
            self.assertIn("ANTHROPIC_API_KEY", removed)
            self.replies(self.reply_with_source("none"))
            self.client_for().complete([{"role": "user", "content": "go"}], [])
        self.assertEqual(self.stub_calls()[-1]["present"], ["CLAUDE_CODE_SESSION_ID"])
        self.assertEqual(run_pilot.read_jsonl(self.calls_path)[-1]["request"]["kept_environment"],
                         ["CLAUDE_CODE_SESSION_ID"])
        environment, _ = claude_cli.child_environment()
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", environment)  # nothing kept without the variable


class NativeArmTests(unittest.TestCase):
    INIT = {"type": "system", "subtype": "init", "tools": native_control.NATIVE_TOOLS.split(","), "mcp_servers": [],
            "apiKeySource": "none", "permissionMode": "bypassPermissions", "model": PINNED}

    def test_the_init_check_pins_a_full_id(self):
        self.assertIsNone(native_control.init_problem(self.INIT, PINNED))
        self.assertIn("model_pin_violation",
                      native_control.init_problem(dict(self.INIT, model="claude-sonnet-5-5"), PINNED))
        self.assertIsNone(native_control.init_problem(dict(self.INIT, model="claude-sonnet-5-5"), "sonnet"))

    def test_the_init_check_accepts_other_logins_and_refuses_environment_keys(self):
        self.assertIsNone(native_control.init_problem(dict(self.INIT, apiKeySource="claude.ai")))
        self.assertIsNotNone(native_control.init_problem(dict(self.INIT, apiKeySource="ANTHROPIC_API_KEY")))

    def test_the_full_id_reaches_the_cli_unchanged(self):
        arguments = native_control.native_arguments(PINNED, 20)
        self.assertEqual(arguments[arguments.index("--model") + 1], PINNED)

    def test_stream_models_reads_every_report(self):
        events = [{"event": dict(self.INIT)},
                  {"event": {"type": "assistant", "message": {"model": PINNED, "content": []}}},
                  {"event": {"type": "result", "modelUsage": {PINNED: {}}}}]
        reported = native_control.stream_models(events)
        self.assertEqual(reported, {"init": PINNED, "messages": [PINNED], "result": [PINNED]})
        self.assertIsNone(claude_cli.model_problem(PINNED, reported))

    def test_powershell_is_offered_only_on_windows(self):
        self.assertEqual("PowerShell" in native_control.NATIVE_TOOLS.split(","), os.name == "nt")


def vm_arm(name, policy, **extra):
    return arm(name, policy, backend={"kind": "trusted-local", "isolation": "vm-sandbox"}, **extra)


class TrustedLocalCardTests(unittest.TestCase):
    def test_a_vm_sandbox_card_runs_without_an_engine_and_logs_the_host(self):
        fixture = Fixture(self)
        card = fixture.card(arms=[vm_arm("a", "stub-policy-a"), vm_arm("b", "stub-policy-b")])
        plan = fixture.plan(card)
        with mock.patch.object(run_card.shutil, "which", return_value=None):  # no engine at all
            self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)
        host = [e for e in fixture.events(plan) if e["event"] == "host"]
        self.assertEqual(len(host), 1)
        self.assertEqual(host[0]["isolation"], {"a": "vm-sandbox", "b": "vm-sandbox"})
        for key in ("os", "cpu_count", "driver_python", "runner_python", "claude_cli_version"):
            self.assertIn(key, host[0])
        self.assertEqual(host[0]["cpu_count"], os.cpu_count())

    def test_the_isolation_value_is_validated(self):
        fixture = Fixture(self)
        card = fixture.card(arms=[arm("a", "stub-policy-a", backend={"kind": "trusted-local", "isolation": "moon"}),
                                  arm("b", "stub-policy-b")])
        self.assertTrue(any("backend" in error for error in run_card.validate_card(card)))

    def test_an_oci_card_is_refused_without_its_engine(self):
        fixture = Fixture(self)
        oci = {"kind": "oci", "image": "localhost/stub:1", "image_id": "a" * 64, "engine": "podman"}
        card = fixture.card(arms=[arm("a", "stub-policy-a", backend=oci), arm("b", "stub-policy-b", backend=oci)])
        plan = fixture.plan(card)
        with mock.patch.object(run_card.shutil, "which", return_value=None):
            self.assertEqual(fixture.execute(plan), run_card.EXIT_REFUSED)
        self.assertTrue(any("podman, which is not on PATH" in line and "OCI cards cannot run here" in line
                            for line in fixture.output), fixture.output)
        self.assertEqual(fixture.invoked(), [])
        self.assertFalse(fixture.lock.exists())

    def test_an_engine_without_a_daemon_is_refused(self):
        fixture = Fixture(self)
        oci = {"kind": "oci", "image": "localhost/stub:1", "image_id": "a" * 64, "engine": "docker"}
        plan = fixture.plan(fixture.card(arms=[arm("a", "stub-policy-a", backend=oci),
                                               arm("b", "stub-policy-b", backend=oci)]))
        failed = run_card.subprocess.CompletedProcess(["docker", "version"], 1, stdout="",
                                                      stderr="Cannot connect to the Docker daemon")
        with mock.patch.object(run_card.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(run_card.subprocess, "run", return_value=failed):
            problems = run_card.engine_problems(plan)
        self.assertEqual(len(problems), 1)
        self.assertIn("the engine is not running", problems[0])

    def test_the_list_price_cap_checkpoints_before_the_next_attempt(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["budgets"]["campaign"]["list_price_cap_usd"] = 0.25
        fixture.behave({}, attempts=2)
        behaviour = json.loads(fixture.behaviour_path.read_text(encoding="utf-8"))
        fixture.behaviour_path.write_text(json.dumps(dict(behaviour, cost_per_attempt=0.05)), encoding="utf-8")
        plan = fixture.plan(card)
        self.assertEqual(fixture.execute(plan), run_card.EXIT_CHECKPOINT)
        self.assertEqual(len(fixture.invoked()), 3)  # 3 runs x 2 attempts x $0.05 = $0.30 >= $0.25
        stop = [e for e in fixture.events(plan) if e["event"] == "checkpoint_stop"][-1]
        self.assertIn("list-price cap", stop["reason"])
        report = Path(card["report"]["path"]).read_text(encoding="utf-8")
        self.assertIn("nested model cost (CLI list price): $0.30 over 6 CLI calls", report)

    def test_a_report_without_a_cap_has_no_spend_section(self):
        fixture = Fixture(self)
        card = fixture.card()
        fixture.execute(fixture.plan(card))
        self.assertNotIn("Spend and time", Path(card["report"]["path"]).read_text(encoding="utf-8"))

    def test_a_model_pin_violation_is_an_integrity_stop(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        first = plan.runs[0].run_name
        fixture.behave({first: "model_pin"})
        self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY)
        self.assertEqual(fixture.invoked(), [first])  # never retried
        stop = [e for e in fixture.events(plan) if e["event"] == "integrity_stop"][-1]
        self.assertIn("corrupted_protocol: model_pin_violation", stop["reason"])


class CloudCardTests(unittest.TestCase):
    def plan(self, name):
        card = run_card.load_card(CARDS / f"{name}.json")
        self.assertEqual(run_card.validate_card(card), [])
        return card, run_card.build_plan(card, CARDS / f"{name}.json")

    def test_card_019_is_card_007_on_the_cloud_backend(self):
        card, plan = self.plan("019")
        c007 = run_card.load_card(CARDS / "007.json")
        # cloud-results-019 set the card running with its approval prerequisite done (2026-09-28); the test still
        # asserted the proposed card (a failure on that branch, fixed on integration/2026-10)
        self.assertEqual(card["status"], "running")
        self.assertEqual(plan.blockers, [])
        self.assertEqual(card["tasks"], {**c007["tasks"], "sets": {
            "calibration": c007["tasks"]["sets"]["calibration"],
            "controls": dict(c007["tasks"]["sets"]["controls"], note=card["tasks"]["sets"]["controls"]["note"])}})
        self.assertEqual(card["budgets"]["per_run"], c007["budgets"]["per_run"])
        self.assertEqual(card["blocks"], c007["blocks"])
        self.assertEqual(card["stop_rules"]["consecutive_failures_to_stop"], 3)
        self.assertEqual(card["budgets"]["campaign"]["list_price_cap_usd"], 40)
        incumbent = card["arms"][0]
        self.assertEqual((incumbent["model"], incumbent["backend"]), (PINNED, {"kind": "trusted-local",
                                                                              "isolation": "vm-sandbox"}))
        self.assertEqual({k: v for k, v in incumbent.items() if k not in ("model", "backend", "note")},
                         {k: v for k, v in c007["arms"][0].items() if k not in ("model", "backend", "note")})
        self.assertEqual((len(plan.runs), len(plan.controls)), (40, 2))
        self.assertEqual(plan.sets["calibration"], run_card.build_plan(c007, CARDS / "007.json").sets["calibration"])
        self.assertEqual({inv.run_name for inv in plan.controls}, {"c019-control-gold", "c019-control-noop"})
        for inv in plan.runs:
            self.assertEqual(inv.args[inv.args.index("--models") + 1], PINNED)
            self.assertEqual(inv.args[inv.args.index("--backend") + 1], "trusted-local")
            self.assertIn("model_pin", inv.expected_config["provider_routing"][PINNED])
        c007_hashes = {inv.expected_hash for inv in run_card.build_plan(c007, CARDS / "007.json").runs}
        self.assertFalse({inv.expected_hash for inv in plan.runs} & c007_hashes)

    def test_card_020_pairs_card_015s_arms_on_the_cloud_backend(self):
        card, plan = self.plan("020")
        c015 = run_card.load_card(CARDS / "015.json")
        # cloud-results-020 set the card running with its prerequisites done (2026-09-29); see card 019's test
        self.assertEqual(card["status"], "running")
        self.assertEqual(plan.blockers, [])
        self.assertEqual([a["name"] for a in card["arms"]], [a["name"] for a in c015["arms"]])
        # Card 015's extra_args plus the same CLI reply recovery in both arms (card 019's restarts).
        self.assertEqual([a["extra_args"] for a in card["arms"]],
                         [a["extra_args"] + ["--cli-reply-recovery", claude_cli.REPLY_RECOVERY] for a in c015["arms"]])
        self.assertEqual(card["blocks"], c015["blocks"])
        self.assertEqual(card["tasks"], c015["tasks"])
        self.assertEqual((len(plan.runs), len(plan.controls)), (32, 2))
        _, plan_019 = self.plan("019")
        hash_019 = {inv.task_ids[0]: inv.expected_hash for inv in plan_019.runs}
        for inv in plan.runs:  # the recovery option is in the CLI contract, so no run shares card 019's hash
            self.assertNotEqual(inv.expected_hash, hash_019[inv.task_ids[0]])
            self.assertEqual(inv.expected_config["provider_routing"][PINNED]["reply_recovery"]["name"],
                             claude_cli.REPLY_RECOVERY)


class CampaignWrapperTests(unittest.TestCase):
    def test_controls_run_while_the_card_awaits_approval(self):
        fixture = Fixture(self)
        card = fixture.card(status="proposed", controls=[
            {"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a", "expect": "accepted"},
            {"name": "noop", "client": "noop", "task_set": "all", "like_arm": "a", "expect": "rejected"}])
        plan = fixture.plan(card)
        lines = []
        self.assertEqual(campaign.run_controls(plan, lock_path=fixture.lock, out=lines.append), 0)
        self.assertEqual(fixture.invoked(), ["tc-control-gold", "tc-control-noop"])
        self.assertEqual(campaign.status(plan)["controls"], {"gold": "ok", "noop": "ok"})
        self.assertFalse(fixture.lock.exists())
        # the campaign later reuses them
        approved = copy.deepcopy(card)
        approved["status"] = "approved"
        self.assertEqual(fixture.execute(fixture.plan(approved), resume=True), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked().count("tc-control-gold"), 1)

    def test_a_failed_control_fails_the_precheck(self):
        fixture = Fixture(self)
        card = fixture.card(status="proposed", controls=[
            {"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a", "expect": "accepted"}])
        fixture.behave({"tc-control-gold": "reject"})
        lines = []
        self.assertEqual(campaign.run_controls(fixture.plan(card), lock_path=fixture.lock, out=lines.append),
                         run_card.EXIT_INTEGRITY)

    def test_other_blockers_refuse_the_controls(self):
        fixture = Fixture(self)
        card = fixture.card(status="proposed")
        card["arms"][0]["expected_protocol_hash"] = "000000000000"
        lines = []
        self.assertEqual(campaign.run_controls(fixture.plan(card), lock_path=fixture.lock, out=lines.append),
                         run_card.EXIT_REFUSED)

    def test_supervise_runs_the_campaign_and_reports_counts_and_cost(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["budgets"]["campaign"]["list_price_cap_usd"] = 100
        behaviour = json.loads(fixture.behaviour_path.read_text(encoding="utf-8"))
        fixture.behaviour_path.write_text(json.dumps(dict(behaviour, cost_per_attempt=0.5)), encoding="utf-8")
        plan = fixture.plan(card)
        lines = []
        code = campaign.supervise(plan, None, poll_seconds=0.2, lock_path=fixture.lock, out=lines.append)
        self.assertEqual(code, 0, lines)
        value = campaign.status(plan)
        self.assertEqual((value["runs_finished"], value["runs_planned"]), (8, 8))
        self.assertEqual((value["nested_calls"], value["nested_cost_usd"]), (16, 8.0))
        self.assertIsNotNone(value["wall_seconds"])
        self.assertIn("nested model cost (CLI list price) $8.00 over 16 calls", lines[-2])
        events = run_card.read_jsonl(campaign.supervisor_path(plan))
        self.assertEqual([e["event"] for e in events], ["start", "end"])
        self.assertEqual(campaign.wait(plan, timeout=0, out=lines.append), "FINISHED")
        self.assertTrue(lines[-1].startswith("FINISHED "))

    def test_wait_reports_a_supervisor_that_never_started_or_died(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        lines = []
        self.assertEqual(campaign.wait(plan, timeout=0, out=lines.append), "GONE")
        campaign.log_supervisor(plan, "start", pid=1, supervisor_pid=os.getpid())
        self.assertEqual(campaign.wait(plan, timeout=0, out=lines.append), "RUNNING")
        campaign.log_supervisor(plan, "start", pid=1, supervisor_pid=2 ** 22 + 12345)  # no such process
        self.assertEqual(campaign.wait(plan, timeout=0, out=lines.append), "GONE")

    @unittest.skipIf(os.name == "nt", "the supervisor interrupts a POSIX process group (the cloud VM)")
    def test_the_spend_guard_interrupts_the_campaign_and_the_lock_is_released(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["budgets"]["campaign"]["list_price_cap_usd"] = 100  # run_card's own check never fires here
        behaviour = json.loads(fixture.behaviour_path.read_text(encoding="utf-8"))
        fixture.behaviour_path.write_text(json.dumps(dict(behaviour, cost_per_attempt=1.0, sleep_seconds=1.5)),
                                          encoding="utf-8")
        plan = fixture.plan(card)
        lines = []
        code = campaign.supervise(plan, None, poll_seconds=0.5, spend_cap=1.5, lock_path=fixture.lock,
                                  out=lines.append)
        self.assertTrue(any(line.startswith("spend guard: nested model cost $2.00") for line in lines), lines)
        self.assertNotEqual(code, 0)
        self.assertFalse(fixture.lock.exists())
        self.assertLess(campaign.status(plan)["runs_finished"], 8)
        events = [e["event"] for e in run_card.read_jsonl(campaign.supervisor_path(plan))]
        self.assertEqual((events[0], events[-1]), ("start", "end"))
        self.assertIn("spend_guard", events)

    def test_a_dead_campaigns_lock_is_released_and_a_live_holders_is_not(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        lock = Path(scratch.name) / "live-run.lock"
        lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        self.assertIsNone(campaign.release_dead_lock(lock, os.getpid()))  # alive
        self.assertIsNone(campaign.release_dead_lock(lock, 2 ** 22 + 12345))  # another holder
        lock.write_text(json.dumps({"pid": 2 ** 22 + 12345}), encoding="utf-8")
        self.assertIn("removed", campaign.release_dead_lock(lock, 2 ** 22 + 12345))
        self.assertFalse(lock.exists())

    def test_the_spend_guard_decision(self):
        self.assertFalse(campaign.over_spend(39.99, 40))
        self.assertFalse(campaign.over_spend(40.0, 40))
        self.assertTrue(campaign.over_spend(40.01, 40))
        self.assertFalse(campaign.over_spend(1000, None))


if __name__ == "__main__":
    unittest.main()
