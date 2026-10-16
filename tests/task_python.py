"""The interpreter tests use to run pytest: this one if it has pytest, else the task interpreter
(.runtime/bugs-venv, Scripts/python.exe or bin/python) of this checkout or of the main checkout that owns this worktree, else None."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
from interpreters import venv_interpreter  # noqa: E402


def pytest_interpreter():
    try:
        import pytest  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    roots = [ROOT]
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if common.returncode == 0 and common.stdout.strip():
        roots.append((ROOT / common.stdout.strip()).resolve().parent)
    candidates = [venv_interpreter(root / ".runtime" / "bugs-venv") for root in roots]
    return next((str(path) for path in candidates if path.exists()), None)


PYTEST_PYTHON = pytest_interpreter()
