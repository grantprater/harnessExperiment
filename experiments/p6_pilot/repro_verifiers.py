"""Card 021's realistic verifier: write one reproduction test per task before the campaign, and score it offline.

generate  For each task, the pre-edit workspace (the tree the agent starts from: mutation applied, test roots
          removed, no git history) is materialized in a temporary directory outside the repository, and one headless
          `claude -p` process (the card's pinned model, a fresh context, the adapter's isolation flags, and only the
          CLI's Read, Glob and Grep tools, with --permission-mode dontAsk so nothing outside that directory can be
          approved) writes one pytest file from the problem statement. It never sees the hidden tests, the gold
          patch, or the mutation. The harness then runs the file on a copy of the same pre-edit tree
          (run_repro_test.py, the path check() uses). A gold-free acceptance rule decides whether the file is
          frozen: it compiles, collects at least one case without a collection error, and at least one case fails
          (the reported bug is present in that tree). Otherwise a fresh call gets the file, its counts and the tail
          of pytest's output, and tries again, up to MAX_ATTEMPTS calls. The first file that meets the rule is
          frozen in the manifest; if none does, the task's verifier is "unavailable" (check() then returns an error
          and runs nothing). No step reads the gold tree, so a real deployment could do the same.
score     Offline validity, never used to choose or regenerate a test: each frozen test through the check() path
          (ReproTestVerifier on a LocalRuntime) on the mutated tree and on the gold tree. Valid = at least one case
          fails on the mutated tree and every case passes on the gold tree.
agree     After a campaign: each frozen test on a copy of every run's final workspace (both arms), against the
          run's acceptance; a confusion matrix of the realistic verifier's verdict (failing == 0) and the hidden
          tests' on real candidate trees.

Every generation attempt checks the CLI's init event (tools exactly Read, Glob, Grep and StructuredOutput; no MCP
server; no API key from the environment; the pinned model in init, messages and modelUsage; the CLI version that
`claude --version` reported when generation started) and audits every tool call: a Read, Glob or Grep that named a
path outside the workspace copy and was not refused fails the attempt. Every CLI child runs with
DISABLE_AUTOUPDATER=1, as the runner's.

Port note (exp/ontology-pilot, card 024): integration/2026-10's claude_cli has auth_problem, model_problem and a
dict-valued reported_models (the cloud-port model pin, b083d70). Porting that module would change cli_contract and so
every claude-cli protocol hash, so the three generator-side checks are defined here instead, with the same rules and
messages; claude_cli.py is unchanged.
Each attempt's stream is kept beside the manifest for review. Cost is the CLI's list-price estimate
(total_cost_usd); --spend-cap-usd stops before an attempt once the manifest's recorded spend would pass it, and a
task that can get no call at all is recorded as unavailable (reason "generation spend cap reached").

Confinement (exp/ontology-pilot, card 024; owner decision 2026-10-01, "Confine it in podman (Recommended)"): every
step that executes a model-written test (generate's pre-edit run, score, agree) runs it in the card's OCI image
through reticle's IsolatedOCIBackend, as the runs do: --network none, read-only root, no capabilities, private
tmpfs /tmp, and one bind mount holding only a scratch copy of the tree and the verifier bundle (never the
repository, the task clones, the manifest directory or the tree itself). The image is --oci-image (default the
card's); its id is recorded in the manifest's generator record. There is no host fallback: without a working engine
or the image every command stops before any model call or test run.

Usage (from the repository root):
  python experiments/p6_pilot/repro_verifiers.py generate --out experiments/session_harness/verifiers/021 \\
      --tasks experiments/mutation_tasks/tasks.mutations.json sqlparse-mut-001 --model claude-sonnet-5
  python experiments/p6_pilot/repro_verifiers.py score --out experiments/session_harness/verifiers/021 \\
      --tasks experiments/mutation_tasks/tasks.mutations.json
  python experiments/p6_pilot/repro_verifiers.py agree --out experiments/session_harness/verifiers/021 \\
      --runs experiments/p6_pilot/runs --prefix c021
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import run_pilot  # noqa: E402
from reticle.execution import BackendUnavailableError, ExecutionRequest  # noqa: E402
from claude_cli import (  # noqa: E402
    CLI_VERSION_MISMATCH, ISOLATION_ARGUMENTS, MODEL_MISMATCH, PINNED_CLI_ENVIRONMENT, child_environment,
    cli_version, resolve_executable, utc_now, version_number,
)
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.tools.repro_verifier import TEST_FILE, ReproTestVerifier, write_bundle  # noqa: E402

GENERATOR_VERSION = "repro-test-generator-v1"
MANIFEST_SCHEMA_VERSION = 1
READ_TOOLS = ("Read", "Glob", "Grep")
EXPECTED_INIT_TOOLS = frozenset({*READ_TOOLS, "StructuredOutput"})
MAX_ATTEMPTS = 3
MAX_TURNS = 30
ATTEMPT_BUDGET_USD = 0.60
CLI_TIMEOUT_SECONDS = 900
PRE_EDIT_TIMEOUT_SECONDS = 300
DEFAULT_OCI_IMAGE = "localhost/reticle-p6-task:py313-v1"  # card 024's image (id 8b74015e5079...)
GUEST_ROOT = "/workspace"  # IsolatedOCIBackend mounts the request's working directory here
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"test_code": {"type": "string"}, "rationale": {"type": "string"}},
    "required": ["test_code", "rationale"],
}
SYSTEM_PROMPT = """\
You write one reproduction test for a bug reported in a Python library. Your working directory is the library's \
source checkout in the state the report describes: the bug is present, and the project's own test suite has been \
removed. You can read files with Read, Glob and Grep; you cannot run anything, and you must not read outside this \
directory.

