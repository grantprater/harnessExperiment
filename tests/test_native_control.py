"""native_control: transcript summary, audit flags, prompt, init and leak checks, the base-commit diff, and the
scripted gold/noop path end to end on a synthetic mutation task (no CLI call, trusted-local evaluator)."""

import contextlib
import difflib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import native_control  # noqa: E402
import run_pilot  # noqa: E402  (native_control put experiments/p6_pilot on sys.path)
from task_python import PYTEST_PYTHON  # noqa: E402
from test_mutation_task_wiring import MUTATED, MutationWiringTestCase  # noqa: E402

HEALTHY_PATCH = (
    "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,4 +1,4 @@\n def sign(x):\n-    if x <= 0:\n+    if x < 0:\n"
    "         return -1\n     return 1\n"
)
ALLOWED_INIT = {"type": "system", "subtype": "init", "tools": native_control.NATIVE_TOOLS.split(","),
                "mcp_servers": [], "apiKeySource": "none", "permissionMode": "bypassPermissions"}


def assistant(message_id, *blocks):
    return {"type": "assistant", "message": {"id": message_id, "content": list(blocks)}}


def use(use_id, name, **inputs):
    return {"type": "tool_use", "id": use_id, "name": name, "input": inputs}


def result(use_id, is_error=False, content=""):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": use_id, "is_error": is_error, "content": content}]}}


