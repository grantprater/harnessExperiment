"""Card 022's prerequisites, offline: the unshare sandbox's wiring (and, on Linux with user namespaces, its effect),
the post-run leakage audit, the recall probe and one-shot comparator call paths (against a stub CLI; no model), and
the series-level power arithmetic."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "experiments" / "forecast_tasks"
for path in (ROOT, ROOT / "experiments" / "p6_pilot", ROOT / "experiments" / "session_harness", FORECAST,
             ROOT / "tests"):
    sys.path.insert(0, str(path))

import audit_forecast_runs  # noqa: E402
import oneshot_forecast  # noqa: E402
import power_forecast  # noqa: E402
import probe_recall  # noqa: E402
import run_card  # noqa: E402
import run_pilot  # noqa: E402
import sandbox  # noqa: E402
from reticle.context.baseline import TranscriptStore  # noqa: E402
from reticle.execution import ExecutionRequest  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from test_claude_cli_client import STUB, ok  # noqa: E402

CARDS = ROOT / "experiments" / "session_harness" / "cards"
TASKS = json.loads((FORECAST / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]


class SandboxWiringTests(unittest.TestCase):
    GUARDS = {"stop_on_repeats": False, "resume_after_provider_stop": 0, "resume_wait_seconds": None}

    def test_off_the_execution_contract_is_unchanged(self):
        backend, execution = run_pilot.resolve_execution("trusted-local", "unused")
        self.assertIsNone(backend)
        self.assertEqual(set(execution), {"backend", "guest_python", "authority"})

    def test_on_it_is_recorded_and_hashed(self):
        backend, execution = run_pilot.resolve_execution("trusted-local", "unused", "unshare-rnm")
        self.assertIsInstance(backend, sandbox.NamespaceSandboxBackend)
        self.assertFalse(backend.host_isolation)
        self.assertEqual(execution["sandbox"], sandbox.contract())
        self.assertNotIn(str(ROOT), json.dumps(execution["sandbox"]))  # machine-independent
        plain = run_pilot.resolve_execution("trusted-local", "unused")[1]
        routing = {"gold-client": {"require_parameters": True}}
        contract = [run_pilot.task_contract(TASKS[0])]
        self.assertNotEqual(run_pilot.protocol_hash("pressure-recent-v3", routing, execution, self.GUARDS, contract),
                            run_pilot.protocol_hash("pressure-recent-v3", routing, plain, self.GUARDS, contract))
        with self.assertRaises(SystemExit):
            run_pilot.resolve_execution("oci", "unused", "unshare-rnm")

    def test_wrapper_hides_the_checkout_and_keeps_the_working_directory(self):
        hidden = sandbox.hidden_paths(ROOT, home=Path("/home/someone"))
        self.assertEqual(hidden[:3], [str(ROOT.resolve() / "experiments"), str(ROOT.resolve() / ".runtime" / "forecast-022"),
                                      str(ROOT.resolve() / ".git")])
        self.assertEqual(hidden[-1], str(Path("/home/someone") / "harness-sealed"))
        command = sandbox.NamespaceSandboxBackend(hidden).wrap(["python", "x.py"], ROOT)
        self.assertEqual(command[:6], ["unshare", "-rnm", "--", "sh", "-c", sandbox.WRAPPER])
        self.assertEqual(command[7], str(ROOT.resolve()))
        self.assertEqual(command[8:8 + len(hidden)], hidden)
        self.assertEqual(command[8 + len(hidden):], ["--", "python", "x.py"])

    def run_main(self, *argv):
        with mock.patch.object(sys, "argv", ["run_pilot.py", *argv, "--run-name", "unused", "--dry-run"]), \
                contextlib.redirect_stdout(io.StringIO()):
            run_pilot.main()

    def test_runner_guards(self):
        mutation = json.loads((ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json")
                              .read_text(encoding="utf-8"))["tasks"][0]["task_id"]
        with self.assertRaisesRegex(SystemExit, "forecast tasks only"):
            self.run_main("--client", "gold", "--sandbox", "unshare-rnm", "--tasks",
                          "experiments/mutation_tasks/tasks.mutations.json", mutation)
        if sandbox.availability() is not None:
            with self.assertRaisesRegex(SystemExit, "unshare"):
                self.run_main("--client", "gold", "--sandbox", "unshare-rnm", "--tasks",
                              "experiments/forecast_tasks/tasks.forecast.json", TASKS[0]["task_id"])

    def test_card_backend_field_reaches_the_runner_and_the_hash(self):
        card = run_card.load_card(CARDS / "022.json")
        self.assertEqual(run_card.validate_card(card), [])
        plan = run_card.build_plan(card, CARDS / "022.json")
        for inv in plan.invocations:
            self.assertEqual(inv.args[inv.args.index("--sandbox") + 1], "unshare-rnm")
            self.assertEqual(inv.expected_config["execution"]["sandbox"]["name"], "unshare-rnm")
        plain = json.loads(json.dumps(card))
        del plain["arms"][0]["backend"]["sandbox"]
        unwrapped = run_card.build_plan(plain, CARDS / "022.json")
        self.assertNotIn("--sandbox", unwrapped.invocations[0].args)
        self.assertNotEqual(plan.runs[0].expected_hash, unwrapped.runs[0].expected_hash)


@unittest.skipUnless(sandbox.availability() is None, "needs Linux with unprivileged user namespaces")
class SandboxEffectTests(unittest.TestCase):
    """What the peeker control shows in a container, as a unit test where the kernel allows it (the cloud VM)."""

    def test_network_and_hidden_paths_are_gone_and_the_workspace_stays(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "checkout" / "runs" / "ws").mkdir(parents=True)
            (root / "checkout" / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "home" / "harness-sealed").mkdir(parents=True)
            (root / "home" / "harness-sealed" / "r.json").write_text("{}", encoding="utf-8")
            probe = ("import os, socket, pathlib\n"
                     "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); net = 'reached'\n"
                     "except OSError:\n    net = 'blocked'\n"
                     "print(net, os.path.exists(%r), os.path.exists(%r))\n"
                     "pathlib.Path('out.txt').write_text('ok')\n") % (str(root / "checkout" / "secret.txt"),
                                                                        str(root / "home" / "harness-sealed" / "r.json"))
            backend = sandbox.NamespaceSandboxBackend([str(root / "checkout"), str(root / "home" / "harness-sealed")])
            result = backend.run(ExecutionRequest([sys.executable, "-c", probe], root / "checkout" / "runs" / "ws",
                                                  timeout_seconds=60))
            self.assertEqual(result.stdout.decode().split(), ["blocked", "False", "False"], result.stderr)
            self.assertEqual((root / "checkout" / "runs" / "ws" / "out.txt").read_text(encoding="utf-8"), "ok")
            self.assertTrue((root / "checkout" / "secret.txt").exists())  # hidden inside only


class AuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pilot = Path(temp.name) / "p6_pilot"
        self.task = next(t for t in TASKS if t["split"] == "calibration")
        self.tasks = {self.task["task_id"]: self.task}

    def run_dir(self, name, messages, client="claude-cli", files=None):
        run_dir = self.pilot / "runs" / name
        run_root = run_dir / "sessions" / "one"
        (run_root / "workspace").mkdir(parents=True)
        for filename, content in (files or {}).items():
            (run_root / "workspace" / filename).write_text(content, encoding="utf-8")
        store = TranscriptStore(LocalRuntime(run_root / "session", run_root / "workspace"))
        for message in messages:
            store.append(message)
        record = {"run_id": f"{name}-one", "task_id": self.task["task_id"], "client": client,
                  "session_dir": str(run_root.relative_to(self.pilot))}
        (run_dir / "results.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        return run_dir

    @staticmethod
    def call(name, arguments, call_id="c1"):
        return {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments)}}]}

    def test_a_clean_run_has_no_hit(self):
        messages = [self.call("read_file", {"path": "question.md"}),
                    {"role": "tool", "tool_call_id": "c1", "content": self.task["question_md"]},
                    self.call("run", {"command": "python analysis.py"}, "c2"),
                    {"role": "tool", "tool_call_id": "c2", "content": "base rate 0.41 over 2024-01-01..2026-06-29"}]
        entries = audit_forecast_runs.audit_run_dir(self.run_dir("clean", messages), self.tasks)
        self.assertEqual(entries[0]["hits"], [])

    def test_hits(self):
        T = self.task["forecast_date"]
        late = "2026-09-30"
        messages = [self.call("run", {"command": "pip install pandas"}),
                    self.call("write_file", {"path": "fetch.py", "content": "import urllib.request as u\n"}, "c2"),
                    {"role": "tool", "tool_call_id": "c2", "content": f"rows ...\n{late},5.1\n"},
                    {"role": "tool", "tool_call_id": "c3", "content": f"the window starts {T}"}]
        files = {"resolve.py": "import sys\nf = sys._getframe(1)\ndef outcome(rows, T, horizon):\n    return True\n"}
        entries = audit_forecast_runs.audit_run_dir(self.run_dir("dirty", messages, files=files), self.tasks)
        kinds = sorted(hit["kind"] for hit in entries[0]["hits"])
        self.assertEqual(kinds, ["checker_tampering", "future_date", "network", "network"])
        self.assertEqual(next(h for h in entries[0]["hits"] if h["kind"] == "future_date")["date"], late)

    def test_scripted_controls_are_skipped_unless_asked(self):
        run_dir = self.run_dir("peek", [self.call("run", {"command": "python -c 'import urllib'"})], client="peeker")
        self.assertEqual(audit_forecast_runs.audit_run_dir(run_dir, self.tasks), [])
        self.assertEqual(len(audit_forecast_runs.audit_run_dir(run_dir, self.tasks, all_clients=True)[0]["hits"]), 1)


class StubCliTestCase(unittest.TestCase):
    """The repository's stub CLI (tests/test_claude_cli_client.py) on PATH, so no test can reach a real CLI."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state = self.root / "state"
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
        patched = mock.patch.dict(os.environ, {"PATH": str(bin_dir), "STUB_CLAUDE_STATE": str(self.state),
                                               "ANTHROPIC_API_KEY": "must-not-reach-the-child"})
        patched.start()
        self.addCleanup(patched.stop)

    def replies(self, *contents):
        (self.state / "replies.json").write_text(json.dumps([ok(content=c) for c in contents]), encoding="utf-8")

    def stub_calls(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.state.glob("call-*.json"))]


