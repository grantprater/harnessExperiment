"""Runner wiring for mutation tasks: task-file selection, mutation applied, hidden tests removed, and the
healthy test root restored for the evaluator (a synthetic two-file repository; no network, no API)."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import evaluate_task  # noqa: E402
import run_pilot  # noqa: E402

GIT = ["git", "-c", "core.autocrlf=false", "-c", "user.name=wiring-test", "-c", "user.email=wiring@localhost"]
HEALTHY = b"def sign(x):\n    if x < 0:\n        return -1\n    return 1\n"
MUTATED = b"def sign(x):\n    if x <= 0:\n        return -1\n    return 1\n"
TESTS = b"from pkg.mod import sign\n\n\ndef test_zero():\n    assert sign(0) == 1\n\n\ndef test_negative():\n    assert sign(-2) == -1\n"
FIXTURE = b"fixture data\n"
MUTATION_PATCH = (
    "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,4 +1,4 @@\n def sign(x):\n-    if x < 0:\n+    if x <= 0:\n"
    "         return -1\n     return 1\n"
)


COMMIT_TIME = 1577836800  # 2020-01-01T00:00:00Z: far from "now", so a fresh timestamp cannot pass for it


def git(cwd, *args):
    environment = dict(os.environ, GIT_AUTHOR_DATE=f"{COMMIT_TIME} +0000", GIT_COMMITTER_DATE=f"{COMMIT_TIME} +0000")
    return subprocess.run([*GIT, *args], cwd=cwd, env=environment, capture_output=True, check=True).stdout.decode().strip()


class MutationWiringTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.repos = self.root / "repos"
        repo = self.repos / "synthetic"
        for path, content in {"pkg/__init__.py": b"", "pkg/mod.py": HEALTHY, "tests/test_mod.py": TESTS,
                              "tests/data/case.txt": FIXTURE, "pyproject.toml": b"[project]\nname = 'pkg'\n"}.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_bytes(content)
        git(repo, "init", "-q", ".")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "healthy")
        self.repo, commit = repo, git(repo, "rev-parse", "HEAD")
        # Runs live inside a repository (experiments/p6_pilot/runs/ is in this checkout); this one's attributes
        # would rewrite the patched file with CRLF if git apply discovered it.
        self.outer = self.root / "outer"
        (self.outer / "runs").mkdir(parents=True)
        (self.outer / ".gitattributes").write_text("* text eol=crlf\n", encoding="utf-8")
        git(self.outer, "init", "-q", ".")
        self.task = {
            "task_id": "synthetic-mut-001", "repo": "synthetic", "repo_url": "https://example.invalid/synthetic",
            "base_commit": commit, "fix_commit": commit,
            "statement": "synthetic has a regression: 'zero' now fails.",
            "evaluator_test_files": ["tests/test_mod.py"],
            "fail_to_pass": ["tests.test_mod::test_zero"], "pass_to_pass": ["tests.test_mod::test_negative"],
            "gold_source_files": ["pkg/mod.py"],
            "hidden_tests": True, "hidden_paths": ["tests"],
            "mutation_patch": MUTATION_PATCH, "mutation_kind": "compare_flip", "mutation_file": "pkg/mod.py",
        }
        self.plain = {key: value for key, value in self.task.items()
                      if key not in ("hidden_tests", "hidden_paths", "mutation_patch", "mutation_kind", "mutation_file")}
        self.plain["task_id"] = "synthetic-plain-001"

    def tearDown(self):
        self.temp_dir.cleanup()

    def workspace(self, name="workspace"):
        return self.outer / "runs" / "run" / name


class MaterializeTests(MutationWiringTestCase):
    def test_mutation_is_applied_and_hidden_paths_are_removed(self):
        workspace = self.workspace()
        run_pilot.materialize_workspace(self.task, self.repo, workspace)
        self.assertEqual((workspace / "pkg" / "mod.py").read_bytes(), MUTATED)  # byte for byte: LF, not CRLF
        self.assertFalse((workspace / "tests").exists())
        self.assertTrue((workspace / "pyproject.toml").is_file())
        self.assertFalse((workspace / ".git").exists())

    def test_no_timestamp_marks_the_mutated_file_or_the_removed_tests(self):
        workspace = self.workspace()
        run_pilot.materialize_workspace(self.task, self.repo, workspace)
        paths = [workspace, *workspace.rglob("*")]
        self.assertEqual({path.stat().st_mtime for path in paths}, {COMMIT_TIME})
        # Files only: listing a directory (this test's rglob) updates its access time, for every directory alike.
        self.assertEqual({path.stat().st_atime for path in paths if path.is_file()}, {COMMIT_TIME})
        self.assertEqual(sorted(p.name for p in workspace.parent.iterdir()), ["workspace"])  # staging removed

    def test_a_task_without_mutation_fields_is_exported_unchanged(self):
        workspace = self.workspace()
        run_pilot.materialize_workspace(self.plain, self.repo, workspace)
        self.assertEqual((workspace / "pkg" / "mod.py").read_bytes(), HEALTHY)
        self.assertEqual((workspace / "tests" / "test_mod.py").read_bytes(), TESTS)

    def test_a_patch_that_does_not_apply_stops_materialization(self):
        broken = dict(self.task, mutation_patch=MUTATION_PATCH.replace(" def sign(x):", " def other(x):"))
        with self.assertRaisesRegex(RuntimeError, "does not apply"):
            run_pilot.materialize_workspace(broken, self.repo, self.workspace())

    def test_hidden_paths_must_exist_and_stay_inside_the_workspace(self):
        cases = [(["../outside"], "not inside"), (["."], "not inside"), (["docs"], "not in the exported tree"),
                 ([], "hidden_paths is empty")]
        for index, (paths, message) in enumerate(cases):
            with self.subTest(paths=paths):
                with self.assertRaisesRegex(ValueError, message):
                    run_pilot.materialize_workspace(dict(self.task, hidden_paths=paths), self.repo,
                                                    self.workspace(f"workspace-{index}"))

    def test_evaluator_bundle_restores_the_healthy_test_root(self):
        workspace, bundle = self.workspace(), self.outer / "runs" / "run" / "evaluator"
        run_pilot.materialize_workspace(self.task, self.repo, workspace)
        run_pilot.build_evaluator(self.task, self.repo, bundle, 60, "python")
        spec = json.loads((bundle / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["test_roots"], ["tests"])
        self.assertEqual((bundle / "files" / "tests" / "test_mod.py").read_bytes(), TESTS)
        self.assertEqual((bundle / "files" / "tests" / "data" / "case.txt").read_bytes(), FIXTURE)
        # What evaluate_task.py does to its candidate copy before pytest runs.
        candidate = self.root / "candidate"
        shutil.copytree(workspace, candidate)
        evaluate_task.install_fixed_test_inputs(bundle, candidate, spec)
        self.assertEqual((candidate / "tests" / "test_mod.py").read_bytes(), TESTS)
        self.assertEqual((candidate / "tests" / "data" / "case.txt").read_bytes(), FIXTURE)
        self.assertEqual((candidate / "pkg" / "mod.py").read_bytes(), MUTATED)
        self.assertFalse((workspace / "tests").exists())


class TaskFileAndProtocolTests(MutationWiringTestCase):
    def write_task_file(self):
        path = self.root / "tasks.synthetic.json"
        path.write_text(json.dumps({"schema_version": 1, "tasks": [self.plain, self.task]}), encoding="utf-8")
        return path

    def test_task_file_selection(self):
        path = self.write_task_file()
        chosen, tasks = run_pilot.load_tasks([str(path)])
        self.assertEqual((chosen, [t["task_id"] for t in tasks]), (path, ["synthetic-plain-001", "synthetic-mut-001"]))
        _, tasks = run_pilot.load_tasks([str(path), "synthetic-mut-001"])
        self.assertEqual([t["task_id"] for t in tasks], ["synthetic-mut-001"])
        default, tasks = run_pilot.load_tasks(None)
        self.assertEqual(default, run_pilot.DEFAULT_TASK_FILE)
        self.assertIn("sqlparse-865", [t["task_id"] for t in tasks])
        _, tasks = run_pilot.load_tasks(["sqlparse-865"])
        self.assertEqual([t["task_id"] for t in tasks], ["sqlparse-865"])
        for selection in ([str(path), "synthetic-missing"], [str(path), str(path)], ["absent.json"]):
            with self.subTest(selection=selection), self.assertRaises(SystemExit):
                run_pilot.load_tasks(selection)

    def test_mutation_contract_enters_the_protocol_hash(self):
        self.assertIsNone(run_pilot.task_contract(self.plain))
        contract = run_pilot.task_contract(self.task)
        self.assertEqual((contract["mutation_kind"], contract["mutation_file"], contract["hidden_tests"],
                          contract["hidden_paths"]), ("compare_flip", "pkg/mod.py", True, ["tests"]))
        execution, guards = {"backend": "trusted-local"}, {"stop_on_repeats": True}
        plain = run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards)
        self.assertEqual(run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, []), plain)
        hashes = {plain, run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards, [contract])}
        for field, value in (("mutation_kind", "drop_not"), ("mutation_file", "pkg/other.py"), ("hidden_tests", False),
                             ("materializer", "mutation-workspace-v1")):
            hashes.add(run_pilot.protocol_hash("pressure-recent-v3", {}, execution, guards,
                                               [dict(contract, **{field: value})]))
        self.assertEqual(len(hashes), 6)

    def test_runner_records_the_task_file_and_contracts_in_config(self):
        path = self.write_task_file()
        here = self.root / "p6_pilot"
        here.mkdir()
        shutil.copyfile(run_pilot.HERE / "evaluate_task.py", here / "evaluate_task.py")
        argv = ["run_pilot.py", "--client", "noop", "--run-name", "wiring", "--tasks", str(path), "synthetic-mut-001"]
        with mock.patch.object(run_pilot, "HERE", here), mock.patch.object(run_pilot, "REPOS", self.repos), \
                mock.patch.object(run_pilot, "TASK_PYTHON", Path(sys.executable)), mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(io.StringIO()):
            run_pilot.main()
        run_dir = here / "runs" / "wiring"
        config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["tasks"], ["synthetic-mut-001"])
        self.assertEqual(config["task_file"]["path"], str(path))
        self.assertEqual(config["task_contracts"], [run_pilot.task_contract(self.task)])
        workspace = run_dir / "sessions" / "synthetic-mut-001__noop-client" / "workspace"
        self.assertEqual((workspace / "pkg" / "mod.py").read_bytes(), MUTATED)
        self.assertFalse((workspace / "tests").exists())
        record = json.loads((run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["protocol_hash"], config["protocol_hash"])


if __name__ == "__main__":
    unittest.main()
