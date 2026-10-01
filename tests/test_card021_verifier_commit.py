"""Card 021 offline validation: the reproduction-test verifier (check() on a mutated and a gold tree, generation
against a stub `claude`), the commitment tools and nudge (stub model client), and the runner wiring (hashes, offered
tools, an end-to-end gold run). Synthetic repository, trusted-local backend; no model, no API."""

import contextlib
import dataclasses
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

from reticle.context import PressureRecentContextPolicyV3
from reticle.execution import TrustedLocalBackend
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.runtime.nudges import COMMIT_NUDGE_TEMPLATE, CommitmentNudge, commit_nudge_text
from reticle.tools import ToolSuite
from reticle.tools.check_oracle import CheckOracleTools, check_schema
from reticle.tools.commitment import CommitmentLog, CommitmentTools, commitment_schemas
from reticle.tools.primitives import TOOL_SCHEMAS
from reticle.tools.repro_verifier import ReproTestVerifier, verifier_schema, write_bundle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import repro_verifiers  # noqa: E402
import score_commitments  # noqa: E402
import run_pilot  # noqa: E402
from task_python import PYTEST_PYTHON  # noqa: E402
from test_claude_cli_client import STUB, result_event  # noqa: E402
from test_mutation_task_wiring import MutationWiringTestCase  # noqa: E402

# Reproduction tests for the synthetic task (sign(0) became -1): a valid one (one case fails on the mutated tree,
# both pass on the gold tree), one that cannot see the bug, and one whose expected value is wrong.
VALID_TEST = ("from pkg.mod import sign\n\n\ndef test_zero_is_positive():\n    assert sign(0) == 1\n\n\n"
              "def test_negative():\n    assert sign(-3) == -1\n")
BLIND_TEST = "from pkg.mod import sign\n\n\ndef test_negative():\n    assert sign(-3) == -1\n"
WRONG_TEST = "from pkg.mod import sign\n\n\ndef test_zero():\n    assert sign(0) == 0\n"
GAMING_CONFTEST = ("import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
                   "    outcome = yield\n    outcome.get_result().outcome = 'passed'\n")
VERIFIER_FLAGS = ["--verifier", "repro-test:3", "--verifier-manifest", "MANIFEST", "--nudge", "commit"]


class HostStandInBackend:
    """Test double for IsolatedOCIBackend (exp/ontology-pilot port): host_isolation is True, so commands are rendered
    with the guest paths (/workspace/...) and the guest interpreter ("python") exactly as for podman; it maps both back
    to the mounted host directory and the test interpreter and runs through TrustedLocalBackend. Each request is kept,
    so a test can check what would have been mounted (only request.working_directory)."""

    name = "isolated-oci-stand-in"
    host_isolation = True

    def __init__(self, python=None):
        self.python = python or PYTEST_PYTHON or sys.executable
        self.requests = []

    def run(self, request, cancellation_event=None):
        self.requests.append(request)
        root = str(Path(request.working_directory).resolve())
        command = [part.replace("/workspace", root) for part in request.command]
        if command[0] == "python":
            command[0] = self.python
        environment = {name: value.replace("/workspace", root) for name, value in request.environment.items()}
        result = TrustedLocalBackend().run(dataclasses.replace(request, command=command, environment=environment),
                                           cancellation_event)
        return dataclasses.replace(result, backend=self.name, host_isolation=True)


def stand_in_execution(backend):
    """What run_pilot.resolve_execution returns for --backend oci, with the stand-in in place of podman."""
    return backend, {"backend": "isolated-oci", "image": "stand-in", "image_id": "stand-in",
                     "guest_python": backend.python, "container_user_arguments": [],
                     "authority": "isolated OCI: task workspace mount only, no network, unprivileged user"}


def call(name, arguments, call_id):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class Script:
    """Response i (1-based) is make(i): a list of tool calls."""

    def __init__(self, make):
        self.make, self.requests, self.tools = make, [], []

    def complete(self, messages, tools):
        self.requests.append(messages)
        self.tools.append([tool["function"]["name"] for tool in tools])
        calls = self.make(len(self.requests))
        return ModelResponse({"role": "assistant", "content": None if calls else "thinking", "tool_calls": calls})