def timed(stream):
    return [{"t": float(i), "event": e} for i, e in enumerate(stream)]


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "pkg").mkdir(parents=True)
        (self.workspace / "pkg" / "mod.py").write_bytes(b"x = 1\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_summary_counts_responses_first_actions_and_audit_flags(self):
        stream = [
            {"type": "system", "subtype": "init", "tools": ["Bash", "Read"], "model": "m", "apiKeySource": "none"},
            assistant("m1", {"type": "thinking", "thinking": ""}),
            assistant("m1", use("u1", "Read", file_path=str(self.workspace / "pkg" / "mod.py"))),
            result("u1"),
            assistant("m2", use("u2", "Bash", command="python -m pytest tests -q"),
                      use("u3", "Bash", command="curl https://example.com/fix.patch")),
            result("u2"), result("u3"),
            assistant("m3", use("u4", "Edit", file_path="pkg/mod.py", old_string="1", new_string="2"),
                      use("u5", "Read", file_path="C:/elsewhere/secret.py")),
            result("u4"), result("u5", is_error=True),
            {"type": "result", "subtype": "success", "num_turns": 4, "is_error": False, "total_cost_usd": 0.5},
        ]
        summary = native_control.summarize_stream(timed(stream), self.workspace, {"pkg/mod.py"})
        self.assertEqual(summary["responses"], 3)
        self.assertEqual(summary["tool_calls"], 5)
        self.assertEqual(summary["tool_calls_by_name"], {"Read": 2, "Bash": 2, "Edit": 1})
        self.assertEqual(summary["first_command"]["response"], 2)
        self.assertTrue(summary["ran_command"])
        self.assertEqual(summary["first_base_file_edit"]["response"], 3)
        self.assertEqual(summary["first_source_edit"]["response"], 3)
        self.assertEqual(summary["edited_files"], ["pkg/mod.py"])
        self.assertEqual(summary["test_commands"], 1)
        self.assertEqual(summary["tool_errors"], 1)
        self.assertEqual(len(summary["audit"]["network_commands"]), 1)
        self.assertEqual([o.get("file_path") for o in summary["audit"]["paths_outside_workspace"]],
                         ["C:/elsewhere/secret.py"])
        self.assertFalse(summary["audit_clean"])
        self.assertEqual(summary["result"]["num_turns"], 4)
        self.assertEqual(summary["result"]["total_cost_usd"], 0.5)

    def test_first_source_edit_skips_tests_and_new_files(self):
        base = {"pkg/mod.py", "tests/test_mod.py", "README.md"}
        stream = [
            assistant("m1", use("u1", "Write", file_path="repro.py", content="print(1)")), result("u1"),
            assistant("m2", use("u2", "Edit", file_path="tests/test_mod.py", old_string="a", new_string="b")),
            result("u2"),
            assistant("m3", use("u3", "Edit", file_path="pkg/mod.py", old_string="1", new_string="2")), result("u3"),
        ]
        summary = native_control.summarize_stream(timed(stream), self.workspace, base)
        self.assertEqual(summary["first_any_edit"]["response"], 1)
        self.assertEqual(summary["first_base_file_edit"]["response"], 2)
        self.assertEqual(summary["first_source_edit"]["response"], 3)
        self.assertFalse(summary["ran_command"])
        self.assertTrue(summary["audit_clean"])

    def test_audit_flags_parent_steps_home_references_and_harness_markers(self):
        markers = (("mutation_patch", native_control.re.compile("mutation_patch")),)
        stream = [
            assistant("m1", use("u1", "Bash", command="ls ../..")), result("u1"),
            assistant("m2", use("u2", "PowerShell", command="Get-ChildItem $env:USERPROFILE")), result("u2"),
            assistant("m3", use("u3", "Glob", pattern="../**/*.json")), result("u3"),
            assistant("m4", use("u4", "Bash", command="python -c \"print(1..2)\" && echo ...")), result("u4"),
            assistant("m5", use("u5", "Bash", command="cat notes.txt")),
            result("u5", content=[{"type": "text", "text": '"mutation_patch": "--- a/x"'}]),
            assistant("m6", use("u6", "Edit", file_path="pkg/mod.py", old_string="x", new_string="from .. import y")),
            result("u6"),
        ]
        summary = native_control.summarize_stream(timed(stream), self.workspace, set(), markers=markers)
        self.assertEqual([e["response"] for e in summary["audit"]["escape_references"]], [1, 2, 3])
        self.assertEqual(summary["audit"]["harness_markers"],
                         [{"response": 5, "tool": "Bash", "where": "result", "marker": "mutation_patch"}])
        self.assertFalse(summary["audit_clean"])

    def test_checkout_paths_are_markers_except_under_an_allowed_root(self):
        root = native_control.checkout_roots()[-1]
        venv = root / ".runtime" / "bugs-venv"
        stream = [
            assistant("m1", use("u1", "Bash", command="python -m pytest -q")),
            result("u1", content=f"File {venv / 'Lib' / 'site-packages' / '_pytest' / 'python.py'}, line 1"),
            assistant("m2", use("u2", "Bash", command="echo hi")),
            result("u2", content=f"{root.as_posix()}/experiments/mutation_tasks"),
        ]
        summary = native_control.summarize_stream(timed(stream), self.workspace, set(), allowed_roots=(venv,),
                                                  markers=tuple(native_control.leak_markers()))
        self.assertEqual({(hit["response"], hit["where"]) for hit in summary["audit"]["harness_markers"]},
                         {(2, "result")})
        self.assertIn("/c/", "".join(native_control.path_forms(Path("C:/x/y"))))

    def test_interpreter_roots_are_the_environment_and_its_base_python(self):
        environment = self.root / "venv"
        (environment / "Scripts").mkdir(parents=True)
        base = self.root / "base-python"
        (environment / "pyvenv.cfg").write_text(f"home = {base}\ninclude-system-site-packages = false\n",
                                                encoding="utf-8")
        roots = native_control.interpreter_roots(environment / "Scripts" / "python.exe")
        self.assertEqual(roots, (environment, base))
        self.assertEqual(native_control.interpreter_roots(self.root / "bare" / "Scripts" / "python.exe"),
                         (self.root / "bare",))

    def test_prompt_is_the_reticle_request_with_only_the_tool_phrases_replaced(self):
        task = {"repo": "demo", "repo_url": "https://example.invalid/demo",
                "statement": "demo has a regression: 'x' fails. Call finish when you are done. with the run tool)"}
        native = native_control.opening_prompt(task)
        reticle = native_control.reticle_opening_request(task)
        self.assertNotIn("run tool", native.replace(task["statement"], ""))
        self.assertNotIn("Call finish", native.replace(task["statement"], ""))
        self.assertIn(task["statement"], native)  # the statement is never rewritten
        before, after = reticle.split(" "), native.split(" ")
        changed = [op for op in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes()
                   if op[0] != "equal"]
        self.assertEqual([(" ".join(before[i1:i2]), " ".join(after[j1:j2])) for _, i1, i2, j1, j2 in changed],
                         [("the run tool). Call finish", "Bash). Stop")])
        with self.assertRaises(SystemExit):
            native_control.native_instructions("A template without the phrases. {statement}")

    def test_init_check_accepts_only_the_arm_configuration(self):
        self.assertIsNone(native_control.init_problem(ALLOWED_INIT))
        for change in ({"tools": [*ALLOWED_INIT["tools"], "WebFetch"]}, {"tools": [*ALLOWED_INIT["tools"], "Agent"]},
                       {"tools": ["Bash"]}, {"mcp_servers": [{"name": "x"}]}, {"apiKeySource": "ANTHROPIC_API_KEY"},
                       {"permissionMode": "default"}):
            with self.subTest(change=change):
                self.assertIsNotNone(native_control.init_problem(dict(ALLOWED_INIT, **change)))

    def test_a_failed_init_check_kills_the_cli_at_once(self):
        fake = self.root / "fake_cli.py"
        init = dict(ALLOWED_INIT, tools=[*ALLOWED_INIT["tools"], "WebFetch"])
        fake.write_text("import json, sys, time\n"
                        f"print(json.dumps({init!r}), flush=True)\n"
                        "print('not json', flush=True)\n"
                        "time.sleep(60)\n", encoding="utf-8")
        run = native_control.run_cli([sys.executable, str(fake)], "prompt", self.root, dict(native_control.os.environ),
                                     90, self.root / "stream.jsonl", self.root / "stderr.txt",
                                     check_init=native_control.init_problem)
        self.assertIn("WebFetch", run["aborted"])
        self.assertFalse(run["timed_out"])
        self.assertLess(run["wall_seconds"], 45)
        summary = native_control.summarize_stream(run["events"], self.workspace, set())
        self.assertEqual(native_control.stop_for(run, summary, None), "isolation_abort")

    def test_stop_classification(self):
        cases = [({"aborted": "tools"}, {}, None, "isolation_abort"), ({"timed_out": True}, {}, None, "wall_cap"),
                 ({}, {"result": None}, None, "cli_error"),
                 ({}, {"result": {"subtype": "error_max_turns", "is_error": True}}, None, "max_turns"),
                 ({}, {"result": {"subtype": "success", "is_error": True}}, None, "cli_error"),
                 ({}, {"result": {"subtype": "success", "is_error": False}}, None, "end_turn"),
                 ({}, {}, "gold", "scripted")]
        for run, summary, scripted, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(native_control.stop_for(run, summary, scripted), expected)
        self.assertEqual(native_control.CLI_FAILURE_STOPS, ("cli_error", "isolation_abort"))

    def test_location_checks_refuse_overlaps_and_leftover_runs(self):
        inside = native_control.ROOT / ".runtime" / "scratch-test"
        self.assertTrue(any("overlap" in p for p in native_control.location_problems(inside, "run")))
        base = self.root / "base"
        self.assertEqual(native_control.location_problems(base, "run"), [])
        (base / "run").mkdir(parents=True)
        self.assertEqual(native_control.location_problems(base, "run"), [])
        (base / "older-run" / "evaluator").mkdir(parents=True)
        self.assertTrue(any("older-run" in p for p in native_control.location_problems(base, "run")))

    def test_workspace_checks_refuse_hidden_paths_history_and_installed_copies(self):
        interpreter = Path(sys.executable)
        task = {"hidden_paths": ["tests"], "gold_source_files": ["pkg/mod.py"]}
        self.assertEqual(native_control.workspace_problems(task, self.workspace, interpreter, self.root), [])
        (self.workspace / "tests").mkdir()
        (self.workspace / ".git").mkdir()
        problems = native_control.workspace_problems(task, self.workspace, interpreter, self.root)
        self.assertEqual(len(problems), 2)
        installed = native_control.workspace_problems({"gold_source_files": ["json/decoder.py"]}, self.workspace,
                                                      interpreter, self.root)
        self.assertTrue(any("installed copy" in p and "json" in p for p in installed))
        missing = native_control.workspace_problems({"gold_source_files": ["src/pkg/mod.py"]}, self.workspace,
                                                    self.root / "absent-python.exe", self.root)
        self.assertTrue(any("not found" in p for p in missing))
        self.assertEqual(native_control.task_packages({"gold_source_files": ["src/pkg/a.py", "top.py"],
                                                       "mutation_file": "other/b.py"}), ["other", "pkg", "top"])

    def test_diff_is_taken_against_a_pristine_copy_without_touching_the_workspace(self):
        pristine = self.root / "pristine"
        (pristine / "pkg").mkdir(parents=True)
        (pristine / "pkg" / "mod.py").write_bytes(b"x = 1\n")
        (self.workspace / "pkg" / "mod.py").write_bytes(b"x = 2\n")
        (self.workspace / "pkg" / "__pycache__").mkdir()
        (self.workspace / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"\0")
        (self.workspace / "check.py").write_text("print(1)\n", encoding="utf-8")
        diff = native_control.workspace_diff(pristine, self.workspace)
        self.assertIn("pkg/mod.py", diff["stat"])
        self.assertIn("check.py", diff["stat"])
        self.assertNotIn("pycache", diff["stat"])
        self.assertIn("-x = 1\n+x = 2", diff["patch"])
        self.assertFalse((self.workspace / ".git").exists())

    def test_criterion_counts(self):
        counts = native_control.criterion_counts(["a", "b", "c"], {"failing": ["a"], "missing": [], "skipped": ["c"]})
        self.assertEqual(counts, {"expected": 3, "passed": 1, "failing": 1, "missing": 0, "skipped": 1})
        self.assertEqual(native_control.criterion_counts(["a"], None), {"expected": 1, "passed": None})


@unittest.skipUnless(PYTEST_PYTHON, "no interpreter with pytest for the trusted-local evaluator")
class ScriptedPathTests(MutationWiringTestCase):
    """The no-model control of the whole native path on the synthetic mutation task."""

    def setUp(self):
        super().setUp()
        self.task["gold_patch"] = HEALTHY_PATCH
        self.task_file = self.root / "tasks.synthetic.json"
        self.task_file.write_text(json.dumps({"schema_version": 1, "tasks": [self.task]}), encoding="utf-8")
        self.records = self.root / "native_runs"
        self.scratch_root = self.root / "scratch"
        for patcher in (mock.patch.object(run_pilot, "REPOS", self.repos),
                        mock.patch.object(run_pilot, "TASK_PYTHON", Path(PYTEST_PYTHON or sys.executable)),
                        mock.patch.object(native_control, "RECORD_ROOT", self.records)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_native(self, name, *extra):
        argv = ["--tasks", str(self.task_file), "synthetic-mut-001", "--backend", "trusted-local", "--pytest-timeout",
                "120", "--run-name", name, "--scratch-root", str(self.scratch_root), *extra]
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            code = native_control.main(argv)
        return code, out.getvalue()

    def test_gold_is_accepted_noop_rejected_and_scratch_removed(self):
        code, _ = self.run_native("control-gold", "--scripted", "gold")
        self.assertEqual(code, native_control.EXIT_OK)
        record = json.loads((self.records / "control-gold" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(record["acceptance"]["status"], "accepted")
        self.assertEqual(record["acceptance"]["test_counts"]["fail-to-pass"],
                         {"expected": 1, "passed": 1, "failing": 0, "missing": 0, "skipped": 0})
        self.assertEqual((record["stop"], record["scripted"]["changed"]), ("scripted", ["pkg/mod.py"]))
        self.assertIn("pkg/mod.py", record["diff_stat"])
        self.assertIsNone(record["scratch_removal_error"])
        config = json.loads((self.records / "control-gold" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["prompt_sha256"], native_control.sha256_text(config["prompt"]))
        self.assertEqual(config["task_contract"], run_pilot.task_contract(self.task))
        self.assertIsNone(config["arguments"])
        base = native_control.scratch_base(str(self.scratch_root))
        self.assertEqual(list(base.iterdir()), [])  # workspace, pristine copy and evaluator bundle are gone

        code, _ = self.run_native("control-noop", "--scripted", "noop")
        record = json.loads((self.records / "control-noop" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual((code, record["acceptance"]["status"]), (native_control.EXIT_OK, "rejected"))
        self.assertEqual(record["acceptance"]["criterion_outcomes"], {"fail-to-pass": "fail", "pass-to-pass": "pass"})
        self.assertEqual(record["diff_stat"], "")

    def test_a_leftover_run_directory_refuses_the_start(self):
        leftover = native_control.scratch_base(str(self.scratch_root)) / "earlier" / "evaluator"
        leftover.mkdir(parents=True)
        code, out = self.run_native("control-gold", "--scripted", "gold")
        self.assertEqual(code, native_control.EXIT_REFUSED)
        self.assertIn("earlier", out)
        self.assertFalse((self.records / "control-gold").exists())

    def test_the_materialized_workspace_is_the_mutated_tree_without_tests(self):
        seen = {}

        def capture(kind, task, repo, workspace):
            seen["mod"] = (workspace / "pkg" / "mod.py").read_bytes()
            seen["tests"] = (workspace / "tests").exists()
            return {"kind": kind, "changed": []}

        with mock.patch.object(native_control, "scripted_agent", side_effect=capture):
            self.run_native("control-noop", "--scripted", "noop")
        self.assertEqual(seen, {"mod": MUTATED, "tests": False})


if __name__ == "__main__":
    unittest.main()
