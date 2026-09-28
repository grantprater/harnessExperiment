"""Generate hidden-test repair tasks by mutating a healthy sqlparse checkout.

Source state: the fix commit of task sqlparse-865 in experiments/p6_pilot/tasks.json, where
the whole suite passes. Candidates are semantic mutations of library code only
(sqlparse/**/*.py, never tests), located with ast and applied as one text edit each:

  compare_flip      == <-> !=, < <-> <=, > <-> >=
  negate_condition  `if c:` / `while c:` -> `if not (c):`
  drop_not          `not x` -> `x`
  off_by_one        integer literal n -> n + 1 inside a subscript/slice or a range() argument
  remove_guard      `if c: return x` followed by more statements -> deleted
  swap_branches     if/else bodies swapped (no elif); `a if c else b` -> `b if c else a`

Each candidate is exported to a fresh workspace, created by `git apply` of its unified diff
(so the recorded patch is itself checked), and the whole suite runs once at idle priority.
It becomes a task only when at least one baseline-passing test fails, at least 90% still
pass, and pytest reports no collection errors or missing tests. The gold patch is the
reverse diff. The statement is a template over the humanized failing-test names and the first
failure message; it never names the file, the line, or a test id (checked, see
statement_leaks).

A task workspace is: export base_commit, apply mutation_patch, remove hidden_paths. The P6
runner (experiments/p6_pilot/run_pilot.py) does neither of the last two steps yet.

Usage (the interpreter only needs the standard library; pytest runs in the task venv):
  python experiments/mutation_tasks/generate.py --work-dir <scratch> [--max-candidates 100]
      [--budget-seconds 660] [--gold-check 2]
"""

import argparse
import ast
import difflib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
from evaluate_task import load_outcomes  # noqa: E402  (the fixed evaluator's JUnit parsing)
from interpreters import venv_interpreter  # noqa: E402

GENERATOR_VERSION = 1
SOURCE_TASK = "sqlparse-865"
LIBRARY_ROOT = "sqlparse"
TEST_ROOT = "tests"
MIN_PASS_FRACTION = 0.90
SEED = 865
KINDS = ("compare_flip", "negate_condition", "drop_not", "off_by_one", "remove_guard", "swap_branches")
FLIPS = {ast.Eq: ("==", "!="), ast.NotEq: ("!=", "=="), ast.Lt: ("<", "<="), ast.LtE: ("<=", "<"),
         ast.Gt: (">", ">="), ast.GtE: (">=", ">")}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(repo), *args],
                          capture_output=True, check=True).stdout


def runtime_dir() -> Path:
    """.runtime of this checkout, else of the main checkout that owns this git worktree."""
    local = ROOT / ".runtime"
    if (local / "bug-mining" / "repos").is_dir():
        return local
    common = git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    return Path(common).parent / ".runtime"


def ensure_repo(task: dict, repos: Path) -> Path:
    """Reuse the P6 bug-mining clone; clone or fetch only when it is missing or lacks the commit."""
    repo = repos / task["repo"]
    if not repo.exists():
        repos.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", task["repo_url"], str(repo)], check=True)
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{task['fix_commit']}^{{commit}}"],
                      capture_output=True).returncode:
        subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*"],
                       check=True)
    return repo


def export(repo: Path, commit: str, dest: Path) -> None:
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", "--format=tar", commit))) as archive:
        archive.extractall(dest, filter="data")