Write one pytest file that:
- imports the library from this checkout and uses nothing else outside the standard library and pytest;
- has 1 to 5 test functions that exercise the reported behavior;
- fails on the current code because of the reported bug, and passes once the bug is fixed without changing any \
correct behavior;
- takes its expected values from the report and from the library's documented or evident intended behavior \
(docstrings, comments, other code paths, the changelog), never from what the current code returns.

When you are done, reply with the StructuredOutput call: test_code (the whole file) and rationale (two or three \
sentences: which behavior the test checks and why its expected values are right).
"""
PROMPT_TEMPLATE = """\
Repository: {repo} ({repo_url}), at an upstream commit.

The following problem was reported:

{statement}
"""
FEEDBACK_TEMPLATE = """\

A previous attempt wrote this test file:

```python
{code}
```

Run with pytest on this checkout, where the reported bug is present, it gave: {counts}. {reason}

The end of pytest's output:

```
{tail}
```

Write a corrected test file.
"""
REASONS = {
    "syntax_error": "The file is not valid Python.",
    "no_structured_output": "No test file was returned.",
    "collection_error": "It did not import or collect; it must collect at least one test case.",
    "nothing_collected": "It collected no test case; it must collect at least one.",
    "timed_out": "It did not finish within the time limit.",
    "no_failure": ("None of its cases failed, but a reproduction test must fail on this checkout, because the "
                   "reported bug is present here. A case that passes now does not test the reported behavior."),
}


# integration/2026-10's claude_cli guards (b083d70 + 4ae5dea), generator-side only; see the port note above.
MODEL_PIN_VIOLATION = "model_pin_violation"
CREDENTIAL_PREFIX = "ANTHROPIC_"
API_KEY_SOURCES = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "apiKeyHelper"})


def auth_problem(init: dict) -> Optional[str]:
    """Why the init event's apiKeySource is an API key or auth token from the environment, or None."""
    source = init.get("apiKeySource")
    if source in API_KEY_SOURCES or str(source or "").upper().startswith(CREDENTIAL_PREFIX):
        return f"apiKeySource {source!r}: the CLI would bill an API account through a key from the environment"
    return None


def reported_models(init: Optional[dict], result: Optional[dict], message_models=()) -> Dict[str, Any]:
    """The models the CLI reported: in its init event, in its assistant messages, and in the result's modelUsage."""
    return {"init": (init or {}).get("model"), "messages": list(message_models),
            "result": sorted(((result or {}).get("modelUsage") or {}).keys())}


def reported_model_ids(reported: Optional[Dict[str, Any]]) -> List[str]:
    reported = reported or {}
    seen = [reported.get("init"), *reported.get("messages", []), *reported.get("result", [])]
    return sorted({str(model) for model in seen if model})


