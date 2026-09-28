"""Finish guard: a pre-finish verification rule (task-completion-detection treatment, S6).

Card 007's commonest failure was a confident wrong fix: the model edited library code and called finish
without a check that exercised the edit; in two runs it ran pytest on the hidden (absent) tests, saw that no
tests ran, and finished anyway. The guard rejects the first finish after an edit to a pre-existing source file
(``reticle.runtime.source_edits``) unless a ``run`` since that edit shows a test or check actually running.
It fires at most once per run: the rejection says the next finish is accepted regardless, so a run can never
be trapped, and an accepted finish that the guard had to let through is recorded as forced.

What counts as a check (``check_ran``), for a run that finished (success or a non-zero exit; not a timeout,
a rejected command, or a cancellation) after the latest edit:
  1. a test-runner summary line (a line ending in "in <seconds>s") reporting at least one test passed, failed,
     xfailed, xpassed, or errored outside collection; or unittest's "Ran N tests" with N >= 1 once the modules
     it could not import (reported as unittest.loader._FailedTest) are subtracted;
  2. a Python run that exercises the edited library: ``python -c CODE`` or ``python SCRIPT.py`` whose code
     imports the top-level package of an edited file, or ``python -m PACKAGE[.module]``, and that printed
     something.
"no tests ran", "collected 0 items", a missing test file, a collection error alone, and a command that
only prints (does not import the library) do not count. A run that itself changes a source file is its own
edit, so its output does not verify it.

Off by default: the runner composes ``FinishGuardTools`` in only when ``--completion finish-guard`` is given,
and the guard's name, version, rejection text and source rule then enter the protocol hash. ToolSuite,
TOOL_SCHEMAS and TOOLSET_VERSION are untouched.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, List, Optional

from reticle.runtime.session import LocalRuntime
from reticle.runtime.source_edits import SourceEditTracker, import_names
from reticle.tools.primitives import PYTHON_ALIASES, ToolOutcome


FINISH_GUARD_VERSION = "finish-guard-v1"
FINISH_GUARD_MESSAGE = (
    "Finish not accepted yet: you changed {files}, and {why}. Before finishing, run a check that exercises the "
    "change: pytest on a test file you wrote (for example `pytest tests/test_fix.py -q`) that reports at least "
    "one passed or failed test, or a reproduction script that imports the library and prints the behaviour "
    "(for example `python repro.py`). Output such as 'no tests ran', 'collected 0 items', 'file or directory not "
    "found', or a command that only prints does not count; the hidden acceptance tests are not in the workspace, "
    "so pytest cannot run them. This check happens once: the next finish call will be accepted regardless."
)
WHY_NO_RUN = "no run has executed since that change"
WHY_NO_CHECK = "none of the {count} run(s) since that change showed a test or check executing (last: `{command}`)"
EDIT_CAPABLE_TOOLS = frozenset({"replace_text", "write_file", "run"})
UNFINISHED_RUN_STATUSES = frozenset({"timeout", "rejected", "cancelled"})
SUMMARY_LINE = re.compile(r"\bin \d+(?:\.\d+)?s\b")
TEST_COUNT = re.compile(r"\b(\d+) (passed|failed|xfailed|xpassed|errors?)\b")
UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in\b", re.MULTILINE)
# unittest reports a module it could not import as a test named after it (unittest.loader._FailedTest).
UNITTEST_IMPORT_FAILURE = re.compile(r"^ERROR: \S+ \(unittest\.loader\._FailedTest", re.MULTILINE)


def tests_executed(output: str) -> int:
    """Tests a runner reports as executed in its summary lines (pytest or unittest); 0 if none."""
    during_collection = "during collection" in output
    ran = sum(int(count) for count in UNITTEST_RAN.findall(output))
    total = max(0, ran - len(UNITTEST_IMPORT_FAILURE.findall(output)))
    for line in output.splitlines():
        if not SUMMARY_LINE.search(line):
            continue
        for count, kind in TEST_COUNT.findall(line):
            if kind.startswith("error") and during_collection:
                continue
            total += int(count)
    return total


def _imports(code: str, packages: List[str]) -> bool:
    return any(re.search(rf"\b(?:from|import)\s+{re.escape(name)}\b", code) for name in packages)


def exercises_library(argv: List[str], workspace_root, packages: List[str]) -> bool:
    """Whether a Python command runs code that imports one of the edited packages."""
    if not argv or argv[0].lower() not in PYTHON_ALIASES or not packages:
        return False
    rest = argv[1:]
    if "-m" in rest:
        position = rest.index("-m")
        module = rest[position + 1] if position + 1 < len(rest) else ""
        return module.split(".")[0] in packages
    if "-c" in rest:
        position = rest.index("-c")
        return position + 1 < len(rest) and _imports(rest[position + 1], packages)
    script = next((item for item in rest if not item.startswith("-")), None)
    if not script or not script.endswith(".py"):
        return False
    try:
        path = (workspace_root / script).resolve()
        path.relative_to(workspace_root.resolve())
        return _imports(path.read_text(encoding="utf-8", errors="replace"), packages)
    except (OSError, ValueError):
        return False


def check_ran(command: str, outcome: ToolOutcome, workspace_root, packages: List[str]) -> bool:
    """Whether a run tool result shows a test or check actually executing (see the module docstring)."""
    if outcome.status in UNFINISHED_RUN_STATUSES:
        return False
    body = outcome.content.split("\n", 1)[1] if "\n" in outcome.content else ""  # drop the "$ command" echo
    if tests_executed(body) > 0:
        return True
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    printed = "--- stdout ---" in body or "--- stderr ---" in body
    # A test runner (pytest, python -m pytest/unittest) counts only through its summary above: it is not a
    # python command that imports an edited package, so exercises_library is false for it.
    return printed and exercises_library(argv, workspace_root, packages)


def _command(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return ""
    command = arguments.get("command") if isinstance(arguments, dict) else None
    return command if isinstance(command, str) else ""


class FinishGuard:
    """State of the guard for one run; journals ``finish_guard`` events (a controller-only kind)."""

    name = "finish-guard"
    version = FINISH_GUARD_VERSION

    def __init__(self, runtime: LocalRuntime, tracker: SourceEditTracker):
        self.runtime, self.tracker = runtime, tracker
        self.step = 0
        self.last_edit_step: Optional[int] = None
        self.last_check_step: Optional[int] = None
        self.runs_since_edit: List[str] = []
        self.triggered = False
        self.reason: Optional[str] = None
        self.forced: Optional[bool] = None  # set when a finish is accepted

    def observe(self, name: str, arguments: Any, outcome: ToolOutcome) -> None:
        """Called after every tool call, in order."""
        self.step += 1
        if name in EDIT_CAPABLE_TOOLS and self.tracker.refresh():
            self.last_edit_step, self.runs_since_edit = self.step, []
            return  # a call that edits cannot verify its own edit
        if name != "run" or self.last_edit_step is None:
            return
        command = _command(arguments)
        self.runs_since_edit.append(command)
        if check_ran(command, outcome, self.tracker.root, import_names(self.tracker.edited_files())):
            self.last_check_step = self.step

    def unverified(self) -> bool:
        return self.last_edit_step is not None and (
            self.last_check_step is None or self.last_check_step <= self.last_edit_step)

    def decide(self, call_id: Optional[str]) -> Optional[str]:
        """The rejection text for this finish call, or None to accept it."""
        unverified = self.unverified()
        if unverified and not self.triggered:
            self.triggered = True
            self.reason = "no_run_after_edit" if not self.runs_since_edit else "no_check_in_runs_after_edit"
            files = self.tracker.edited_files()
            shown = ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
            why = WHY_NO_RUN if not self.runs_since_edit else WHY_NO_CHECK.format(
                count=len(self.runs_since_edit), command=self.runs_since_edit[-1][:200])
            self.runtime.journal.append("finish_guard", {
                "event": "rejected", "call_id": call_id, "guard_triggered": True, "guard_reason": self.reason,
                "forced_finish": False, "edited_files": files, "runs_since_edit": list(self.runs_since_edit),
                "version": self.version,
            })
            return FINISH_GUARD_MESSAGE.format(files=shown, why=why)
        self.forced = bool(self.triggered and unverified)
        self.runtime.journal.append("finish_guard", {
            "event": "accepted", "call_id": call_id, "guard_triggered": self.triggered, "guard_reason": self.reason,
            "forced_finish": self.forced, "edited_files": self.tracker.edited_files(), "version": self.version,
        })
        return None

    def record(self) -> Dict[str, Any]:
        return {"guard_triggered": self.triggered, "guard_reason": self.reason, "forced_finish": self.forced,
                "edited_files": self.tracker.edited_files(), "version": self.version}


class FinishGuardTools:
    """ToolSuite mixin: ``finish`` consults the guard; every tool call is shown to the guard afterwards."""

    def __init__(self, *args, finish_guard: FinishGuard, **kwargs):
        super().__init__(*args, **kwargs)
        self.finish_guard = finish_guard
        self._handlers["finish"] = self._guarded_finish
        self._guard_call_id: Optional[str] = None

    def dispatch(self, name, arguments, call_id):
        self._guard_call_id = call_id
        outcome = super().dispatch(name, arguments, call_id)
        self.finish_guard.observe(name, arguments, outcome)
        return outcome

    def _guarded_finish(self, arguments: Dict[str, Any]) -> ToolOutcome:
        rejection = self.finish_guard.decide(self._guard_call_id)
        if rejection is not None:
            return ToolOutcome(rejection, "rejected")
        return self._finish(arguments)
