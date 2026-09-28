"""The native reference arm: a task through Claude Code's own agent loop, scored by the Reticle runner's evaluator.

v1 (card 006) ran one upstream P6 task. v2 (card 018) runs any task of a task file exactly as the Reticle runner
`run_pilot.py` materializes and scores it, so a run of this arm pairs with the incumbent's run of the same task:

- task: `--tasks [FILE.json] TASK_ID` (run_pilot.load_tasks; exactly one task must be selected);
- workspace: run_pilot.ensure_commits and run_pilot.materialize_workspace, the runner's own functions (a mutation task
  gets its mutation_patch applied, its hidden_paths removed, and every timestamp set to the commit time; no history);
- evaluator: run_pilot.build_evaluator, acceptance_plan and AcceptanceRunner on the final workspace, in the pinned OCI
  image (`--backend auto` uses it when it exists, `oci` requires it), built only after the CLI has exited;
- opening request: run_pilot.INSTRUCTIONS with the task's repo, repo_url and statement, with the two phrases that name
  Reticle tools replaced (PROMPT_SUBSTITUTIONS) and nothing else changed. config.json records the prompt, its sha256,
  and the sha256 of the Reticle arm's opening request for the same task.

The CLI (`claude -p`, stream-json) runs on the host with v1's flags (bypassPermissions, --setting-sources "",
--no-session-persistence, --safe-mode, --strict-mcp-config, --disable-slash-commands) and `--tools` NATIVE_TOOLS.
Its init event is checked as it arrives: a tool outside NATIVE_TOOLS (WebFetch, WebSearch, Agent, ...), an MCP server,
an API key or auth token from the environment (claude_cli.auth_problem), another permission mode, or, when --model is a
full id (claude-...), another model (claude_cli.model_problem) kills the CLI at once (stop `isolation_abort`). The
models the CLI reported (init, assistant messages, result modelUsage) are recorded in result.json under model_pin.

CONFINEMENT: every CLI run gets `--settings <scratch>/cli-settings.json` (cli_settings), recorded verbatim with its
sha256 in config.json under "confinement":
  layer read_block  permissions.blockReadsOutsideWorkingDirectories: the file tools (Read, Grep, Glob) refuse paths
                    outside the working directory (the workspace);
  layer bash_deny   permissions.deny: DENY_NETWORK_COMMANDS, and the read/list commands DENY_READ_VERBS on every
                    spelling of each hidden root (this repository's checkouts, which hold the task file, the run
                    records, the evaluator bundles and the task clones; and the run's scratch entries other than the
                    workspace), for Bash and PowerShell. Pattern rules are best-effort (see DENY_NETWORK_COMMANDS);
  layer sandbox     only with --sandbox (off by default): sandbox.enabled, no allowed network domain, and
                    filesystem.denyRead over the hidden paths (sandbox_deny_read). It needs `claude sandbox install`;
                    unless `claude sandbox status` reports it installed and available, the run refuses to start.
The CLI enforces the layers; this script cannot see them work until something is denied. result.json records the layers
that were on and the denials the stream shows ("confinement"); the transcript audit below stays on either way.

LEAK CHECKS: the run refuses to start (exit 3) unless
  1. the scratch base (default %TEMP%/reticle-native-control) is outside this checkout, the main checkout that owns it,
     and the task clones (.runtime/bug-mining/repos), and contains none of them;
  2. the scratch base is on a local fixed drive: not a UNC path, not a network or removable drive, not in a OneDrive
     folder, so no network location can hold the evaluator bundle;
  3. the scratch base holds nothing but this run's directory: no earlier run's workspace, pristine copy or evaluator
     bundle (every run removes its scratch directory after scoring);
  4. the materialized workspace has none of the task's hidden_paths, no .git, and no evaluator file;
  5. the task interpreter, started outside the workspace without PYTHONPATH, cannot import the task's package (no
     installed healthy copy of the library).
Not confined (config.json, "authority"): the network (the upstream repository and the package index hold the healthy
code and its tests) and host files outside the scratch base (this repository with its task files and run records, the
task clones, caches). The transcript audit flags network commands, paths outside the workspace, parent-directory and
home/temp references, and harness markers (checkout paths, task-file field names) in tool inputs and results;
`audit_clean` is false if any flag is raised, and such a run needs a review before it counts.

Per run, native_runs/<run-name>/ holds config.json (written before the CLI starts), stream.jsonl (every CLI event with
its arrival time), stderr.txt, diff.patch and result.json; the scratch directory is removed after scoring.

`--scripted gold|noop` replaces the CLI with a scripted agent (gold: the task's gold_patch applied with git apply, or
the gold source files from fix_commit for an upstream task; noop: no change) and keeps every other step. It is the
no-model control of this path.

Usage (from the repo root):
  python experiments/session_harness/native_control.py --tasks experiments/mutation_tasks/tasks.mutations.json \\
      sqlparse-mut-001 --backend oci --run-name c018-sqlparse-mut-001-r1 [--dry-run]
  python experiments/session_harness/native_control.py --tasks experiments/mutation_tasks/tasks.mutations.json \\
      sqlparse-mut-001 --backend oci --scripted gold --run-name c018-control-gold
  python experiments/session_harness/native_control.py --tasks sqlparse-865 --backend oci --run-name pc-native-2

PORTABILITY: the task interpreter resolves on POSIX (interpreters.task_python) and PowerShell is offered only on
Windows, but the transcript audit's path patterns are Windows' (drive letters, Git Bash /c/ paths, %TEMP%): on a
POSIX host it misses absolute paths outside the workspace and flags every path under /tmp as an escape. The native
arm is not ported to POSIX; no cloud card uses it.

Exit codes: 0 scored (whatever the outcome); 2 existing run name or bad selection; 3 refused by a leak check.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import run_pilot  # noqa: E402
from claude_cli import (  # noqa: E402
    auth_problem, child_environment, cli_version, model_problem, pins_model, reported_models, resolve_executable,
)
from interpreters import task_python  # noqa: E402
from reticle.evaluation import AcceptanceRunner  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.source_edits import SOURCE_RULE_VERSION, is_source_path  # noqa: E402

NATIVE_VERSION = 2
RECORD_ROOT = HERE / "native_runs"
SCRATCH_NAME = "reticle-native-control"
EXIT_OK, EXIT_INVALID, EXIT_REFUSED = 0, 2, 3
# The CLI's coding tools. Excluded from its default set: Agent and other session/scheduling tools (sub-agents would
# spend model calls outside the matched turn budget), WebFetch/WebSearch (the most direct route to the upstream code),
# notebooks, worktrees, and skills. The init check (init_problem) enforces the set at run time.
# PowerShell is a Windows tool of the CLI; a POSIX host (a cloud VM) offers the same set without it.
NATIVE_TOOLS = "Bash,PowerShell,Read,Edit,Write,Glob,Grep" if os.name == "nt" else "Bash,Read,Edit,Write,Glob,Grep"
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
COMMAND_TOOLS = {"Bash", "PowerShell"}
PATH_KEYS = ("file_path", "path", "notebook_path")
# The Reticle arm's opening request names two Reticle tools; each phrase is replaced by the Claude Code equivalent and
# nothing else changes. Each must occur exactly once in run_pilot.INSTRUCTIONS, or the arm refuses to build a prompt.
PROMPT_SUBSTITUTIONS = (
    ("with the run tool)", "with Bash)"),
    ("Call finish when you are done.", "Stop when you are done."),
)
CLI_FAILURE_STOPS = ("cli_error", "isolation_abort")
CONFINEMENT_VERSION = "cli-settings-v1"
SETTINGS_NAME = "cli-settings.json"
# ---- CLI-enforced confinement: the one place the deny rules are defined. ----------------------------------------
# Pattern deny is best-effort. A rule matches the start of one command (the CLI splits compound commands), so
# `python -c "import urllib.request ..."`, a URL or path held in a variable, a script file, an alias, or another
# spelling of a path still gets through. The transcript audit (summarize_stream) stays on and still decides
# audit_clean; the rules only make the easy routes fail loudly.
DENY_NETWORK_COMMANDS = (
    "curl *", "wget *", "git clone *", "git fetch *", "git pull *", "pip *", "pip3 *", "python -m pip *",
    "py -m pip *", "uv pip *", "Invoke-WebRequest *", "Invoke-RestMethod *", "iwr *", "irm *",
)
# Commands that read or list a path; each is denied on every spelling of every hidden root (hidden_roots).
DENY_READ_VERBS = ("cat", "type", "head", "tail", "less", "more", "ls", "dir", "find", "grep", "rg", "Get-Content",
                   "gc", "Get-ChildItem", "gci", "Select-String")
DENY_TOOLS = ("Bash", "PowerShell")
# The run's scratch entries besides the workspace: the session store; after the CLI exits, the pristine copy and the
# evaluator bundle; and the settings file itself.
SCRATCH_HIDDEN = ("session", "pristine", "evaluator", SETTINGS_NAME)
DENIAL_TEXT = re.compile(r"permission|denied|not allowed|outside (?:of )?(?:the )?(?:allowed )?working director",
                         re.IGNORECASE)
NETWORK_PATTERN = re.compile(
    r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|pip3?\s+install|pip\s+download|git\s+clone|"
    r"git\s+fetch|git\s+pull|npm\s+install)\b|https?://", re.IGNORECASE)
ABSOLUTE_PATH = re.compile(r"(?:(?<!\w)[A-Za-z]:[\\/]|(?<![\w.:/])/[a-z]/)[^\s\"'`|;&<>]*")  # not URLs
# References that leave the workspace without an absolute path: a parent-directory step, the home or temp folders.
ESCAPE_PATTERN = re.compile(
    r"(?<![\w.])\.\.(?=[\\/\s\"';&|)]|$)"
    r"|(?<![\w$~])~(?=[\\/\s\"']|$)"
    r"|(?<![\w.])/tmp\b"
    r"|%(?:USERPROFILE|HOMEPATH|HOMEDRIVE|TEMP|TMP|APPDATA|LOCALAPPDATA)%"
    r"|\$env:(?:USERPROFILE|HOMEPATH|HOMEDRIVE|HOME|TEMP|TMP|APPDATA|LOCALAPPDATA)\b"
    r"|\$\{?(?:HOME|TMPDIR|TEMP|TMP|USERPROFILE)\b", re.IGNORECASE)
# Words that occur in the harness's task files, run records and layout, not in the task repository.
HARNESS_MARKERS = ("mutation_patch", "gold_patch", "gold_source_files", "hidden_paths", "fail_to_pass", "pass_to_pass",
                   "tasks.mutations", "evaluate_task", "bug-mining", "native_runs", "p6_pilot", "session_harness")
CACHE_EXCLUDES = "__pycache__/\n.pytest_cache/\n*.pyc\n"
LEAK_CHECKS = (
    "scratch base outside every checkout of this repository and the task clones, and containing none of them",
    "scratch base on a local fixed drive (not UNC, network, removable, or OneDrive)",
    "scratch base holds nothing but this run's directory (no earlier workspace, pristine copy, or evaluator bundle)",
    "workspace without the task's hidden_paths, .git, or evaluator files",
    "task interpreter, outside the workspace and without PYTHONPATH, cannot import the task's package",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def checkout_roots() -> List[Path]:
    """This checkout, then the main checkout that owns it when this is a git worktree."""
    roots = [ROOT.resolve()]
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if common.returncode == 0 and common.stdout.strip():
        main = (ROOT / common.stdout.strip()).resolve().parent
        if main not in roots:
            roots.append(main)
    return roots


def task_interpreter() -> Path:
    """The runner's task interpreter (.runtime/bugs-venv) of this checkout, else of the main checkout."""
    candidates = [run_pilot.TASK_PYTHON] + [task_python(root) for root in checkout_roots()[1:]]
    return next((path for path in candidates if path.exists()), run_pilot.TASK_PYTHON)


