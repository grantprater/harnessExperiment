"""Runner wiring for card 022's forecast tasks: contract and protocol hash (code-task hashes unchanged), the workspace
materializer (data before T only, no outcome), the in-run evaluator through AcceptanceRunner, the scripted controls,
the runner's guards, and card 022's plan. Offline: a bank built from tests/fixtures/forecast; no network, no API."""

import contextlib
import datetime
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "experiments" / "forecast_tasks"
FIXTURES = ROOT / "tests" / "fixtures" / "forecast"
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))
sys.path.insert(0, str(FORECAST))

import build_bank  # noqa: E402
import evaluate_forecast  # noqa: E402
import resolvers  # noqa: E402
import run_card  # noqa: E402
import run_pilot  # noqa: E402
from reticle.evaluation import AcceptanceRunner  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402

CARDS = ROOT / "experiments" / "session_harness" / "cards"


class ForecastRunnerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.bank = Path(cls.scratch.name) / "bank"
        config = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
        build_bank.build(config, build_bank.parse_series(config, FIXTURES / "raw"), cls.bank,
                         Path(cls.scratch.name) / "sealed", build_bank.read_manifest(FIXTURES / "raw"),
                         FIXTURES / "sources.json")
        cls.tasks = json.loads((cls.bank / "tasks.forecast.json").read_text(encoding="utf-8"))["tasks"]
        cls.patch = mock.patch.object(run_pilot, "FORECAST_DATA_DIR", cls.bank)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.scratch.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def task(self, template=None):
        return next(t for t in self.tasks if template is None or t["template"] == template)


