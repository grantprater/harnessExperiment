"""Realistic verifier (tool-use treatment, card 021): ``check`` runs a reproduction test written before the run.

Card 020's oracle (reticle/tools/check_oracle.py) ran the task's hidden fail_to_pass tests. This verifier has no
access to them: for each task, one separate model call (the run's pinned model, fresh context, able only to read the
pre-edit workspace; experiments/p6_pilot/repro_verifiers.py) wrote one pytest file from the problem statement, and
that file was frozen in a manifest before the campaign. ``check()`` has the oracle's interface: no arguments,
``{"failing": N, "passing": M, "calls_left": K}``, at most K calls per run, never test names or output. passing
counts the reproduction test's cases that pass, failing the others of the cases collected when it was written
(failed, errored, skipped, or not collected, as the oracle counts). The test is not the acceptance test and may
itself be wrong; how often it is right (fails on the mutated tree, passes on the gold tree) is scored offline.

How a call runs (HiddenTestOracle.check, with this class's counts): the run's verifier bundle (the frozen test,
verifier.json, an empty pytest ini and run_repro_test.py) lives outside the workspace; each call copies it and a
snapshot of the workspace to a scratch directory under the session directory, runs run_repro_test.py there through
the run's execution backend (an isolated one only: the class refuses a trusted-local backend), parses the counts
in memory, removes the directory, and journals one ``verifier_check`` event with the counts only. When no test could be written for the task (the generator found no
candidate that failed on the pre-edit tree), the tool is still offered, with the same schema, and every call returns
an error without running anything or spending a call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Tuple

from reticle.runtime.session import LocalRuntime
from reticle.tools.check_oracle import REFUSAL, HiddenTestOracle, _outside


VERIFIER_VERSION = "repro-test-verifier-v1"
DEFAULT_MAX_CALLS = 3
TEST_FILE = "test_reticle_repro.py"
RUNNER_FILE = "run_repro_test.py"
PYTEST_INI = "verifier-pytest.ini"
RUNNER_COMMAND = ("{python}", "{bundle}/" + RUNNER_FILE, "{bundle}", "{candidate}")
UNAVAILABLE = "no reproduction test could be written for this task; nothing was run"


def verifier_schema(max_calls: int) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "check",
            "description": (
                "Run a reproduction test for the reported behavior against the current workspace. The test was "
                "written for this task before your run, from the problem statement and the unmodified source only; "
                "it is not one of the hidden acceptance tests and may itself be wrong. Returns only counts, "
                "{\"failing\": N, \"passing\": M, \"calls_left\": K}: passing is how many of its test cases pass, "
                "failing how many do not (failed, errored, or not collected). It never shows the test or its "
                f"output. At most {max_calls} calls per run; later calls are refused."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_bundle(bundle: Path, *, test_file: Optional[Path], python: str, timeout_seconds: float,
                 runner: Path, collected: Optional[int]) -> Path:
    """A verifier bundle: the frozen test (absent when none could be written), its spec, the runner and an empty
    pytest ini. ``collected`` is the number of test cases the test had on the pre-edit tree."""
    bundle.mkdir(parents=True)
    shutil.copyfile(runner, bundle / RUNNER_FILE)
    (bundle / PYTEST_INI).write_text("[pytest]\n", encoding="utf-8")
    spec = {"python": python, "timeout_seconds": float(timeout_seconds), "test_file": TEST_FILE,
            "available": test_file is not None, "collected": collected,
            "test_sha256": sha256_file(test_file) if test_file is not None else None}
    if test_file is not None:
        shutil.copyfile(test_file, bundle / TEST_FILE)
    (bundle / "verifier.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return bundle


class ReproTestVerifier(HiddenTestOracle):
    """check() over a frozen reproduction test; the oracle's scratch copy, backend run and journaling."""

    name = "repro-test"
    version = VERIFIER_VERSION
    event_kind = "verifier_check"
    scratch_prefix = "verifier-"

    def __init__(self, runtime: LocalRuntime, backend, verifier_root, *, max_calls: int = DEFAULT_MAX_CALLS,
                 timeout_seconds: float = 720.0, command=RUNNER_COMMAND):
        super(HiddenTestOracle, self).__init__(runtime, backend)  # AcceptanceRunner: no task.json to read
        if not getattr(self.backend, "host_isolation", False):
            # card 024 port: the frozen test is model-written, so it runs only in an isolated backend (podman,
            # --network none); with backend None AcceptanceRunner would have fallen back to TrustedLocalBackend
            raise ValueError("the reproduction-test verifier runs only in an isolated backend, never trusted-local")
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        workspace = Path(runtime.workspace.root).resolve()
        self.evaluator_root = Path(verifier_root).resolve()
        self.scratch_parent = Path(runtime.session_dir).resolve()
        for label, path in (("verifier bundle", self.evaluator_root), ("session directory", self.scratch_parent)):
            if not _outside(path, workspace):
                raise ValueError(f"the verifier's {label} must be outside the workspace")
        self.spec = json.loads((self.evaluator_root / "verifier.json").read_text(encoding="utf-8"))
        self.available = bool(self.spec.get("available"))
        self.collected = int(self.spec.get("collected") or 0)
        if self.available and self.collected < 1:
            raise ValueError("an available reproduction test must have at least one test case")
        self.fail_to_pass = []
        self.max_calls, self.timeout_seconds, self.command = max_calls, float(timeout_seconds), list(command)
        self.calls = 0
        self.refused = 0
        self.unavailable_calls = 0
        self.results = []

    def schema(self) -> Dict[str, Any]:
        return verifier_schema(self.max_calls)

    def _counts(self, report: dict) -> Tuple[int, int]:
        """(failing, passing) over the test cases collected on the pre-edit tree."""
        passing = min(int(report["passed"]), self.collected)
        return self.collected - passing, passing

    def check(self) -> Tuple[str, str]:
        if not self.available:
            self.unavailable_calls += 1
            self.runtime.journal.append(self.event_kind, {
                "version": self.version, "refused": False, "available": False, "calls_used": self.calls})
            return json.dumps({"error": UNAVAILABLE, "calls_left": self.max_calls - self.calls}), "error"
        return super().check()

    def record(self) -> Dict[str, Any]:
        return {**super().record(), "available": self.available, "collected": self.collected,
                "test_sha256": self.spec.get("test_sha256"), "unavailable_calls": self.unavailable_calls}


__all__ = ["DEFAULT_MAX_CALLS", "REFUSAL", "ReproTestVerifier", "RUNNER_FILE", "TEST_FILE", "UNAVAILABLE",
           "VERIFIER_VERSION", "verifier_schema", "write_bundle"]