def interpreter_roots(interpreter: Path) -> tuple:
    """The task interpreter's environment and the base Python it was made from (pyvenv.cfg `home`): the only places
    outside the workspace the audit accepts, since tracebacks, `which python` and stdlib reads name them."""
    environment = interpreter.parent.parent
    roots = [environment]
    config = environment / "pyvenv.cfg"
    if config.exists():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home" and value.strip():
                roots.append(Path(value.strip()))
    return tuple(roots)


def scratch_base(scratch_root: Optional[str] = None) -> Path:
    return Path(scratch_root or tempfile.gettempdir()).resolve() / SCRATCH_NAME


def reticle_opening_request(task: dict) -> str:
    """What the Reticle arm sends as the task (run_pilot's TaskEnvelope description)."""
    return run_pilot.INSTRUCTIONS.format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"])


def native_instructions(template: Optional[str] = None) -> str:
    text = run_pilot.INSTRUCTIONS if template is None else template
    for old, new in PROMPT_SUBSTITUTIONS:
        if text.count(old) != 1:
            raise SystemExit(f"run_pilot.INSTRUCTIONS contains {old!r} {text.count(old)} times, not once; "
                             "the native prompt would not be the Reticle request with only the tool phrases replaced")
        text = text.replace(old, new)
    return text