class ContractAndHashTests(ForecastRunnerTestCase):
    ARGS = ("pressure-recent-v3", {"gold-client": {"require_parameters": True}},
            {"backend": "trusted-local", "guest_python": "python", "authority": "x"},
            {"stop_on_repeats": False, "resume_after_provider_stop": 0, "resume_wait_seconds": None})

    def test_contract_records_every_input_as_a_digest(self):
        task = self.task()
        contract = run_pilot.task_contract(task)
        self.assertEqual(contract["kind"], "forecast")
        self.assertEqual(contract["materializer"], run_pilot.FORECAST_MATERIALIZER_VERSION)
        self.assertEqual(set(contract["snapshot_sha256"]), {task["series"], *task["related"]})
        self.assertEqual(contract["statement_sha256"], hashlib.sha256(task["statement"].encode()).hexdigest())
        self.assertEqual(set(contract["evaluator"]), {"evaluate_forecast.py", "resolvers.py", "resolver_timeout_seconds",
                                                     "agreement_windows"})

    def test_forecast_hash_uses_the_forecast_instructions_and_evaluator(self):
        task = self.task()
        contract = run_pilot.task_contract(task)
        base = run_pilot.protocol_hash(*self.ARGS, [contract])
        tampered = dict(contract, snapshot_sha256={k: "0" * 64 for k in contract["snapshot_sha256"]})
        self.assertNotEqual(run_pilot.protocol_hash(*self.ARGS, [tampered]), base)
        with mock.patch.object(run_pilot, "FORECAST_INSTRUCTIONS", run_pilot.FORECAST_INSTRUCTIONS + " "):
            self.assertNotEqual(run_pilot.protocol_hash(*self.ARGS, [contract]), base)
        # evaluate_task.py (the code evaluator) is not an input of a forecast hash
        with tempfile.TemporaryDirectory() as other:
            with mock.patch.object(run_pilot, "HERE", Path(other)):
                (Path(other) / "evaluate_task.py").write_text("changed", encoding="utf-8")
                self.assertEqual(run_pilot.protocol_hash(*self.ARGS, [contract]), base)

    def test_forecast_evaluator_digest_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as other:
            for name in run_pilot.FORECAST_EVALUATOR_FILES:
                data = (FORECAST / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                (Path(other) / name).write_bytes(data)
            with mock.patch.object(run_pilot, "FORECAST_DIR", Path(other)):
                crlf = run_pilot.forecast_evaluator_digests()
        self.assertEqual(crlf, run_pilot.forecast_evaluator_digests())

    def test_code_task_hash_inputs_are_unchanged(self):
        """The pre-022 formula, restated: a mutation task's hash is exactly what it was."""
        mutation = json.loads((ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json")
                              .read_text(encoding="utf-8"))["tasks"][0]
        contracts = [run_pilot.task_contract(mutation)]
        arm, routing, execution, guards = self.ARGS
        inputs = {
            "runner_version": run_pilot.RUNNER_VERSION, "arm": arm, "instructions": run_pilot.INSTRUCTIONS,
            "tools": run_pilot.TOOL_SCHEMAS,
            "evaluator": hashlib.sha256((run_pilot.HERE / "evaluate_task.py").read_bytes()).hexdigest(),
            "managed_root_files": run_pilot.MANAGED_ROOT_FILES, "provider_routing": routing, "execution": execution,
            "guards": guards, "toolset_version": run_pilot.TOOLSET_VERSION, "task_contracts": contracts,
        }
        expected = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        self.assertEqual(run_pilot.protocol_hash(arm, routing, execution, guards, contracts), expected)
        self.assertNotIn("kind", contracts[0])


class MaterializerTests(ForecastRunnerTestCase):
    def test_workspace_holds_the_question_and_data_before_T_only(self):
        task = self.task()
        workspace = self.root / "workspace"
        run_pilot.materialize_forecast_workspace(task, workspace)
        files = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file())
        expected = sorted(["question.md", "data/README.md", *(f"data/{n}.csv" for n in [task["series"], *task["related"]])])
        self.assertEqual(files, expected)
        for name in [task["series"], *task["related"]]:
            lines = (workspace / "data" / f"{name}.csv").read_bytes().decode().split("\n")
            self.assertTrue(all(line[:10] < task["forecast_date"] for line in lines[1:] if line))
        self.assertIn(task["criteria"], (workspace / "question.md").read_text(encoding="utf-8"))

    def test_no_workspace_ever_holds_an_outcome(self):
        """Every fixture task's workspace: no resolution file, no row on or after T, no outcome word."""
        for task in self.tasks:
            workspace = self.root / task["task_id"]
            run_pilot.materialize_forecast_workspace(task, workspace)
            for path in workspace.rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("resolution", path.name)
                    self.assertNotIn('"outcome"', text)
                    if path.suffix == ".csv":
                        self.assertTrue(all(line[:10] < task["forecast_date"] for line in text.splitlines()[1:]))

    def test_a_tampered_or_late_snapshot_is_refused(self):
        task = json.loads(json.dumps(self.task()))
        item = task["snapshot"][task["series"]]
        original = (self.bank / item["path"]).read_bytes()
        late = original + f"{task['forecast_date']},1\n".encode()
        (self.bank / "late.csv").write_bytes(late)
        self.addCleanup((self.bank / "late.csv").unlink)
        with self.assertRaisesRegex(ValueError, "does not match its sha256"):
            run_pilot.materialize_forecast_workspace(dict(task, snapshot={**task["snapshot"], task["series"]: dict(
                item, path="late.csv")}), self.root / "a")
        with self.assertRaisesRegex(ValueError, "not before the forecast date"):
            run_pilot.materialize_forecast_workspace(dict(task, snapshot={**task["snapshot"], task["series"]: dict(
                item, path="late.csv", sha256=hashlib.sha256(late).hexdigest())}), self.root / "b")


class EvaluatorTests(ForecastRunnerTestCase):
    def evaluate(self, files, task=None, timeout=None):
        task = task or self.task("touch")
        run_root = self.root / "run"
        workspace, bundle = run_root / "workspace", run_root / "evaluator"
        run_pilot.materialize_forecast_workspace(task, workspace)
        patch = (mock.patch.object(run_pilot, "FORECAST_RESOLVER_TIMEOUT_SECONDS", timeout) if timeout
                 else contextlib.nullcontext())
        with patch:
            version = run_pilot.build_forecast_evaluator(task, bundle, sys.executable)
        for name, content in files.items():
            (workspace / name).write_text(content, encoding="utf-8")
        runtime = LocalRuntime(run_root / "session", workspace)
        decision = AcceptanceRunner(runtime).evaluate(run_pilot.forecast_acceptance_plan(task, version),
                                                      evaluator_root=bundle, timeout_seconds=120)
        details = run_pilot.evaluator_details(runtime, decision.report_artifact_id)
        return decision.status, details["forecast"]

    def gold(self, task):
        return {"forecast.json": json.dumps({"probability": task["base_rate"]}),
                "resolve.py": run_pilot.true_resolver_source(task)}

    def test_gold_commits_and_agrees_on_every_past_window(self):
        task = self.task("touch")
        status, forecast = self.evaluate(self.gold(task), task)
        self.assertEqual(status, "accepted")
        self.assertEqual(forecast["probability"], task["base_rate"])
        self.assertEqual(forecast["reading_agreement"]["agree"], forecast["reading_agreement"]["windows"])
        self.assertEqual(forecast["reading_agreement"]["windows"], run_pilot.FORECAST_AGREEMENT_WINDOWS)

    def test_rejections(self):
        task = self.task("touch")
        resolver = run_pilot.true_resolver_source(task)
        cases = {
            "nothing": {},
            "probability 1.7": {"forecast.json": '{"probability": 1.7}', "resolve.py": resolver},
            "two numbers": {"forecast.json": '{"probability": 0.4, "alt": 0.6}', "resolve.py": resolver},
            "no resolver": {"forecast.json": '{"probability": 0.4}'},
            "0/1 not bool": {"forecast.json": '{"probability": 0.4}',
                             "resolve.py": "def outcome(rows, T, horizon):\n    return 1\n"},
            "raises": {"forecast.json": '{"probability": 0.4}',
                       "resolve.py": "def outcome(rows, T, horizon):\n    raise ValueError('x')\n"},
            "no outcome()": {"forecast.json": '{"probability": 0.4}', "resolve.py": "x = 1\n"},
        }
        for name, files in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.root / "run", ignore_errors=True)
                status, forecast = self.evaluate(files, task)
                self.assertEqual(status, "rejected")
                self.assertFalse(forecast["committed"])
                self.assertTrue(forecast["problems"])

    def test_a_hanging_resolver_times_out(self):
        status, forecast = self.evaluate({"forecast.json": '{"probability": 0.4}',
                                          "resolve.py": "def outcome(rows, T, horizon):\n    while True:\n        pass\n"},
                                         timeout=3)
        self.assertEqual(status, "rejected")
        self.assertIn("did not finish", " ".join(forecast["problems"]))

    def test_a_misreading_commits_but_disagrees_on_past_windows(self):
        files = {"forecast.json": '{"probability": 0.4, "note": "strings are fine"}',
                 "resolve.py": "print('noise on stdout')\n\ndef outcome(rows, T, horizon):\n    return True\n"}
        status, forecast = self.evaluate(files)
        self.assertEqual(status, "accepted")
        agreement = forecast["reading_agreement"]
        self.assertLess(agreement["agree"], agreement["windows"])
        self.assertGreater(agreement["agree"], 0)

    def test_check_forecast(self):
        cases = {'{"probability": 0.25}': 0.25, '{"probability": 0}': 0.0, '{"probability": 1}': 1.0,
                 '{"probability": true}': None, '{"probability": "0.3"}': None, "0.3": None, "[0.3]": None,
                 '{"probability": NaN}': None, "not json": None, '{"p": 0.3}': None,
                 '{"probability": -0.1}': None, '{"probability": 0.3, "details": {"k": 2}}': None}
        for text, expected in cases.items():
            with self.subTest(text):
                path = self.root / "forecast.json"
                path.write_text(text, encoding="utf-8")
                self.assertEqual(evaluate_forecast.check_forecast(path)[0], expected)