class VerifierFixture(MutationWiringTestCase):
    """The synthetic mutation task materialized as the mutated and the gold tree, and a verifier bundle."""

    def setUp(self):
        super().setUp()
        self.python = PYTEST_PYTHON

    def tree(self, label, gold=False):
        return repro_verifiers.materialize(self.task, self.repos, self.root / "trees" / label, gold=gold)

    def bundle(self, code, label="bundle", collected=2):
        test = None
        if code is not None:
            test = self.root / f"{label}.py"
            test.write_text(code, encoding="utf-8")
        return write_bundle(self.root / label, test_file=test, python=self.python, timeout_seconds=120,
                            runner=run_pilot.VERIFIER_RUNNER, collected=collected)


@unittest.skipUnless(PYTEST_PYTHON, "the verifier needs an interpreter with pytest")
class VerifierCheckPathTests(VerifierFixture):
    def check(self, bundle, tree, max_calls=3):
        runtime = LocalRuntime(self.root / "sessions" / tree.name, tree)
        verifier = ReproTestVerifier(runtime, HostStandInBackend(), bundle, max_calls=max_calls, timeout_seconds=240)
        return runtime, verifier

    def test_a_scripted_test_fails_on_the_mutated_tree_and_passes_on_the_gold_tree(self):
        bundle = self.bundle(VALID_TEST)
        mutated, gold = self.tree("mutated"), self.tree("gold", gold=True)
        for tree, expected in ((mutated, '{"failing": 1, "passing": 1, "calls_left": 2}'),
                               (gold, '{"failing": 0, "passing": 2, "calls_left": 2}')):
            runtime, verifier = self.check(bundle, tree)
            before = runtime.workspace.revision()
            self.assertEqual(verifier.check(), (expected, "success"))
            self.assertEqual(runtime.workspace.revision(), before)
            self.assertFalse((tree / "test_reticle_repro.py").exists(), "the test never enters the workspace")
            self.assertEqual(list(Path(runtime.session_dir).glob("verifier-*")), [])
            events = [e.payload for e in runtime.journal.read_all() if e.kind == "verifier_check"]
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["scratch_removed"])
            self.assertNotIn("test_zero_is_positive", json.dumps(events))

    def test_through_the_tool_suite_the_fix_turns_the_count_and_the_cap_holds(self):
        tree = self.tree("workspace")
        runtime, verifier = self.check(self.bundle(VALID_TEST), tree, max_calls=2)
        tools = type("VerifiedSuite", (CheckOracleTools, ToolSuite), {})(runtime, interpreter=sys.executable,
                                                                         oracle=verifier)
        self.assertEqual(tools.schemas(), [*TOOL_SCHEMAS, verifier_schema(2)])
        self.assertEqual(tools.dispatch("check", "{}", "c1").content, '{"failing": 1, "passing": 1, "calls_left": 1}')
        edit = tools.dispatch("replace_text", json.dumps({"path": "pkg/mod.py", "old_text": "x <= 0",
                                                          "new_text": "x < 0"}), "c2")
        self.assertEqual(edit.status, "success")
        self.assertEqual(tools.dispatch("check", "{}", "c3").content, '{"failing": 0, "passing": 2, "calls_left": 0}')
        refused = tools.dispatch("check", "{}", "c4")
        self.assertEqual(refused.status, "rejected")
        self.assertEqual(verifier.record()["calls"], 2)
        self.assertEqual(verifier.record()["refused"], 1)

    def test_a_conftest_in_the_workspace_cannot_rewrite_the_counts(self):
        tree = self.tree("gamed")
        (tree / "conftest.py").write_text(GAMING_CONFTEST, encoding="utf-8")
        (tree / "pytest.ini").write_text("[pytest]\naddopts = -p no:python\n", encoding="utf-8")
        _, verifier = self.check(self.bundle(VALID_TEST), tree)
        self.assertEqual(verifier.check()[0], '{"failing": 1, "passing": 1, "calls_left": 2}')

    def test_a_broken_package_counts_every_case_as_failing(self):
        tree = self.tree("broken")
        (tree / "pkg" / "mod.py").write_text("def sign(x) broken\n", encoding="utf-8")
        _, verifier = self.check(self.bundle(VALID_TEST), tree)
        self.assertEqual(verifier.check()[0], '{"failing": 2, "passing": 0, "calls_left": 2}')

    def test_an_unavailable_verifier_runs_nothing_and_spends_nothing(self):
        runtime, verifier = self.check(self.bundle(None, collected=None), self.tree("none"))
        content, status = verifier.check()
        self.assertEqual(status, "error")
        self.assertEqual(json.loads(content)["calls_left"], 3)
        self.assertEqual((verifier.calls, verifier.record()["unavailable_calls"], verifier.record()["available"]),
                         (0, 1, False))

    def test_a_bundle_inside_the_workspace_is_refused(self):
        tree = self.tree("inside")
        bundle = write_bundle(tree / "verifier", test_file=None, python=self.python, timeout_seconds=60,
                              runner=run_pilot.VERIFIER_RUNNER, collected=None)
        with self.assertRaisesRegex(ValueError, "outside the workspace"):
            ReproTestVerifier(LocalRuntime(self.root / "s", tree), HostStandInBackend(), bundle)


class CommitmentToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        (self.root / "workspace" / "pkg").mkdir(parents=True)
        (self.root / "workspace" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", self.root / "workspace")
        self.log = CommitmentLog(self.runtime)
        self.tools = type("CommitSuite", (CommitmentTools, ToolSuite), {})(
            self.runtime, interpreter=sys.executable, commitment=self.log)

    def tearDown(self):
        self.temp_dir.cleanup()

    def dispatch(self, name, call_id, **arguments):
        return self.tools.dispatch(name, json.dumps(arguments), call_id)

    def test_fields_are_journaled_with_the_calls_between(self):
        self.assertEqual(self.tools.schemas(), [*TOOL_SCHEMAS, *commitment_schemas()])
        committed = self.dispatch("commit_hypothesis", "c1", file="pkg/mod.py", function="f", line=1,
                                  mechanism="x is 1", observation="read pkg/mod.py", prediction="x = 1")
        self.assertEqual(committed.status, "success")
        self.dispatch("read_file", "c2", path="pkg/mod.py")
        observed = self.dispatch("record_observation", "c3", observed="x = 1", matched=False,
                                 surprise="it matched after all", revised_hypothesis="none")
        self.assertEqual(observed.status, "success")
        events = {e.kind: e.payload for e in self.runtime.journal.read_all()
                  if e.kind in ("hypothesis_commit", "hypothesis_observation")}
        self.assertEqual((events["hypothesis_commit"]["file"], events["hypothesis_commit"]["line"],
                          events["hypothesis_commit"]["after_nudge"]), ("pkg/mod.py", 1, False))
        self.assertEqual(events["hypothesis_observation"]["tool_calls_since_commit"], ["read_file"])
        self.assertEqual((events["hypothesis_observation"]["commit"], events["hypothesis_observation"]["matched"]),
                         (1, False))
        record = self.log.record()
        self.assertEqual((record["commits"], record["observations"], record["mismatched"], record["first_commit"]),
                         (1, 1, 1, {"file": "pkg/mod.py", "function": "f", "line": 1}))

    def test_bad_arguments_are_rejected_and_nothing_is_recorded(self):
        full = dict(file="a.py", function="f", line=3, mechanism="m", observation="o", prediction="p")
        cases = [("commit_hypothesis", {k: v for k, v in full.items() if k != "prediction"}, "missing argument"),
                 ("commit_hypothesis", {**full, "line": "three"}, "'line' must be integer"),
                 ("commit_hypothesis", {**full, "line": True}, "'line' must be integer"),
                 ("commit_hypothesis", {**full, "mechanism": " "}, "non-empty"),
                 ("commit_hypothesis", {**full, "extra": 1}, "unknown argument"),
                 ("record_observation", {"observed": "o", "matched": False}, "'surprise' is required"),
                 ("record_observation", {"observed": "o", "matched": "no"}, "'matched' must be boolean")]
        for index, (name, arguments, message) in enumerate(cases):
            with self.subTest(message=message):
                outcome = self.tools.dispatch(name, json.dumps(arguments), f"c{index}")
                self.assertEqual(outcome.status, "rejected")
                self.assertIn(message, outcome.content)
        self.assertEqual(self.tools.dispatch("commit_hypothesis", "{not json", "cx").status, "rejected")
        self.assertEqual((self.log.record()["commits"], self.log.record()["observations"]), (0, 0))
        digits = self.tools.dispatch("commit_hypothesis", json.dumps({**full, "line": " 163"}), "cd")
        self.assertEqual(digits.status, "success")
        self.assertEqual(self.log.commits[0]["line"], 163)

    def test_tools_absent_without_the_option(self):
        plain = ToolSuite(self.runtime, interpreter=sys.executable)
        self.assertEqual(plain.dispatch("commit_hypothesis", "{}", "c1").status, "rejected")


class CommitmentNudgeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_script(self, make, limit=6, fraction=0.5):
        workspace = self.root / "workspace"
        (workspace / "pkg").mkdir(parents=True)
        (workspace / "pkg" / "core.py").write_text("def sign(x):\n    if x <= 0:\n        return -1\n    return 1\n",
                                                  encoding="utf-8")
        runtime = LocalRuntime(self.root / "session", workspace)
        log = CommitmentLog(runtime)
        tools = type("CommitSuite", (CommitmentTools, ToolSuite), {})(runtime, interpreter=sys.executable,
                                                                      commitment=log)
        nudge = CommitmentNudge(fraction)
        client = Script(make)
        task = TaskEnvelope("commit-task", "Fix sign.", budgets={"model_responses": limit})
        result = AgentController(runtime, task, tools, client, AgentLimits(limit, 100_000),
                                 policy=PressureRecentContextPolicyV3(), interventions=[nudge]).run()
        return runtime, log, nudge, client, result

    def test_fires_once_at_the_fraction_even_after_an_edit_and_the_model_can_answer_it(self):
        def make(i):
            if i == 1:  # an edit before the nudge: the midpoint nudge would stay silent, this one does not
                return [call("replace_text", {"path": "pkg/core.py", "old_text": "x <= 0", "new_text": "x < 0"}, "e1")]
            if i == 4:
                return [call("commit_hypothesis", {"file": "pkg/core.py", "function": "sign", "line": 2,
                                                   "mechanism": "<= makes zero negative", "observation": "read it",
                                                   "prediction": "x < 0 after the edit"}, "h1"),
                        call("read_file", {"path": "pkg/core.py"}, "r1")]
            if i == 5:
                return [call("record_observation", {"observed": "x < 0", "matched": True}, "o1")]
            if i == 6:
                return [call("finish", {"summary": "done"}, "f1")]
            return [call("read_file", {"path": "pkg/core.py"}, f"r{i}")]

        runtime, log, nudge, client, result = self.run_script(make)
        self.assertEqual(result.stop_reason, "finish_requested")
        messages = [e.payload for e in runtime.journal.read_all() if e.kind == "harness_message"]
        self.assertEqual([(m["name"], m["version"], m["after_response"]) for m in messages],
                         [("commit", "commit-nudge-v1", 3)])
        self.assertEqual(messages[0]["content"], commit_nudge_text(0.5))
        self.assertTrue(commit_nudge_text(0.5).startswith("Half of the response budget is spent. This reply must"))
        self.assertIn(commit_nudge_text(0.5), json.dumps(client.requests[3]))
        self.assertNotIn(commit_nudge_text(0.5), json.dumps(client.requests[2]))
        self.assertEqual(nudge.record(), {"fired": True, "after_response": 3, "fraction": 0.5,
                                          "version": "commit-nudge-v1"})
        record = log.record()
        self.assertEqual((record["commits"], record["commits_after_nudge"], record["matched"]), (1, 1, 1))
        observation = [e.payload for e in runtime.journal.read_all() if e.kind == "hypothesis_observation"][0]
        self.assertEqual(observation["tool_calls_since_commit"], ["read_file"])

    def test_the_offline_score_reads_the_journal(self):
        def make(i):
            if i == 3:
                return [call("commit_hypothesis", {"file": "pkg/core.py", "function": "sign", "line": 3,
                                                   "mechanism": "m", "observation": "o", "prediction": "p"}, "h1")]
            if i == 4:
                return [call("record_observation", {"observed": "q", "matched": False, "surprise": "s"}, "o1")]
            return [call("read_file", {"path": "pkg/core.py"}, f"r{i}")]

        runtime, *_ = self.run_script(make, limit=5)
        events = [e.to_dict() for e in runtime.journal.read_all()]
        task = {"mutation_file": "pkg/core.py", "mutated_function": "Sign.sign", "mutation_line": 2}
        row = score_commitments.score_run({"run_id": "r", "task_id": "t", "acceptance": {"status": "rejected"}},
                                          events, task)
        self.assertEqual((row["prediction"], row["located_file"], row["located_function"], row["line_distance"],
                          row["nudged"], row["committed_after_nudge"], row["accepted"]),
                         ("mismatched", True, True, 1, True, False, False))
        self.assertEqual(score_commitments.score_run({}, [], task)["prediction"], "none")

    def test_the_share_follows_the_fraction(self):
        self.assertTrue(commit_nudge_text(0.4).startswith("40% of the response budget"))
        self.assertEqual(COMMIT_NUDGE_TEMPLATE.format(share="Half"), commit_nudge_text())


class RunnerWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.manifest = self.root / "manifest.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def flags(self, manifest=None):
        return [str(manifest or self.manifest) if flag == "MANIFEST" else flag for flag in VERIFIER_FLAGS]

    def test_records_hashes_and_offered_tools(self):
        execution, guards = {"backend": "trusted-local"}, {"stop_on_repeats": False}
        missing = run_pilot.treatments_from_args(self.flags())
        self.assertIsNone(missing["verifier"]["manifest_sha256_lf"])
        self.manifest.write_bytes(b'{"tasks": {}}\r\n')
        present = run_pilot.treatments_from_args(self.flags())
        self.assertEqual(present["verifier"]["manifest_sha256_lf"],
                         run_pilot.hashlib.sha256(b'{"tasks": {}}\n').hexdigest())  # line endings do not count
        self.assertEqual((present["verifier"]["version"], present["verifier"]["max_calls"],
                          present["nudge"]["name"], present["nudge"]["version"], present["nudge"]["tools"]["names"]),
                         ("repro-test-verifier-v1", 3, "commit", "commit-nudge-v1",
                          ["commit_hypothesis", "record_observation"]))
        self.assertEqual(run_pilot.model_tool_schemas(present), [*TOOL_SCHEMAS, verifier_schema(3),
                                                                 *commitment_schemas()])
        only_commit = run_pilot.treatments_from_args(["--nudge", "commit"])
        self.assertEqual(run_pilot.model_tool_schemas(only_commit), [*TOOL_SCHEMAS, *commitment_schemas()])
        oracle = run_pilot.treatments_from_args(["--oracle", "hidden-tests:3"])
        self.assertEqual(run_pilot.model_tool_schemas(oracle), [*TOOL_SCHEMAS, check_schema(3)])
        hashes = {run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, (), treatments)
                  for treatments in ({}, missing, present, only_commit, oracle,
                                     run_pilot.treatments_from_args(["--nudge", "midpoint"]))}
        self.assertEqual(len(hashes), 6)
        self.assertEqual(run_pilot.treatments_from_args([]), {})

    def test_bad_combinations_are_refused(self):
        for bad in (["--verifier", "repro-test:0", "--verifier-manifest", "m"], ["--verifier", "hidden-tests"],
                    ["--verifier", "repro-test"], ["--verifier-manifest", "m"],
                    ["--verifier", "repro-test", "--verifier-manifest", "m", "--oracle", "hidden-tests"],
                    ["--nudge-fraction", "0.5"], ["--nudge", "commit", "--nudge-fraction", "1"]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                run_pilot.treatments_from_args(bad)

    def test_build_tools_offers_what_the_hash_lists(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        runtime = LocalRuntime(self.root / "session", workspace)
        bundle = write_bundle(self.root / "verifier", test_file=None, python=sys.executable, timeout_seconds=60,
                              runner=run_pilot.VERIFIER_RUNNER, collected=None)
        for flags in (self.flags(), [*self.flags(), "--completion", "finish-guard"], ["--nudge", "commit"],
                      self.flags()[:4]):
            with self.subTest(flags=flags):
                treatments = run_pilot.treatments_from_args(flags)
                tools, state = run_pilot.build_tools(runtime, treatments, ToolSuite, interpreter=sys.executable,
                                                     verifier_root=bundle, oracle_timeout_seconds=60,
                                                     backend=HostStandInBackend())
                self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(treatments))
                interventions = run_pilot.build_interventions(runtime, treatments, state)
                if (treatments.get("nudge") or {}).get("name") == "commit":
                    self.assertIsInstance(interventions[0], CommitmentNudge)
                    self.assertIn("commitment", state)

    def test_the_verifier_never_runs_trusted_local(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        runtime = LocalRuntime(self.root / "session", workspace)
        bundle = write_bundle(self.root / "verifier", test_file=None, python=sys.executable, timeout_seconds=60,
                              runner=run_pilot.VERIFIER_RUNNER, collected=None)
        treatments = run_pilot.treatments_from_args(self.flags())
        for backend in (None, TrustedLocalBackend()):
            with self.subTest(backend=backend), self.assertRaisesRegex(SystemExit, "never runs trusted-local"):
                run_pilot.build_tools(runtime, treatments, ToolSuite, interpreter=sys.executable,
                                      verifier_root=bundle, backend=backend)
        argv = ["run_pilot.py", "--client", "gold", "--run-name", "x", *self.flags()]
        with mock.patch.object(sys, "argv", argv), self.assertRaisesRegex(SystemExit, "needs --backend oci"):
            run_pilot.main()

    def test_a_manifest_changed_after_hashing_is_refused(self):
        self.manifest.write_text('{"tasks": {}}\n', encoding="utf-8")
        treatments = run_pilot.treatments_from_args(self.flags())
        self.manifest.write_text('{"tasks": {"x": {}}}\n', encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "changed since"):
            run_pilot.load_verifier_manifest(treatments)


def stream(*events):
    return {"events": list(events)}


def init(tools=("Read", "Glob", "Grep", "StructuredOutput")):
    return {"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": [], "apiKeySource": "none",
            "model": "claude-stub", "claude_code_version": "0.0.0"}


def tool_use(name, arguments, use_id):
    return {"type": "assistant", "message": {"id": f"m-{use_id}", "role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": name, "input": arguments}]}}


