"""S2b focused tests: cache revision scope and evaluator mounts."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from reticle.evaluation import AcceptancePlan, AcceptanceRunner, CriterionContract
from reticle.execution import ExecutionRequest, ExecutionResult, IsolatedOCIBackend
from reticle.runtime import LocalRuntime


class CacheRevisionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "pkg").mkdir(parents=True)
        (self.workspace / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cache_files_do_not_change_revision_but_sources_do(self):
        before = self.runtime.workspace.revision()
        for cache in ("pkg/__pycache__/__init__.cpython-313.pyc", ".pytest_cache/v/cache/lastfailed",
                      ".hypothesis/examples/x"):
            path = self.workspace / cache
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"cache")
        self.assertEqual(self.runtime.workspace.revision(), before)

        (self.workspace / "pkg" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertNotEqual(self.runtime.workspace.revision(), before)
        # A sourceless module outside a cache directory is importable, so it stays in scope.
        changed = self.runtime.workspace.revision()
        (self.workspace / "pkg" / "extra.pyc").write_bytes(b"bytecode")
        self.assertNotEqual(self.runtime.workspace.revision(), changed)

    def test_evaluator_snapshot_omits_candidate_caches(self):
        (self.workspace / "pkg" / "__pycache__").mkdir()
        (self.workspace / "pkg" / "__pycache__" / "__init__.cpython-313.pyc").write_bytes(b"stale")
        destination = self.root / "snapshot"
        AcceptanceRunner(self.runtime)._copy_candidate(destination)
        self.assertTrue((destination / "pkg" / "__init__.py").is_file())
        self.assertFalse((destination / "pkg" / "__pycache__").exists())


class EvaluatorMountTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "answer.txt").write_text("42", encoding="utf-8")
        self.evaluator = self.root / "evaluator"
        self.evaluator.mkdir()
        self.runtime = LocalRuntime(self.root / "session", self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def plan(self):
        return AcceptancePlan(
            "mount-task",
            [CriterionContract("answer", "Answer is 42.", "executable", "answer-v1",
                               expected_coverage_ids=["answer::value"])],
            evaluator_command=["{python}", "{bundle}/evaluate.py", "{candidate}"],
        )

    def test_writable_mount_overrides_workspace_mutation_flag(self):
        backend = IsolatedOCIBackend("image:local", engine="podman")
        readonly = backend.build_command(ExecutionRequest(["python"], self.root), "c1")
        private_copy = backend.build_command(ExecutionRequest(["python"], self.root, writable_mount=True), "c2")
        pinned_readonly = backend.build_command(
            ExecutionRequest(["python"], self.root, mutates_workspace=True, writable_mount=False), "c3")
        mount = lambda command: command[command.index("--mount") + 1]
        self.assertTrue(mount(readonly).endswith(",readonly"))
        self.assertFalse(mount(private_copy).endswith(",readonly"))
        self.assertTrue(mount(pinned_readonly).endswith(",readonly"))

    def test_guest_user_is_non_root_per_engine(self):
        request = ExecutionRequest(["python"], self.root)
        podman = IsolatedOCIBackend("image:local", engine=r"C:\Program Files\RedHat\Podman\podman.exe")
        docker = IsolatedOCIBackend("image:local", engine="docker")
        podman_command = podman.build_command(request, "c1")
        docker_command = docker.build_command(request, "c2")
        self.assertIn("keep-id", podman_command)
        self.assertNotIn("--user", podman_command)
        self.assertEqual(docker_command[docker_command.index("--user") + 1], "65534:65534")
        for command in (podman_command, docker_command):
            self.assertIn("--cap-drop", command)
            self.assertIn("no-new-privileges", command)

    def test_acceptance_mounts_private_evaluation_copy_writable_without_mutation_effect(self):
        requests = []

        class CapturingBackend:
            name, host_isolation = "capturing", True

            def run(self, request, cancellation_event=None):
                requests.append(request)
                report = {"criteria": {"answer": {"outcome": "pass", "evaluator_version": "answer-v1",
                                                  "coverage_ids": ["answer::value"]}}}
                return ExecutionResult("success", 0, json.dumps(report).encode(), b"", 1, self.name, True)

        (self.evaluator / "evaluate.py").write_text("# not launched\n", encoding="utf-8")
        decision = AcceptanceRunner(self.runtime, CapturingBackend()).evaluate(
            self.plan(), evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "accepted")
        self.assertTrue(requests[0].writable_mount)
        self.assertFalse(requests[0].mutates_workspace)
        self.assertNotEqual(Path(requests[0].working_directory).resolve(), self.workspace.resolve())

    @unittest.skipUnless(
        os.environ.get("RETICLE_OCI_TEST_IMAGE"),
        "set RETICLE_OCI_TEST_IMAGE to run an evaluator that writes its report files in isolated OCI",
    )
    def test_isolated_evaluator_can_write_inside_its_private_copy_only(self):
        (self.evaluator / "evaluate.py").write_text(
            "import json, pathlib, sys\n"
            "candidate = pathlib.Path(sys.argv[1])\n"
            "(candidate.parent / 'junit.xml').write_text('<testsuite/>')\n"
            "(candidate / 'installed-fixed-input.txt').write_text('fixed')\n"
            "value = (candidate / 'answer.txt').read_text().strip()\n"
            "print(json.dumps({'criteria': {'answer': {'outcome': 'pass' if value == '42' else 'fail', "
            "'evaluator_version': 'answer-v1', 'coverage_ids': ['answer::value']}}}))\n",
            encoding="utf-8",
        )
        before = self.runtime.workspace.revision()
        decision = AcceptanceRunner(
            self.runtime, IsolatedOCIBackend(os.environ["RETICLE_OCI_TEST_IMAGE"])
        ).evaluate(self.plan(), evaluator_root=self.evaluator)
        self.assertEqual(decision.status, "accepted")
        self.assertEqual(self.runtime.workspace.revision(), before)
        self.assertFalse((self.workspace / "installed-fixed-input.txt").exists())


if __name__ == "__main__":
    unittest.main()
