"""Bounded check oracle (tool-use treatment, S6): a ``check`` tool that runs the task's hidden fail_to_pass tests.

This treatment changes the task (the model gets a bounded acceptance signal), so it is an arm of its own.
``check()`` takes no arguments and returns only ``{"failing": N, "passing": M, "calls_left": K}`` over the task's
fail_to_pass tests: passing counts the hidden fail_to_pass tests that passed, failing all the others (failed,
errored, skipped, or not collected). Never test names, never output. At most ``max_calls`` calls per run; a
further call is refused with the count and runs nothing.

How the hidden tests stay out of the model's reach (``HiddenTestOracle.check``):
  1. The runner's evaluator bundle (the fix commit's healthy test roots, task.json, evaluate_task.py) lives
     outside the workspace; the constructor refuses a bundle, or a session directory, inside it.
  2. Each call copies the bundle and a snapshot of the workspace (as final acceptance copies it) into a fresh
     temporary directory under the session directory, runs the evaluator there through the run's own execution
     backend (under OCI: a separate --rm container whose only mount is that directory; the model's commands
     mount only the workspace), and deletes the directory before returning. The evaluator installs the tests
     into the snapshot copy, never into the workspace.
  3. The evaluator's stdout (test ids, pytest output) is parsed in memory and dropped. It is not sent through
     ExecutionController, so no model-visible action or artifact holds it; the journal gets one
     ``oracle_check`` event per call with the counts only, a kind the history tools do not expose.
Under the trusted-local backend nothing is isolated: model commands run on the host and could read the
evaluator bundle at any time (as without this treatment).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from reticle.evaluation.acceptance import AcceptanceRunner
from reticle.execution import ExecutionRequest
from reticle.runtime.session import LocalRuntime
from reticle.tools.primitives import ToolOutcome


ORACLE_VERSION = "hidden-test-oracle-v1"
DEFAULT_MAX_CALLS = 3
EVALUATOR_COMMAND = ("{python}", "{bundle}/evaluate_task.py", "{bundle}", "{candidate}")
REFUSAL = "ERROR: check refused: all {limit} check calls of this run are used ({used} of {limit}); nothing was run."


def check_schema(max_calls: int) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "check",
            "description": (
                "Run the task's hidden acceptance tests for the reported behavior against the current workspace. "
                "Returns only counts, {\"failing\": N, \"passing\": M, \"calls_left\": K}: passing is how many of "
                "those hidden tests pass, failing how many do not (failed, errored, or not collected). It never "
                f"shows test names or output. At most {max_calls} calls per run; later calls are refused."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _outside(path: Path, workspace: Path) -> bool:
    return path != workspace and workspace not in path.parents


class HiddenTestOracle(AcceptanceRunner):
    """Runs the fixed evaluator on a workspace snapshot, like final acceptance, and keeps only fail_to_pass counts.

    It reuses AcceptanceRunner's candidate copy and command rendering, so a check sees exactly the tree and
    interpreter final acceptance would, but it records no acceptance decision and no execution evidence.
    """

    name = "hidden-tests"
    version = ORACLE_VERSION
    event_kind = "oracle_check"
    scratch_prefix = "oracle-"

    def __init__(self, runtime: LocalRuntime, backend, evaluator_root, *, max_calls: int = DEFAULT_MAX_CALLS,
                 timeout_seconds: float = 720.0, command=EVALUATOR_COMMAND):
        super().__init__(runtime, backend)
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        workspace = Path(runtime.workspace.root).resolve()
        self.evaluator_root = Path(evaluator_root).resolve()
        self.scratch_parent = Path(runtime.session_dir).resolve()
        for label, path in (("evaluator root", self.evaluator_root), ("session directory", self.scratch_parent)):
            if not _outside(path, workspace):
                raise ValueError(f"the oracle's {label} must be outside the workspace")
        spec = json.loads((self.evaluator_root / "task.json").read_text(encoding="utf-8"))
        self.fail_to_pass: List[str] = list(spec["fail_to_pass"])
        self.max_calls, self.timeout_seconds, self.command = max_calls, float(timeout_seconds), list(command)
        self.calls = 0
        self.refused = 0
        self.results: List[Dict[str, Any]] = []

    def schema(self) -> Dict[str, Any]:
        return check_schema(self.max_calls)

    def _evaluate(self) -> Tuple[Optional[dict], Dict[str, Any]]:
        """(the parsed evaluator report or None, execution facts). The scratch directory is removed before return,
        and every failure becomes a fact without its message (an exception text could name a test file)."""
        scratch = Path(tempfile.mkdtemp(prefix=self.scratch_prefix, dir=self.scratch_parent))
        execution = None
        try:
            shutil.copytree(self.evaluator_root, scratch / "evaluator")
            self._copy_candidate(scratch / "candidate")
            execution = self.backend.run(ExecutionRequest(
                command=self._render_command(self.command, scratch), working_directory=scratch,
                timeout_seconds=self.timeout_seconds, output_limit_bytes=1_000_000, mutates_workspace=False,
                writable_mount=True,
            ))
        except Exception as exc:  # noqa: BLE001 - a failed check is a result, never a crash or a leaked message
            failure = type(exc).__name__
        else:
            failure = None
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        facts: Dict[str, Any] = {"scratch_removed": not scratch.exists()}
        if execution is None:
            return None, {**facts, "status": "error", "error": failure}
        facts.update(status=execution.status, exit_code=execution.exit_code, duration_ms=execution.duration_ms)
        try:
            report = json.loads(execution.stdout.decode("utf-8"))
            self._counts(report)  # a report without the fields the counts need is no report
            return report, facts
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
            return None, {**facts, "error": "no evaluator report"}

    def _counts(self, report: dict) -> Tuple[int, int]:
        """(failing, passing) over the task's fail_to_pass tests, from the evaluator's report."""
        criterion = report["criteria"]["fail-to-pass"]
        observed = set(criterion.get("coverage_ids") or []) - set(criterion.get("failing") or [])
        passing = len(observed.intersection(self.fail_to_pass))
        return len(self.fail_to_pass) - passing, passing

    def check(self) -> Tuple[str, str]:
        """(tool result text, tool status) for one check call; journals an oracle_check event."""
        if self.calls >= self.max_calls:
            self.refused += 1
            self.runtime.journal.append(self.event_kind, {
                "version": self.version, "refused": True, "calls_used": self.calls, "max_calls": self.max_calls})
            return REFUSAL.format(limit=self.max_calls, used=self.calls), "rejected"
        self.calls += 1
        revision = self.runtime.workspace.revision()
        report, facts = self._evaluate()
        unchanged = self.runtime.workspace.revision() == revision
        calls_left = self.max_calls - self.calls
        if report is None or not unchanged:
            payload = {"error": "the check did not complete", "calls_left": calls_left}
            status = "error"
        else:
            failing, passing = self._counts(report)
            payload = {"failing": failing, "passing": passing, "calls_left": calls_left}
            status = "success"
        result = {"call": self.calls, **payload, **facts, "workspace_revision": revision,
                  "workspace_unchanged": unchanged}
        self.results.append(result)
        self.runtime.journal.append(self.event_kind, {"version": self.version, "refused": False,
                                                     "max_calls": self.max_calls, **result})
        return json.dumps(payload), status

    def record(self) -> Dict[str, Any]:
        return {"version": self.version, "max_calls": self.max_calls, "calls": self.calls, "refused": self.refused,
                "results": [{key: result.get(key) for key in ("call", "failing", "passing", "calls_left", "status")}
                            for result in self.results]}


class CheckOracleTools:
    """ToolSuite mixin: offers ``check`` (appended to the toolset's schemas) backed by a HiddenTestOracle, or by any
    object with the same schema(), check() and record() (reticle.tools.repro_verifier.ReproTestVerifier)."""

    def __init__(self, *args, oracle: HiddenTestOracle, **kwargs):
        super().__init__(*args, **kwargs)
        self.oracle = oracle
        self._handlers["check"] = self._check

    def schemas(self) -> List[Dict[str, Any]]:
        return [*super().schemas(), json.loads(json.dumps(self.oracle.schema()))]

    def _check(self, arguments: Dict[str, Any]) -> ToolOutcome:
        content, status = self.oracle.check()
        return ToolOutcome(content, status)