class ScriptedControlTests(ForecastRunnerTestCase):
    def calls(self, client):
        steps = []
        while True:
            response = client.complete([], [])
            names = [call["function"]["name"] for call in response.message["tool_calls"]]
            steps.append([(n, json.loads(c["function"]["arguments"])) for n, c in
                          zip(names, response.message["tool_calls"])])
            if names == ["finish"]:
                return steps

    def test_clients_write_the_forecast_deliverables(self):
        task = self.task()
        forecast = lambda steps: next(json.loads(a["content"]) for step in steps for n, a in step  # noqa: E731
                                      if n == "write_file" and a["path"] == "forecast.json")
        self.assertEqual(forecast(self.calls(run_pilot.scripted_client("gold", task, None))),
                         {"probability": task["base_rate"]})
        self.assertEqual(forecast(self.calls(run_pilot.scripted_client("constant", task, None))), {"probability": 0.5})
        self.assertEqual(forecast(self.calls(run_pilot.scripted_client("gamer", task, None))), {"probability": 1.7})
        self.assertEqual(self.calls(run_pilot.scripted_client("noop", task, None))[0][0][0], "finish")
        peeker = self.calls(run_pilot.scripted_client("peeker", task, None))
        self.assertEqual(peeker[1], [("run", {"command": "python peek.py", "timeout_seconds": 60})])
        with self.assertRaises(SystemExit):
            run_pilot.scripted_client("breaker", task, None)

    def test_true_resolver_source_is_the_true_resolver(self):
        for task in self.tasks[:8]:
            namespace = {}
            exec(compile(run_pilot.true_resolver_source(task), "resolve.py", "exec"), namespace)
            rows = [(datetime.date.fromisoformat(line[:10]), float(line.split(",")[1])) for line in
                    (self.bank / task["snapshot"][task["series"]]["path"]).read_text(encoding="utf-8").splitlines()[1:]]
            past = resolvers.past_forecast_dates(datetime.date.fromisoformat(task["forecast_date"]), task["horizon_days"],
                                                 task["template"], datetime.date.fromisoformat(task["history_start"]))[:10]
            for day in past:
                self.assertEqual(namespace["outcome"](rows, day, task["horizon_days"]),
                                 resolvers.resolve(task["template"], rows, day, task["horizon_days"], task["params"]))

    def test_peek_script_blocks_are_all_required(self):
        self.assertIn('if all(value.startswith("blocked")', run_pilot.PEEK_SCRIPT)
        for probe in ("https", "socket", "dns", "checkout", "evaluator_bundle", "sealed"):
            self.assertIn(f'attempt("{probe}"', run_pilot.PEEK_SCRIPT)