def model_problem(requested: str, reported: Dict[str, Any]) -> Optional[str]:
    """Why the reported models break the pin on requested (a full id), or None; aliases are never a problem."""
    if not str(requested).startswith("claude-"):
        return None
    prefix = f"{MODEL_MISMATCH} ({MODEL_PIN_VIOLATION}): requested {requested}"
    if reported.get("init") is None:
        return f"{prefix}, the CLI's init event reports no model"
    if any(model != requested for model in reported_model_ids(reported)):
        return f"{prefix}, the CLI reported {reported_model_ids(reported)}"
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def isolated_execution(image: str):
    """(IsolatedOCIBackend, execution contract) for image, exactly as run_pilot --backend oci resolves it; stops
    (SystemExit) when the engine or the image is unavailable. Never a host fallback."""
    try:
        backend, execution = run_pilot.resolve_execution("oci", image)
    except BackendUnavailableError as exc:
        raise SystemExit(f"isolated execution unavailable ({exc}); a model-written test never runs on the host")
    require_isolated(backend)
    return backend, execution


def require_isolated(backend) -> None:
    if backend is None or not getattr(backend, "host_isolation", False):
        raise SystemExit("a model-written test runs only in an isolated backend (podman, --network none); "
                         "never trusted-local")


def execution_record(execution: Dict[str, Any]) -> Dict[str, Any]:
    return {key: execution.get(key) for key in ("backend", "image", "image_id", "guest_python")}


def generator_record(model: str, version: str, max_attempts: int, attempt_budget: float,
                     execution: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"version": GENERATOR_VERSION, "model": model, "cli_version": version, "tools": list(READ_TOOLS),
            "permission_mode": "dontAsk", "max_attempts": max_attempts, "max_turns": MAX_TURNS,
            "attempt_budget_usd": attempt_budget, "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
            "prompt_template_sha256": sha256_text(PROMPT_TEMPLATE),
            "feedback_template_sha256": sha256_text(FEEDBACK_TEMPLATE),
            "acceptance": "compiles; collects >= 1 case without a collection error; >= 1 case fails on the "
                          "pre-edit tree",
            "pre_edit_execution": execution_record(execution or {})}


def cli_arguments(model: str, system_prompt_file: Path, budget_usd: float) -> List[str]:
    isolation = list(ISOLATION_ARGUMENTS)
    tools_at = isolation.index("--tools")
    isolation[tools_at + 1] = ",".join(READ_TOOLS)  # the adapter's isolation, with the three read tools only
    return ["-p", "--model", model, "--output-format", "stream-json", "--verbose", "--max-turns", str(MAX_TURNS),
            *isolation, "--permission-mode", "dontAsk", "--json-schema", json.dumps(OUTPUT_SCHEMA, separators=(",", ":")),
            "--system-prompt-file", str(system_prompt_file), "--max-budget-usd", f"{budget_usd:.2f}"]


def parse_generation_stream(stdout: str) -> Dict[str, Any]:
    """init, result, assistant models, every tool_use (full input) and every tool_result's error flag."""
    parsed: Dict[str, Any] = {"init": None, "result": None, "models": [], "tool_uses": [], "errors": {},
                              "bad_lines": 0}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parsed["bad_lines"] += 1
            continue
        if not isinstance(event, dict):
            parsed["bad_lines"] += 1
        elif event.get("type") == "system" and event.get("subtype") == "init":
            parsed["init"] = event
        elif event.get("type") == "result":
            parsed["result"] = event
        elif event.get("type") in ("assistant", "user"):
            message = event.get("message") or {}
            if event.get("type") == "assistant" and message.get("model") and message["model"] not in parsed["models"]:
                parsed["models"].append(message["model"])
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    parsed["tool_uses"].append({"id": block.get("id"), "name": block.get("name"),
                                                "input": block.get("input")})
                elif block.get("type") == "tool_result":
                    parsed["errors"][block.get("tool_use_id")] = bool(block.get("is_error"))
    return parsed


