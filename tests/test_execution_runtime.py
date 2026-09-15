"""P4 supervision, worker, and backend-boundary tests."""

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from reticle.execution import (
    BackendUnavailableError,
    ExecutionController,
    ExecutionRequest,
    IsolatedOCIBackend,
    ProgramRegistry,
    ProgramRunner,
    TrustedLocalBackend,
)
from reticle.runtime import LocalRuntime


class TrustedLocalSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.backend = TrustedLocalBackend()

    def tearDown(self):
        self.temp_dir.cleanup()

    def request(self, code, **kwargs):
        timeout_seconds = kwargs.pop("timeout_seconds", 2)
        return ExecutionRequest(
            [sys.executable, "-c", code], self.root,
            timeout_seconds=timeout_seconds, **kwargs
        )

    def test_success_crash_and_clean_environment(self):
        secret_name = "RETICLE_TEST_UNINHERITED_SECRET"
        os.environ[secret_name] = "do-not-inherit"
        try:
            result = self.backend.run(self.request(
                f"import os,sys; print(os.getenv('{secret_name}')); "
                "print('err', file=sys.stderr)"
            ))
        finally:
            os.environ.pop(secret_name, None)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.stdout.strip(), b"None")
        self.assertEqual(result.stderr.strip(), b"err")
        self.assertFalse(result.host_isolation)

        crash = self.backend.run(self.request("raise RuntimeError('worker-crash')"))
        self.assertEqual(crash.status, "error")
        self.assertEqual(crash.error_kind, "process_exit")
        self.assertIn(b"worker-crash", crash.stderr)

    def test_timeout_and_output_flood_do_not_hang_controller(self):
        timeout = self.backend.run(self.request("while True: pass", timeout_seconds=0.2))
        self.assertEqual(timeout.status, "timeout")
        self.assertLess(timeout.duration_ms, 2_000)

        flood = self.backend.run(self.request(
            "import sys; sys.stdout.write('x' * 10000000); sys.stdout.flush()",
            output_limit_bytes=4_096,
        ))
        self.assertEqual(flood.error_kind, "output_limit")
        self.assertTrue(flood.output_truncated)
        self.assertLessEqual(len(flood.stdout) + len(flood.stderr), 4_096)

    def test_cancellation_and_timeout_kill_descendants(self):
        cancellation = threading.Event()
        cancellation.set()
        cancelled = self.backend.run(
            self.request("import time; time.sleep(10)"), cancellation_event=cancellation
        )
        self.assertEqual(cancelled.status, "cancelled")

        marker = self.root / "descendant-marker.txt"
        child_code = f"import time; time.sleep(1); open(r'{marker}', 'w').write('escaped')"
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
            "time.sleep(10)"
        )
        timed_out = self.backend.run(self.request(parent_code, timeout_seconds=0.25))
        self.assertEqual(timed_out.status, "timeout")
        time.sleep(1.2)
        self.assertFalse(marker.exists(), "descendant escaped the Windows Job Object")


class ProgramWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.session = self.root / "session"
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.session, self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_registration_does_not_evaluate_and_worker_supports_module_semantics(self):
        source = (
            "import math\n"
            "OFFSET = 1\n"
            "def helper(value):\n"
            "    return math.floor(value) + OFFSET\n"
            "async def run(value):\n"
            "    print('worker-visible')\n"
            "    return helper(value) * 2\n"
        )
        manifest = ProgramRegistry(self.runtime).register("composed", source, "run", 0)
        self.assertEqual(manifest.reference_version, 1)
        run = ProgramRunner(self.runtime).run("composed", {"value": 2.8})
        self.assertEqual(run.execution.status, "success")
        self.assertEqual(run.value, 6)
        self.assertIn(b"worker-visible", run.execution.stdout)
        self.assertEqual(
            self.runtime.artifacts.read(run.tool_result.stdout_ref), run.execution.stdout
        )

        dangerous = "raise RuntimeError('top-level-ran')\ndef run():\n    return 1\n"
        ProgramRegistry(self.runtime).register("dangerous", dangerous, "run", 0)
        failed = ProgramRunner(self.runtime).run("dangerous", {})
        self.assertEqual(failed.execution.status, "error")
        self.assertEqual(failed.worker_error["error_type"], "RuntimeError")
        self.assertIn("top-level-ran", failed.worker_error["message"])

    def test_controller_allows_parallel_reads_and_serializes_mutations(self):
        class ProbeBackend:
            name = "probe"

            def __init__(self):
                self.lock = threading.Lock()
                self.active = 0
                self.maximum = 0

            def run(self, request, cancellation_event=None):
                from reticle.execution.backends import ExecutionResult
                with self.lock:
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                time.sleep(0.12)
                with self.lock:
                    self.active -= 1
                return ExecutionResult("success", 0, b"", b"", 120, self.name, False)

        read_backend = ProbeBackend()
        read_controller = ExecutionController(self.runtime, read_backend)
        read_request = ExecutionRequest(["probe"], self.workspace, mutates_workspace=False)
        errors = []

        def execute(controller, request):
            try:
                controller.execute(request)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=execute, args=(read_controller, read_request)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(read_backend.maximum, 2)

        write_backend = ProbeBackend()
        write_controllers = [
            ExecutionController(self.runtime, write_backend),
            ExecutionController(self.runtime, write_backend),
        ]
        write_request = ExecutionRequest(["probe"], self.workspace, mutates_workspace=True)
        threads = [
            threading.Thread(target=execute, args=(controller, write_request))
            for controller in write_controllers
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(write_backend.maximum, 1)


class IsolatedBackendTests(unittest.TestCase):
    def test_missing_engine_fails_without_local_fallback(self):
        with mock.patch("reticle.execution.backends.shutil.which", return_value=None):
            with self.assertRaisesRegex(BackendUnavailableError, "Docker or Podman"):
                IsolatedOCIBackend("python:3.13-alpine")

    def test_oci_command_declares_isolation_boundaries(self):
        backend = IsolatedOCIBackend("reticle-test:local", engine="docker.exe")
        with tempfile.TemporaryDirectory() as name:
            command = backend.build_command(
                ExecutionRequest(["python", "task.py"], name), "reticle-fixed"
            )
        rendered = " ".join(command)
        self.assertIn("--network none", rendered)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop ALL", rendered)
        self.assertIn("--security-opt no-new-privileges", rendered)
        self.assertIn("readonly", rendered)
        self.assertEqual(command.count("--mount"), 1)

    @unittest.skipUnless(
        os.environ.get("RETICLE_OCI_TEST_IMAGE"),
        "set RETICLE_OCI_TEST_IMAGE to run real OCI filesystem/network boundaries",
    )
    def test_real_oci_filesystem_and_network_boundaries(self):
        backend = IsolatedOCIBackend(os.environ["RETICLE_OCI_TEST_IMAGE"])
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            (workspace / "visible.txt").write_text("visible", encoding="utf-8")
            filesystem = backend.run(ExecutionRequest(
                [
                    "python", "-c",
                    "from pathlib import Path; "
                    "assert Path('/workspace/visible.txt').read_text() == 'visible'; "
                    "print('filesystem-probe-ran', flush=True); "
                    "Path('/workspace/blocked.txt').write_text('no')",
                ],
                workspace,
            ))
            self.assertEqual(filesystem.status, "error")
            self.assertIn(b"filesystem-probe-ran", filesystem.stdout)
            self.assertFalse((workspace / "blocked.txt").exists())
            network = backend.run(ExecutionRequest(
                [
                    "python", "-c",
                    "import socket; print('network-probe-ran', flush=True); "
                    "socket.create_connection(('1.1.1.1', 53), 1)",
                ],
                workspace,
            ))
            self.assertEqual(network.status, "error")
            self.assertIn(b"network-probe-ran", network.stdout)
            self.assertTrue(network.host_isolation)

    @unittest.skipUnless(
        os.environ.get("RETICLE_OCI_TEST_IMAGE"),
        "set RETICLE_OCI_TEST_IMAGE to run a registered program in isolated OCI",
    )
    def test_registered_program_runs_in_isolated_oci(self):
        backend = IsolatedOCIBackend(os.environ["RETICLE_OCI_TEST_IMAGE"])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            workspace = root / "workspace"
            workspace.mkdir()
            runtime = LocalRuntime(root / "session", workspace)
            ProgramRegistry(runtime).register(
                "isolated", "def run(value):\n    print('isolated-worker')\n    return value * 3\n",
                "run", 0,
            )
            result = ProgramRunner(runtime, backend=backend).run(
                "isolated", {"value": 7}
            )

            self.assertEqual(
                result.execution.status,
                "success",
                result.execution.stderr.decode("utf-8", errors="replace"),
            )
            self.assertTrue(result.execution.host_isolation)
            self.assertEqual(result.value, 21)
            self.assertIn(b"isolated-worker", result.execution.stdout)
            self.assertEqual(
                runtime.artifacts.read(result.tool_result.stdout_ref),
                result.execution.stdout,
            )
            self.assertFalse(list(workspace.glob(".reticle-program-*")))


if __name__ == "__main__":
    unittest.main()