def split_lines(text: str) -> list:
    """Split on \\n only, keeping ends, so indices match ast line numbers."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


# ---------------------------------------------------------------- candidates


@dataclass
class Candidate:
    file: str
    line: int
    end_line: int
    kind: str
    detail: str
    function: str
    original: str
    mutated: str

    def patch(self) -> str:
        return "".join(difflib.unified_diff(split_lines(self.original), split_lines(self.mutated),
                                            f"a/{self.file}", f"b/{self.file}"))

    def gold_patch(self) -> str:
        return "".join(difflib.unified_diff(split_lines(self.mutated), split_lines(self.original),
                                            f"a/{self.file}", f"b/{self.file}"))


def int_literals(node):
    """Integer literals of an index expression, not descending into nested calls or subscripts."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        yield node
        return
    if isinstance(node, (ast.Call, ast.Subscript, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(node):
        yield from int_literals(child)


class Finder(ast.NodeVisitor):
    def __init__(self, path: str, text: str):
        self.path, self.text = path, text
        self.lines = split_lines(text)
        self.tree = ast.parse(text)
        self.baseline_dump = ast.dump(self.tree)
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                child.parent = parent
        self.scope = []
        self.found, self.rejected_invalid = [], 0

    def run(self) -> list:
        self.visit(self.tree)
        return self.found

    # helpers
    def raw(self, lineno: int) -> bytes:
        return self.lines[lineno - 1].encode("utf-8")  # ast columns are UTF-8 byte offsets

    def with_line(self, lineno: int, new_raw: bytes) -> str:
        return "".join(self.lines[:lineno - 1] + [new_raw.decode("utf-8")] + self.lines[lineno:])

    def add(self, line: int, end_line: int, kind: str, detail: str, mutated: str) -> None:
        try:
            dump = ast.dump(ast.parse(mutated))
        except SyntaxError:
            self.rejected_invalid += 1
            return
        if dump == self.baseline_dump:
            return
        self.found.append(Candidate(self.path, line, end_line, kind, detail,
                                    ".".join(self.scope) or "<module>", self.text, mutated))

    def visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_scope

    # compare_flip
    def visit_Compare(self, node):
        operands = [node.left, *node.comparators]
        for i, op in enumerate(node.ops):
            flip = FLIPS.get(type(op))
            left, right = operands[i], operands[i + 1]
            if not flip or left.end_lineno != right.lineno:
                continue
            raw = self.raw(right.lineno)
            segment = raw[left.end_col_offset:right.col_offset]
            if segment.replace(b"(", b"").replace(b")", b"").strip() != flip[0].encode():
                continue
            at = left.end_col_offset + segment.index(flip[0].encode())
            new = raw[:at] + flip[1].encode() + raw[at + len(flip[0]):]
            self.add(right.lineno, right.lineno, "compare_flip", f"`{flip[0]}` -> `{flip[1]}`",
                     self.with_line(right.lineno, new))
        self.generic_visit(node)

    # negate_condition, remove_guard, swap_branches
    def negate(self, test, keyword: str):
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return  # drop_not covers it
        if test.lineno != test.end_lineno:
            return
        raw = self.raw(test.lineno)
        start, end = test.col_offset, test.end_col_offset
        new = raw[:start] + b"not (" + raw[start:end] + b")" + raw[end:]
        self.add(test.lineno, test.lineno, "negate_condition", f"`{keyword}` condition negated",
                 self.with_line(test.lineno, new))

    def visit_While(self, node):
        self.negate(node.test, "while")
        self.generic_visit(node)

    def visit_If(self, node):
        is_elif = self.lines[node.lineno - 1].lstrip().startswith("elif")
        self.negate(node.test, "elif" if is_elif else "if")
        self.guard(node)
        self.swap(node)
        self.generic_visit(node)

    def guard(self, node):
        if node.orelse or len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
            return
        parent = node.parent
        block = next((b for b in (getattr(parent, f, None) for f in ("body", "orelse", "finalbody"))
                      if isinstance(b, list) and any(s is node for s in b)), None)
        if block is None:
            return
        i = next(k for k, s in enumerate(block) if s is node)
        if i == len(block) - 1:
            return  # not early: nothing follows it in the block
        if (i and block[i - 1].end_lineno >= node.lineno) or block[i + 1].lineno <= node.end_lineno:
            return
        if self.raw(node.lineno)[:node.col_offset].strip() or not re.fullmatch(
                rb"\s*(#.*)?", self.raw(node.end_lineno)[node.end_col_offset:]):
            return
        mutated = "".join(self.lines[:node.lineno - 1] + self.lines[node.end_lineno:])
        self.add(node.lineno, node.end_lineno, "remove_guard", "early-return guard deleted", mutated)

    def swap(self, node):
        if not node.orelse or self.lines[node.orelse[0].lineno - 1].lstrip().startswith("elif"):
            return
        start = lambda s: min([s.lineno] + [d.lineno for d in getattr(s, "decorator_list", [])])  # noqa: E731
        b0, b1, o0, o1 = node.body[0], node.body[-1], node.orelse[0], node.orelse[-1]
        if start(b0) <= node.test.end_lineno or b0.col_offset != o0.col_offset:
            return  # inline body or unusual indentation
        middle = self.lines[b1.end_lineno:start(o0) - 1]
        if not any(re.match(r"\s*else\s*:", line) for line in middle):
            return
        if not re.fullmatch(rb"\s*(#.*)?", self.raw(o1.end_lineno)[o1.end_col_offset:]):
            return
        mutated = "".join(self.lines[:start(b0) - 1] + self.lines[start(o0) - 1:o1.end_lineno] + middle
                          + self.lines[start(b0) - 1:b1.end_lineno] + self.lines[o1.end_lineno:])
        self.add(start(b0), o1.end_lineno, "swap_branches", "if/else bodies swapped", mutated)

    def visit_IfExp(self, node):
        if node.lineno == node.end_lineno:
            raw = self.raw(node.lineno)
            bs, be, os_, oe = (node.body.col_offset, node.body.end_col_offset,
                               node.orelse.col_offset, node.orelse.end_col_offset)
            if node.body.lineno == node.orelse.lineno == node.lineno and be <= os_:
                new = raw[:bs] + raw[os_:oe] + raw[be:os_] + raw[bs:be] + raw[oe:]
                self.add(node.lineno, node.lineno, "swap_branches", "conditional-expression branches swapped",
                         self.with_line(node.lineno, new))
        self.generic_visit(node)

    # drop_not
    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.Not) and node.lineno == node.operand.lineno:
            raw = self.raw(node.lineno)
            match = re.match(rb"not\s*", raw[node.col_offset:node.operand.col_offset])
            if match:
                new = raw[:node.col_offset] + raw[node.col_offset + match.end():]
                self.add(node.lineno, node.lineno, "drop_not", "`not` removed", self.with_line(node.lineno, new))
        self.generic_visit(node)

    # off_by_one
    def bump(self, const, where: str):
        if const.lineno != const.end_lineno:
            return
        raw = self.raw(const.lineno)
        if raw[const.col_offset:const.end_col_offset] != str(const.value).encode():
            return  # hex, underscores, ...
        new = raw[:const.col_offset] + str(const.value + 1).encode() + raw[const.end_col_offset:]
        self.add(const.lineno, const.lineno, "off_by_one", f"{where} literal {const.value} -> {const.value + 1}",
                 self.with_line(const.lineno, new))

    def visit_Subscript(self, node):
        for const in int_literals(node.slice):
            self.bump(const, "index/slice")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "range":
            for arg in node.args:
                for const in int_literals(arg):
                    self.bump(const, "range()")
        self.generic_visit(node)


def find_candidates(tree: Path):
    found, invalid, seen = [], 0, set()
    for path in sorted((tree / LIBRARY_ROOT).rglob("*.py")):
        rel = path.relative_to(tree).as_posix()
        finder = Finder(rel, path.read_bytes().decode("utf-8"))
        for cand in finder.run():
            if (cand.file, cand.mutated) not in seen:
                seen.add((cand.file, cand.mutated))
                found.append(cand)
        invalid += finder.rejected_invalid
    return found, invalid


def schedule(candidates: list) -> list:
    """Seeded shuffle within each kind, then round-robin across kinds, so a cap samples all kinds."""
    rng = random.Random(SEED)
    pools = {kind: [c for c in candidates if c.kind == kind] for kind in KINDS}
    for pool in pools.values():
        rng.shuffle(pool)
    order = []
    while any(pools.values()):
        for kind in KINDS:
            if pools[kind]:
                order.append(pools[kind].pop())
    return order


# ---------------------------------------------------------------- suite runs


@dataclass
class SuiteRun:
    outcomes: dict
    collection_errors: list
    failures: list  # (test id, first message line) in report order
    seconds: float
    timed_out: bool
    exit_code: object
    tail: str


def failure_messages(xml_path: Path) -> list:
    if not xml_path.exists():
        return []
    found = []
    for case in ET.parse(xml_path).iter("testcase"):
        for child in case:
            if child.tag in ("failure", "error"):
                message = child.get("message") or (child.text or "")
                found.append((f"{case.get('classname') or ''}::{case.get('name') or ''}", message))
                break
    return found


def run_suite(python: str, workspace: Path, targets: list, xml_path: Path, timeout: float,
              timeout_plugin: bool) -> SuiteRun:
    """One single-process pytest run at idle priority (trusted-local)."""
    if xml_path.exists():
        xml_path.unlink()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(workspace),
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"]
    if timeout_plugin:
        cmd += ["--timeout", "120"]
    priority = ({"creationflags": subprocess.IDLE_PRIORITY_CLASS} if os.name == "nt"
                else {"preexec_fn": lambda: os.nice(19)})
    started = time.monotonic()
    timed_out, exit_code, output = False, None, ""
    try:
        done = subprocess.run(cmd + targets, cwd=workspace, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, **priority)
        exit_code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        timed_out = True
    seconds = time.monotonic() - started
    outcomes, errors = load_outcomes(xml_path) if not timed_out else ({}, [])
    return SuiteRun(outcomes, errors, failure_messages(xml_path) if not timed_out else [], seconds,
                    timed_out, exit_code, output[-800:])


def apply_patch(workspace: Path, patch: str) -> None:
    """git apply outside any repository; autocrlf off so LF files stay LF on Windows."""
    subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", "-"],
                   input=patch.encode("utf-8"), cwd=workspace, capture_output=True, check=True)


