"""Which pre-existing source files a run has changed.

Shared by two harness treatments: the finish guard (task completion detection) and the midpoint nudge
(agent loop). Both ask the same question, "has the model edited the code it was given?", and both must
answer it the same way whichever tool made the change (replace_text, write_file, or a run command).

Rule (``SOURCE_RULE_VERSION``): a source file is a file present in the workspace when the tracker is created
(before the model's first action) whose suffix is in ``SOURCE_SUFFIXES``, outside cache/VCS directories and the
runtime's excluded paths, and not a test file (under a test/tests/testing directory, named test_*.py or
*_test.py, or conftest.py). An edit is a change of its bytes, or its removal, observed by ``refresh``.
New files (reproduction scripts, scratch tests) are never source files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set

from reticle.runtime.workspace import WorkspaceTracker


SOURCE_RULE_VERSION = "pre-existing-python-source-v1"
SOURCE_SUFFIXES = (".py", ".pyi", ".pyx")
TEST_DIRECTORY_NAMES = frozenset({"test", "tests", "testing"})
# As the tools' SKIPPED_DIRECTORIES (reticle.tools.primitives); repeated here so the runtime does not import tools.
SKIPPED_DIRECTORY_NAMES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "node_modules",
})


def is_source_path(relative: str) -> bool:
    """Whether a workspace-relative POSIX path is a source file under SOURCE_RULE_VERSION (existence aside)."""
    path = PurePosixPath(relative)
    if path.suffix not in SOURCE_SUFFIXES:
        return False
    if SKIPPED_DIRECTORY_NAMES.intersection(path.parts) or TEST_DIRECTORY_NAMES.intersection(path.parts[:-1]):
        return False
    name = path.name
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


class SourceEditTracker:
    """Snapshot of the pre-existing source files at construction; ``refresh`` reports which ones changed."""

    def __init__(self, workspace: WorkspaceTracker):
        self.workspace = workspace
        self.root = Path(workspace.root)
        self.baseline: Dict[str, Optional[str]] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or workspace._is_excluded(path):
                continue
            relative = path.relative_to(self.root).as_posix()
            if is_source_path(relative):
                self.baseline[relative] = self._digest(relative)
        self._current = dict(self.baseline)
        self.edited: Set[str] = set()

    def _digest(self, relative: str) -> Optional[str]:
        try:
            return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
        except FileNotFoundError:
            return None

    def refresh(self) -> List[str]:
        """Source files whose bytes changed (or that disappeared) since the previous refresh."""
        changed = []
        for relative, previous in self._current.items():
            digest = self._digest(relative)
            if digest != previous:
                changed.append(relative)
                self._current[relative] = digest
        self.edited.update(changed)
        return changed

    def edited_files(self) -> List[str]:
        return sorted(self.edited)