def opening_prompt(task: dict) -> str:
    return native_instructions().format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"])


def native_arguments(model: str, max_turns: int, tools: str = NATIVE_TOOLS, settings: Optional[Path] = None) -> list:
    """v1's flags, plus `--settings FILE` (the confinement) when given. --setting-sources "" drops the user, project
    and local settings files; a --settings file is loaded on top (as the CLI's help says for --restricted)."""
    arguments = ["-p", "--model", model, "--max-turns", str(max_turns), "--permission-mode", "bypassPermissions",
                 "--output-format", "stream-json", "--verbose", "--setting-sources", "", "--no-session-persistence",
                 "--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--tools", tools]
    return arguments + (["--settings", str(settings)] if settings is not None else [])


def hidden_roots(scratch: Path) -> List[Path]:
    """Path prefixes the agent must not read: each checkout of this repository (the task clones, task files, run
    records and evaluator bundles are under the main one) and the run's scratch entries other than the workspace.
    The scratch base as a whole is not listed, because the workspace is inside it; leak check 3 keeps other runs'
    directories out of it instead."""
    return [*checkout_roots(), *(scratch / name for name in SCRATCH_HIDDEN)]


def deny_rules(scratch: Path) -> List[str]:
    """DENY_NETWORK_COMMANDS, and each read verb on each spelling of each hidden root (a spelling that another one
    already covers as a prefix, such as a worktree under the main checkout's name, is left out), for each tool."""
    forms = [form for root in hidden_roots(scratch) for form in path_forms(root)]
    forms = [form for form in dict.fromkeys(forms)
             if not any(other != form and form.lower().startswith(other.lower()) for other in forms)]
    rules = []
    for tool in DENY_TOOLS:
        rules += [f"{tool}({command})" for command in DENY_NETWORK_COMMANDS]
        rules += [f"{tool}({verb} {form}*)" for form in forms for verb in DENY_READ_VERBS]
    return rules


def sandbox_deny_read(scratch: Path) -> List[str]:
    """What the OS sandbox denies reading. Not the checkout roots themselves: the task interpreter and the Python it
    was made from live in the main checkout's .runtime. So: every top-level entry of each checkout except .runtime,
    .runtime's task clones, and the run's scratch entries other than the workspace."""
    paths = []
    for root in checkout_roots():
        if root.is_dir():
            paths += [entry for entry in sorted(root.iterdir()) if entry.name != ".runtime"]
        paths.append(root / ".runtime" / "bug-mining")
    paths += [scratch / name for name in SCRATCH_HIDDEN]
    return [str(path) for path in dict.fromkeys(paths)]


def cli_settings(scratch: Path, sandbox: bool = False) -> dict:
    """The --settings JSON of one run (CONFINEMENT in the module docstring)."""
    settings = {"permissions": {"blockReadsOutsideWorkingDirectories": True, "deny": deny_rules(scratch)}}
    if sandbox:
        settings["sandbox"] = {"enabled": True, "network": {"allowedDomains": []},
                               "filesystem": {"denyRead": sandbox_deny_read(scratch)}}
    return settings


def settings_text(settings: dict) -> str:
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def confinement_layers(sandbox: bool) -> dict:
    return {"read_block": True, "bash_deny": True, "sandbox": bool(sandbox)}


def sandbox_status(executable: Optional[str]) -> dict:
    """`claude sandbox status` (one JSON line; no model call), or {"error": ...}."""
    if executable is None:
        return {"error": "claude is not on PATH"}
    try:
        completed = subprocess.run([executable, "sandbox", "status"], capture_output=True, text=True, timeout=60,
                                   env=child_environment()[0])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": repr(exc)}
    for line in reversed(completed.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"error": f"no JSON from `claude sandbox status` (exit {completed.returncode}): "
                     f"{(completed.stdout + completed.stderr).strip()[-300:]}"}


def sandbox_problem(status: Optional[dict]) -> Optional[str]:
    """Why --sandbox cannot be honoured, or None. The setting alone confines nothing: the install
    (`claude sandbox install`) must be present and the sandbox available."""
    status = status or {"error": "not checked"}
    if status.get("error"):
        return f"sandbox status unknown: {status['error']}"
    if not status.get("installed"):
        return "the CLI sandbox is not installed (run `claude sandbox install` first); --sandbox refuses to start"
    if not status.get("available"):
        reasons = status.get("reasons") or status.get("unavailableReason")
        return f"the CLI sandbox is installed but not available: {reasons}"
    return None