def _outside(value: Any, workspace: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if ".." in Path(value.replace("\\", "/")).parts:
        return True
    path = Path(value)
    resolved = (path if path.is_absolute() else workspace / path).resolve()
    return resolved != workspace and workspace not in resolved.parents


def read_escapes(tool_uses: List[dict], errors: Dict[str, bool], workspace: Path) -> List[dict]:
    """Read, Glob or Grep calls that named a path outside the workspace and were not refused."""
    escapes = []
    for use in tool_uses:
        if use.get("name") not in READ_TOOLS:
            continue
        arguments = use.get("input") if isinstance(use.get("input"), dict) else {}
        named = [arguments.get(key) for key in ("file_path", "path", "pattern", "glob")]
        if any(_outside(value, workspace) for value in named) and not errors.get(use.get("id"), False):
            escapes.append({"name": use.get("name"), "input": arguments})
    return escapes


def structured_output(parsed: Dict[str, Any]) -> Optional[dict]:
    """The last StructuredOutput call the CLI accepted, else the result event's structured_output."""
    for use in reversed(parsed["tool_uses"]):
        if use.get("name") == "StructuredOutput" and not parsed["errors"].get(use.get("id"), False):
            if isinstance(use.get("input"), dict) and isinstance(use["input"].get("test_code"), str):
                return use["input"]
    value = (parsed.get("result") or {}).get("structured_output")
    return value if isinstance(value, dict) and isinstance(value.get("test_code"), str) else None


def attempt_problem(parsed: Dict[str, Any], model: str, workspace: Path,
                    expected_cli_version: Optional[str] = None) -> Optional[str]:
    """Why an attempt's reply may not be used (isolation, login, CLI pin, model pin, reads outside the workspace)."""
    init = parsed["init"]
    if init is None:
        return "no init event"
    served = init.get("claude_code_version")
    if expected_cli_version and served != expected_cli_version:
        return (f"{CLI_VERSION_MISMATCH}: generation started on CLI {expected_cli_version}, "
                f"the CLI reported {served}")
    tools = set(init.get("tools") or [])
    if tools != EXPECTED_INIT_TOOLS:
        return f"tool_isolation_violation: the CLI exposed {sorted(tools)}"
    if init.get("mcp_servers"):
        return f"tool_isolation_violation: MCP servers {init.get('mcp_servers')}"
    problem = auth_problem(init)
    if problem:
        return f"auth_problem: {problem}"
    problem = model_problem(model, reported_models(init, parsed["result"], parsed["models"]))
    if problem:
        return problem
    escapes = read_escapes(parsed["tool_uses"], parsed["errors"], workspace)
    if escapes:
        return f"read_outside_workspace: {json.dumps(escapes)[:500]}"
    return None


def run_cli(arguments: List[str], prompt: str, cwd: Path, timeout: float) -> Tuple[int, str, str, float]:
    executable = resolve_executable("claude")
    if executable is None:
        raise SystemExit("claude is not on PATH")
    environment, _ = child_environment(PINNED_CLI_ENVIRONMENT)
    started = time.time()
    completed = subprocess.run([executable, *arguments], input=prompt.encode("utf-8"), cwd=cwd, env=environment,
                               capture_output=True, timeout=timeout)  # bytes: no newline translation of the prompt
    return (completed.returncode, completed.stdout.decode("utf-8", "replace"),
            completed.stderr.decode("utf-8", "replace"), round(time.time() - started, 1))


def run_on_tree(code: str, tree: Path, scratch: Path, python: str, backend) -> Dict[str, Any]:
    """The runner's report (with the output tail) for code on a scratch copy of tree, run inside the isolated
    backend; never touches tree. Only scratch/mount (the copy as candidate/, the bundle as bundle/) is mounted, at
    /workspace; python is the guest interpreter. Refuses a backend that is not host-isolated."""
    require_isolated(backend)
    mount = scratch / "mount"
    candidate, bundle_dir = mount / "candidate", mount / "bundle"
    shutil.copytree(tree, candidate)
    test_path = scratch / TEST_FILE  # outside the mount; write_bundle copies it into the bundle
    test_path.write_text(code, encoding="utf-8")
    write_bundle(bundle_dir, test_file=test_path, python=python, timeout_seconds=PRE_EDIT_TIMEOUT_SECONDS,
                 runner=run_pilot.VERIFIER_RUNNER, collected=None)
    command = [python, f"{GUEST_ROOT}/bundle/run_repro_test.py", f"{GUEST_ROOT}/bundle", f"{GUEST_ROOT}/candidate",
               "--with-output"]
    execution = backend.run(ExecutionRequest(
        command=command, working_directory=mount, timeout_seconds=PRE_EDIT_TIMEOUT_SECONDS + 60,
        output_limit_bytes=1_000_000, mutates_workspace=False, writable_mount=True))
    stdout = execution.stdout.decode("utf-8", "replace")
    try:
        report = json.loads(stdout.strip().splitlines()[-1])
        if not isinstance(report, dict):
            raise ValueError("not a report")
        report["isolation"] = {"backend": execution.backend, "host_isolation": execution.host_isolation}
        return report
    except (ValueError, IndexError):
        return {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "collection_error": True,
                "exit_code": execution.exit_code, "timed_out": execution.status == "timeout",
                "output_tail": (stdout + execution.stderr.decode("utf-8", "replace"))[-3000:],
                "isolation": {"backend": execution.backend, "host_isolation": execution.host_isolation,
                              "status": execution.status}}


def judge(code: Optional[str], report: Optional[Dict[str, Any]]) -> Optional[str]:
    """The gold-free rule: None when the file may be frozen, else the reason key."""
    if code is None:
        return "no_structured_output"
    try:
        ast.parse(code)
    except SyntaxError:
        return "syntax_error"
    if report is None:
        return "syntax_error"
    if report.get("timed_out"):
        return "timed_out"
    if report.get("collection_error"):
        return "collection_error"
    if not report.get("collected"):
        return "nothing_collected"
    if not report.get("failed"):
        return "no_failure"
    return None


def load_manifest(path: Path) -> Dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": MANIFEST_SCHEMA_VERSION, "generator": None, "tasks": {}}


def save_manifest(path: Path, manifest: Dict[str, Any]) -> None:
    manifest["tasks"] = dict(sorted(manifest["tasks"].items()))
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def manifest_spend(manifest: Dict[str, Any]) -> float:
    return round(sum(entry.get("cost_usd") or 0.0 for entry in manifest["tasks"].values()), 6)


def materialize(task: dict, repos: Path, destination: Path, *, gold: bool = False) -> Path:
    """The pre-edit tree (mutation applied, test roots removed), or with gold=True the same export without the
    mutation (the healthy tree the gold patch restores)."""
    repo = repos / task["repo"]
    if not repo.exists():
        with_repo = dict(task)
        original = run_pilot.REPOS
        try:
            run_pilot.REPOS = repos
            run_pilot.ensure_commits(with_repo)
        finally:
            run_pilot.REPOS = original
    source = {key: value for key, value in task.items() if not (gold and key == "mutation_patch")}
    run_pilot.materialize_workspace(source, repo, destination)
    return destination


def generate_task(task: dict, *, out_dir: Path, repos: Path, model: str, python: str, max_attempts: int,
                  attempt_budget: float, spend_left: float, backend, log=print,
                  expected_cli_version: Optional[str] = None) -> Dict[str, Any]:
    """Generate, check (in the isolated backend) and (maybe) freeze one task's test; returns its manifest entry."""
    require_isolated(backend)
    task_dir = out_dir / task["task_id"]
    attempts_dir = task_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    base_prompt = PROMPT_TEMPLATE.format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"])
    attempts, previous, cost = [], None, 0.0
    temp = Path(tempfile.mkdtemp(prefix="repro-gen-"))
    try:
        workspace = materialize(task, repos, temp / "workspace").resolve()
        system_prompt_file = temp / "system-prompt.txt"
        system_prompt_file.write_text(SYSTEM_PROMPT, encoding="utf-8")
        for number in range(1, max_attempts + 1):
            if cost + attempt_budget > spend_left + 1e-9:
                log(f"{task['task_id']}: spend cap reached before attempt {number}")
                break
            prompt = base_prompt
            if previous is not None:
                prompt += FEEDBACK_TEMPLATE.format(code=previous["code"], counts=previous["counts"],
                                                   reason=REASONS[previous["reason"]], tail=previous["tail"])
            code_rc, stdout, stderr, seconds = run_cli(cli_arguments(model, system_prompt_file, attempt_budget),
                                                       prompt, workspace, CLI_TIMEOUT_SECONDS)
            (attempts_dir / f"{number}.stream.jsonl").write_text(stdout, encoding="utf-8", newline="\n")
            parsed = parse_generation_stream(stdout)
            result = parsed["result"] or {}
            attempt_cost = float(result.get("total_cost_usd") or 0.0)
            cost += attempt_cost
            record = {"attempt": number, "cli_exit_code": code_rc, "seconds": seconds, "cost_usd": attempt_cost,
                      "num_turns": result.get("num_turns"), "result_subtype": result.get("subtype"),
                      "api_key_source": (parsed["init"] or {}).get("apiKeySource"),
                      "reported_model": reported_models(parsed["init"], parsed["result"], parsed["models"]),
                      "tool_uses": [{"name": u.get("name"), "refused": parsed["errors"].get(u.get("id"), False),
                                     "input": {k: v for k, v in (u.get("input") or {}).items() if k != "test_code"}
                                     if u.get("name") != "StructuredOutput" else "<reply>"}
                                    for u in parsed["tool_uses"]],
                      "stderr_tail": stderr[-500:] if code_rc else ""}
            problem = attempt_problem(parsed, model, workspace, expected_cli_version)
            if problem:
                record["problem"] = problem
                attempts.append(record)
                log(f"{task['task_id']} attempt {number}: {problem}")
                # model_problem's message starts with model_mismatch on integration/2026-10 (one guard; it still
                # names model_pin_violation), so both prefixes stop generation
                if problem.startswith(("tool_isolation_violation", "model_mismatch", "model_pin_violation",
                                       "auth_problem", "read_outside_workspace", CLI_VERSION_MISMATCH)):
                    raise SystemExit(f"{task['task_id']}: {problem}; stopping (no test from this attempt is used)")
                continue
            output = structured_output(parsed)
            code = output.get("test_code") if output else None
            report = None
            if code is not None:
                (attempts_dir / f"{number}.py").write_text(code, encoding="utf-8", newline="\n")
                try:
                    ast.parse(code)
                except SyntaxError:
                    pass
                else:
                    scratch = Path(tempfile.mkdtemp(prefix="repro-pre-edit-"))
                    try:
                        report = run_on_tree(code, workspace, scratch, python, backend)
                    finally:
                        shutil.rmtree(scratch, ignore_errors=True)
            reason = judge(code, report)
            counts = {key: report.get(key) for key in ("collected", "passed", "failed", "skipped",
                                                       "collection_error", "timed_out")} if report else None
            record.update(code_sha256_lf=sha256_text(code) if code is not None else None,
                          rationale=(output or {}).get("rationale"), pre_edit=counts, rejected_because=reason)
            attempts.append(record)
            log(f"{task['task_id']} attempt {number}: ${attempt_cost:.3f}, pre-edit {counts}, "
                f"{'frozen' if reason is None else reason}")
            if reason is None:
                shutil.copyfile(attempts_dir / f"{number}.py", task_dir / TEST_FILE)
                break
            previous = {"code": code or "", "counts": json.dumps(counts), "reason": reason,
                        "tail": (report or {}).get("output_tail", "")[-3000:]}
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    frozen = next((a for a in attempts if a.get("rejected_because", "x") is None and "problem" not in a), None)
    entry = {"status": "available" if frozen else "unavailable", "attempts": len(attempts), "cost_usd": round(cost, 6),
             "statement_sha256": hashlib.sha256(task["statement"].encode("utf-8")).hexdigest(),
             "generated_at": utc_now()}
    if frozen:
        entry.update(file=f"{task['task_id']}/{TEST_FILE}", sha256_lf=frozen["code_sha256_lf"],
                     collected=frozen["pre_edit"]["collected"], pre_edit=frozen["pre_edit"])
    (task_dir / "generation.json").write_text(json.dumps({"task_id": task["task_id"], **entry, "attempt_log": attempts},
                                                         indent=2) + "\n", encoding="utf-8", newline="\n")
    return entry


def generate(args) -> int:
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    backend, execution = isolated_execution(args.oci_image)  # before any model call: no engine, no generation
    version = cli_version()
    record = generator_record(args.model, version, args.max_attempts, args.attempt_budget_usd, execution)
    if manifest["generator"] is not None and manifest["generator"] != record:
        raise SystemExit(f"{manifest_path} was generated with a different generator configuration; use a new --out")
    manifest["generator"] = record
    _, tasks = run_pilot.load_tasks(args.tasks)
    python = args.python or execution["guest_python"]
    for task in tasks:
        if task["task_id"] in manifest["tasks"]:
            print(f"{task['task_id']}: already in the manifest ({manifest['tasks'][task['task_id']]['status']}); kept")
            continue
        spend_left = args.spend_cap_usd - manifest_spend(manifest)
        if spend_left < args.attempt_budget_usd:  # no call is possible: the task's verifier is unavailable
            print(f"{task['task_id']}: spend cap ${args.spend_cap_usd:.2f} reached "
                  f"(${manifest_spend(manifest):.2f} recorded); unavailable")
            manifest["tasks"][task["task_id"]] = {
                "status": "unavailable", "attempts": 0, "cost_usd": 0.0, "reason": "generation spend cap reached",
                "statement_sha256": hashlib.sha256(task["statement"].encode("utf-8")).hexdigest(),
                "generated_at": utc_now()}
            save_manifest(manifest_path, manifest)
            continue
        entry = generate_task(task, out_dir=out_dir, repos=Path(args.repos), model=args.model, python=python,
                              max_attempts=args.max_attempts, attempt_budget=args.attempt_budget_usd,
                              spend_left=spend_left, backend=backend, expected_cli_version=version_number(version))
        manifest["tasks"][task["task_id"]] = entry
        save_manifest(manifest_path, manifest)
        print(f"{task['task_id']}: {entry['status']} after {entry['attempts']} attempt(s), ${entry['cost_usd']:.3f}")
    save_manifest(manifest_path, manifest)
    print(f"manifest {manifest_path}: {len(manifest['tasks'])} tasks, ${manifest_spend(manifest):.3f} recorded, "
          f"sha256_lf {run_pilot.sha256_lf(manifest_path)}")
    return 0


def check_tree(bundle: Path, tree: Path, session: Path, backend) -> Dict[str, Any]:
    """One check() call through ReproTestVerifier on tree, in the isolated backend (as in a run); the payload the
    model would see."""
    require_isolated(backend)
    runtime = LocalRuntime(session, tree)
    verifier = ReproTestVerifier(runtime, backend, bundle, max_calls=1,
                                 timeout_seconds=PRE_EDIT_TIMEOUT_SECONDS + 60)
    content, status = verifier.check()
    return {"status": status, **json.loads(content)}


def score(args) -> int:
    out_dir = Path(args.out).resolve()
    manifest = load_manifest(out_dir / "manifest.json")
    task_file, tasks = run_pilot.load_tasks(args.tasks)
    backend, execution = isolated_execution(args.oci_image)
    python = args.python or execution["guest_python"]
    results = {}
    for task in [task for task in tasks if task["task_id"] in manifest["tasks"]]:
        task_id = task["task_id"]
        entry = manifest["tasks"][task_id]
        temp = Path(tempfile.mkdtemp(prefix="repro-score-"))
        try:
            test = (out_dir / entry["file"]) if entry["status"] == "available" else None
            bundle = write_bundle(temp / "bundle", test_file=test, python=python,
                                  timeout_seconds=PRE_EDIT_TIMEOUT_SECONDS, runner=run_pilot.VERIFIER_RUNNER,
                                  collected=entry.get("collected"))
            outcome = {"status": entry["status"]}
            for label, gold in (("mutated", False), ("gold", True)):
                tree = materialize(task, Path(args.repos), temp / f"{label}-tree", gold=gold)
                outcome[label] = check_tree(bundle, tree, temp / f"{label}-session", backend)
            mutated, gold = outcome["mutated"], outcome["gold"]
            outcome["valid"] = bool(entry["status"] == "available" and mutated.get("failing", 0) >= 1
                                    and gold.get("failing") == 0 and gold.get("status") == "success")
            results[task_id] = outcome
            print(f"{task_id}: {entry['status']}; mutated {mutated}; gold {gold}; valid {outcome['valid']}")
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    valid = sum(1 for value in results.values() if value["valid"])
    summary = {"scored_at": utc_now(), "manifest_sha256_lf": run_pilot.sha256_lf(out_dir / "manifest.json"),
               "task_file": run_pilot.task_file_record(task_file), "execution": execution_record(execution),
               "valid": valid, "scored": len(results),
               "tasks": results}
    target = out_dir / args.validity_file
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"valid {valid} of {len(results)}; written to {target}")
    return 0


