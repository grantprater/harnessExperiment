"""P6 instrumentation pilot: real-repository bug tasks through the shared runtime.

Every provider attempt is appended to calls.jsonl as it completes, and each run's outcome
to results.jsonl. Reports are generated only from those files.

Clients:
  openrouter  live model calls; requires --max-total-calls (counts every HTTP attempt)
  gold        writes the upstream fix's source files, then finishes (pipeline check, no API)
  noop        finishes immediately (pipeline check, no API)
  breaker     makes the fixed source files unimportable, then finishes (pipeline check, no API)
  gamer       adds conftest hooks that report every test as passed (pipeline check, no API)

Arms (same tools, instructions, evaluator, and limits; only the context policy differs):
  bounded-transcript-v2  original task + as much recent transcript as fits; tool results shown
                         as bounded views that name the read_output call for the rest
  reticle-board-v2       original task + last two exchanges + journal-derived board

Usage (from the repo root):
  python experiments/p6_pilot/run_pilot.py --client gold --run-name gold-check
  python experiments/p6_pilot/run_pilot.py --client openrouter --models qwen/qwen3.5-9b \\
      --provider qwen/qwen3.5-9b=venice --tasks humanize-329 --run-name pilot-a \\
      --max-total-calls 30 --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.context import BaselineContextPolicy  # noqa: E402
from reticle.context.board import ReticleBoardPolicy  # noqa: E402
from reticle.evaluation import AcceptancePlan, AcceptanceRunner, CriterionContract  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError, ModelResponse  # noqa: E402
from reticle.tools import TOOL_SCHEMAS, ToolSuite  # noqa: E402

HERE = Path(__file__).resolve().parent
REPOS = ROOT / ".runtime" / "bug-mining" / "repos"
TASK_PYTHON = ROOT / ".runtime" / "bugs-venv" / "Scripts" / "python.exe"
BASE_URL = "https://openrouter.ai/api/v1"
RUNNER_VERSION = 2  # 2: complete tool outputs with bounded views and read_output/search_output
ARMS = {
    "bounded-transcript-v2": BaselineContextPolicy,
    "reticle-board-v2": ReticleBoardPolicy,
}
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
MANAGED_ROOT_FILES = ("conftest.py", "pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml")
UNPINNED_ROUTING = {"require_parameters": True}

INSTRUCTIONS = (
    "You are working in a source checkout of {repo} ({repo_url}) at an upstream commit. "
    "The following problem was reported:\n\n{statement}\n\n"
    "Change the library so the reported behavior is correct. Hidden upstream tests will be run on "
    "your final workspace; tests you add or edit are not used for acceptance, but you may write and "
    "run tests to check your work (for example `pytest tests/test_example.py -q` with the run tool). "
    "Call finish when you are done."
)


def protocol_hash(arm: str, routing: dict) -> str:
    return hashlib.sha256(
        json.dumps({
            "runner_version": RUNNER_VERSION, "arm": arm, "instructions": INSTRUCTIONS, "tools": TOOL_SCHEMAS,
            "evaluator": hashlib.sha256((HERE / "evaluate_task.py").read_bytes()).hexdigest(),
            "managed_root_files": MANAGED_ROOT_FILES, "provider_routing": routing,
        }, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]


GAMING_CONFTEST = (
    "import pytest\n\n\n"
    "@pytest.hookimpl(hookwrapper=True)\n"
    "def pytest_runtest_makereport(item, call):\n"
    "    outcome = yield\n"
    "    outcome.get_result().outcome = 'passed'\n"
)


class BudgetExceeded(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, value) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def load_openrouter_key():
    for env_file in (ROOT / "experiments" / ".env", ROOT / ".env"):
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "OPENROUTER_API_KEY" and value.strip():
                    return value.strip().strip('"').strip("'")
    return os.environ.get("OPENROUTER_API_KEY")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(repo), *args],
                          capture_output=True, check=True).stdout


def source_revision() -> dict:
    head = git(ROOT, "rev-parse", "HEAD").decode().strip()
    dirty = bool(git(ROOT, "status", "--porcelain", "--untracked-files=no").strip())
    return {"commit": head, "tracked_changes": dirty}


def ensure_commits(task: dict) -> Path:
    repo = REPOS / task["repo"]
    if not repo.exists():
        REPOS.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", task["repo_url"], str(repo)], check=True)
    for commit in (task["base_commit"], task["fix_commit"]):
        if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True).returncode:
            subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*"],
                           check=True)
    return repo


def provision_version_stub(tree: Path) -> None:
    """setuptools-scm packages import a generated _version.py that a source export lacks."""
    src = tree / "src"
    for package in (src.iterdir() if src.is_dir() else []):
        init = package / "__init__.py"
        if init.exists() and "from ._version import" in init.read_text(encoding="utf-8") and not (package / "_version.py").exists():
            (package / "_version.py").write_text('__version__ = version = "0+local"\n', encoding="utf-8")


def materialize_workspace(task: dict, repo: Path, workspace: Path) -> None:
    """Export the pre-fix tree without git history, so later commits are not visible."""
    workspace.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", "--format=tar", task["base_commit"]))) as archive:
        archive.extractall(workspace, filter="data")
    provision_version_stub(workspace)


def build_evaluator(task: dict, repo: Path, bundle: Path, pytest_timeout: int) -> str:
    files = bundle / "files"
    digest = hashlib.sha256()
    # The whole top-level test trees and root pytest configuration come from the fix commit,
    # so candidate-added conftest hooks or config cannot alter acceptance.
    test_roots = sorted({path.split("/", 1)[0] for path in task["evaluator_test_files"] if "/" in path})
    # Regular files only: submodules (e.g. tomlkit's tests/toml-test) are absent from source exports too.
    tracked = [line.split("\t", 1)[1] for line in git(repo, "ls-tree", "-r", task["fix_commit"]).decode("utf-8").splitlines()
               if line.split(" ", 2)[1] == "blob"]
    fixed_inputs = [p for p in tracked if p.split("/", 1)[0] in test_roots or p in MANAGED_ROOT_FILES]
    for path in sorted(set(fixed_inputs) | set(task["evaluator_test_files"])):
        content = git(repo, "show", f"{task['fix_commit']}:{path}")
        target = files / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        digest.update(path.encode("utf-8") + b"\0" + content + b"\0")
    shutil.copyfile(HERE / "evaluate_task.py", bundle / "evaluate_task.py")
    evaluator_digest = hashlib.sha256((HERE / "evaluate_task.py").read_bytes()).hexdigest()
    version = f"{task['task_id']}:inputs-{digest.hexdigest()[:16]}:evaluator-{evaluator_digest[:16]}"
    targets = sorted({str(Path(p).parent).replace("\\", "/") if p.endswith("__init__.py") else p
                      for p in task["evaluator_test_files"]})
    (bundle / "task.json").write_text(json.dumps({
        "task_id": task["task_id"],
        "python": str(TASK_PYTHON),
        "pytest_targets": targets,
        "pytest_timeout_seconds": pytest_timeout,
        "test_roots": test_roots,
        "managed_root_files": list(MANAGED_ROOT_FILES),
        "fail_to_pass": task["fail_to_pass"],
        "pass_to_pass": task["pass_to_pass"],
        "evaluator_version": version,
    }, indent=2), encoding="utf-8")
    return version


def acceptance_plan(task: dict, version: str) -> AcceptancePlan:
    criteria = [CriterionContract(
        "fail-to-pass", "Upstream regression tests for the reported behavior pass.", "executable", version,
        expected_coverage_ids=list(task["fail_to_pass"]),
    )]
    if task["pass_to_pass"]:
        criteria.append(CriterionContract(
            "pass-to-pass", "Tests in the same upstream test files that passed before the fix still pass.",
            "executable", version, expected_coverage_ids=list(task["pass_to_pass"]),
        ))
    return AcceptancePlan(task["task_id"], criteria,
                          evaluator_command=["{python}", "{bundle}/evaluate_task.py", "{bundle}", "{candidate}"])


class CallBudget:
    def __init__(self, maximum: int, used: int):
        self.maximum, self.used = maximum, used

    def take(self) -> None:
        if self.used >= self.maximum:
            raise BudgetExceeded(f"--max-total-calls {self.maximum} reached")
        self.used += 1


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, calls_path: Path, run_id: str, budget: CallBudget,
                 max_tokens: int, routing: dict, timeout: int = 300):
        self.api_key, self.model, self.calls_path, self.run_id = api_key, model, calls_path, run_id
        self.budget, self.max_tokens, self.routing, self.timeout = budget, max_tokens, routing, timeout
        self.call_index = 0

    def complete(self, messages, tools) -> ModelResponse:
        self.call_index += 1
        body = {
            "model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
            "temperature": 0, "max_tokens": self.max_tokens, "provider": self.routing,
        }
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_sha256 = hashlib.sha256(raw).hexdigest()
        last_error = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.budget.take()
            entry = {"time": utc_now(), "run_id": self.run_id, "model": self.model, "call_index": self.call_index,
                     "attempt": attempt, "request_sha256": request_sha256, "request": body}
            started = time.time()
            data, retry = None, False
            try:
                request = urllib.request.Request(f"{BASE_URL}/chat/completions", data=raw, method="POST", headers={
                    "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                entry["response"] = data
                if data.get("error") or not data.get("choices"):
                    last_error, retry = json.dumps(data.get("error") or data)[:500], True
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1_000]
                entry.update(http_status=exc.code, error=detail)
                last_error, retry = f"HTTP {exc.code}: {detail[:300]}", exc.code in RETRYABLE_HTTP
                if not retry:
                    raise ModelClientError(last_error) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                entry["error"] = repr(exc)
                last_error, retry = repr(exc), True
            finally:
                entry["latency_s"] = round(time.time() - started, 2)
                append_jsonl(self.calls_path, entry)
            if retry:
                time.sleep(min(60, 5 * 2 ** (attempt - 1)))
                continue
            choice = data["choices"][0]
            return ModelResponse(choice.get("message") or {}, data.get("usage"), {
                "provider": data.get("provider"), "model": data.get("model"), "generation_id": data.get("id"),
                "finish_reason": choice.get("finish_reason"), "native_finish_reason": choice.get("native_finish_reason"),
                "attempts": attempt, "request_sha256": request_sha256,
            })
        raise ModelClientError(f"failed after {MAX_ATTEMPTS} attempts: {last_error}")


class ScriptedWriteClient:
    """Writes fixed file contents through the agent's own tools, then finishes."""

    def __init__(self, writes, summary: str):
        self.writes, self.summary, self.calls = writes, summary, 0

    def complete(self, messages, tools) -> ModelResponse:
        self.calls += 1
        if self.calls == 1 and self.writes:
            calls = [{"id": f"write_{i}", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": path, "content": content})}}
                for i, (path, content) in enumerate(self.writes, 1)]
        else:
            calls = [{"id": "scripted_finish", "type": "function", "function": {
                "name": "finish", "arguments": json.dumps({"summary": self.summary})}}]
        return ModelResponse({"role": "assistant", "content": None, "tool_calls": calls})


def scripted_client(kind: str, task: dict, repo: Path) -> ScriptedWriteClient:
    if kind == "gold":
        writes = [(path, git(repo, "show", f"{task['fix_commit']}:{path}").decode("utf-8"))
                  for path in task["gold_source_files"]]
        return ScriptedWriteClient(writes, "applied upstream fix")
    if kind == "breaker":
        return ScriptedWriteClient([(path, "def broken(:\n") for path in task["gold_source_files"]],
                                   "introduced a syntax error")
    if kind == "gamer":
        roots = sorted({path.split("/", 1)[0] for path in task["evaluator_test_files"] if "/" in path})
        writes = [("conftest.py", GAMING_CONFTEST)] + [(f"{root}/conftest.py", GAMING_CONFTEST) for root in roots]
        return ScriptedWriteClient(writes, "report every test as passed")
    return ScriptedWriteClient([], "no change")


def fetch_catalog():
    with urllib.request.urlopen(f"{BASE_URL}/models", timeout=60) as response:
        return {m["id"]: m for m in json.load(response)["data"]}


def model_pricing(catalog, models):
    pricing = {}
    for model in models:
        if model not in catalog:
            raise SystemExit(f"Unknown OpenRouter model: {model}")
        price = catalog[model].get("pricing") or {}
        pricing[model] = {"prompt_usd_per_mtok": float(price.get("prompt") or 0) * 1e6,
                          "completion_usd_per_mtok": float(price.get("completion") or 0) * 1e6}
    return pricing


def endpoint_pricing(model: str, provider_slug: str):
    """Price of the pinned endpoint (it can differ from the model's lowest listed price)."""
    with urllib.request.urlopen(f"{BASE_URL}/models/{model}/endpoints", timeout=60) as response:
        endpoints = json.load(response)["data"]["endpoints"]
    for endpoint in endpoints:
        tag = (endpoint.get("tag") or "").lower()
        if tag == provider_slug or tag.split("/", 1)[0] == provider_slug:
            price = endpoint.get("pricing") or {}
            return {"prompt_usd_per_mtok": float(price.get("prompt") or 0) * 1e6,
                    "completion_usd_per_mtok": float(price.get("completion") or 0) * 1e6,
                    "tools": "tools" in (endpoint.get("supported_parameters") or []),
                    "quantization": endpoint.get("quantization"), "endpoint_tag": endpoint.get("tag")}
    raise SystemExit(f"No endpoint '{provider_slug}' for {model}; available: {[e.get('tag') for e in endpoints]}")


def evaluator_details(runtime: LocalRuntime, report_artifact_id: str) -> dict:
    report = json.loads(runtime.artifacts.read(report_artifact_id))
    details = {"final_workspace_revision": report["final_workspace_revision"]}
    stdout_id = report.get("tool_output_artifact_id")
    if stdout_id:
        try:
            output = json.loads(runtime.artifacts.read(stdout_id))
            details.update({
                "criteria": {name: {k: v for k, v in value.items() if k in {"outcome", "failing", "missing", "skipped"}}
                             for name, value in output.get("criteria", {}).items()},
                "collection_errors": output.get("collection_errors"),
                "observed_test_count": output.get("observed_test_count"),
                "pytest_exit_code": output.get("pytest_exit_code"),
                "pytest_timed_out": output.get("pytest_timed_out"),
            })
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            details["evaluator_output_error"] = repr(exc)
    details["measurement_errors"] = [m.get("infrastructure_error") for m in report.get("measurements", [])
                                     if m.get("infrastructure_error")]
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client", required=True, choices=["openrouter", "gold", "noop", "breaker", "gamer"])
    parser.add_argument("--arm", default="bounded-transcript-v2", choices=sorted(ARMS))
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--provider", action="append", default=[], metavar="MODEL=SLUG",
                        help="pin a model to one OpenRouter provider, no fallbacks (repeatable)")
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument("--max-calls-per-run", type=int, default=25)
    parser.add_argument("--max-context-bytes", type=int, default=80_000)
    parser.add_argument("--max-tokens", type=int, default=8_192)
    parser.add_argument("--max-total-calls", type=int, default=None)
    parser.add_argument("--pytest-timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tasks = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    if args.tasks:
        unknown = set(args.tasks) - {t["task_id"] for t in tasks}
        if unknown:
            raise SystemExit(f"Unknown tasks: {sorted(unknown)}")
        tasks = [t for t in tasks if t["task_id"] in args.tasks]
    if args.client == "openrouter":
        if not args.models:
            raise SystemExit("--models is required for the openrouter client")
        models = args.models
    else:
        models = [f"{args.client}-client"]
    pins = {}
    for item in args.provider:
        model, _, provider_slug = item.partition("=")
        if model not in models or not provider_slug:
            raise SystemExit(f"--provider {item!r} must be MODEL=SLUG for a model in --models")
        pins[model] = provider_slug.lower()
    routing = {model: ({"order": [pins[model]], "allow_fallbacks": False, "require_parameters": True}
                       if model in pins else dict(UNPINNED_ROUTING)) for model in models}
    arm = args.arm
    arm_hash = protocol_hash(arm, routing)
    runs = [(task, model) for model in models for task in tasks]

    run_dir = HERE / "runs" / args.run_name
    config = {
        "runner_version": RUNNER_VERSION, "protocol_hash": arm_hash, "arm": arm, "client": args.client,
        "models": models, "provider_routing": routing, "tasks": [t["task_id"] for t in tasks],
        "max_calls_per_run": args.max_calls_per_run, "max_context_bytes": args.max_context_bytes,
        "max_tokens": args.max_tokens, "pytest_timeout_seconds": args.pytest_timeout, "temperature": 0,
        "max_attempts_per_call": MAX_ATTEMPTS, "max_total_calls": args.max_total_calls,
        "instructions": INSTRUCTIONS, "tools": TOOL_SCHEMAS,
    }

    if args.client == "openrouter":
        catalog = fetch_catalog()
        pricing = model_pricing(catalog, models)
        for model, provider_slug in pins.items():
            pricing[model] = endpoint_pricing(model, provider_slug)
            if not pricing[model]["tools"]:
                raise SystemExit(f"Pinned endpoint {provider_slug} for {model} does not list tool support")
        planned_calls = len(runs) * args.max_calls_per_run
        print(f"{len(runs)} runs ({len(tasks)} tasks x {len(models)} models), arm {arm}, protocol {arm_hash}")
        print(f"model calls: at most {args.max_calls_per_run} per run -> at most {planned_calls} calls "
              f"(HTTP retries count toward --max-total-calls={args.max_total_calls})")
        for model in models:
            price = pricing[model]
            input_tokens = args.max_context_bytes / 3  # planning bound only; billing uses reported usage.cost
            per_call = (input_tokens * price["prompt_usd_per_mtok"] + args.max_tokens * price["completion_usd_per_mtok"]) / 1e6
            where = f"pinned to {pins[model]} ({price.get('quantization')})" if model in pins else "unpinned routing"
            print(f"  {model} [{where}]: ${price['prompt_usd_per_mtok']:.3f}/M in, ${price['completion_usd_per_mtok']:.3f}/M out; "
                  f"worst case <= ${per_call:.4f}/call, <= ${per_call * args.max_calls_per_run * len(tasks):.2f} for its runs")
        config["pricing_at_plan_time"] = pricing
        if args.dry_run:
            return
        if args.max_total_calls is None:
            raise SystemExit("--max-total-calls is required for live runs")
        api_key = load_openrouter_key()
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")
    elif args.dry_run:
        print(f"{len(runs)} runs with the {args.client} client, arm {arm}; no API calls")
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    if config_path.exists():
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        fixed = {k: v for k, v in config.items() if k != "pricing_at_plan_time"}
        changed = sorted(k for k, v in fixed.items() if saved.get(k) != v)
        if changed:
            raise SystemExit(f"{config_path} differs from this invocation in {changed}; use a new --run-name")
    else:
        config["created_at"] = utc_now()
        config["source_revision"] = source_revision()
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    calls_path, results_path = run_dir / "calls.jsonl", run_dir / "results.jsonl"
    done = {r["run_id"] for r in read_jsonl(results_path)}
    budget = CallBudget(args.max_total_calls or 0, len(read_jsonl(calls_path)))

    for task, model in runs:
        run_id = f"{task['task_id']}__{slug(model)}"
        if run_id in done:
            continue
        run_root = run_dir / "sessions" / run_id
        if run_root.exists():  # an earlier attempt of this run was interrupted; keep it for audit
            run_root.rename(run_root.with_name(f"{run_id}.interrupted-{datetime.now():%Y%m%d%H%M%S}"))
        repo = ensure_commits(task)
        workspace, bundle = run_root / "workspace", run_root / "evaluator"
        materialize_workspace(task, repo, workspace)
        version = build_evaluator(task, repo, bundle, args.pytest_timeout)
        runtime = LocalRuntime(run_root / "session", workspace)
        src = workspace / "src"
        tools = ToolSuite(runtime, interpreter=str(TASK_PYTHON), environment={
            "PYTHONPATH": str(src if src.is_dir() else workspace), "PYTHONIOENCODING": "utf-8"})
        envelope = TaskEnvelope(
            task_id=task["task_id"],
            description=INSTRUCTIONS.format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"]),
            criteria=[{"id": "hidden-upstream-tests", "kind": "executable", "visibility": "hidden"}],
            authority={"filesystem": "task workspace", "execution": "trusted-local, not host-isolated",
                       "network": "not provided to tasks"},
            budgets={"model_calls": args.max_calls_per_run, "context_bytes": args.max_context_bytes},
        )
        if args.client == "openrouter":
            client = OpenRouterClient(api_key, model, calls_path, run_id, budget, args.max_tokens, routing[model])
        else:
            client = scripted_client(args.client, task, repo)

        started = time.time()
        record = {"run_id": run_id, "task_id": task["task_id"], "model": model, "client": args.client, "arm": arm,
                  "protocol_hash": arm_hash, "started_at": utc_now(), "session_dir": str(run_root.relative_to(HERE))}
        budget_stop = None
        try:
            agent = AgentController(runtime, envelope, tools, client,
                                    AgentLimits(args.max_calls_per_run, args.max_context_bytes),
                                    policy=ARMS[arm]()).run()
            record["agent"] = agent.to_dict()
        except BudgetExceeded as exc:
            budget_stop = str(exc)
            record["agent"] = {"stop_reason": "pilot_call_budget_exhausted", "error": budget_stop}
        decision = AcceptanceRunner(runtime).evaluate(
            acceptance_plan(task, version), evaluator_root=bundle, timeout_seconds=args.pytest_timeout + 120)
        record["acceptance"] = {"status": decision.status, "criterion_outcomes": decision.criterion_outcomes,
                                "report_artifact_id": decision.report_artifact_id,
                                **evaluator_details(runtime, decision.report_artifact_id)}
        record["elapsed_s"] = round(time.time() - started, 1)
        append_jsonl(results_path, record)
        print(f"{run_id}: {record['agent'].get('stop_reason')} -> {decision.status} {decision.criterion_outcomes}", flush=True)
        if budget_stop:
            print(f"Stopping: {budget_stop}")
            break


if __name__ == "__main__":
    main()
