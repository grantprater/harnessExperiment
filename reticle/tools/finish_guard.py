"""Finish guard: a pre-finish verification rule (task-completion-detection treatment, S6).

Evidence (card 007, weakness mining of all 40 journals): every rejected run that called finish (001-r1, 057-r1,
057-r2, 061-r1) had run a check after its last edit, an exit-0 ``python -c`` on inputs the model chose; in 3 of 4
the reported failure was never reproduced at all. "pytest found no tests" happened in 19 of the 32 accepted runs
too. So neither "a check ran after the edit" nor "no tests ran" separates the failures. What the rejected runs lack
is a reproduced failure that the fix turns into a pass (most accepted runs lack it too; see the replay below).

Rule (``finish-guard-v2``, fail-then-pass). After an edit to a pre-existing source file
(``reticle.runtime.source_edits``), finish is accepted only if the run shows a pair of ``run`` calls:
  1. a command that FAILED before the first source edit: it ran to completion with a non-zero exit code, or its
     output holds a traceback or AssertionError. A run that executed no check is neither a failure nor a pass:
     a timeout, rejected or cancelled call, a command that could not start (exit 126/127, "can't open file"),
     or a test runner that ran no tests (in card 007, 125 git calls exited 127 and 121 pytest calls ran no tests);
  2. the same command (the same argument list) or the same script path (the first ``.py`` argument, pytest
     node ids reduced to their file) that SUCCEEDED after the latest source edit: exit code 0, no traceback,
     no AssertionError.
Otherwise the first such finish is rejected with a message that says so, and names what would count; the next
finish is accepted regardless and recorded as forced, so a run can never be trapped. A call that itself edits a
source file (including a ``run`` command that rewrites one) is an edit, not evidence. Runs of a test runner that
executed no tests ("no tests ran", "collected 0 items") are recorded as a journal fact; they are not the rule.
Known limits: a failure of the model's own script (a syntax error, a wrong assertion) counts as a reproduction,
and a check the model wrote can pass without testing the reported behaviour; the rule asks for the pair, it
cannot judge the check. Replayed over card 007's journals (offline, from calls.jsonl), it would have fired on
the 4 rejected runs that finished and on 30 of the 32 accepted runs: it does not separate outcomes either, so
the card measures what demanding the pair changes, at the cost of about one response per run.

Off by default: the runner composes ``FinishGuardTools`` in only with ``--completion finish-guard``, and the
guard's name, version, rejection texts and source rule then enter the protocol hash. ToolSuite, TOOL_SCHEMAS
and TOOLSET_VERSION are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from reticle.runtime.session import LocalRuntime
from reticle.runtime.source_edits import SourceEditTracker
from reticle.tools.primitives import PYTHON_ALIASES, ToolOutcome


FINISH_GUARD_VERSION = "finish-guard-v2"
FINISH_GUARD_MESSAGE = (
    "Finish not accepted yet: you changed {files}, but this run has not shown the reported failure reproduced "
    "and then fixed: {why}. Reproduce the reported failure with a command that fails on the unfixed code (a "
    "non-zero exit or a traceback; for example a script `python repro.py` whose assertion fails, or `pytest "
    "tests/test_repro.py -q` with a failing test), then run the same command after the fix and show it passing "
    "(exit code 0, no traceback). A check that only ever passed, or a different command after the fix, does not "
    "count. This check happens once: the next finish call will be accepted regardless."
)
WHY_NO_FAILURE = "no run failed before your first source edit"
WHY_NO_RERUN = "`{failing}` failed before your first source edit, but no run has executed since your latest edit"
WHY_NO_PASS = ("`{failing}` failed before your first source edit, but no run since your latest edit reran it "
               "(the same command or script) and passed")
REASONS = {"no_failing_run_before_edit": WHY_NO_FAILURE, "no_run_after_edit": WHY_NO_RERUN,
           "no_matching_pass_after_edit": WHY_NO_PASS}
EDIT_CAPABLE_TOOLS = frozenset({"replace_text", "write_file", "run"})
UNFINISHED_RUN_STATUSES = frozenset({"timeout", "rejected", "cancelled"})
FAILURE_MARKERS = ("Traceback (most recent call last)", "AssertionError")
STATUS_LINE = re.compile(r"status: (\S+); exit code: (\S+);")
NOT_STARTED_EXIT_CODES = frozenset({"None", "126", "127"})  # no exit code; not executable; command not found
CANNOT_OPEN_SCRIPT = "can't open file"
SUMMARY_LINE = re.compile(r"\bin \d+(?:\.\d+)?s\b")
TEST_COUNT = re.compile(r"\b(\d+) (passed|failed|xfailed|xpassed|errors?)\b")
UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in\b", re.MULTILINE)
# unittest reports a module it could not import as a test named after it (unittest.loader._FailedTest).
UNITTEST_IMPORT_FAILURE = re.compile(r"^ERROR: \S+ \(unittest\.loader\._FailedTest", re.MULTILINE)
SHOWN_COMMAND_CHARACTERS = 300


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


def run_result(command: str, outcome: ToolOutcome) -> Optional[str]:
    """'failed' or 'passed' for a run that executed a check; None for one that did not: a timeout, rejected, or
    cancelled call, an unreadable result, a command that could not start (exit 126/127, or python's "can't open
    file"), or a test runner that ran no tests ("no tests ran" is a recorded fact, not a failure). The command echo
    is not searched for failure markers."""
    if outcome.status in UNFINISHED_RUN_STATUSES:
        return None
    echo = f"$ {command}\n"
    rest = outcome.content[len(echo):] if outcome.content.startswith(echo) else outcome.content
    status = STATUS_LINE.match(rest)
    if status is None or status.group(2) in NOT_STARTED_EXIT_CODES:
        return None
    output = rest[status.end():]
    if CANNOT_OPEN_SCRIPT in output:
        return None
    argv, _ = command_identity(command)
    if is_test_runner(argv) and tests_executed(output) == 0:
        return None
    return "failed" if status.group(2) != "0" or any(marker in output for marker in FAILURE_MARKERS) else "passed"


def command_identity(command: str) -> Tuple[Tuple[str, ...], Optional[str]]:
    """(the argument list, the script path or None). The script path is the first argument (options and the
    code after -c skipped) that names a .py file; a pytest node id counts as its file."""
    try:
        argv = tuple(shlex.split(command, posix=True))
    except ValueError:
        return (command,), None
    skip_next = False
    for token in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if token == "-c":
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        path = token.split("::", 1)[0]
        if path.endswith(".py"):
            return argv, PurePosixPath(path).as_posix().removeprefix("./")
    return argv, None


def is_test_runner(argv: Tuple[str, ...]) -> bool:
    head = argv[0].lower() if argv else ""
    return head == "pytest" or (head in PYTHON_ALIASES and "-m" in argv
                                and argv[argv.index("-m") + 1:argv.index("-m") + 2] in (("pytest",), ("unittest",)))


def _command(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return ""
    command = arguments.get("command") if isinstance(arguments, dict) else None
    return command if isinstance(command, str) else ""


@dataclass(frozen=True)
class RunRecord:
    step: int
    call_id: Optional[str]
    command: str
    argv: Tuple[str, ...]
    script: Optional[str]
    result: str  # failed | passed

    def same_check(self, other: "RunRecord") -> bool:
        return self.argv == other.argv or (self.script is not None and self.script == other.script)

    def shown(self) -> Dict[str, Any]:
        return {"call_id": self.call_id, "command": self.command[:SHOWN_COMMAND_CHARACTERS], "result": self.result}


class FinishGuard:
    """State of the guard for one run; journals ``finish_guard`` events (a controller-only kind)."""

    name = "finish-guard"
    version = FINISH_GUARD_VERSION

    def __init__(self, runtime: LocalRuntime, tracker: SourceEditTracker):
        self.runtime, self.tracker = runtime, tracker
        self.step = 0
        self.first_edit_step: Optional[int] = None
        self.last_edit_step: Optional[int] = None
        self.runs: List[RunRecord] = []
        self.no_tests_ran: List[str] = []
        self.triggered = False
        self.reason: Optional[str] = None
        self.forced: Optional[bool] = None  # set when a finish is accepted
        self.matched: Optional[Dict[str, Any]] = None
        self._call_id: Optional[str] = None

    def observe(self, name: str, arguments: Any, outcome: ToolOutcome, call_id: Optional[str] = None) -> None:
        """Called after every tool call, in order."""
        self.step += 1
        if name in EDIT_CAPABLE_TOOLS and self.tracker.refresh():
            if self.first_edit_step is None:
                self.first_edit_step = self.step
            self.last_edit_step = self.step
            return  # a call that edits is not evidence about its own edit
        if name != "run":
            return
        command = _command(arguments)
        argv, script = command_identity(command)
        if is_test_runner(argv) and outcome.status not in UNFINISHED_RUN_STATUSES and \
                tests_executed(outcome.content) == 0:
            self.no_tests_ran.append(command[:SHOWN_COMMAND_CHARACTERS])
        result = run_result(command, outcome)
        if result is not None:
            self.runs.append(RunRecord(self.step, call_id, command, argv, script, result))

    def evaluate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[RunRecord]]:
        """(the matched fail-then-pass pair, or None and the reason none matched, and the latest pre-edit failure)."""
        failures = [run for run in self.runs if run.result == "failed" and run.step < self.first_edit_step]
        after = [run for run in self.runs if run.step > self.last_edit_step]
        latest_failure = failures[-1] if failures else None
        for passed in reversed([run for run in after if run.result == "passed"]):
            matching = [failed for failed in failures if failed.same_check(passed)]
            if matching:
                return {"failed": matching[-1].shown(), "passed": passed.shown()}, None, latest_failure
        if not failures:
            return None, "no_failing_run_before_edit", None
        if not after:
            return None, "no_run_after_edit", latest_failure
        return None, "no_matching_pass_after_edit", latest_failure

    def decide(self, call_id: Optional[str]) -> Optional[str]:
        """The rejection text for this finish call, or None to accept it."""
        edited = self.first_edit_step is not None
        matched, reason, failure = self.evaluate() if edited else (None, None, None)
        facts = {"edited_files": self.tracker.edited_files(), "runs_before_first_edit": sum(
            1 for run in self.runs if edited and run.step < self.first_edit_step), "runs_after_last_edit": sum(
            1 for run in self.runs if edited and run.step > self.last_edit_step),
            "no_tests_ran": list(self.no_tests_ran), "version": self.version}
        if edited and matched is None and not self.triggered:
            self.triggered, self.reason = True, reason
            self.runtime.journal.append("finish_guard", {
                "event": "rejected", "call_id": call_id, "guard_triggered": True, "guard_reason": reason,
                "forced_finish": False, "matched_pair": None, **facts,
            })
            files = facts["edited_files"]
            shown = ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
            failing = failure.command[:200] if failure is not None else ""
            return FINISH_GUARD_MESSAGE.format(files=shown, why=REASONS[reason].format(failing=failing))
        self.matched = matched
        self.forced = bool(self.triggered and edited and matched is None)
        self.runtime.journal.append("finish_guard", {
            "event": "accepted", "call_id": call_id, "guard_triggered": self.triggered, "guard_reason": self.reason,
            "forced_finish": self.forced, "matched_pair": matched, **facts,
        })
        return None

    def record(self) -> Dict[str, Any]:
        return {"guard_triggered": self.triggered, "guard_reason": self.reason, "forced_finish": self.forced,
                "matched_pair": self.matched, "edited_files": self.tracker.edited_files(),
                "no_tests_ran": len(self.no_tests_ran), "version": self.version}


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
        self.finish_guard.observe(name, arguments, outcome, call_id)
        return outcome

    def _guarded_finish(self, arguments: Dict[str, Any]) -> ToolOutcome:
        rejection = self.finish_guard.decide(self._guard_call_id)
        if rejection is not None:
            return ToolOutcome(rejection, "rejected")
        return self._finish(arguments)
