"""Post-run integrity check: flag `run` commands that reach outside the workspace. Report only.

    python experiments/session_harness/run_integrity.py RUN_DIR [RUN_DIR ...] [--json]

Reads each run directory's calls.jsonl (the model's replies, in every client's format: choices[].message.tool_calls)
and classifies every `run` tool call's command, as the 019-021 integrity audit did by hand
(experiments/cloud/INTEGRITY_AUDIT_019-021.md, "How the check was done", step 2). Flags:

  outside-path   an absolute path (/..., ~..., C:\\...) that is not the run's own workspace, as an argument or a
                 string literal in a python -c / sh -c snippet (find /, cat /home/..., diff <clone> ..., /tmp/...)
  parent-path    a `..` path component (ls .., cat ../evaluator/...)
  git            any git command: the workspace has no repository, so git reaches the enclosing harness checkout
  package-tool   pip, uv, conda and the like (pip show, pip download), also as python -m pip
  network        a network tool (curl, wget, ssh, ...), a package or git subcommand that fetches (pip download,
                 git clone), or a python -c snippet using urllib, requests, socket, http.client

It changes no acceptance and no record: run_card.py logs its summary as an `integrity_scan` campaign event after each
invocation and prints the flagged commands; a reviewer decides what a flag means. A flag says the command tried to
reach outside; whether it got anything back is in the tool result (and under unshare-confined it gets nothing).
No model calls; standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable, List, Optional

SCAN_VERSION = "run-integrity-v1"
FLAGS = ("outside-path", "parent-path", "git", "package-tool", "network")
OPERATORS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "2>", "2>&1"}
PYTHON_HEADS = {"python", "python3", "py"}
SHELL_HEADS = {"sh", "bash", "dash", "zsh"}
SCRIPT_TOOLS = {"sed", "awk", "gawk", "perl"}  # their first operand is a program, not a path
NETWORK_TOOLS = {"curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp", "rsync", "ftp", "aria2c",
                 "http", "https", "socat", "ping", "dig", "nslookup", "host"}
PACKAGE_TOOLS = {"pip", "pip3", "uv", "pipx", "conda", "mamba", "poetry", "pdm", "easy_install", "apt", "apt-get",
                 "npm", "yarn"}
PACKAGE_FETCH = {"download", "install", "wheel", "add", "sync", "fetch", "search", "index", "lock"}
GIT_FETCH = {"clone", "fetch", "pull", "ls-remote", "push", "submodule", "archive"}
PATH_TOKEN = re.compile(r"^(?:/(?:[\w.@+~-]+/?)*|~[\w.@+-]*(?:/[\w.@+~-]*)*|[A-Za-z]:[\\/][^\s]*)$")
PARENT = re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)")
CODE_PATH = re.compile(r"""['"](?:/(?![/*])|~|[A-Za-z]:[\\/])""")
CODE_PARENT = re.compile(r"""['"/\\]\.\.(?:['"/\\])""")
CODE_NETWORK = re.compile(r"\b(?:urllib|urlopen|requests|httpx|http\.client|socket|aiohttp|ftplib|smtplib|pip)\b")


def _split(command: str) -> List[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _segments(argv: List[str]) -> List[List[str]]:
    segments, current = [], []
    for token in argv:
        if token in OPERATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _head(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _in_workspace(token: str, workspaces: Iterable[str]) -> bool:
    token = token.replace("\\", "/").rstrip("/")
    for workspace in workspaces:
        workspace = workspace.replace("\\", "/").rstrip("/")
        if workspace and (token == workspace or token.startswith(workspace + "/")):
            return True
    return False


def _workspace_pattern(token: str, run_names: Iterable[str]) -> bool:
    """An absolute path into this run's own workspace (runs/<run>/sessions/<run_id>/workspace[/...])."""
    token = token.replace("\\", "/")
    return any(re.search(rf"/runs/{re.escape(name)}/sessions/[^/]+/workspace(?:/|$)", token) for name in run_names)


def _code_flags(code: str, flags: set) -> None:
    if CODE_PATH.search(code):
        flags.add("outside-path")
    if CODE_PARENT.search(code):
        flags.add("parent-path")
    if CODE_NETWORK.search(code):
        flags.add("network")
    if re.search(r"\bpip\b", code):
        flags.add("package-tool")


def classify(command: str, workspaces: Iterable[str] = (), run_names: Iterable[str] = ()) -> List[str]:
    """The flags (FLAGS order) for one run-tool command string; empty for a command that stays in the workspace."""
    flags: set = set()
    workspaces, run_names = list(workspaces), list(run_names)
    for segment in _segments(_split(command)):
        head = _head(segment[0])
        rest = segment[1:]
        if head in PYTHON_HEADS or re.fullmatch(r"python[\d.]*(?:\.exe)?", head):
            if "-m" in rest:
                module = rest[rest.index("-m") + 1] if rest.index("-m") + 1 < len(rest) else ""
                if module in PACKAGE_TOOLS or module in {"ensurepip"}:
                    flags.add("package-tool")
                    after = rest[rest.index("-m") + 2:]
                    if after and after[0] in PACKAGE_FETCH:
                        flags.add("network")
                if module in {"http.server", "urllib.request"}:
                    flags.add("network")
            if "-c" in rest and rest.index("-c") + 1 < len(rest):
                _code_flags(rest[rest.index("-c") + 1], flags)
                rest = [t for i, t in enumerate(rest) if i != rest.index("-c") + 1]
        elif head in SHELL_HEADS and "-c" in rest and rest.index("-c") + 1 < len(rest):
            for flag in classify(rest[rest.index("-c") + 1], workspaces, run_names):
                flags.add(flag)
            rest = [t for i, t in enumerate(rest) if i != rest.index("-c") + 1]
        elif head == "git":
            flags.add("git")
            if any(token in GIT_FETCH for token in rest):
                flags.add("network")
        elif head in PACKAGE_TOOLS:
            flags.add("package-tool")
            if rest and rest[0] in PACKAGE_FETCH or any(t in {"download", "install"} for t in rest[:2]):
                flags.add("network")
        elif head in NETWORK_TOOLS:
            flags.add("network")
        if head in SCRIPT_TOOLS:  # drop the program text (-e PROGRAM, or the first operand), keep the file operands
            if "-e" in rest or "--expression" in rest:
                rest = [t for i, t in enumerate(rest) if not (i > 0 and rest[i - 1] in {"-e", "--expression"})]
            else:
                first = next((i for i, t in enumerate(rest) if not t.startswith("-")), None)
                if first is not None:
                    rest = rest[:first] + rest[first + 1:]
        for token in rest + ([segment[0]] if "/" in segment[0] or "\\" in segment[0] else []):
            values = [token] + ([token.split("=", 1)[1]] if token.startswith("-") and "=" in token else [])
            for value in values:
                if PARENT.search(value):
                    flags.add("parent-path")
                if PATH_TOKEN.match(value) and not _in_workspace(value, workspaces) \
                        and not _workspace_pattern(value, run_names):
                    flags.add("outside-path")
    return [flag for flag in FLAGS if flag in flags]


def run_commands(calls_path: Path) -> List[dict]:
    """Every `run` tool call in calls.jsonl, once per tool-call id, in order: {response, tool_call_id, command}."""
    seen, commands = set(), []
    if not calls_path.exists():
        return commands
    for line_number, line in enumerate(calls_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for choice in ((row.get("response") or {}).get("choices") or []):
            for call in ((choice.get("message") or {}).get("tool_calls") or []):
                function = call.get("function") or {}
                if function.get("name") != "run" or call.get("id") in seen:
                    continue
                seen.add(call.get("id"))
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                command = arguments.get("command") if isinstance(arguments, dict) else None
                if isinstance(command, str):
                    commands.append({"response": row.get("call_index", line_number), "line": line_number,
                                     "run_id": row.get("run_id"), "tool_call_id": call.get("id"), "command": command})
    return commands


def scan_run(run_dir: Path) -> dict:
    """{run, version, run_commands, flagged: [{response, tool_call_id, command, flags}], flag_counts}."""
    run_dir = Path(run_dir)
    commands = run_commands(run_dir / "calls.jsonl")
    workspaces = []
    sessions = run_dir / "sessions"
    if sessions.is_dir():
        workspaces = [str((path / "workspace").resolve()) for path in sessions.iterdir() if path.is_dir()]
    flagged = []
    for entry in commands:
        flags = classify(entry["command"], workspaces, [run_dir.name])
        if flags:
            flagged.append({**entry, "flags": flags})
    counts = {flag: sum(1 for entry in flagged if flag in entry["flags"]) for flag in FLAGS}
    return {"run": run_dir.name, "version": SCAN_VERSION, "run_commands": len(commands), "flagged": flagged,
            "flag_counts": {k: v for k, v in counts.items() if v}}


def summary_line(scan: dict) -> str:
    if not scan["flagged"]:
        return f"{scan['run']}: {scan['run_commands']} run commands, none reach outside the workspace"
    counts = ", ".join(f"{k} {v}" for k, v in scan["flag_counts"].items())
    return (f"{scan['run']}: FLAGGED {len(scan['flagged'])} of {scan['run_commands']} run commands ({counts}); "
            f"review the trajectory (report only, acceptance unchanged)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="print one JSON object per run")
    args = parser.parse_args(argv)
    for run_dir in args.run_dirs:
        scan = scan_run(run_dir)
        if args.json:
            print(json.dumps(scan, ensure_ascii=False))
            continue
        print(summary_line(scan))
        for entry in scan["flagged"]:
            print(f"  r{entry['response']} {entry['tool_call_id']} [{', '.join(entry['flags'])}] {entry['command'][:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
