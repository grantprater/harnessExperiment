"""Automated falsification extraction for multi-turn repair attempts.

Each failed attempt becomes negative knowledge: the approach the model stated,
paired with evidence parsed from the test run rather than written by the model.
The ledger stays small enough to render into every blank-slate prompt:

- attempts with the same failure signature merge into one dead end;
- a dead end is resolved only when its cited tests are observed passing under the
  same suite version;
- code whose syntax tree matches an already-failed attempt is flagged as a repeat;
- rendering shows only the most recent unresolved dead ends in full.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


SEPARATOR_RE = re.compile(r"^={20,}[ \t]*$", re.MULTILINE)
HEADER_RE = re.compile(r"^(FAIL|ERROR): (\S+) \(([^)]*)\)")
RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
EXCEPTION_LINE_RE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)(?::.*)?$")
APPROACH_RE = re.compile(r"^\s*[*_`]*approach[*_`]*\s*:\s*[*_`]*\s*(.+)$", re.IGNORECASE | re.MULTILINE)
VERBOSE_TEST_RE = re.compile(r"^(\S+) \([^)]+\) \.\.\. (?:ok|FAIL|ERROR|skipped)", re.MULTILINE)

MESSAGE_CHARS = 200
EVIDENCE_CHARS = 160


def exception_type(line: str) -> str:
    """Leading exception name of a final traceback line, e.g. 'AssertionError'."""
    m = re.match(r"([A-Za-z_][\w.]*)", line.strip())
    return m.group(1) if m else "unknown"


@dataclass(frozen=True)
class FailureDetail:
    test: str
    kind: str      # "FAIL" or "ERROR"
    message: str   # final exception line of the traceback


@dataclass(frozen=True)
class RunReport:
    ran: int
    failures: Tuple[FailureDetail, ...]
    passed: bool
    collection_error: Optional[str] = None  # tests could not run at all (syntax/import error, timeout)
    observed_tests: FrozenSet[str] = frozenset()
    suite_id: str = "unittest"
    suite_version: str = "unknown"
    environment_revision: str = "unknown"
    coverage_complete: bool = False

    @property
    def failing_tests(self) -> FrozenSet[str]:
        return frozenset(f.test for f in self.failures)

    @property
    def signature(self) -> str:
        """Identity of the failure: which tests fail and with which exception types."""
        if self.collection_error:
            key = "collection:" + exception_type(self.collection_error)
        else:
            key = "|".join(sorted(f"{f.test}:{exception_type(f.message)}" for f in self.failures))
        scoped = f"{self.suite_id}@{self.suite_version}|{key}"
        return hashlib.sha256(scoped.encode("utf-8")).hexdigest()[:12]


def _last_exception_line(output: str) -> Optional[str]:
    for line in reversed(output.splitlines()):
        if EXCEPTION_LINE_RE.match(line.strip()):
            return line.strip()[:MESSAGE_CHARS]
    return None


def parse_unittest_output(
    output: str,
    timed_out: bool = False,
    *,
    suite_id: str = "unittest",
    suite_version: str = "unknown",
    environment_revision: str = "unknown",
    observed_test_ids: Optional[List[str]] = None,
    expected_test_ids: Optional[List[str]] = None,
) -> RunReport:
    """Parse `python -m unittest` output into failing tests and their final exception lines."""
    if timed_out:
        return RunReport(
            ran=0, failures=(), passed=False,
            collection_error="Timeout: tests did not finish within the time limit",
            suite_id=suite_id, suite_version=suite_version,
            environment_revision=environment_revision,
        )
    ran_match = RAN_RE.search(output)
    if not ran_match:
        # The loader itself crashed, e.g. a SyntaxError in the solution file.
        return RunReport(
            ran=0, failures=(), passed=False,
            collection_error=_last_exception_line(output) or "RunnerError: no test summary in output",
            suite_id=suite_id, suite_version=suite_version,
            environment_revision=environment_revision,
        )
    ran = int(ran_match.group(1))

    failures: List[FailureDetail] = []
    for block in SEPARATOR_RE.split(output)[1:]:
        lines = block.strip("\n").splitlines()
        header = HEADER_RE.match(lines[0]) if lines else None
        if not header:
            continue
        summary = RAN_RE.search(block)
        body = block[:summary.start()] if summary else block
        content = [l for l in body.splitlines() if l.strip() and set(l.strip()) != {"-"}]
        message = content[-1].strip()[:MESSAGE_CHARS] if len(content) > 1 else ""
        if "unittest.loader._FailedTest" in header.group(3):
            return RunReport(
                ran=ran, failures=(), passed=False,
                collection_error=message or "ImportError: failed to import test module",
                suite_id=suite_id, suite_version=suite_version,
                environment_revision=environment_revision,
            )
        failures.append(FailureDetail(test=header.group(2), kind=header.group(1), message=message))

    passed = not failures and ran > 0 and re.search(r"^OK\b", output, re.MULTILINE) is not None
    if not passed and not failures:
        reason = "RunnerError: no tests ran" if ran == 0 else "RunnerError: tests failed but no failure details were parsed"
        return RunReport(
            ran=ran, failures=(), passed=False, collection_error=reason,
            suite_id=suite_id, suite_version=suite_version,
            environment_revision=environment_revision,
        )
    observed = set(observed_test_ids or VERBOSE_TEST_RE.findall(output))
    observed.update(f.test for f in failures)
    expected = set(expected_test_ids or [])
    return RunReport(
        ran=ran,
        failures=tuple(failures),
        passed=passed,
        observed_tests=frozenset(observed),
        suite_id=suite_id,
        suite_version=suite_version,
        environment_revision=environment_revision,
        coverage_complete=bool(expected) and expected.issubset(observed),
    )


class _StripDocstrings(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
        return node

    visit_Module = visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _strip


def code_fingerprint(code: str) -> str:
    """Hash of the code's syntax tree, so comments, formatting, and docstrings are not changes."""
    try:
        tree = _StripDocstrings().visit(ast.parse(code))
        canonical = "ast:" + ast.dump(tree, include_attributes=False)
    except (SyntaxError, ValueError):
        canonical = "text:" + "\n".join(line.rstrip() for line in code.splitlines() if line.strip())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def parse_approach(reply: str, limit: int = MESSAGE_CHARS) -> Tuple[str, bool]:
    """Return (approach, found) from the reply's `APPROACH:` line."""
    m = APPROACH_RE.search(reply)
    if not m:
        return "", False
    text = m.group(1).strip().strip("*_` ").strip()
    return text[:limit], bool(text)