def tool_result(use_id, is_error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": "...", "is_error": is_error}]}}


def reply_with(code, read_path="pkg/mod.py", read_refused=False):
    return stream(init(), tool_use("Read", {"file_path": read_path}, "u1"), tool_result("u1", read_refused),
                  tool_use("StructuredOutput", {"test_code": code, "rationale": "zero is positive"}, "u2"),
                  tool_result("u2"), result_event(structured={"test_code": code, "rationale": "zero is positive"}))


@unittest.skipUnless(PYTEST_PYTHON, "the generator's pre-edit run needs an interpreter with pytest")
class GenerationTests(VerifierFixture):
    """repro_verifiers.py generate and score against a stub `claude` on PATH (the only thing on PATH)."""

    def setUp(self):
        super().setUp()
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
        git_dir = Path(shutil.which("git")).parent
        patched = mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(bin_dir), str(git_dir)]),
                                               "STUB_CLAUDE_STATE": str(self.state),
                                               "ANTHROPIC_API_KEY": "must-not-reach-the-child"})
        patched.start()
        self.addCleanup(patched.stop)
        self.task_file = self.root / "tasks.synthetic.json"
        self.task_file.write_text(json.dumps({"schema_version": 1, "tasks": [self.task]}), encoding="utf-8")
        self.out = self.root / "verifiers"

    def replies(self, *replies):
        (self.state / "replies.json").write_text(json.dumps(list(replies)), encoding="utf-8")

    def stub_calls(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.state.glob("call-*.json"))]

    def generate(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = repro_verifiers.main(["generate", "--out", str(self.out), "--tasks", str(self.task_file),
                                         "--repos", str(self.repos), "--python", self.python,
                                         "--model", "claude-stub", *extra])
        return code, output.getvalue()

    def test_a_blind_test_is_sent_back_and_the_failing_one_is_frozen_then_scored_valid(self):
        self.replies(reply_with(BLIND_TEST), reply_with(VALID_TEST))
        code, output = self.generate()
        self.assertEqual(code, 0, output)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["tasks"]["synthetic-mut-001"]
        self.assertEqual((entry["status"], entry["attempts"], entry["collected"]), ("available", 2, 2))
        self.assertEqual(entry["pre_edit"]["failed"], 1)
        self.assertAlmostEqual(entry["cost_usd"], 2 * 0.0123)
        self.assertEqual((self.out / entry["file"]).read_text(encoding="utf-8"), VALID_TEST)
        self.assertEqual(manifest["generator"]["model"], "claude-stub")
        first, second = self.stub_calls()
        for stub_call in (first, second):
            argv = stub_call["argv"]
            self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
            self.assertIn("--safe-mode", argv)
            self.assertEqual(stub_call["present"], [], "no API key or session variable reaches the child")
            cwd = Path(stub_call["cwd"]).resolve()
            self.assertNotIn(ROOT.resolve(), cwd.parents, "the generator works outside the repository")
            self.assertIn("'zero' now fails", stub_call["prompt"])
        self.assertNotIn("A previous attempt", first["prompt"])
        self.assertIn(BLIND_TEST, second["prompt"])
        self.assertIn("None of its cases failed", second["prompt"])
        generation = json.loads((self.out / "synthetic-mut-001" / "generation.json").read_text(encoding="utf-8"))
        self.assertEqual([a["rejected_because"] for a in generation["attempt_log"]], ["no_failure", None])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            repro_verifiers.main(["score", "--out", str(self.out), "--tasks", str(self.task_file),
                                  "--repos", str(self.repos), "--python", self.python])
        validity = json.loads((self.out / "validity.json").read_text(encoding="utf-8"))
        scored = validity["tasks"]["synthetic-mut-001"]
        self.assertEqual((scored["mutated"]["failing"], scored["gold"]["failing"], scored["valid"]), (1, 0, True))
        self.assertEqual(validity["valid"], 1)

    def test_agreement_with_acceptance_on_final_workspaces(self):
        self.replies(reply_with(VALID_TEST))
        self.generate()
        runs = self.root / "runs"
        for name, gold, status in (("c021-a-r1-incumbent", True, "accepted"), ("c021-a-r1-verifier-commit", False,
                                                                               "rejected")):
            run_id = "synthetic-mut-001__claude-stub"
            repro_verifiers.materialize(self.task, self.repos, runs / name / "sessions" / run_id / "workspace",
                                        gold=gold)
            (runs / name / "results.jsonl").write_text(json.dumps({
                "run_id": run_id, "task_id": "synthetic-mut-001", "acceptance": {"status": status}}) + "\n",
                encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            repro_verifiers.main(["agree", "--out", str(self.out), "--runs", str(runs), "--prefix", "c021",
                                  "--python", self.python])
        agreement = json.loads((self.out / "agreement.json").read_text(encoding="utf-8"))
        self.assertEqual(agreement["matrix"], {"accepted=True, verifier_passes=True": 1,
                                               "accepted=True, verifier_passes=False": 0,
                                               "accepted=False, verifier_passes=True": 0,
                                               "accepted=False, verifier_passes=False": 1})
        self.assertFalse(any((runs / "c021-a-r1-incumbent").rglob("test_reticle_repro.py")))

    def test_a_test_that_fails_for_the_wrong_reason_is_frozen_and_scored_invalid(self):
        self.replies(reply_with(WRONG_TEST))
        self.generate()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            repro_verifiers.main(["score", "--out", str(self.out), "--tasks", str(self.task_file),
                                  "--repos", str(self.repos), "--python", self.python])
        scored = json.loads((self.out / "validity.json").read_text(encoding="utf-8"))["tasks"]["synthetic-mut-001"]
        self.assertEqual((scored["mutated"]["failing"], scored["gold"]["failing"], scored["valid"]), (1, 1, False))

    def test_no_acceptable_test_leaves_the_verifier_unavailable(self):
        self.replies(reply_with(BLIND_TEST))
        self.generate("--max-attempts", "2")
        entry = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))["tasks"]["synthetic-mut-001"]
        self.assertEqual((entry["status"], entry["attempts"]), ("unavailable", 2))
        self.assertNotIn("file", entry)

    def test_a_task_past_the_spend_cap_is_unavailable_without_a_call(self):
        self.replies(reply_with(VALID_TEST))
        self.generate("--spend-cap-usd", "0.10")
        entry = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))["tasks"]["synthetic-mut-001"]
        self.assertEqual((entry["status"], entry["attempts"], entry["reason"]),
                         ("unavailable", 0, "generation spend cap reached"))
        self.assertEqual(self.stub_calls(), [])

    def test_isolation_problems_stop_and_freeze_nothing(self):
        cases = {"tool_isolation_violation": stream(init(("Read", "Bash", "StructuredOutput")),
                                                    result_event(structured={"test_code": VALID_TEST})),
                 "read_outside_workspace": reply_with(VALID_TEST, read_path="../evaluator/task.json")}
        # integration/2026-10: the merged model guard's message starts with model_mismatch and names
        # model_pin_violation; either way generation stops (it used to start with model_pin_violation)
        drifted = reply_with(VALID_TEST)
        drifted["events"][0] = dict(drifted["events"][0], model="claude-other")
        cases[r"model_mismatch \(model_pin_violation\)"] = drifted
        for problem, reply in cases.items():
            with self.subTest(problem=problem):
                shutil.rmtree(self.out, ignore_errors=True)
                self.replies(reply)
                with self.assertRaisesRegex(SystemExit, problem):
                    self.generate()
                self.assertFalse((self.out / "synthetic-mut-001" / "test_reticle_repro.py").exists())

    def test_a_refused_read_outside_is_not_an_escape(self):
        workspace = (self.root / "ws").resolve()
        workspace.mkdir()
        uses = [{"id": "a", "name": "Read", "input": {"file_path": str(self.root / "secret.txt")}},
                {"id": "b", "name": "Grep", "input": {"pattern": "x", "path": "sub"}},
                {"id": "c", "name": "Glob", "input": {"pattern": "../**/*.py"}}]
        escapes = repro_verifiers.read_escapes(uses, {"a": True, "b": False, "c": False}, workspace)
        self.assertEqual([e["name"] for e in escapes], ["Glob"])


