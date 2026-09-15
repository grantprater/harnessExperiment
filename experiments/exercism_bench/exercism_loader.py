"""Exercism Benchmark Suite Loader & Task Cache.

Fetches real-world practice exercises directly from exercism/python on GitHub:
- .docs/instructions.md
- {exercise}.py (starter stub)
- {exercise}_test.py (official unittest suite)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.request
from typing import Any, Dict, List

BENCH_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCH_DIR / "tasks"

DEFAULT_EXERCISES = [
    "bank-account",
    "clock",
    "allergies",
    "grade-school",
    "circular-buffer",
    "markdown",
    "ledger",
    "word-count",
    "robot-simulator",
    "tournament",
]

RAW_BASE = "https://raw.githubusercontent.com/exercism/python/main/exercises/practice"


def fetch_exercise(name: str, force: bool = False) -> Path:
    target_dir = TASKS_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)
    snake_name = name.replace("-", "_")

    files_to_fetch = {
        "instructions.md": f"{RAW_BASE}/{name}/.docs/instructions.md",
        f"{snake_name}.py": f"{RAW_BASE}/{name}/{snake_name}.py",
        f"{snake_name}_test.py": f"{RAW_BASE}/{name}/{snake_name}_test.py",
    }

    headers = {"User-Agent": "Reticle-Exercism-Loader"}

    for filename, url in files_to_fetch.items():
        dest = target_dir / filename
        if dest.exists() and not force:
            continue
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
            dest.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            raise

    return target_dir


def load_exercise(name: str) -> Dict[str, Any]:
    snake_name = name.replace("-", "_")
    task_dir = TASKS_DIR / name
    if not (task_dir / f"{snake_name}_test.py").exists():
        fetch_exercise(name)

    return {
        "slug": name,
        "snake_name": snake_name,
        "instructions": (task_dir / "instructions.md").read_text(encoding="utf-8"),
        "stub": (task_dir / f"{snake_name}.py").read_text(encoding="utf-8"),
        "test_code": (task_dir / f"{snake_name}_test.py").read_text(encoding="utf-8"),
        "dir": task_dir,
    }


def fetch_all(exercises: List[str] = DEFAULT_EXERCISES):
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {len(exercises)} Exercism tasks...")
    for ex in exercises:
        print(f"  Fetching '{ex}'...", end=" ", flush=True)
        fetch_exercise(ex)
        print("Done.")
    print("All tasks ready in:", TASKS_DIR)


if __name__ == "__main__":
    fetch_all()