@dataclass
class AttemptRecord:
    attempt_id: str
    turn: int
    program_version: str
    environment_revision: str
    action: str
    observations: List[str]
    approach: str
    failure_category: str
    conditions: Dict[str, str]
    suite_id: str
    suite_version: str
    failure_signature: str


@dataclass
class DeadEnd:
    dead_end_id: str
    signature: str
    failing_tests: List[str]
    evidence: List[str]
    approaches: List[str] = field(default_factory=list)
    fingerprints: List[str] = field(default_factory=list)
    attempts: int = 0
    first_turn: int = 0
    last_turn: int = 0
    resolved_turn: Optional[int] = None
    collection_error: bool = False
    suite_id: str = "unittest"
    suite_version: str = "unknown"
    failure_category: str = "assertion_failure"
    environment_revisions: List[str] = field(default_factory=list)
    conditions: Dict[str, str] = field(default_factory=dict)
    attempt_records: List[AttemptRecord] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.resolved_turn is not None


def _evidence(report: RunReport, limit: int) -> List[str]:
    if report.collection_error:
        return [f"tests could not run: {report.collection_error}"[:EVIDENCE_CHARS]]
    shown = [(f"{f.test}: {f.message}" if f.message else f.test)[:EVIDENCE_CHARS] for f in report.failures[:limit]]
    hidden = len(report.failures) - len(shown)
    if hidden > 0:
        shown.append(f"...and {hidden} more failing test(s)")
    return shown


