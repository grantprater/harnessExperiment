"""Opt-in network and file isolation for trusted-local commands on Linux: `--sandbox unshare-rnm` (card 022, cloud first).

Every command the backend runs (the run tool's commands and the evaluator's) starts inside new user, mount and network
namespaces (`unshare -rnm`, which needs no root: the cloud VM passed experiments/cloud/probe_isolation.sh on
2026-09-29, branch cloud-probe-isolation). Inside, before the command:
- the only network interface is an unconfigured loopback, so nothing outside the machine is reachable;
- a tmpfs covers each hidden directory (a hidden file is covered by /dev/null): the checkout's experiments/ (the task
  file, every snapshot, other runs and this run's evaluator bundle), the raw series cache .runtime/forecast-022, the
  checkout's .git and the repository's common git directory, and ~/harness-sealed;
- the command's working directory, bind-mounted aside first, is mounted back at its own path, so the workspace (or the
  evaluator's private evaluation root) is the one part of the hidden tree that stays visible and writable.
The interpreters (.runtime/bugs-venv, the runner's own) stay visible. Mounts made inside the namespace vanish with it,
and files the command writes in its working directory belong to the invoking user outside.

The execution contract records the sandbox (name, version, what it hides, by role rather than by absolute path), so it
enters the protocol hash only when it is on.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import List, Optional

from reticle.execution import TrustedLocalBackend

SANDBOX_NAME = "unshare-rnm"
SANDBOX_VERSION = "unshare-rnm-v1"
HIDDEN_ROLES = ("checkout/experiments", "checkout/.runtime/forecast-022", "checkout/.git", "git common directory",
                "~/harness-sealed")
# sh -c script: $1 = working directory, then hidden paths, then "--", then the command.
WRAPPER = r'''set -e
wd=$1; shift
view=$(mktemp -d)
mount --bind "$wd" "$view"
while [ "$1" != "--" ]; do
  if [ -d "$1" ]; then mount -t tmpfs -o size=1m,mode=755 reticle-hidden "$1"
  elif [ -e "$1" ]; then mount --bind /dev/null "$1"; fi
  shift
done
shift
mkdir -p "$wd"
mount --bind "$view" "$wd"
cd "$wd"
exec "$@"
'''


def hidden_paths(root: Path, home: Optional[Path] = None) -> List[str]:
    """The absolute paths the sandbox hides on this machine, in HIDDEN_ROLES order (missing ones are skipped at run
    time by the wrapper)."""
    root = Path(root).resolve()
    paths = [root / "experiments", root / ".runtime" / "forecast-022", root / ".git"]
    try:
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        common = ""
    if common and Path(common).resolve() != (root / ".git").resolve():
        paths.append(Path(common).resolve())
    paths.append(Path(home or Path.home()) / "harness-sealed")
    return [str(path) for path in paths]


def contract() -> dict:
    """What the execution contract records for the sandbox (machine-independent)."""
    return {"name": SANDBOX_NAME, "version": SANDBOX_VERSION, "hides": list(HIDDEN_ROLES),
            "network": "new network namespace: loopback only",
            "wrapper_sha256": hashlib.sha256(WRAPPER.encode("utf-8")).hexdigest()}


def availability() -> Optional[str]:
    """Why the sandbox cannot run on this machine, or None."""
    if os.name != "posix":
        return "--sandbox unshare-rnm needs Linux (user, mount and network namespaces)"
    if shutil.which("unshare") is None:
        return "--sandbox unshare-rnm needs util-linux unshare on PATH"
    completed = subprocess.run(["unshare", "-rnm", "true"], capture_output=True, text=True)
    if completed.returncode:
        return f"unshare -rnm is refused here: {completed.stderr.strip()[:200]}"
    return None


class NamespaceSandboxBackend(TrustedLocalBackend):
    """TrustedLocalBackend whose every command runs under unshare -rnm with the hidden paths covered."""

    name = "trusted-local-unshare-rnm"
    host_isolation = False  # paths are the host's; only what is visible and reachable changes

    def __init__(self, hidden: List[str]):
        self.hidden = list(hidden)

    def wrap(self, command: List[str], working_directory) -> List[str]:
        directory = str(Path(working_directory).resolve())
        return ["unshare", "-rnm", "--", "sh", "-c", WRAPPER, "reticle-sandbox", directory, *self.hidden, "--",
                *command]

    def run(self, request, cancellation_event=None):
        wrapped = dataclasses.replace(request, command=self.wrap(request.command, request.working_directory))
        return super().run(wrapped, cancellation_event)