def materialize(pristine: Path, workspace: Path, patch: str) -> None:
    """Fresh copy of the healthy export with the patch applied by git apply (validates the diff)."""
    shutil.rmtree(workspace, ignore_errors=True)
    shutil.copytree(pristine, workspace)
    if patch:
        apply_patch(workspace, patch)


# ---------------------------------------------------------------- statements


def words(identifier: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", identifier).replace("_", " ")
    return re.sub(r"\s+", " ", spaced).strip().lower()


def humanize(test_id: str) -> str:
    module, _, name = test_id.partition("::")
    name = re.sub(r"\[.*\]$", "", name)
    label = words(re.sub(r"^test_?", "", name))
    last = module.rsplit(".", 1)[-1]
    if last[:1].isupper():  # a test class
        label = f"{words(re.sub(r'^Test', '', last))}: {label}"
    return label


def clean_message(message: str) -> str:
    lines = [line for line in (message or "").strip().splitlines() if line.strip()]
    first = lines[0].strip() if lines else "(no message)"
    first = re.sub(r"[\w./\\:-]*\.py\b(:\d+)?", "<file>", first)
    first = re.sub(r"\bline \d+", "line ?", first)
    first = re.sub(r"\btests?\.[\w.]+::\S+", "<test>", first)
    first = first.replace("`", "'")
    return first if len(first) <= 240 else first[:237] + "..."


def build_statement(failing_in_order: list, messages: dict, with_message: bool = True) -> str:
    counts = {}
    for test_id in failing_in_order:
        label = humanize(test_id)
        counts[label] = counts.get(label, 0) + 1
    labels = list(counts.items())
    shown = "; ".join(f"'{label}'" + (f" ({n} cases)" if n > 1 else "") for label, n in labels[:3])
    more = f"; and {len(labels) - 3} more" if len(labels) > 3 else ""
    n = len(failing_in_order)
    text = (f"sqlparse has a regression: {n} previously passing check{'s' if n != 1 else ''} of its behaviour "
            f"now fail{'s' if n == 1 else ''}. Affected behaviour: {shown}{more}.")
    if with_message:
        text += f" The first failing check reports: `{clean_message(messages[failing_in_order[0]])}`."
    return text + (" Fix the library so this behaviour is correct again; behaviour that works today must keep "
                   "working.")


def statement_leaks(statement: str, cand: Candidate, failing: list) -> list:
    leaks = []
    stem = Path(cand.file).stem
    if cand.file in statement or Path(cand.file).name in statement or re.search(rf"\bsqlparse[./]{stem}\b", statement):
        leaks.append("file")
    if re.search(rf"(\bline {cand.line}\b|:{cand.line}\b)", statement):
        leaks.append("line")
    for test_id in failing:
        module, _, name = test_id.partition("::")
        if test_id in statement or re.sub(r"\[.*\]$", "", name) in statement or module.split(".")[1] in statement:
            leaks.append("test id")
            break
    return leaks


def names_mutated_function(statement: str, cand: Candidate) -> bool:
    name = cand.function.rsplit(".", 1)[-1]
    if name in ("<module>", "__init__") or len(name.strip("_")) < 3:
        return False
    return name in statement or words(name.strip("_")) in statement.lower()


# ---------------------------------------------------------------- main


def classify(baseline_pass: list, run: SuiteRun):
    if run.timed_out:
        return "timeout", [], [], []
    if run.collection_errors:
        return "collection_error", [], [], []
    missing = [t for t in baseline_pass if t not in run.outcomes]
    if missing:
        return "missing_tests", [], [], []
    failing = [t for t in baseline_pass if run.outcomes[t] == "fail"]
    skipped = [t for t in baseline_pass if run.outcomes[t] == "skip"]
    passing = [t for t in baseline_pass if run.outcomes[t] == "pass"]
    if not failing:
        return "survived", failing, passing, skipped
    if len(failing) == len(baseline_pass):
        return "whole_suite", failing, passing, skipped
    if len(passing) / len(baseline_pass) < MIN_PASS_FRACTION:
        return "too_destructive", failing, passing, skipped
    return "kept", failing, passing, skipped


def gold_check(task: dict, pristine: Path, work: Path, python: str, targets: list, timeout: float,
               timeout_plugin: bool) -> dict:
    workspace = work / f"gold-{task['task_id']}"
    materialize(pristine, workspace, task["mutation_patch"])
    mutated = run_suite(python, workspace, targets, work / "gold-mutated.xml", timeout, timeout_plugin)
    mutated_failing = sorted(t for t, s in mutated.outcomes.items() if s == "fail")
    apply_patch(workspace, task["gold_patch"])
    restored = (workspace / task["mutation_file"]).read_bytes() == (pristine / task["mutation_file"]).read_bytes()
    fixed = run_suite(python, workspace, targets, work / "gold-fixed.xml", timeout, timeout_plugin)
    f2p = {t: fixed.outcomes.get(t, "missing") for t in task["fail_to_pass"]}
    p2p_bad = sorted(t for t in task["pass_to_pass"] if fixed.outcomes.get(t) != "pass")
    shutil.rmtree(workspace, ignore_errors=True)
    return {
        "task_id": task["task_id"],
        "mutated_failing_matches_record": mutated_failing == sorted(task["fail_to_pass"]),
        "mutated_failing_count": len(mutated_failing),
        "gold_restores_file_bytes": restored,
        "fail_to_pass_after_gold": {"pass": sum(s == "pass" for s in f2p.values()), "total": len(f2p),
                                    "not_passing": sorted(t for t, s in f2p.items() if s != "pass")},
        "pass_to_pass_not_passing_after_gold": p2p_bad,
        "suite_after_gold": {s: sum(v == s for v in fixed.outcomes.values()) for s in ("pass", "fail", "skip")},
        "ok": (mutated_failing == sorted(task["fail_to_pass"]) and restored
               and all(s == "pass" for s in f2p.values()) and not p2p_bad),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-dir", default=None, help="scratch directory (default: a new temp directory)")
    parser.add_argument("--python", default=None, help="task interpreter with pytest (default: the P6 bugs-venv)")
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--budget-seconds", type=float, default=660.0, help="wall cap for the candidate loop")
    parser.add_argument("--gold-check", type=int, default=2, help="kept tasks to gold-check after generation")
    parser.add_argument("--out", default=str(HERE / "tasks.mutations.json"))
    parser.add_argument("--log", default=str(HERE / "generation_log.json"))
    args = parser.parse_args()
    started = time.monotonic()

    source = next(t for t in json.loads((ROOT / "experiments" / "p6_pilot" / "tasks.json").read_text(
        encoding="utf-8"))["tasks"] if t["task_id"] == SOURCE_TASK)
    runtime = runtime_dir()
    repo = ensure_repo(source, runtime / "bug-mining" / "repos")
    python = args.python or str(venv_interpreter(runtime / "bugs-venv"))
    timeout_plugin = subprocess.run([python, "-c", "import pytest_timeout"], capture_output=True).returncode == 0
    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="mutation-tasks-"))
    work.mkdir(parents=True, exist_ok=True)
    pristine = work / "pristine"
    shutil.rmtree(pristine, ignore_errors=True)
    export(repo, source["fix_commit"], pristine)
    test_files = sorted(p.relative_to(pristine).as_posix() for p in (pristine / TEST_ROOT).rglob("test_*.py"))

    base_ws = work / "baseline"
    materialize(pristine, base_ws, "")
    baseline = run_suite(python, base_ws, test_files, work / "baseline.xml", 600, timeout_plugin)
    shutil.rmtree(base_ws, ignore_errors=True)
    baseline_pass = sorted(t for t, s in baseline.outcomes.items() if s == "pass")
    baseline_skip = sorted(t for t, s in baseline.outcomes.items() if s == "skip")
    if baseline.timed_out or baseline.collection_errors or any(s == "fail" for s in baseline.outcomes.values()):
        raise SystemExit(f"baseline suite is not healthy: {baseline.tail}")
    timeout = max(60.0, 10 * baseline.seconds)
    print(f"baseline: {len(baseline_pass)} pass, {len(baseline_skip)} skip, {baseline.seconds:.1f}s; "
          f"pytest-timeout plugin: {timeout_plugin}; per-run timeout {timeout:.0f}s", flush=True)

    candidates, invalid = find_candidates(pristine)
    pool = {kind: sum(c.kind == kind for c in candidates) for kind in KINDS}
    print(f"candidate pool: {len(candidates)} {pool}; invalid after edit: {invalid}", flush=True)

    log, tasks = [], []
    loop_started = time.monotonic()
    for cand in schedule(candidates):
        if len(log) >= args.max_candidates or time.monotonic() - loop_started > args.budget_seconds:
            break
        t0 = time.monotonic()
        workspace = work / "ws"
        patch = cand.patch()
        materialize(pristine, workspace, patch)
        if (workspace / cand.file).read_bytes().decode("utf-8") != cand.mutated:
            raise SystemExit(f"git apply did not reproduce the mutation of {cand.file}:{cand.line}")
        run = run_suite(python, workspace, test_files, work / "candidate.xml", timeout, timeout_plugin)
        verdict, failing, passing, skipped = classify(baseline_pass, run)
        entry = {"n": len(log) + 1, "file": cand.file, "line": cand.line, "kind": cand.kind, "detail": cand.detail,
                 "function": cand.function, "verdict": verdict, "failing": len(failing),
                 "pass_fraction": (round(len(passing) / len(baseline_pass), 4)
                                   if verdict not in ("timeout", "collection_error", "missing_tests") else None),
                 "suite_seconds": round(run.seconds, 2)}
        if verdict == "kept":
            messages = dict(run.failures)
            failing_in_order = [t for t, _ in run.failures if t in set(failing)]
            statement, fallback = build_statement(failing_in_order, messages), False
            leaks = statement_leaks(statement, cand, failing)
            if leaks:  # the message named something it must not; state the behaviour only
                statement, fallback = build_statement(failing_in_order, messages, with_message=False), True
                if statement_leaks(statement, cand, failing):
                    entry["verdict"] = verdict = "statement_leak"
        if verdict == "kept":
            task_id = f"sqlparse-mut-{len(tasks) + 1:03d}"
            entry["task_id"] = task_id
            tasks.append({
                "task_id": task_id,
                "repo": source["repo"],
                "repo_url": source["repo_url"],
                "upstream_pr": None,
                "base_commit": source["fix_commit"],
                "fix_commit": source["fix_commit"],
                "statement": statement,
                "evaluator_test_files": test_files,
                "fail_to_pass": sorted(failing),
                "excluded_fail_to_pass": {t: "baseline-passing test is skipped (xfail) under the mutation, so it "
                                             "cannot show fail-to-pass" for t in skipped},
                "pass_to_pass": passing,
                "skipped_after_fix": baseline_skip,
                "gold_source_files": [cand.file],
                "hidden_tests": True,
                "hidden_paths": [TEST_ROOT],
                "source_task": SOURCE_TASK,
                "generator_version": GENERATOR_VERSION,
                "mutation_file": cand.file,
                "mutation_line": cand.line,
                "mutation_end_line": cand.end_line,
                "mutation_kind": cand.kind,
                "mutation_detail": cand.detail,
                "mutated_function": cand.function,
                "mutation_patch": patch,
                "gold_patch": cand.gold_patch(),
                "statement_message_dropped": fallback,
                "statement_names_mutated_function": names_mutated_function(statement, cand),
                "first_failure_message": clean_message(messages[failing_in_order[0]]),
            })
        entry["candidate_seconds"] = round(time.monotonic() - t0, 2)
        log.append(entry)
        print(f"[{entry['n']:3d}] {verdict:16s} {cand.kind:16s} {cand.file}:{cand.line} failing={len(failing)} "
              f"{entry['candidate_seconds']:.1f}s" + (f" -> {entry['task_id']}" if "task_id" in entry else ""),
              flush=True)
    loop_seconds = time.monotonic() - loop_started
    shutil.rmtree(work / "ws", ignore_errors=True)

    checks = [gold_check(task, pristine, work, python, test_files, timeout, timeout_plugin)
              for task in tasks[:args.gold_check]]
    for check in checks:
        print(f"gold check {check['task_id']}: ok={check['ok']} f2p after gold "
              f"{check['fail_to_pass_after_gold']['pass']}/{check['fail_to_pass_after_gold']['total']} pass; "
              f"p2p regressions {len(check['pass_to_pass_not_passing_after_gold'])}; "
              f"suite {check['suite_after_gold']}", flush=True)

    verdicts = {}
    for entry in log:
        verdicts[entry["verdict"]] = verdicts.get(entry["verdict"], 0) + 1
    by_kind = {kind: {"tried": sum(e["kind"] == kind for e in log),
                      "kept": sum(e["kind"] == kind and e["verdict"] == "kept" for e in log)} for kind in KINDS}
    summary = {
        "generator_version": GENERATOR_VERSION, "source_task": SOURCE_TASK, "commit": source["fix_commit"],
        "task_python": python, "pytest_timeout_plugin": timeout_plugin, "per_run_timeout_seconds": timeout,
        "baseline": {"pass": len(baseline_pass), "skip": len(baseline_skip), "seconds": round(baseline.seconds, 2)},
        "candidate_pool": pool, "candidate_pool_total": len(candidates), "invalid_after_edit": invalid,
        "max_candidates": args.max_candidates, "budget_seconds": args.budget_seconds,
        "tried": len(log), "verdicts": verdicts, "by_kind": by_kind, "kept": len(tasks),
        "loop_seconds": round(loop_seconds, 1),
        "mean_candidate_seconds": round(sum(e["candidate_seconds"] for e in log) / max(1, len(log)), 2),
        "fail_to_pass_sizes": [len(t["fail_to_pass"]) for t in tasks],
        "total_seconds": round(time.monotonic() - started, 1),
    }
    Path(args.out).write_text(json.dumps({"schema_version": 1, "tasks": tasks}, indent=2) + "\n", encoding="utf-8")
    Path(args.log).write_text(json.dumps({"summary": summary, "gold_checks": checks, "candidates": log},
                                         indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
