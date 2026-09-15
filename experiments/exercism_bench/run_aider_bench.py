"""Exercism / Aider Coding Benchmark Runner.

Evaluates coding performance under two conditions:
- Arm A (Direct Baseline): Single-turn direct code generation from instructions + stub.
- Arm B (Cognitive Harness): Multi-turn with deterministic test execution,
  traceback extraction, epistemic falsification tracking, and automated Turn-2 recovery.

Uses native python unittest in isolated temporary directories.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.cognitive.llm_client import LLMClient
from experiments.exercism_bench.exercism_loader import DEFAULT_EXERCISES, load_exercise

SYSTEM_PROMPT = """You are an expert Python software engineer.
You are implementing solutions to programming exercises so that all provided unit tests pass.
Write clean, idiomatic, and correct Python code.
Always return your complete implementation inside a ```python ``` code block.
Do not import private or non-standard packages unless specified.
"""

DIRECT_USER_PROMPT = """# Task: {slug}

## Instructions
{instructions}

## Starting Code Stub ({snake_name}.py)
```python
{stub}
```

Implement the complete solution in `{snake_name}.py` that satisfies all requirements.
Return ONLY the complete implementation inside a ```python ``` code block.
"""

REVISE_USER_PROMPT = """# Test Failure on Task: {slug}

Your previous implementation of `{snake_name}.py` failed unit tests.

## Current Code
```python
{current_code}
```

## Failed Test Diagnostics (unittest output)
```
{test_output}
```

## Falsification Analysis
The tests above failed against your previous implementation.
Carefully review the failure traceback, identify the exact logic or edge case that caused it,
and provide the complete, corrected implementation of `{snake_name}.py`.