def init_problem(init: dict, model: Optional[str] = None) -> Optional[str]:
    """Why the CLI's init event shows a configuration other than the arm's, or None. With a full model id, the init
    event must report exactly that model (an alias is not checked)."""
    tools, allowed = set(init.get("tools") or []), set(NATIVE_TOOLS.split(","))
    if tools != allowed:
        return f"CLI tools {sorted(tools)} are not {sorted(allowed)}"
    if init.get("mcp_servers"):
        return f"MCP servers present: {init.get('mcp_servers')}"
    problem = auth_problem(init)
    if problem:
        return problem
    if init.get("permissionMode") not in (None, "bypassPermissions"):
        return f"permission mode {init.get('permissionMode')!r}"
    if model is not None:
        return model_problem(model, reported_models(init, None))
    return None


def stream_models(events: list) -> dict:
    """The models a recorded stream reports (claude_cli.reported_models over the init, assistant and result events)."""
    init = result = None
    messages: List[str] = []
    for record in events:
        event = record.get("event") or {}
        if event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "result":
            result = event
        elif event.get("type") == "assistant":
            name = (event.get("message") or {}).get("model")
            if name and name not in messages:
                messages.append(name)
    return reported_models(init, result, messages)


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def network_location(path: Path) -> Optional[str]:
    """Why a directory could be reached over a network or a sync service, or None for a local fixed drive."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return "a UNC (network) path"
    if os.name == "nt":
        import ctypes
        drive = os.path.splitdrive(text)[0]
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        if kind != 3:  # DRIVE_FIXED; 4 is DRIVE_REMOTE, 2 removable
            return f"on drive {drive} of type {kind}, not a local fixed drive"
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        synced = os.environ.get(name)
        if synced and _within(path, Path(synced).resolve()):
            return f"inside {name} ({synced}), a cloud-synced folder"
    return None


def location_problems(base: Path, run_name: str) -> List[str]:
    """Leak checks 1-3, before anything is materialized."""
    problems = []
    for root in [*checkout_roots(), run_pilot.REPOS.resolve()]:
        if _within(base, root) or _within(root, base):
            problems.append(f"scratch base {base} and {root} overlap: the workspace would sit inside, or contain, "
                            "harness material")
    where = network_location(base)
    if where:
        problems.append(f"scratch base {base} is {where}")
    if base.exists():
        others = sorted(entry.name for entry in base.iterdir() if entry.name != run_name)
        if others:
            problems.append(f"{base} holds other runs' directories ({', '.join(others)}); an earlier workspace, "
                            "pristine copy or evaluator bundle there is reachable from this run's workspace. "
                            "Remove them first")
    return problems


def task_packages(task: dict) -> List[str]:
    """The top-level packages or modules the task's fix touches (from gold_source_files and mutation_file)."""
    names = set()
    for path in [*(task.get("gold_source_files") or []), task.get("mutation_file") or ""]:
        parts = PurePosixPath(path).parts
        if parts[:1] == ("src",):
            parts = parts[1:]
        if len(parts) > 1:
            names.add(parts[0])
        elif len(parts) == 1 and parts[0].endswith(".py"):
            names.add(parts[0][:-3])
    return sorted(names)


def workspace_problems(task: dict, workspace: Path, interpreter: Path, base: Path) -> List[str]:
    """Leak checks 4-5, on the materialized workspace, before the CLI starts."""
    problems = [f"hidden path {name!r} is in the workspace" for name in task.get("hidden_paths") or []
                if (workspace / name).exists()]
    if (workspace / ".git").exists():
        problems.append("the workspace has a .git directory")
    problems += [f"evaluator file in the workspace: {path.relative_to(workspace).as_posix()}"
                 for path in workspace.rglob("evaluate_task.py")]
    packages = task_packages(task)
    if not packages:
        return problems
    if not interpreter.exists():
        return problems + [f"task interpreter {interpreter} not found: cannot check for an installed copy "
                           f"of {packages}"]
    environment = child_environment()[0]
    environment.pop("PYTHONPATH", None)
    code = ("import importlib.util, json, sys; "
            "print(json.dumps({n: getattr(importlib.util.find_spec(n), 'origin', None) for n in sys.argv[1:]}))")
    completed = subprocess.run([str(interpreter), "-c", code, *packages], cwd=str(base), env=environment,
                               capture_output=True, text=True, timeout=120)
    if completed.returncode:
        return problems + [f"installed-copy check failed: {completed.stderr.strip()[-300:]}"]
    installed = {name: origin for name, origin in json.loads(completed.stdout).items() if origin}
    if installed:
        problems.append(f"the task interpreter imports an installed copy of the task's package: {installed}")
    return problems


def workspace_files(workspace: Path) -> set:
    return {path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()}


def path_forms(path: Path) -> List[str]:
    """A directory as a tool input or output may spell it: native, forward slashes, and Git Bash (/c/...)."""
    posix = path.as_posix()
    forms = {str(path), posix}
    if re.match(r"^[A-Za-z]:/", posix):
        forms.add(f"/{posix[0].lower()}/{posix[3:]}")
    return sorted(forms, key=len, reverse=True)


def leak_markers() -> list:
    """(label, pattern) pairs whose appearance in a tool input or result points at harness material."""
    markers = [(word, re.compile(re.escape(word), re.IGNORECASE)) for word in HARNESS_MARKERS]
    for root in checkout_roots():
        markers += [(f"checkout path {root}", re.compile(re.escape(form), re.IGNORECASE)) for form in path_forms(root)]
    return markers


