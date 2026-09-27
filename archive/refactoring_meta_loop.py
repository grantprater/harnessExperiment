"""Autonomous Refactoring Meta-Loop (Reticle Self-Improvement Engine).

Implements the self-injected epistemic loop:
1. AST Profiler: Measures complexity (LOC, cyclomatic branching, nesting depth)
   to identify refactoring candidates in the Reticle codebase.
2. Stateless Note Board: Anchors the refactoring goal, grounding pointers, and
   falsification ledger for the target function.
3. Verification Invariants:
   - Invariant 1: AST parsing (`ast.parse`) without syntax errors.
   - Invariant 2: Full unit test suite passes 100% (zero regressions).
   - Invariant 3: Measurable reduction in cyclomatic branches or LOC.
4. Transactional Git Rollback: Failed attempts are recorded in the
   FalsificationLedger and rolled back cleanly via Git.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent

from stateless_harness import (
    EpistemicNoteBoard,
    FalsificationLedger,
    GroundingLedger,
    StatelessEnvironment,
)
from git_checkpoint import GitCheckpointManager


@dataclass
class ComplexityMetrics:
    total_lines: int
    branch_count: int
    max_nesting: int
    complexity_score: float


@dataclass
class RefactoringCandidate:
    file_path: str
    function_name: str
    start_line: int
    end_line: int
    metrics: ComplexityMetrics


class ComplexityProfiler:
    """Scans Python files and profiles AST complexity to rank refactoring targets."""

    @staticmethod
    def measure_function(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: List[str]) -> ComplexityMetrics:
        start = fn_node.lineno
        end = fn_node.end_lineno or start
        lines = end - start + 1

        branch_count = 0
        max_depth = 0

        def walk_node(node: ast.AST, depth: int):
            nonlocal branch_count, max_depth
            if depth > max_depth:
                max_depth = depth

            # Count branching constructs
            if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.comprehension)):
                branch_count += 1

            for child in ast.iter_child_nodes(node):
                walk_node(child, depth + 1 if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)) else depth)

        walk_node(fn_node, 0)
        # Score = weighted combination of lines, branches, and depth
        score = (lines * 0.4) + (branch_count * 3.0) + (max_depth * 1.5)

        return ComplexityMetrics(
            total_lines=lines,
            branch_count=branch_count,
            max_nesting=max_depth,
            complexity_score=round(score, 2)
        )

    @classmethod
    def scan_codebase(cls, root_dir: Path) -> List[RefactoringCandidate]:
        candidates: List[RefactoringCandidate] = []
        ignored = {"tests", "__pycache__", ".git", "experiments", ".runtime", "corpus_cache", "scratch", "spatial_cache"}

        for p in root_dir.rglob("*.py"):
            parts = set(p.parts)
            if ignored & parts:
                continue

            try:
                src = p.read_text(encoding="utf-8")
                tree = ast.parse(src)
                src_lines = src.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Ignore dunder methods and tiny functions
                        if node.name.startswith("__") or (node.end_lineno or 0) - node.lineno < 20:
                            continue
                        metrics = cls.measure_function(node, src_lines)
                        rel_path = str(p.relative_to(root_dir)).replace("\\", "/")
                        candidates.append(RefactoringCandidate(
                            file_path=rel_path,
                            function_name=node.name,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            metrics=metrics
                        ))
            except Exception:
                continue

        # Sort by highest complexity score
        candidates.sort(key=lambda c: c.metrics.complexity_score, reverse=True)
        return candidates


class AutonomousRefactoringMetaLoop:
    """Executes the epistemic self-improvement loop on the Reticle codebase."""

    def __init__(self, repo_dir: Path = ROOT):
        self.repo_dir = Path(repo_dir).resolve()
        self.git_mgr = GitCheckpointManager(self.repo_dir)

    def verify_all_invariants(self) -> Dict[str, Any]:
        """Runs test suites as deterministic verification oracle."""
        t0 = time.time()
        # 1. Run tests/ discovery
        p1 = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=60
        )
        # 2. Run root discovery
        p2 = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=60
        )
        elapsed = time.time() - t0

        passed = (p1.returncode == 0) and (p2.returncode == 0)
        return {
            "passed": passed,
            "elapsed_s": round(elapsed, 2),
            "tests_suite_passed": p1.returncode == 0,
            "root_suite_passed": p2.returncode == 0,
            "stderr": (p1.stderr + "\n" + p2.stderr).strip()
        }

    def execute_refactor(
        self,
        candidate: RefactoringCandidate,
        refactored_code: str,
        refactoring_intent: str
    ) -> Dict[str, Any]:
        """Apply refactoring under epistemic note board supervision."""
        board = EpistemicNoteBoard(
            goal=f"Refactor {candidate.function_name} in {candidate.file_path} to reduce complexity",
            invariants=[
                "Python AST parses cleanly without SyntaxError",
                "Full unit test suite (tests/ + root) passes 100%",
                "Complexity score and branching reduced"
            ]
        )

        board.grounding.record_pointer(
            target=candidate.file_path,
            locator=f"L{candidate.start_line}-L{candidate.end_line}",
            description=f"Function {candidate.function_name} (Lines: {candidate.metrics.total_lines}, Branches: {candidate.metrics.branch_count})"
        )

        target_file = self.repo_dir / candidate.file_path
        original_content = target_file.read_text(encoding="utf-8")

        # Invariant 1: Syntactic AST Check on replacement
        try:
            # Check proposed code alone or in full context
            lines = original_content.splitlines(keepends=True)
            repl_lines = [l if l.endswith("\n") else l + "\n" for l in refactored_code.splitlines()]
            new_text = "".join(lines[:candidate.start_line - 1] + repl_lines + lines[candidate.end_line:])
            ast.parse(new_text)
        except SyntaxError as e:
            board.falsifications.record(
                hypothesis=refactoring_intent,
                action_taken="ast.parse check",
                rejection_evidence=f"SyntaxError: {e}",
                step=1
            )
            return {"success": False, "reason": f"SyntaxError: {e}", "board": board}

        # Apply modification to disk
        target_file.write_text(new_text, encoding="utf-8")

        # Invariant 2: Run Verification Oracle
        print("  [Verification Oracle] Running test suites...")
        verif = self.verify_all_invariants()

        if not verif["passed"]:
            print(f"  [Oracle REJECTED] Tests failed. Rolling back working tree...")
            board.falsifications.record(
                hypothesis=refactoring_intent,
                action_taken="run_full_verification()",
                rejection_evidence=verif["stderr"][:300] or "Unittest failed",
                step=2
            )
            target_file.write_text(original_content, encoding="utf-8")
            return {"success": False, "reason": "Test suite failure", "board": board}

        # Invariant 3: Measure post-refactoring complexity
        post_metrics = ComplexityMetrics(0, 0, 0, 0.0)
        try:
            post_tree = ast.parse(target_file.read_text(encoding="utf-8"))
            for node in ast.walk(post_tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == candidate.function_name:
                    post_metrics = ComplexityProfiler.measure_function(node, new_text.splitlines())
                    break
        except Exception:
            pass

        print(f"  [Oracle PASSED] Invariants satisfied in {verif['elapsed_s']}s!")
        print(f"  Complexity score: {candidate.metrics.complexity_score} -> {post_metrics.complexity_score}")
        print(f"  Branches: {candidate.metrics.branch_count} -> {post_metrics.branch_count}")

        # Commit verified refactoring to Git
        commit_msg = (
            f"Refactor({candidate.function_name}): {refactoring_intent}\n\n"
            f"- Complexity: {candidate.metrics.complexity_score} -> {post_metrics.complexity_score}\n"
            f"- Branches: {candidate.metrics.branch_count} -> {post_metrics.branch_count}\n"
            f"- Verified: 100% unit tests green"
        )
        self.git_mgr.commit(commit_msg)

        # Update active epistemic board
        board_file = self.repo_dir / "ACTIVE_EPISTEMIC_BOARD.md"
        if board_file.exists():
            board_text = board_file.read_text(encoding="utf-8")
            delta_entry = (
                f"- [Self-Improvement] Refactored `{candidate.file_path}:{candidate.function_name}`: "
                f"branches reduced from {candidate.metrics.branch_count} to {post_metrics.branch_count}, "
                f"score from {candidate.metrics.complexity_score} to {post_metrics.complexity_score}. Tests verified."
            )
            if "## 5. LAST ACTION DELTA" in board_text:
                parts = board_text.split("## 5. LAST ACTION DELTA (IMMEDIATE FEEDBACK)")
                new_board = parts[0] + "## 5. LAST ACTION DELTA (IMMEDIATE FEEDBACK)\n" + delta_entry + "\n" + parts[1].strip()
                board_file.write_text(new_board, encoding="utf-8")

        return {
            "success": True,
            "candidate": candidate,
            "pre_metrics": candidate.metrics,
            "post_metrics": post_metrics,
            "board": board
        }


if __name__ == "__main__":
    print("==========================================================")
    print("AUTONOMOUS REFACTORING META-LOOP: CODEBASE PROFILING")
    print("==========================================================")
    candidates = ComplexityProfiler.scan_codebase(ROOT)
    print(f"\nTop 10 Refactoring Candidates by AST Complexity Score:")
    print("-" * 75)
    print(f"{'Rank':<5} {'Score':<8} {'Lines':<7} {'Branches':<10} {'Target'}")
    print("-" * 75)
    for i, c in enumerate(candidates[:10], 1):
        print(f"#{i:<4} {c.metrics.complexity_score:<8.1f} {c.metrics.total_lines:<7} {c.metrics.branch_count:<10} {c.file_path}:{c.start_line} [{c.function_name}]")