class DeadEndLedger:
    """Negative knowledge from failed attempts, merged and pruned for blank-slate prompts."""

    def __init__(self, max_rendered: int = 5, max_approaches: int = 3, max_evidence: int = 3):
        self.max_rendered = max_rendered
        self.max_approaches = max_approaches
        self.max_evidence = max_evidence
        self.dead_ends: List[DeadEnd] = []

    def find_repeat(self, code: str) -> Optional[DeadEnd]:
        """The dead end whose attempts include this exact code (ignoring formatting), if any."""
        fingerprint = code_fingerprint(code)
        return next((d for d in self.dead_ends if fingerprint in d.fingerprints), None)

    def record_attempt(
        self,
        turn: int,
        approach: str,
        code: str,
        report: RunReport,
        *,
        program_version: str = "unknown",
        environment_revision: Optional[str] = None,
        action: str = "replace_candidate",
        observations: Optional[List[str]] = None,
        conditions: Optional[Dict[str, str]] = None,
    ) -> Optional[DeadEnd]:
        """Add one tested attempt; returns the dead end it joined or created, or None if it passed."""
        self._resolve(turn, report)
        if report.passed:
            return None
        dead_end = next((d for d in self.dead_ends if d.signature == report.signature), None)
        category = self._failure_category(report)
        revision = environment_revision or report.environment_revision
        if dead_end is None:
            dead_end = DeadEnd(
                dead_end_id=f"f_{len(self.dead_ends) + 1:02d}",
                signature=report.signature,
                failing_tests=sorted(report.failing_tests),
                evidence=[],
                first_turn=turn,
                collection_error=report.collection_error is not None,
                suite_id=report.suite_id,
                suite_version=report.suite_version,
                failure_category=category,
                conditions=dict(conditions or {}),
            )
            self.dead_ends.append(dead_end)
        dead_end.attempts += 1
        dead_end.last_turn = turn
        dead_end.resolved_turn = None
        dead_end.evidence = _evidence(report, self.max_evidence)
        fingerprint = code_fingerprint(code)
        if fingerprint not in dead_end.fingerprints:
            dead_end.fingerprints.append(fingerprint)
        if approach and approach not in dead_end.approaches:
            dead_end.approaches.append(approach)
            del dead_end.approaches[:-self.max_approaches]
        if revision not in dead_end.environment_revisions:
            dead_end.environment_revisions.append(revision)
        dead_end.attempt_records.append(AttemptRecord(
            attempt_id=f"attempt_{len(dead_end.attempt_records) + 1:03d}",
            turn=turn,
            program_version=program_version,
            environment_revision=revision,
            action=action,
            observations=list(observations or dead_end.evidence),
            approach=approach,
            failure_category=category,
            conditions=dict(conditions or {}),
            suite_id=report.suite_id,
            suite_version=report.suite_version,
            failure_signature=report.signature,
        ))
        return dead_end

    @staticmethod
    def _failure_category(report: RunReport) -> str:
        if report.collection_error:
            return "timeout" if report.collection_error.startswith("Timeout:") else "collection_error"
        if any(failure.kind == "ERROR" for failure in report.failures):
            return "test_error"
        return "assertion_failure"

    def _resolve(self, turn: int, report: RunReport) -> None:
        if report.collection_error:
            return  # a run that could not collect tests says nothing about individual tests
        for d in self.dead_ends:
            same_suite = d.suite_id == report.suite_id and d.suite_version == report.suite_version
            cited = set(d.failing_tests)
            cited_observed_passing = (
                bool(cited)
                and cited.issubset(report.observed_tests)
                and report.failing_tests.isdisjoint(cited)
            )
            if not d.resolved and same_suite and (d.collection_error or cited_observed_passing):
                d.resolved_turn = turn

    def render(self) -> str:
        if not self.dead_ends:
            return "No failed attempts yet."
        open_ends = sorted((d for d in self.dead_ends if not d.resolved), key=lambda d: d.last_turn, reverse=True)
        resolved = len(self.dead_ends) - len(open_ends)
        resolved_note = f"({resolved} earlier dead end(s) resolved: their failing tests now pass)" if resolved else ""
        if not open_ends:
            return f"No unresolved dead ends. {resolved_note}".strip()
        lines = [
            "These attempts were contradicted under the recorded conditions. "
            "Retry only when the program, environment, or applicable conditions changed."
        ]
        for d in open_ends[:self.max_rendered]:
            turns = f"turn {d.first_turn}" if d.first_turn == d.last_turn else f"turns {d.first_turn}-{d.last_turn}"
            approaches = "; ".join(d.approaches) if d.approaches else "(approach not stated)"
            lines.append(f"- {d.dead_end_id} ({turns}, {d.attempts} attempt{'s' if d.attempts != 1 else ''}): {approaches}")
            lines.extend(f"    evidence: {e}" for e in d.evidence)
        hidden = len(open_ends) - self.max_rendered
        if hidden > 0:
            lines.append(f"- {hidden} older unresolved dead end(s) not shown")
        if resolved_note:
            lines.append(resolved_note)
        return "\n".join(lines)

    def to_dict(self) -> List[Dict[str, Any]]:
        return [asdict(d) for d in self.dead_ends]
