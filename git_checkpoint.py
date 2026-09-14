"""Transactional Git Checkpoint & Rollback Manager.

Ensures that exploratory edits, broken syntax, or failed experiments
do not poison the workspace state across agent attempts.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Optional


class GitCheckpointManager:
    """Manages clean working directory checkpoints and rollbacks."""

    def __init__(self, repo_dir: str | Path = "."):
        self.repo_dir = Path(repo_dir).resolve()
        self._initial_commit: Optional[str] = None
        self._save_clean_state()

    def _run_git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True
        )

    def _save_clean_state(self):
        res = self._run_git("rev-parse", "HEAD")
        if res.returncode == 0:
            self._initial_commit = res.stdout.strip()

    def get_diff(self) -> str:
        """Return unified diff of all uncommitted modifications."""
        res = self._run_git("diff", "HEAD")
        if res.returncode == 0:
            return res.stdout
        # If no commits yet
        res2 = self._run_git("diff")
        return res2.stdout if res2.returncode == 0 else ""

    def status(self) -> str:
        """Return short git status."""
        res = self._run_git("status", "--short")
        return res.stdout.strip() if res.returncode == 0 else "error"

    def has_changes(self) -> bool:
        """True if there are unstaged or staged modifications."""
        return bool(self.status())

    def rollback(self) -> bool:
        """Revert all uncommitted modifications and remove untracked files."""
        # Restore modified tracked files
        res1 = self._run_git("checkout", "--", ".")
        # Remove untracked files created during the attempt
        res2 = self._run_git("clean", "-fd")
        return res1.returncode == 0 and res2.returncode == 0

    def commit(self, message: str) -> bool:
        """Stage all modifications and commit with message."""
        add_res = self._run_git("add", "-A")
        if add_res.returncode != 0:
            return False
        commit_res = self._run_git("commit", "-m", message)
        return commit_res.returncode == 0


if __name__ == "__main__":
    mgr = GitCheckpointManager()
    print("Git Repository:", mgr.repo_dir)
    print("Initial commit:", mgr._initial_commit)
    print("Has changes:", mgr.has_changes())
    print("Current diff size:", len(mgr.get_diff()), "chars")