def kill_tree(process: subprocess.Popen) -> None:
    """Stop the CLI and every process it started (only processes this script launched)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)


def run_cli(argv: list, prompt: str, cwd: Path, env: dict, wall_seconds: float, stream_path: Path,
            stderr_path: Path, check_init=None) -> dict:
    """Run the CLI with a hard wall-clock cap, recording each stdout line with its arrival time.

    check_init(event) is called on the init event; a returned reason kills the CLI at once (`aborted`)."""
    events: list = []
    aborted: list = []
    start = time.monotonic()
    with stream_path.open("w", encoding="utf-8") as sink, stderr_path.open("wb") as err:
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=err, start_new_session=(os.name != "nt"))

        def pump():
            for raw in iter(process.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = None
                if not isinstance(event, dict):
                    event = {"unparsed": line}
                record = {"t": round(time.monotonic() - start, 2), "event": event}
                events.append(record)
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                if (check_init is not None and not aborted
                        and event.get("type") == "system" and event.get("subtype") == "init"):
                    try:
                        problem = check_init(event)
                    except Exception as exc:  # a malformed init event is a failed check, not a stalled reader
                        problem = f"init check failed: {exc!r}"
                    if problem:
                        aborted.append(problem)
                        kill_tree(process)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
        except OSError:  # the CLI exited (or was stopped) before reading the prompt
            pass
        timed_out = False
        try:
            process.wait(timeout=wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(process)
            process.wait()
        reader.join(timeout=30)
    return {"timed_out": timed_out, "exit_code": process.returncode, "aborted": aborted[0] if aborted else None,
            "wall_seconds": round(time.monotonic() - start, 1), "events": events}


def _inside(path_text: str, workspace: Path) -> bool:
    text = path_text.strip().strip("\"'")
    if re.match(r"^/[a-z]/", text):  # Git Bash form of a Windows drive path
        text = f"{text[1]}:/{text[3:]}"
    try:
        resolved = (workspace / text).resolve() if not os.path.isabs(text) else Path(text).resolve()
        resolved.relative_to(workspace.resolve())
        return True
    except (ValueError, OSError):
        return False


def _content_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return "" if content is None else str(content)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def summarize_stream(events: list, workspace: Path, base_files: set, allowed_roots: tuple = (),
                     markers: tuple = ()) -> dict:
    """Responses, tool calls, first actions, and the leak audit, from the CLI's stream-json events.

    base_files: workspace-relative POSIX paths present before the run; allowed_roots: directories outside the
    workspace the audit accepts (the task interpreter's environment); markers: (label, pattern) pairs (leak_markers).
    """
    init = next((r["event"] for r in events if r["event"].get("type") == "system"
                 and r["event"].get("subtype") == "init"), None)
    result = next((r["event"] for r in reversed(events) if r["event"].get("type") == "result"), None)
    response_ids, uses, results, outputs = [], [], {}, {}
    for record in events:
        event = record["event"]
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            if message.get("id") not in response_ids:
                response_ids.append(message.get("id"))
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    uses.append({"response": response_ids.index(message.get("id")) + 1, "seconds": record["t"],
                                 "id": block.get("id"), "name": block.get("name"), "input": block.get("input") or {}})
        elif event.get("type") == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[block.get("tool_use_id")] = bool(block.get("is_error"))
                    outputs[block.get("tool_use_id")] = _content_text(block.get("content"))
    for use in uses:
        use["is_error"] = results.get(use["id"])

    def allowed(path_text):
        return _inside(path_text, workspace) or any(_inside(path_text, root) for root in allowed_roots)

    def relative(use):
        for key in PATH_KEYS:
            value = use["input"].get(key)
            if isinstance(value, str) and _inside(value, workspace):
                full = (workspace / value).resolve() if not os.path.isabs(value) else Path(value).resolve()
                return full.relative_to(workspace.resolve()).as_posix()
        return None

    def first(predicate):
        hit = next((u for u in uses if predicate(u)), None)
        return None if hit is None else {"response": hit["response"], "seconds": hit["seconds"], "tool": hit["name"]}

    def edit_of(use, paths):
        return use["name"] in EDIT_TOOLS and use["is_error"] is False and relative(use) in paths

    # Paths under an allowed root (the task interpreter's environment, which lives in the main checkout's .runtime)
    # are masked before the marker search: tracebacks and `which python` name them legitimately.
    masks = [re.compile(re.escape(form), re.IGNORECASE) for root in allowed_roots for form in path_forms(Path(root))]

    def masked(text):
        for mask in masks:
            text = mask.sub("<allowed-root>", text)
        return text

    outside, network, escapes, marker_hits = [], [], [], []
    for use in uses:
        for key in PATH_KEYS:
            value = use["input"].get(key)
            if isinstance(value, str) and not allowed(value):
                outside.append({"response": use["response"], "tool": use["name"], key: value})
        command = use["input"].get("command")
        if isinstance(command, str):
            if NETWORK_PATTERN.search(command):
                network.append({"response": use["response"], "tool": use["name"], "command": command[:300]})
            for path_text in ABSOLUTE_PATH.findall(command):
                if not allowed(path_text):
                    outside.append({"response": use["response"], "tool": use["name"], "command_path": path_text})
        inputs = list(_strings(use["input"]))
        # Commands and path arguments only: file contents (Edit/Write) legitimately hold `..` (relative imports) or `~`.
        where_to = [use["input"].get(key) for key in ("command", *PATH_KEYS)]
        if use["name"] == "Glob":
            where_to.append(use["input"].get("pattern"))
        escape = next((text for text in where_to if isinstance(text, str) and ESCAPE_PATTERN.search(text)), None)
        if escape is not None:
            escapes.append({"response": use["response"], "tool": use["name"], "text": escape[:300]})
        result_text = masked(outputs.get(use["id"]) or "")
        for where, texts in (("input", [masked(text) for text in inputs]), ("result", [result_text])):
            for label, pattern in markers:
                if any(pattern.search(text) for text in texts):
                    marker_hits.append({"response": use["response"], "tool": use["name"], "where": where,
                                        "marker": label})
    by_name: dict = {}
    for use in uses:
        by_name[use["name"]] = by_name.get(use["name"], 0) + 1
    commands = [u for u in uses if u["name"] in COMMAND_TOOLS]
    denied = [{"response": u["response"], "tool": u["name"], "input": json.dumps(u["input"], ensure_ascii=False)[:200],
               "result": (outputs.get(u["id"]) or "")[:200]}
              for u in uses if u["is_error"] and DENIAL_TEXT.search(outputs.get(u["id"]) or "")]
    source_files = {path for path in base_files if is_source_path(path)}
    audit = {"paths_outside_workspace": outside, "network_commands": network, "escape_references": escapes,
             "harness_markers": marker_hits,
             "tools_outside_allowed_set": sorted(set(by_name) - set(NATIVE_TOOLS.split(",")))}
    return {
        "init": None if init is None else {k: init.get(k) for k in (
            "model", "tools", "mcp_servers", "apiKeySource", "permissionMode", "claude_code_version", "skills",
            "slash_commands", "cwd")},
        "result": None if result is None else {k: result.get(k) for k in (
            "subtype", "is_error", "num_turns", "stop_reason", "terminal_reason", "duration_ms", "duration_api_ms",
            "total_cost_usd", "usage", "permission_denials", "result")},
        "responses": len(response_ids),
        "tool_calls": len(uses),
        "tool_calls_by_name": by_name,
        "tool_errors": sum(1 for u in uses if u["is_error"]),
        "first_command": first(lambda u: u["name"] in COMMAND_TOOLS),
        "ran_command": bool(commands),
        "first_base_file_edit": first(lambda u: edit_of(u, base_files)),
        "first_source_edit": first(lambda u: edit_of(u, source_files)),
        "source_rule": SOURCE_RULE_VERSION,
        "first_any_edit": first(lambda u: u["name"] in EDIT_TOOLS and u["is_error"] is False),
        "test_commands": sum(1 for u in commands if "pytest" in (u["input"].get("command") or "")),
        "edited_files": sorted({relative(u) or str(u["input"].get("file_path"))
                                for u in uses if u["name"] in EDIT_TOOLS and u["is_error"] is False}),
        "audit": audit,
        "audit_clean": not any(audit.values()),
        "denied_calls": denied,
        "permission_denials": (result or {}).get("permission_denials") or [],
        "tool_sequence": [{"response": u["response"], "seconds": u["seconds"], "tool": u["name"],
                           "is_error": u["is_error"], "input": json.dumps(u["input"], ensure_ascii=False)[:200]}
                          for u in uses],
    }


def stop_for(run: dict, summary: dict, scripted: Optional[str]) -> str:
    """How the agent step ended: scripted, isolation_abort, wall_cap, max_turns, end_turn, or cli_error."""
    if scripted:
        return "scripted"
    if run.get("aborted"):
        return "isolation_abort"
    if run.get("timed_out"):
        return "wall_cap"
    result = summary.get("result")
    if result is None:
        return "cli_error"
    if result.get("subtype") == "error_max_turns":
        return "max_turns"
    if result.get("is_error"):
        return "cli_error"
    return "end_turn"


def scripted_agent(kind: str, task: dict, repo: Path, workspace: Path) -> dict:
    """The no-model stand-in for the CLI: gold applies the task's fix as an agent's edits would; noop changes
    nothing."""
    if kind == "noop":
        return {"kind": "noop", "changed": []}
    if task.get("gold_patch"):
        run_pilot.apply_mutation(workspace, task["gold_patch"])  # git apply, then git apply --reverse --check
        changed = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", task["gold_patch"], re.MULTILINE)))
        return {"kind": "gold", "applied": "the task's gold_patch (git apply)", "changed": changed}
    for path in task["gold_source_files"]:
        (workspace / path).parent.mkdir(parents=True, exist_ok=True)
        (workspace / path).write_bytes(run_pilot.git(repo, "show", f"{task['fix_commit']}:{path}"))
    return {"kind": "gold", "applied": "gold_source_files from fix_commit",
            "changed": sorted(task["gold_source_files"])}


def workspace_diff(pristine: Path, workspace: Path) -> dict:
    """`git diff --stat` of the final workspace against an untouched materialization of the same task.

    The git directory lives in the pristine copy, never in the workspace; cache files are excluded.
    """
    git = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
           "-c", "user.name=native-control", "-c", "user.email=native-control@localhost"]
    subprocess.run([*git, "init", "-q", str(pristine)], check=True)
    (pristine / ".git" / "info" / "exclude").write_text(CACHE_EXCLUDES, encoding="utf-8")
    subprocess.run([*git, "-C", str(pristine), "add", "-A", "-f"], check=True)
    subprocess.run([*git, "-C", str(pristine), "commit", "-q", "-m", "base"], check=True)
    tree = [*git, f"--git-dir={pristine / '.git'}", f"--work-tree={workspace}"]

    def out(*args):
        return subprocess.run([*tree, *args], capture_output=True, check=True).stdout.decode("utf-8", "replace")

    out("read-tree", "HEAD")  # no cached stat data: add hashes every file (the materializer gives equal mtimes)
    out("add", "-A")
    ignored = [line[3:] for line in out("status", "--porcelain", "--ignored").splitlines()
               if line.startswith("!! ") and not any(part in line for part in ("__pycache__", ".pytest_cache", ".pyc"))]
    return {"stat": out("diff", "--cached", "--stat"), "numstat": out("diff", "--cached", "--numstat"),
            "patch": out("diff", "--cached"), "ignored_untracked": ignored}


def criterion_counts(expected_ids, criterion: Optional[dict]) -> dict:
    """Expected, passed, failing, missing and skipped tests of one evaluator criterion."""
    expected = len(expected_ids or [])
    if criterion is None:
        return {"expected": expected, "passed": None}
    failing, missing, skipped = (len(criterion.get(key) or []) for key in ("failing", "missing", "skipped"))
    return {"expected": expected, "passed": expected - failing - missing - skipped, "failing": failing,
            "missing": missing, "skipped": skipped}


def evaluator_test_counts(task: dict, details: dict) -> dict:
    criteria = details.get("criteria") or {}
    return {"fail-to-pass": criterion_counts(task.get("fail_to_pass"), criteria.get("fail-to-pass")),
            "pass-to-pass": criterion_counts(task.get("pass_to_pass"), criteria.get("pass-to-pass"))}


def remove_tree(path: Path, attempts: int = 3) -> Optional[str]:
    """Delete a directory tree (read-only git objects included); None when it is gone, else the error."""
    def clear_readonly(function, target, _info):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    error = None
    for attempt in range(attempts):
        if not path.exists():
            return None
        try:
            shutil.rmtree(path, onexc=clear_readonly)
        except OSError as exc:
            error = repr(exc)
            time.sleep(1 + attempt)
    return None if not path.exists() else (error or "still present")


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", nargs="+", required=True, metavar="FILE.json|TASK_ID",
                        help="an argument ending in .json names the task file (default experiments/p6_pilot/"
                             "tasks.json); the other selects the one task to run")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--wall-seconds", type=float, default=1200.0)
    parser.add_argument("--backend", default="auto", choices=["auto", "oci", "trusted-local"],
                        help="evaluator backend; auto = the pinned OCI image when it exists, else trusted-local")
    parser.add_argument("--oci-image", default=run_pilot.DEFAULT_OCI_IMAGE)
    parser.add_argument("--pytest-timeout", type=int, default=600)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--scratch-root", default=None,
                        help=f"parent of the scratch base {SCRATCH_NAME}/ (default: the system temp folder)")
    parser.add_argument("--scripted", choices=["gold", "noop"], default=None,
                        help="no CLI: a scripted agent stands in (the no-model control of this path)")
    parser.add_argument("--sandbox", action="store_true",
                        help="add the CLI's OS sandbox to the settings (no network, denyRead over hidden paths); needs "
                             "`claude sandbox install` and refuses to start without an installed, available sandbox")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def resolve_backend(name: str, image: str):
    if name != "auto":
        return run_pilot.resolve_execution(name, image)
    try:
        return run_pilot.resolve_execution("oci", image)
    except (SystemExit, OSError, RuntimeError) as exc:
        backend, execution = run_pilot.resolve_execution("trusted-local", image)
        return backend, dict(execution, fallback=f"OCI unavailable: {exc}")


def main(argv=None) -> int:
    args = parse_arguments(argv)
    task_file, tasks = run_pilot.load_tasks(args.tasks)
    if len(tasks) != 1:
        print(f"--tasks must select exactly one task, not {len(tasks)}", file=sys.stderr)
        return EXIT_INVALID
    task = tasks[0]
    backend, execution = resolve_backend(args.backend, args.oci_image)
    interpreter = task_interpreter()
    executable = None
    if args.scripted is None:
        executable = resolve_executable("claude")
        if executable is None:
            raise SystemExit("claude is not on PATH")
    record_dir = RECORD_ROOT / args.run_name
    base = scratch_base(args.scratch_root)
    scratch = base / args.run_name
    workspace, pristine, bundle = scratch / "workspace", scratch / "pristine", scratch / "evaluator"
    prompt = opening_prompt(task)
    settings_path = scratch / SETTINGS_NAME
    arguments = native_arguments(args.model, args.max_turns, settings=settings_path)
    settings = cli_settings(scratch, sandbox=args.sandbox)
    status = sandbox_status(executable or resolve_executable("claude")) if args.sandbox else None
    config = {
        "native_version": NATIVE_VERSION, "run_name": args.run_name, "task_id": task["task_id"],
        "task_file": run_pilot.task_file_record(task_file), "task_contract": run_pilot.task_contract(task),
        "materializer": "run_pilot.ensure_commits + run_pilot.materialize_workspace "
                        f"({run_pilot.MATERIALIZER_VERSION} for a mutation task)",
        "model": args.model,
        "cli_version": None if args.scripted else cli_version(),
        "arguments": None if args.scripted else arguments,
        "scripted": None if args.scripted is None else {
            "kind": args.scripted, "replaces": "the CLI step only; every other step is the native arm's"},
        "prompt": prompt, "prompt_sha256": sha256_text(prompt),
        "prompt_source": "run_pilot.INSTRUCTIONS with prompt_substitutions applied, formatted with the task's repo, "
                         "repo_url and statement; sent on stdin as the whole user message",
        "prompt_substitutions": [list(pair) for pair in PROMPT_SUBSTITUTIONS],
        "native_instructions_sha256": sha256_text(native_instructions()),
        "reticle_opening_request_sha256": sha256_text(reticle_opening_request(task)),
        "reticle_instructions_sha256": sha256_text(run_pilot.INSTRUCTIONS),
        "allowed_tools": NATIVE_TOOLS,
        "confinement": {
            "version": CONFINEMENT_VERSION, "layers": confinement_layers(args.sandbox),
            "settings_file": str(settings_path), "settings_text": settings_text(settings),
            "settings_sha256": sha256_text(settings_text(settings)), "sandbox_status": status,
            "enforced_by": "the CLI (--settings); pattern deny is best-effort; the transcript audit stays on",
            "confirmed": "not observable before a denial; see result.json confinement",
        },
        "init_check": ("tools == allowed_tools, no MCP server, apiKeySource not a key or token from the environment, "
                       "bypassPermissions" + (", model == --model" if pins_model(args.model) else "") + "; else killed"),
        "budgets": {"max_turns": args.max_turns, "wall_seconds": args.wall_seconds, "enforcement":
                    "--max-turns in the CLI; hard kill of the CLI process tree at the wall cap"},
        "scratch_base": str(base), "workspace": str(workspace), "execution": execution,
        "pytest_timeout_seconds": args.pytest_timeout, "task_interpreter": str(interpreter),
        "audit_allowed_roots": [str(root) for root in interpreter_roots(interpreter)],
        "environment_added": {"PATH": f"{interpreter.parent} (prepended)", "PYTHONPATH": "workspace (its src/ if any)",
                              "PYTHONIOENCODING": "utf-8", "OMP/MKL/OPENBLAS_NUM_THREADS": "1"},
        "authority": {
            "cli": "host process with bypassPermissions (not isolated); cwd = the workspace",
            "network": "available to the CLI and every command it runs; cannot be disabled here",
            "host_files": "readable and writable outside the workspace; this repository (task files, run records), "
                          "the task clones and caches are not hidden from it",
            "leak_checks": list(LEAK_CHECKS),
        },
        "evaluator": "run_pilot.build_evaluator + acceptance_plan + AcceptanceRunner on the final workspace, "
                     "the bundle built only after the agent step",
    }
    print(json.dumps({k: v for k, v in config.items() if k != "prompt"}, indent=2))
    if args.dry_run:
        print(prompt)
        return EXIT_OK
    if record_dir.exists() or scratch.exists():
        print(f"{record_dir} or {scratch} exists; use a new --run-name", file=sys.stderr)
        return EXIT_INVALID
    problems = location_problems(base, args.run_name)
    if args.sandbox and sandbox_problem(status):
        problems.append(sandbox_problem(status))
    if problems:
        print(json.dumps({"refused": args.run_name, "leak_checks": problems}, indent=2))
        return EXIT_REFUSED
    repo = run_pilot.ensure_commits(task)
    run_pilot.materialize_workspace(task, repo, workspace)
    problems = workspace_problems(task, workspace, interpreter, base)
    if problems:
        remove_tree(scratch)
        print(json.dumps({"refused": args.run_name, "leak_checks": problems}, indent=2))
        return EXIT_REFUSED
    base_files = workspace_files(workspace)
    settings_path.write_text(settings_text(settings), encoding="utf-8")  # a sibling of the workspace, never inside it
    record_dir.mkdir(parents=True)
    runtime = LocalRuntime(scratch / "session", workspace)
    initial_revision = runtime.workspace.revision()
    config.update(created_at=utc_now(), source_revision=run_pilot.source_revision(),
                  initial_workspace_revision=initial_revision, leak_checks_passed=list(LEAK_CHECKS),
                  base_file_count=len(base_files))
    (record_dir / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    src = workspace / "src"
    environment, removed = child_environment({
        "PATH": str(interpreter.parent) + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONPATH": str(src if src.is_dir() else workspace), "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    })
    started_at = utc_now()
    scripted = None
    if args.scripted:
        began = time.monotonic()
        scripted = scripted_agent(args.scripted, task, repo, workspace)
        (record_dir / "stream.jsonl").write_text("", encoding="utf-8")
        (record_dir / "stderr.txt").write_text("", encoding="utf-8")
        run = {"timed_out": False, "exit_code": None, "aborted": None,
               "wall_seconds": round(time.monotonic() - began, 1), "events": []}
    else:
        print(f"running the CLI in {workspace} (wall cap {args.wall_seconds:.0f} s, max turns {args.max_turns})",
              flush=True)
        run = run_cli([executable, *arguments], prompt, workspace, environment, args.wall_seconds,
                      record_dir / "stream.jsonl", record_dir / "stderr.txt",
                      check_init=lambda event: init_problem(event, args.model))
    summary = summarize_stream(run["events"], workspace, base_files, allowed_roots=interpreter_roots(interpreter),
                               markers=tuple(leak_markers()))
    stop = stop_for(run, summary, args.scripted)
    run_pilot.materialize_workspace(task, repo, pristine)  # after the agent step, so the CLI never sees a second tree
    diff = workspace_diff(pristine, workspace)
    (record_dir / "diff.patch").write_text(diff["patch"], encoding="utf-8")

    # The evaluator bundle holds the fix commit's tests: built only now that the agent step is over.
    version = run_pilot.build_evaluator(task, repo, bundle, args.pytest_timeout, execution["guest_python"])
    decision = AcceptanceRunner(runtime, backend).evaluate(
        run_pilot.acceptance_plan(task, version), evaluator_root=bundle, timeout_seconds=args.pytest_timeout + 120)
    details = run_pilot.evaluator_details(runtime, decision.report_artifact_id)
    record = {
        "run_name": args.run_name, "task_id": task["task_id"], "model": args.model, "native_version": NATIVE_VERSION,
        "scripted": scripted, "started_at": started_at, "finished_at": utc_now(),
        "wall_seconds": run["wall_seconds"], "timed_out": run["timed_out"], "exit_code": run["exit_code"],
        "aborted": run["aborted"], "stop": stop, "cli_failure": stop in CLI_FAILURE_STOPS,
        "turns_used": (summary["result"] or {}).get("num_turns"), "removed_environment": removed, **summary,
        "cost_estimate_usd": (summary["result"] or {}).get("total_cost_usd"),
        "model_pin": None if args.scripted else {
            "requested": args.model, "pinned": pins_model(args.model), "reported": stream_models(run["events"]),
            "violation": model_problem(args.model, stream_models(run["events"]))},
        "confinement": {"layers": confinement_layers(args.sandbox),
                        "settings_sha256": sha256_text(settings_text(settings)),
                        "denials": len(summary["denied_calls"]) + len(summary["permission_denials"]),
                        "observed_active": bool(summary["denied_calls"] or summary["permission_denials"])},
        "diff_stat": diff["stat"], "diff_numstat": diff["numstat"],
        "ignored_untracked_files": diff["ignored_untracked"],
        "initial_workspace_revision": initial_revision, "evaluator_version": version,
        "acceptance": {"status": decision.status, "criterion_outcomes": decision.criterion_outcomes,
                       "report_artifact_id": decision.report_artifact_id,
                       "test_counts": evaluator_test_counts(task, details), **details},
        "billing": "unknown (local Claude Code subscription login); cost_estimate_usd is the CLI's list-price estimate",
    }
    # Workspace, pristine copy, evaluator bundle and session store go, so no later run can find them.
    record["scratch_removal_error"] = remove_tree(scratch)
    (record_dir / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("stop", "wall_seconds", "turns_used", "responses", "tool_calls",
                                              "tool_calls_by_name", "first_base_file_edit", "ran_command",
                                              "audit_clean", "confinement", "cost_estimate_usd")}, indent=2))
    print(json.dumps({k: record["acceptance"][k] for k in ("status", "criterion_outcomes", "test_counts")}, indent=2))
    print(diff["stat"])
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
