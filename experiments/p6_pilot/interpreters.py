"""Where the task interpreter lives, on Windows and POSIX checkouts (no third-party imports).

The task interpreter is the Python of .runtime/bugs-venv (pytest and the task repositories' test dependencies).
A venv made on Windows has Scripts/python.exe, one made on Linux or macOS has bin/python. Every script that needs the
task interpreter resolves it here, so a Windows checkout keeps the path it always had and a Linux checkout (a cloud
VM, see experiments/cloud/) finds its own without a flag.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

TASK_PYTHON_VARIABLE = "RETICLE_TASK_PYTHON"


def venv_interpreter(venv: Path) -> Path:
    """The venv's Windows interpreter if it exists, else its POSIX one if it exists, else the one this platform's
    venv layout would have (so a missing venv still names the path the error should mention)."""
    venv = Path(venv)
    windows, posix = venv / "Scripts" / "python.exe", venv / "bin" / "python"
    for candidate in (windows, posix):
        if candidate.exists():
            return candidate
    return windows if os.name == "nt" else posix


def task_python(root: Path, environ: Optional[Mapping[str, str]] = None) -> Path:
    """$RETICLE_TASK_PYTHON if set, else root/.runtime/bugs-venv's interpreter (venv_interpreter)."""
    environ = os.environ if environ is None else environ
    override = environ.get(TASK_PYTHON_VARIABLE)
    if override:
        return Path(override)
    return venv_interpreter(Path(root) / ".runtime" / "bugs-venv")