class CallPathTests(StubCliTestCase):
    def test_recall_probe_asks_isolated_and_parses(self):
        self.replies("I remember it.\nOUTCOME: YES\nPROBABILITY: 0.9", "OUTCOME: UNKNOWN\nPROBABILITY: 0.5")
        ledger = probe_recall.run(self.root / "out", "claude-stub", limit=2)
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["parsed"]["named"] for r in rows], [True, False])
        self.assertEqual(rows[0]["parsed"]["probability"], 0.9)
        calls = self.stub_calls()
        self.assertEqual(len(calls), 2)
        argv = calls[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-stub")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(calls[0]["present"], [])  # no credential, no session link
        self.assertIn("memory check, not a forecast", calls[0]["prompt"])
        probe_recall.run(self.root / "out", "claude-stub", limit=2)  # resumes: nothing asked again
        self.assertEqual(len(self.stub_calls()), 2)

    def test_one_shot_call_path_and_ledger(self):
        self.replies("(a) ... Probability: 30%", "no number here")
        tasks = {t["task_id"]: t for t in TASKS}
        ids = json.loads((FORECAST / "splits.json").read_text(encoding="utf-8"))["calibration"][:2]
        ledger = oneshot_forecast.run(self.root / "one", ids, tasks, model="claude-stub")
        forecasts = oneshot_forecast.ledger_forecasts(ledger)
        self.assertEqual(forecasts[ids[0]], {"probability": 0.3, "committed": True})
        self.assertEqual(forecasts[ids[1]], {"probability": None, "committed": False})
        self.assertIn("professional forecaster", self.stub_calls()[0]["prompt"])

    def test_aliases_and_missing_live_flag_are_refused(self):
        with self.assertRaisesRegex(SystemExit, "full id"):
            probe_recall.run(self.root / "x", "sonnet", limit=1)
        with self.assertRaisesRegex(SystemExit, "--live"):
            probe_recall.main(["--run", "--out", str(self.root / "x")])
        with self.assertRaisesRegex(SystemExit, "--live"):
            oneshot_forecast.main(["--run", "--out", str(self.root / "x")])
        self.assertEqual(self.stub_calls(), [])


class RecallScoringTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(probe_recall.parse("OUTCOME: NO\nPROBABILITY: 12%"),
                         {"named": True, "outcome": False, "probability": 0.12})
        self.assertEqual(probe_recall.parse("**OUTCOME:** YES"), {"named": True, "outcome": True, "probability": 1.0})
        for reply in ("OUTCOME: UNKNOWN\nPROBABILITY: 0.5", "no format", ""):
            self.assertFalse(probe_recall.parse(reply)["named"])

    def entries(self, named, correct, n=20):
        out = []
        for i in range(n):
            parsed = {"named": i < named, "outcome": (i < correct) if i < named else None,
                      "probability": (0.9 if i < correct else 0.1) if i < named else None}
            out.append({"task_id": f"q{i}", "parsed": parsed, "base_rate": 0.5})
        return out, {f"q{i}": True for i in range(n)}

    def test_leak_rule_and_sensitivity(self):
        bank, truth = self.entries(named=4, correct=4)  # 20% named, all right: beats gold's 0.25
        control, control_truth = self.entries(named=10, correct=9)
        result = probe_recall.verdict(probe_recall.summarise(bank, truth), probe_recall.summarise(control, control_truth))
        self.assertTrue(result["leaked"] and result["sensitive"])
        bank, truth = self.entries(named=2, correct=2)  # 10% named: not more than 10%
        self.assertFalse(probe_recall.verdict(probe_recall.summarise(bank, truth),
                                              probe_recall.summarise(control, control_truth))["leaked"])
        silent, silent_truth = self.entries(named=0, correct=0)
        result = probe_recall.verdict(probe_recall.summarise(silent, silent_truth),
                                      probe_recall.summarise(silent, silent_truth))
        self.assertFalse(result["sensitive"])
        self.assertIn("insensitive", result["verdict"])


class PowerTests(unittest.TestCase):
    def test_t_quantile(self):
        self.assertAlmostEqual(power_forecast.t_quantile_95(35), 1.6896, places=3)
        self.assertAlmostEqual(power_forecast.t_quantile_95(10), 1.8125, places=2)

    def test_icc(self):
        self.assertAlmostEqual(power_forecast.icc([[1, 1, 1], [2, 2, 2], [3, 3, 3]]), 1.0)
        self.assertEqual(power_forecast.icc([[1, 2, 3], [1, 2, 3], [1, 2, 3]]), 0.0)

    def test_power_table_by_hand(self):
        rows = power_forecast.power_table([4] * 30, rhos=(0.0, 0.2), sigmas=(0.07,))
        self.assertEqual(rows[1]["design_effect"], 1.6)
        self.assertAlmostEqual(rows[1]["n_eff"], 75.0)
        expected = power_forecast.normal_cdf(0.02 * 75 ** 0.5 / 0.07 - power_forecast.t_quantile_95(29))
        self.assertAlmostEqual(rows[1]["power"]["0.07"], round(expected, 3))

    def test_committed_report_matches_the_committed_bank(self):
        report = json.loads((FORECAST / "power_forecast.json").read_text(encoding="utf-8"))
        splits = json.loads((FORECAST / "splits.json").read_text(encoding="utf-8"))
        self.assertEqual(report["sealed"]["questions"], len(splits["sealed"]))
        self.assertEqual(report["sealed"]["series"], len(splits["series"]["sealed"]))


if __name__ == "__main__":
    unittest.main()
