"""Test running Aider harness on bank-account exercise."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "experiments" / "exercism_bench" / "tasks" / "bank-account"

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    print("Work dir:", tmp_path)

    # Copy files
    shutil.copy(TASK_DIR / "bank_account.py", tmp_path / "bank_account.py")
    shutil.copy(TASK_DIR / "bank_account_test.py", tmp_path / "bank_account_test.py")
    shutil.copy(TASK_DIR / "instructions.md", tmp_path / "instructions.md")

    # Initialize git repo for Aider
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "AiderTester"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@aider.local"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial stub"], cwd=str(tmp_path), capture_output=True, check=True)

    env = os.environ.copy()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or LLM_API_KEY in the environment to run this test.")
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_API_BASE"] = "https://generativelanguage.googleapis.com/v1beta/openai"

    cmd = [
        "uvx", "--from", "aider-chat", "aider",
        "--model", "openai/gemini-flash-lite-latest",
        "--file", "bank_account.py",
        "--read", "instructions.md",
        "--read", "bank_account_test.py",
        "--test-cmd", f"{sys.executable} -B -m unittest bank_account_test.py",
        "--auto-test",
        "--yes-always",
        "--no-show-model-warnings",
        "--message", "Implement bank_account.py according to instructions.md so that bank_account_test.py passes.",
        "--exit"
    ]

    t0 = time.time()
    res = subprocess.run(cmd, cwd=str(tmp_path), env=env, capture_output=True, text=True)
    elapsed = time.time() - t0

    print("=== AIDER RUN COMPLETED in", round(elapsed, 2), "s ===")
    print("Exit code:", res.returncode)
    print("STDOUT tail:")
    print("\n".join(res.stdout.splitlines()[-25:]))

    # Verify final test status directly
    test_res = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "bank_account_test.py"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True
    )
    print("\n=== FINAL TEST VERIFICATION ===")
    print("Return code:", test_res.returncode)
    print("Passed:", test_res.returncode == 0)
    print(test_res.stdout + test_res.stderr)