class RunnerGuardTests(ForecastRunnerTestCase):
    def main(self, *argv):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["run_pilot.py", *argv, "--run-name", "unused", "--dry-run"]), \
                contextlib.redirect_stdout(output):
            run_pilot.main()
        return output.getvalue()

    def test_forecast_and_code_tasks_do_not_mix_and_forecast_clients_need_forecast_tasks(self):
        mixed = self.root / "mixed.json"
        mutation = json.loads((ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json")
                              .read_text(encoding="utf-8"))["tasks"][0]
        mixed.write_text(json.dumps({"tasks": [mutation, self.task()]}), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "mixes forecast and code"):
            self.main("--client", "gold", "--tasks", str(mixed))
        with self.assertRaisesRegex(SystemExit, "forecast tasks only"):
            self.main("--client", "constant", "--tasks", "experiments/mutation_tasks/tasks.mutations.json",
                      mutation["task_id"])
        tasks = self.root / "forecast.json"
        tasks.write_text(json.dumps({"tasks": self.tasks[:2]}), encoding="utf-8")
        self.assertIn("2 runs with the peeker client", self.main("--client", "peeker", "--tasks", str(tasks)))


class ProbeFileTests(unittest.TestCase):
    CLOUD = ROOT / "experiments" / "cloud"

    def test_owner_prompt_runs_only_the_probe(self):
        prompt = (self.CLOUD / "RUN_PROBE_ISOLATION.md").read_text(encoding="utf-8")
        steps = prompt.split("---")[1]
        for forbidden in ("campaign.py", "--execute", "setup_cloud.sh ", "pip install"):
            self.assertNotIn(forbidden, steps.replace("no setup script", ""))
        self.assertIn("bash experiments/cloud/probe_isolation.sh", steps)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_probe_script_parses(self):
        import subprocess
        script = (self.CLOUD / "probe_isolation.sh").read_bytes().replace(bytes([13, 10]), bytes([10]))
        completed = subprocess.run(["bash", "-n"], input=script, capture_output=True)  # a Linux checkout has LF
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for line in (b"ISOLATION: NETWORK+FILES", b"ISOLATION: NETWORK ONLY", b"ISOLATION: NONE"):
            self.assertIn(line, script)


class Card022Tests(unittest.TestCase):
    def test_card_validates_and_is_blocked_only_by_approval_and_prerequisites(self):
        card = run_card.load_card(CARDS / "022.json")
        self.assertEqual(run_card.validate_card(card), [])
        plan = run_card.build_plan(card, CARDS / "022.json")
        self.assertTrue(plan.blockers)
        for blocker in plan.blockers:
            self.assertTrue(blocker.startswith(("card status is 'proposed'", "prerequisite not done: ")), blocker)
        self.assertEqual((len(plan.runs), len(plan.controls)), (60, 5))
        expected = {c["name"]: c["expect"] for c in card["controls"]}
        self.assertEqual(expected, {"gold": "accepted", "constant": "accepted", "noop": "rejected",
                                    "gamer": "rejected", "peeker": "accepted"})
        hashes = {inv.task_ids[0]: inv.expected_hash for inv in plan.runs if inv.block == "calibration"}
        self.assertEqual(len(set(hashes.values())), 40)  # one per question contract
        self.assertEqual(plan.line_ending_hashes, {})  # the forecast hash does not read evaluate_task.py
        for inv in plan.runs:
            self.assertEqual(inv.expected_hash, hashes[inv.task_ids[0]])
            self.assertEqual(inv.expected_config["task_contracts"][0]["kind"], "forecast")


if __name__ == "__main__":
    unittest.main()
