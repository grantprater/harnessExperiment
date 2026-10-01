"""run_native_bank (card 018 driver): the plan, resume, lock refusal, control gate, crash rerun, and stop rules with
fake runs; and one run end to end through native_control with a stub `claude` on PATH (synthetic mutation task,
trusted-local evaluator). No model is called and the real lock, records and campaign log are never touched."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import native_control  # noqa: E402
import run_native_bank as driver  # noqa: E402
from task_python import PYTEST_PYTHON  # noqa: E402
from test_mutation_task_wiring import MutationWiringTestCase  # noqa: E402

TASKS = sorted(json.loads(driver.SELECTION.read_text(encoding="utf-8"))["task_ids"])

# A stand-in for Claude Code: reads the mutated file, fixes it in its cwd (the workspace), runs one command, stops.
STUB = r'''
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ["--version"]:
    print("0.0.0 (stub)")
    sys.exit(0)
if sys.argv[1:] == ["sandbox", "status"]:
    print(os.environ.get("STUB_SANDBOX_STATUS", json.dumps({"installed": False, "available": False})))
    sys.exit(0)
prompt = sys.stdin.buffer.read().decode("utf-8")
state = Path(os.environ["STUB_CLAUDE_STATE"])
settings = Path(sys.argv[sys.argv.index("--settings") + 1]) if "--settings" in sys.argv else None
n = len(list(state.glob("call-*.json"))) + 1
(state / f"call-{n:03d}.json").write_text(json.dumps({
    "argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
    "settings": settings.read_text(encoding="utf-8") if settings and settings.exists() else None,
    "present": sorted(k for k in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID") if k in os.environ)}),
    encoding="utf-8")
target = Path.cwd() / "pkg" / "mod.py"
tools = sys.argv[sys.argv.index("--tools") + 1].split(",")
def emit(event):
    print(json.dumps(event), flush=True)
def call(message_id, use_id, name, content, **arguments):
    emit({"type": "assistant", "message": {"id": message_id, "content": [
        {"type": "tool_use", "id": use_id, "name": name, "input": arguments}]}})
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": use_id, "content": content}]}})
emit({"type": "system", "subtype": "init", "cwd": os.getcwd(), "tools": tools, "mcp_servers": [],
      "apiKeySource": "none", "permissionMode": "bypassPermissions", "model": "claude-stub"})
call("msg_1", "t1", "Read", target.read_bytes().decode(), file_path=str(target))
target.write_bytes(target.read_bytes().replace(b"x <= 0", b"x < 0"))
call("msg_2", "t2", "Edit", "updated", file_path=str(target), old_string="x <= 0", new_string="x < 0")
call("msg_3", "t3", "Bash", "", command='python -c "import pkg.mod"')
emit({"type": "assistant", "message": {"id": "msg_4", "content": [{"type": "text", "text": "Fixed."}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": 4, "total_cost_usd": 0.01,
      "result": "Fixed."})
'''

WRAPPER = '''import sys
from pathlib import Path
sys.path.insert(0, {harness!r})
import native_control, run_pilot
run_pilot.REPOS = Path({repos!r})
run_pilot.TASK_PYTHON = Path({python!r})
native_control.RECORD_ROOT = Path({records!r})
sys.exit(native_control.main())
'''


def write_record(root: Path, name: str, **fields):
    (root / name).mkdir(parents=True, exist_ok=True)
    record = {"stop": "end_turn", "acceptance": {"status": "accepted"}, "cli_failure": False, **fields}
    (root / name / "result.json").write_text(json.dumps(record), encoding="utf-8")
    return record


class DriverRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.records = self.root / "native_runs"
        self.records.mkdir()
        self.lock = self.root / "locks" / "live-run.lock"
        self.commit = mock.MagicMock()
        for patcher in (mock.patch.object(driver, "RECORD_ROOT", self.records),
                        mock.patch.object(driver, "LOG", self.root / "c018-campaign.jsonl"),
                        mock.patch.object(driver, "LOCK", self.lock),
                        mock.patch.object(driver, "SCRATCH_ROOT", str(self.root / "scratch")),
                        mock.patch.object(driver, "commit_evidence", self.commit)):
            patcher.start()
            self.addCleanup(patcher.stop)
        write_record(self.records, "c018-control-gold")
        write_record(self.records, "c018-control-noop", acceptance={"status": "rejected"})
        self.calls = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def execute(self, outcomes=None):
        """Run the driver with run_one faked: each outcome is ok, crash, refused, cli_failure, or isolation_abort."""
        outcomes = list(outcomes or [])

        def fake_run_one(name, cmd):
            self.calls.append(name)
            outcome = outcomes.pop(0) if outcomes else "ok"
            if outcome == "crash":
                (self.records / name).mkdir(exist_ok=True)
                (self.records / name / "config.json").write_text("{}", encoding="utf-8")
                return 1, None, 1.0
            if outcome == "refused":
                return native_control.EXIT_REFUSED, None, 1.0
            fields = {"cli_failure": outcome in ("cli_failure", "isolation_abort")}
            if outcome == "isolation_abort":
                fields.update(stop="isolation_abort", aborted="CLI tools differ")
            return 0, write_record(self.records, name, **fields), 1.0

        with mock.patch.object(driver, "run_one", side_effect=fake_run_one), \
                contextlib.redirect_stdout(io.StringIO()):
            return driver.execute()

    def log_rows(self):
        text = (self.root / "c018-campaign.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def test_plan_is_forty_rollout_major_runs_with_card_007_budgets(self):
        plan = driver.invocations()
        self.assertEqual(len(plan), 40)
        self.assertEqual([name for name, *_ in plan],
                         [f"c018-{task}-r{k}" for k in (1, 2) for task in TASKS])
        name, task, k, cmd = plan[0]
        self.assertEqual((name, task, k), ("c018-sqlparse-mut-001-r1", "sqlparse-mut-001", 1))
        text = " ".join(cmd)
        for flag in ("--model sonnet", "--max-turns 20", "--wall-seconds 1200", "--backend oci",
                     f"--tasks {driver.TASK_FILE} sqlparse-mut-001", "--run-name c018-sqlparse-mut-001-r1"):
            self.assertIn(flag, text)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            driver.print_plan()
        self.assertTrue(out.getvalue().startswith("40 invocations (20 tasks x 2 rollouts, rollout-major), 0 already"))

    def test_finished_runs_are_skipped_on_restart(self):
        finished = [name for name, *_ in driver.invocations()[:3]]
        for name in finished:
            write_record(self.records, name)
        self.assertEqual(self.execute(), driver.EXIT_OK)
        self.assertEqual(len(self.calls), 37)
        self.assertFalse(set(finished) & set(self.calls))
        self.assertEqual(self.log_rows()[-1]["status"], "complete")
        self.assertEqual(self.log_rows()[-1]["finished_runs"], 40)
        self.assertEqual(self.commit.call_count, 3 + 1)  # after 10, 20 and 30 new runs (37 new), then the final commit
        self.assertFalse(self.lock.exists())

    def test_a_held_lock_refuses_the_start(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text("another campaign", encoding="utf-8")
        self.assertEqual(self.execute(), driver.EXIT_LOCKED)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.lock.read_text(encoding="utf-8"), "another campaign")

    def test_missing_or_wrong_controls_refuse_the_start(self):
        (self.records / "c018-control-noop" / "result.json").unlink()
        self.assertEqual(self.execute(), driver.EXIT_REFUSED)
        write_record(self.records, "c018-control-noop")  # accepted: the noop control must be rejected
        self.assertEqual(self.execute(), driver.EXIT_REFUSED)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.lock.exists())

    def test_a_crash_is_rerun_once_and_a_second_crash_stops(self):
        self.assertEqual(self.execute(["crash", "ok", "crash", "crash"]), driver.EXIT_INTEGRITY)
        first, second = [name for name, *_ in driver.invocations()[:2]]
        self.assertEqual(self.calls, [first, first, second, second])
        self.assertTrue(any(p.name.startswith(f"{first}.interrupted-") for p in self.records.iterdir()))
        self.assertIn("evidence loss", self.log_rows()[-1]["status"])
        self.assertEqual([row.get("crash_retry") for row in self.log_rows()[:-1]], [0, 1, 0, 1])

    def test_three_consecutive_cli_failures_stop_and_a_success_resets_the_count(self):
        outcomes = ["cli_failure", "cli_failure", "ok", "cli_failure", "cli_failure", "cli_failure"]
        self.assertEqual(self.execute(outcomes), driver.EXIT_CHECKPOINT)
        self.assertEqual(len(self.calls), 6)
        self.assertIn("three consecutive CLI failures", self.log_rows()[-1]["status"])

    def test_a_leak_refusal_or_an_init_abort_stops_at_once(self):
        self.assertEqual(self.execute(["refused"]), driver.EXIT_INTEGRITY)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("leak check", self.log_rows()[-1]["status"])
        self.calls.clear()
        self.assertEqual(self.execute(["isolation_abort"]), driver.EXIT_INTEGRITY)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("init check", self.log_rows()[-1]["status"])


@unittest.skipUnless(PYTEST_PYTHON, "no interpreter with pytest for the trusted-local evaluator")
class EndToEndTests(MutationWiringTestCase):
    """One driver run through the real native_control path, with the stub CLI and a synthetic mutation task."""

    def setUp(self):
        super().setUp()
        self.records = self.root / "native_runs"
        self.state = self.root / "stub-state"
        self.state.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "stub_claude.py").write_text(STUB, encoding="utf-8")
        if os.name == "nt":
            (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{bin_dir / "stub_claude.py"}" %*\r\n',
                                                encoding="utf-8")
        else:
            launcher = bin_dir / "claude"
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_dir / "stub_claude.py"}" "$@"\n',
                                encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        # The stub comes first, and no directory that holds a real `claude` stays on PATH.
        kept = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
                if entry and shutil.which("claude", path=entry) is None]
        task_file = self.root / "tasks.synthetic.json"
        task_file.write_text(json.dumps({"schema_version": 1, "tasks": [self.task]}), encoding="utf-8")
        selection = self.root / "selection.json"
        selection.write_text(json.dumps({"task_ids": [self.task["task_id"]]}), encoding="utf-8")
        wrapper = self.root / "native_wrapper.py"
        wrapper.write_text(WRAPPER.format(harness=str(ROOT / "experiments" / "session_harness"),
                                          repos=str(self.repos), python=str(PYTEST_PYTHON),
                                          records=str(self.records)), encoding="utf-8")
        flags = [flag if flag != "oci" else "trusted-local" for flag in driver.FLAGS]
        flags[flags.index("--pytest-timeout") + 1] = "120"
        write_record(self.records, "c018-control-gold")
        write_record(self.records, "c018-control-noop", acceptance={"status": "rejected"})
        self.lock = self.root / "locks" / "live-run.lock"
        for patcher in (mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(bin_dir), *kept]),
                                                     "STUB_CLAUDE_STATE": str(self.state),
                                                     "ANTHROPIC_API_KEY": "must-not-reach-the-child",
                                                     "CLAUDECODE": "1"}),
                        mock.patch.object(driver, "NATIVE", wrapper),
                        mock.patch.object(driver, "TASK_FILE", task_file),
                        mock.patch.object(driver, "SELECTION", selection),
                        mock.patch.object(driver, "RECORD_ROOT", self.records),
                        mock.patch.object(driver, "LOG", self.root / "c018-campaign.jsonl"),
                        mock.patch.object(driver, "LOCK", self.lock),
                        mock.patch.object(driver, "ROLLOUTS", (1,)),
                        mock.patch.object(driver, "FLAGS", flags),
                        mock.patch.object(driver, "SCRATCH_ROOT", str(self.root / "scratch")),
                        mock.patch.object(driver, "commit_evidence", mock.MagicMock())):
            patcher.start()
            self.addCleanup(patcher.stop)

    @unittest.skipUnless(os.name == "nt", "the native arm's transcript audit knows Windows paths only (native_control.py, PORTABILITY); not ported to POSIX")
    def test_one_stub_run_end_to_end(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.execute(), driver.EXIT_OK)
        run = self.records / "c018-synthetic-mut-001-r1"
        for name in ("config.json", "stream.jsonl", "stderr.txt", "diff.patch", "result.json"):
            self.assertTrue((run / name).is_file(), name)
        result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        config = json.loads((run / "config.json").read_text(encoding="utf-8"))
        self.assertEqual((result["stop"], result["acceptance"]["status"]), ("end_turn", "accepted"))
        self.assertEqual(result["acceptance"]["test_counts"]["fail-to-pass"]["passed"], 1)
        self.assertEqual((result["turns_used"], result["responses"], result["tool_calls"]), (4, 4, 3))
        self.assertEqual(result["tool_calls_by_name"], {"Read": 1, "Edit": 1, "Bash": 1})
        self.assertEqual(result["first_base_file_edit"]["response"], 2)
        self.assertEqual(result["first_source_edit"]["response"], 2)
        self.assertTrue(result["ran_command"])
        self.assertTrue(result["audit_clean"], result["audit"])
        self.assertEqual(result["cost_estimate_usd"], 0.01)
        self.assertIn("pkg/mod.py | 2 +-", result["diff_stat"])
        self.assertFalse(result["cli_failure"])
        self.assertIsNone(result["scratch_removal_error"])
        call = json.loads((self.state / "call-001.json").read_text(encoding="utf-8"))
        self.assertEqual(call["prompt"], config["prompt"])
        self.assertEqual(config["prompt_sha256"], native_control.sha256_text(call["prompt"]))
        settings_file = Path(config["confinement"]["settings_file"])
        self.assertEqual(call["argv"], native_control.native_arguments("sonnet", 20, settings=settings_file))
        self.assertEqual(settings_file.parent.name, "c018-synthetic-mut-001-r1")  # beside the workspace, not in it
        self.assertEqual(call["settings"], config["confinement"]["settings_text"])
        self.assertEqual(native_control.sha256_text(call["settings"]), config["confinement"]["settings_sha256"])
        settings = json.loads(call["settings"])
        self.assertIs(settings["permissions"]["blockReadsOutsideWorkingDirectories"], True)
        self.assertIn("Bash(curl *)", settings["permissions"]["deny"])
        self.assertNotIn("sandbox", settings)
        self.assertEqual(result["confinement"]["layers"], {"read_block": True, "bash_deny": True, "sandbox": False})
        self.assertFalse(result["confinement"]["observed_active"])  # the stub denied nothing
        self.assertEqual(call["present"], [])  # session links and the API key are stripped
        self.assertTrue(call["cwd"].endswith("workspace"))
        text = (self.root / "c018-campaign.jsonl").read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual((rows[0]["run"], rows[0]["acceptance"], rows[0]["exit"]),
                         ("c018-synthetic-mut-001-r1", "accepted", 0))
        self.assertEqual(rows[-1]["status"], "complete")
        self.assertFalse(self.lock.exists())
        self.assertEqual(list(native_control.scratch_base(str(self.root / "scratch")).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