@unittest.skipUnless(PYTEST_PYTHON, "the evaluator needs an interpreter with pytest")
class RunnerEndToEndTests(VerifierFixture):
    """run_pilot.main() with --verifier and --nudge commit on the synthetic task (gold client, --backend oci with
    the host stand-in in place of podman)."""

    def test_config_hash_bundle_and_records(self):
        verifiers = self.root / "verifiers"
        (verifiers / "synthetic-mut-001").mkdir(parents=True)
        (verifiers / "synthetic-mut-001" / "test_reticle_repro.py").write_text(VALID_TEST, encoding="utf-8")
        manifest = verifiers / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1, "generator": None, "tasks": {"synthetic-mut-001": {
            "status": "available", "file": "synthetic-mut-001/test_reticle_repro.py",
            "sha256_lf": run_pilot.sha256_lf(verifiers / "synthetic-mut-001" / "test_reticle_repro.py"),
            "collected": 2}}}), encoding="utf-8")
        task_file = self.root / "tasks.synthetic.json"
        task_file.write_text(json.dumps({"schema_version": 1, "tasks": [self.task]}), encoding="utf-8")
        here = self.root / "p6_pilot"
        here.mkdir()
        shutil.copyfile(run_pilot.HERE / "evaluate_task.py", here / "evaluate_task.py")
        flags = [str(manifest) if flag == "MANIFEST" else flag for flag in VERIFIER_FLAGS]
        argv = ["run_pilot.py", "--client", "gold", "--run-name", "treated", "--tasks", str(task_file),
                "synthetic-mut-001", "--max-calls-per-run", "6", "--backend", "oci", *flags]
        backend = HostStandInBackend()
        with mock.patch.object(run_pilot, "HERE", here), mock.patch.object(run_pilot, "REPOS", self.repos), \
                mock.patch.object(run_pilot, "TASK_PYTHON", Path(PYTEST_PYTHON)), \
                mock.patch.object(run_pilot, "resolve_execution", lambda *a, **k: stand_in_execution(backend)), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            run_pilot.main()
        run_dir = here / "runs" / "treated"
        config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        treatments = run_pilot.treatments_from_args(flags)
        self.assertEqual(config["treatments"], treatments)
        self.assertEqual(config["tools"], run_pilot.model_tool_schemas(treatments))
        record = json.loads((run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["protocol_hash"], config["protocol_hash"])
        self.assertEqual(record["acceptance"]["status"], "accepted")
        self.assertEqual((record["treatments"]["verifier"]["available"], record["treatments"]["verifier"]["calls"],
                          record["treatments"]["verifier"]["collected"]), (True, 0, 2))
        self.assertEqual(record["treatments"]["commitment"]["commits"], 0)
        self.assertEqual(record["treatments"]["nudge"]["version"], "commit-nudge-v1")
        session = run_dir / "sessions" / "synthetic-mut-001__gold-client"
        self.assertTrue((session / "verifier" / "test_reticle_repro.py").is_file())
        self.assertFalse((session / "workspace" / "test_reticle_repro.py").exists())


if __name__ == "__main__":
    unittest.main()