Return ONLY the complete implementation inside a ```python ``` code block.
"""


def extract_python_code(text: str) -> str:
    """Extract python code from markdown code block or fallback to raw text."""
    pattern = r"```python\s*(.*?)\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    pattern_generic = r"```\s*(.*?)\s*```"
    matches_generic = re.findall(pattern_generic, text, re.DOTALL)
    if matches_generic:
        return matches_generic[-1].strip()
    return text.strip()


def run_test_suite(work_dir: Path, test_filename: str) -> Tuple[bool, int, int, str]:
    """Run python -m unittest in work_dir. Returns (all_passed, passed_count, total_count, output)."""
    cmd = [sys.executable, "-B", "-m", "unittest", test_filename]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        output = (res.stdout + res.stderr).strip()
        all_passed = (res.returncode == 0)
    except subprocess.TimeoutExpired:
        return False, 0, 1, "TIMEOUT: Unit tests timed out after 5.0 seconds (likely infinite loop in implementation)."

    # Parse test count e.g. "Ran 16 tests in 0.004s"
    total = 0
    passed = 0
    m_ran = re.search(r"Ran (\d+) test", output)
    if m_ran:
        total = int(m_ran.group(1))

    if all_passed:
        passed = total
    else:
        # e.g. FAILED (failures=2, errors=1)
        m_fails = re.search(r"failures=(\d+)", output)
        m_errs = re.search(r"errors=(\d+)", output)
        f_count = int(m_fails.group(1)) if m_fails else 0
        e_count = int(m_errs.group(1)) if m_errs else 0
        passed = max(0, total - (f_count + e_count))

    return all_passed, passed, total, output


def evaluate_arm_a_direct(
    client: LLMClient,
    task: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute Arm A: Single-turn direct generation."""
    slug = task["slug"]
    snake = task["snake_name"]
    t0 = time.time()

    prompt = DIRECT_USER_PROMPT.format(
        slug=slug,
        instructions=task["instructions"],
        snake_name=snake,
        stub=task["stub"]
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    resp = client.chat_completion(messages)
    generated_code = extract_python_code(resp["content"])
    tokens = resp.get("usage", {}).get("total_tokens", 0)

    # Execute tests in isolated temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / f"{snake}.py").write_text(generated_code, encoding="utf-8")
        (tmp_path / f"{snake}_test.py").write_text(task["test_code"], encoding="utf-8")

        all_passed, passed, total, test_out = run_test_suite(tmp_path, f"{snake}_test.py")

    elapsed = time.time() - t0
    return {
        "passed": all_passed,
        "tests_passed": passed,
        "tests_total": total,
        "pass_ratio": round(passed / total, 2) if total > 0 else 0.0,
        "elapsed_s": round(elapsed, 2),
        "tokens": tokens,
        "test_output": test_out[:500] if not all_passed else "ALL PASSED"
    }


def evaluate_arm_b_harness(
    client: LLMClient,
    task: Dict[str, Any],
    max_turns: int = 2
) -> Dict[str, Any]:
    """Execute Arm B: Multi-turn harness with test feedback and state tracking."""
    slug = task["slug"]
    snake = task["snake_name"]
    t0 = time.time()
    total_tokens = 0

    # Turn 1: Initial generation
    prompt = DIRECT_USER_PROMPT.format(
        slug=slug,
        instructions=task["instructions"],
        snake_name=snake,
        stub=task["stub"]
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    resp1 = client.chat_completion(messages)
    total_tokens += resp1.get("usage", {}).get("total_tokens", 0)
    current_code = extract_python_code(resp1["content"])

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        code_file = tmp_path / f"{snake}.py"
        test_file = tmp_path / f"{snake}_test.py"
        code_file.write_text(current_code, encoding="utf-8")
        test_file.write_text(task["test_code"], encoding="utf-8")

        all_passed, passed, total, test_out = run_test_suite(tmp_path, f"{snake}_test.py")
        turn1_passed = all_passed
        turn1_stats = (passed, total)

        if all_passed or max_turns <= 1:
            elapsed = time.time() - t0
            return {
                "passed": all_passed,
                "turn1_passed": turn1_passed,
                "turn2_recovered": False,
                "turns_used": 1,
                "tests_passed": passed,
                "tests_total": total,
                "pass_ratio": round(passed / total, 2) if total > 0 else 0.0,
                "elapsed_s": round(elapsed, 2),
                "tokens": total_tokens,
                "test_output": "ALL PASSED" if all_passed else test_out[:500]
            }

        # Turn 2: Epistemic Test Feedback (Refinement)
        # Extract the concise failure traceback (omit boilerplate)
        clean_traceback = test_out
        if len(clean_traceback) > 2000:
            clean_traceback = clean_traceback[-2000:]

        revise_prompt = REVISE_USER_PROMPT.format(
            slug=slug,
            snake_name=snake,
            current_code=current_code,
            test_output=clean_traceback
        )

        messages.append({"role": "assistant", "content": resp1["content"]})
        messages.append({"role": "user", "content": revise_prompt})

        resp2 = client.chat_completion(messages)
        total_tokens += resp2.get("usage", {}).get("total_tokens", 0)
        current_code = extract_python_code(resp2["content"])

        code_file.write_text(current_code, encoding="utf-8")
        all_passed2, passed2, total2, test_out2 = run_test_suite(tmp_path, f"{snake}_test.py")

        elapsed = time.time() - t0
        return {
            "passed": all_passed2,
            "turn1_passed": False,
            "turn2_recovered": all_passed2,
            "turns_used": 2,
            "tests_passed": passed2,
            "tests_total": total2,
            "pass_ratio": round(passed2 / total2, 2) if total2 > 0 else 0.0,
            "elapsed_s": round(elapsed, 2),
            "tokens": total_tokens,
            "test_output": "ALL PASSED" if all_passed2 else test_out2[:500]
        }


def evaluate_arm_c_aider(
    task: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute Arm C: Official Aider CLI harness with auto-test and git tracking."""
    slug = task["slug"]
    snake = task["snake_name"]
    t0 = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Write starter files
        (tmp_path / f"{snake}.py").write_text(task["stub"], encoding="utf-8")
        (tmp_path / f"{snake}_test.py").write_text(task["test_code"], encoding="utf-8")
        (tmp_path / "instructions.md").write_text(task["instructions"], encoding="utf-8")

        # Initialize git repo for Aider
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "AiderBench"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "bench@aider.local"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial stub"], cwd=str(tmp_path), capture_output=True, check=True)

        env = os.environ.copy()
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError("Set GEMINI_API_KEY or LLM_API_KEY (e.g. in .env) to run the Aider arm.")
        env["OPENAI_API_KEY"] = api_key
        env["OPENAI_API_BASE"] = "https://generativelanguage.googleapis.com/v1beta/openai"

        cmd = [
            "uvx", "--from", "aider-chat", "aider",
            "--model", "openai/gemini-flash-lite-latest",
            "--file", f"{snake}.py",
            "--read", "instructions.md",
            "--read", f"{snake}_test.py",
            "--test-cmd", f"{sys.executable} -B -m unittest {snake}_test.py",
            "--auto-test",
            "--yes-always",
            "--no-show-model-warnings",
            "--message", f"Implement {snake}.py according to instructions.md so that {snake}_test.py passes.",
            "--exit"
        ]

        try:
            res = subprocess.run(cmd, cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=90)
            aider_output = res.stdout + res.stderr
        except subprocess.TimeoutExpired:
            aider_output = "Aider execution timed out (90s)"

        elapsed = time.time() - t0

        all_passed, passed, total, test_out = run_test_suite(tmp_path, f"{snake}_test.py")

        # Parse token estimate if printed in aider output
        m_tok = re.findall(r"Tokens:\s*([\d\.]+)k?\s*sent,\s*([\d\.]+)k?\s*received", aider_output)
        est_tokens = 0
        for sent, rec in m_tok:
            s_val = float(sent) * 1000 if 'k' in sent else float(sent)
            r_val = float(rec) * 1000 if 'k' in rec else float(rec)
            est_tokens += int(s_val + r_val)

        return {
            "passed": all_passed,
            "tests_passed": passed,
            "tests_total": total,
            "pass_ratio": round(passed / total, 2) if total > 0 else 0.0,
            "elapsed_s": round(elapsed, 2),
            "tokens": est_tokens,
            "test_output": "ALL PASSED" if all_passed else test_out[:500]
        }


def run_benchmark(exercises: Optional[List[str]] = None, run_aider: bool = True):
    client = LLMClient(model="gemini-flash-lite-latest")
    slugs = exercises or DEFAULT_EXERCISES

    print("=" * 85)
    print("LIVE 3-WAY BENCHMARK: DIRECT BASELINE vs COGNITIVE HARNESS vs OFFICIAL AIDER")
    print(f"Model: {client.model} | Tasks: {len(slugs)}")
    print("=" * 85)

    results = []

    for i, slug in enumerate(slugs, 1):
        task = load_exercise(slug)
        print(f"\n[{i}/{len(slugs)}] Task: '{slug}'")

        # Arm A: Direct Baseline
        print("  [Arm A: Direct Baseline]   ", end=" ", flush=True)
        res_a = evaluate_arm_a_direct(client, task)
        status_a = "PASS" if res_a["passed"] else f"FAIL ({res_a['tests_passed']}/{res_a['tests_total']})"
        print(f"{status_a:18s} ({res_a['elapsed_s']:5.2f}s, {res_a['tokens']:5d} tok)")

        # Arm B: Cognitive Harness
        print("  [Arm B: Cognitive Harness] ", end=" ", flush=True)
        res_b = evaluate_arm_b_harness(client, task, max_turns=2)
        if res_b["turn1_passed"]:
            status_b = "PASS [T1]"
        elif res_b["turn2_recovered"]:
            status_b = "PASS [RECOVERED]"
        else:
            status_b = f"FAIL ({res_b['tests_passed']}/{res_b['tests_total']})"
        print(f"{status_b:18s} ({res_b['elapsed_s']:5.2f}s, {res_b['tokens']:5d} tok)")

        # Arm C: Official Aider
        res_c = None
        if run_aider:
            print("  [Arm C: Official Aider]    ", end=" ", flush=True)
            res_c = evaluate_arm_c_aider(task)
            status_c = "PASS" if res_c["passed"] else f"FAIL ({res_c['tests_passed']}/{res_c['tests_total']})"
            print(f"{status_c:18s} ({res_c['elapsed_s']:5.2f}s, {res_c['tokens']:5d} tok)")

        results.append({
            "slug": slug,
            "arm_a": res_a,
            "arm_b": res_b,
            "arm_c": res_c
        })

    # Summary Statistics
    total_tasks = len(results)
    a_passed = sum(1 for r in results if r["arm_a"]["passed"])
    b_passed = sum(1 for r in results if r["arm_b"]["passed"])
    c_passed = sum(1 for r in results if r["arm_c"] and r["arm_c"]["passed"]) if run_aider else 0

    a_time = sum(r["arm_a"]["elapsed_s"] for r in results)
    b_time = sum(r["arm_b"]["elapsed_s"] for r in results)
    c_time = sum(r["arm_c"]["elapsed_s"] for r in results if r["arm_c"]) if run_aider else 0

    print("\n" + "=" * 85)
    print("3-WAY HEAD-TO-HEAD BENCHMARK SUMMARY")
    print("=" * 85)
    print(f"Arm A (Direct Baseline Pass@1):       {a_passed:2d}/{total_tasks} ({a_passed/total_tasks*100:5.1f}%) | Total Time: {a_time:6.1f}s")
    print(f"Arm B (Cognitive Harness Pass@2):     {b_passed:2d}/{total_tasks} ({b_passed/total_tasks*100:5.1f}%) | Total Time: {b_time:6.1f}s")
    if run_aider:
        print(f"Arm C (Official Aider Harness):       {c_passed:2d}/{total_tasks} ({c_passed/total_tasks*100:5.1f}%) | Total Time: {c_time:6.1f}s")

    out_file = ROOT / "experiments" / "exercism_bench" / "3way_bench_results.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nDetailed 3-way JSON report saved to: {out_file}")


if __name__ == "__main__":
    tasks_to_run = [arg for arg in sys.argv[1:] if not arg.startswith("--")] or None
    run_benchmark(tasks_to_run)