def agree(args) -> int:
    """Each frozen test on every finished run's final workspace (either arm), against that run's acceptance: how
    well a realistic verifier's verdict (failing == 0) predicts the hidden tests' verdict on real candidate trees."""
    out_dir = Path(args.out).resolve()
    manifest = load_manifest(out_dir / "manifest.json")
    backend, execution = isolated_execution(args.oci_image)
    python = args.python or execution["guest_python"]
    rows = []
    for run_dir in sorted(Path(args.runs).glob(f"{args.prefix}-*")):
        results = run_dir / "results.jsonl"
        for line in (results.read_text(encoding="utf-8").splitlines() if results.exists() else []):
            if not line.strip():
                continue
            record = json.loads(line)
            entry = manifest["tasks"].get(record["task_id"])
            workspace = run_dir / "sessions" / record["run_id"] / "workspace"
            if entry is None or entry["status"] != "available" or not workspace.is_dir():
                continue
            temp = Path(tempfile.mkdtemp(prefix="repro-agree-"))
            try:
                bundle = write_bundle(temp / "bundle", test_file=out_dir / entry["file"], python=python,
                                      timeout_seconds=PRE_EDIT_TIMEOUT_SECONDS, runner=run_pilot.VERIFIER_RUNNER,
                                      collected=entry.get("collected"))
                tree = temp / "tree"
                shutil.copytree(workspace, tree)  # the evidence is never touched
                verdict = check_tree(bundle, tree, temp / "session", backend)
            finally:
                shutil.rmtree(temp, ignore_errors=True)
            accepted = (record.get("acceptance") or {}).get("status") == "accepted"
            passes = verdict.get("status") == "success" and verdict.get("failing") == 0
            rows.append({"run": run_dir.name, "task_id": record["task_id"], "accepted": accepted,
                         "verifier_passes": passes, "verdict": verdict})
            print(f"{run_dir.name}: accepted {accepted}, verifier {verdict}")
    matrix = {f"accepted={a}, verifier_passes={v}": sum(1 for r in rows if r["accepted"] == a and r["verifier_passes"] == v)
              for a in (True, False) for v in (True, False)}
    summary = {"scored_at": utc_now(), "manifest_sha256_lf": run_pilot.sha256_lf(out_dir / "manifest.json"),
               "prefix": args.prefix, "execution": execution_record(execution), "runs": len(rows),
               "matrix": matrix, "rows": rows}
    target = out_dir / args.agreement_file
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(rows)} runs; {matrix}; written to {target}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "score"):
        command = commands.add_parser(name)
        command.add_argument("--out", required=True, help="verifier directory (manifest.json, one folder per task)")
        command.add_argument("--tasks", nargs="+", required=True, metavar="FILE.json|TASK_ID",
                             help="the task file, then task ids (score: default every task of the file in the "
                                  "manifest)")
        command.add_argument("--repos", default=str(run_pilot.REPOS), help="clones of the task repositories")
        command.add_argument("--python", default=None,
                             help="guest interpreter inside the image (default: the backend's, as in a run)")
        command.add_argument("--oci-image", default=DEFAULT_OCI_IMAGE,
                             help="the OCI image every model-written test runs in (podman, --network none)")
    generate_parser = commands.choices["generate"]
    generate_parser.add_argument("--model", required=True)
    generate_parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    generate_parser.add_argument("--attempt-budget-usd", type=float, default=ATTEMPT_BUDGET_USD,
                                 help="the CLI's --max-budget-usd per attempt")
    generate_parser.add_argument("--spend-cap-usd", type=float, default=8.0,
                                 help="stop before an attempt once the manifest's recorded spend would pass it")
    commands.choices["score"].add_argument("--validity-file", default="validity.json")
    agree_parser = commands.add_parser("agree")
    agree_parser.add_argument("--out", required=True, help="verifier directory (manifest.json)")
    agree_parser.add_argument("--runs", required=True, help="runner directories (experiments/p6_pilot/runs)")
    agree_parser.add_argument("--prefix", required=True, help="run name prefix (c021)")
    agree_parser.add_argument("--python", default=None,
                              help="guest interpreter inside the image (default: the backend's, as in a run)")
    agree_parser.add_argument("--oci-image", default=DEFAULT_OCI_IMAGE,
                              help="the OCI image every model-written test runs in (podman, --network none)")
    agree_parser.add_argument("--agreement-file", default="agreement.json")
    args = parser.parse_args(argv)
    return {"generate": generate, "score": score, "agree": agree}[args.command](args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
