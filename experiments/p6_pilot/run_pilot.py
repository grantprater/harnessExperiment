"""P6 instrumentation pilot: real-repository bug tasks through the shared runtime.

Every provider attempt is appended to calls.jsonl as it completes, and each run's outcome
to results.jsonl. Reports are generated only from those files.

Clients:
  openrouter  live model calls; requires --max-total-calls (counts every HTTP attempt)
  claude-cli  live model calls through the local Claude Code CLI (claude -p, subscription login, no API key),
              one stateless process per attempt with every built-in tool disabled (see claude_cli.py);
              requires --models (a CLI model alias such as sonnet) and --max-total-calls (counts every attempt)
  gold       writes the upstream fix's source files, then finishes (pipeline check, no API)
  noop        finishes immediately (pipeline check, no API)
  breaker     makes the fixed source files unimportable, then finishes (pipeline check, no API)
  gamer       adds conftest hooks that report every test as passed (pipeline check, no API)
  tester      runs the existing test roots through the run tool without edits (pipeline check, no API)

Backends:
  trusted-local  candidate commands and evaluation run on the host (not isolated)
  oci            candidate commands and evaluation run in a pinned local image by image ID,
                 workspace-only mount, no network (see experiments/p6_pilot/oci/Containerfile)

Arms (same tools, instructions, evaluator, and limits; only the context policy differs):
  bounded-transcript-v2  original task + as much recent transcript as fits; tool results shown
                         as bounded views that name the read_output call for the rest
  reticle-board-v2       original task + last two exchanges + journal-derived board

Tasks (--tasks [FILE.json] [TASK_ID ...]):
  An argument ending in .json names the task file (default experiments/p6_pilot/tasks.json); the other
  arguments select task ids from it (default: all). A mutation task (experiments/mutation_tasks/) gets its
  mutation_patch applied with git apply and its hidden_paths (the test root) removed from the workspace;
  the evaluator still installs the healthy test roots from fix_commit. Each such task's contract (mutation
  kind and file, hidden-tests flag, patch and statement digests) is recorded in config.json and enters the
  protocol hash; tasks without one leave both unchanged.

Treatments (S6 harness surfaces; all off by default, and a run with none of them is hashed, configured, and
executed exactly as before). Each one that is on is described under "treatments" in config.json and in the
protocol hash (name, version, fixed texts, parameters), and reported under "treatments" in results.jsonl:
  --completion finish-guard  task completion detection: the first finish after an edit to a pre-existing
                             source file is rejected once unless a command that failed before the first edit
                             passed, rerun, after the latest edit (reticle/tools/finish_guard.py)
  --nudge midpoint           agent loop: once per run, when --nudge-fraction (default 0.5) of the response
                             budget is spent and no pre-existing source file has been edited, one fixed harness
                             message after the latest tool results (reticle/runtime/nudges.py)
  --oracle hidden-tests[:K]  tool use (changes the task): a check() tool returning only the counts of the task's
                             hidden fail_to_pass tests failing and passing, at most K calls per run (default 3),
                             run on a snapshot outside the workspace (reticle/tools/check_oracle.py)
  --reasoning memory        durable evidence ontology with explicit model assertions and runtime observations
  --reasoning symbolic      same memory/tools, with advisory rules for stale evidence, declared coverage,
                             non-discriminating checks and contradictions; see experiments/neurosymbolic/README.md
  --reasoning injected      same as symbolic, plus a bounded advisory summary appended to the result of each
                             replace_text/write_file/run action (never finish; nothing is rejected)
  --verifier repro-test[:K] --verifier-manifest MANIFEST.json
                             tool use (card 021): the same check() interface over a reproduction test a separate
                             model call wrote before the campaign from the statement and the pre-edit tree, frozen
                             in the manifest (reticle/tools/repro_verifier.py, repro_verifiers.py); not with --oracle
  --nudge commit             agent loop (card 021): once per run at --nudge-fraction of the response budget, edits or
                             not, a harness message asking for a committed hypothesis and a tested prediction, with
                             the commit_hypothesis and record_observation tools offered from the first request
                             (reticle/runtime/nudges.py, reticle/tools/commitment.py)

claude-cli client options (off by default; not treatments, since they change how a reply is obtained, not what the
model is offered; one that is on is recorded in the CLI contract under provider_routing and so in the protocol hash;
other clients ignore them):
  --cli-reply-recovery lenient-json+second-turn-on-retry
                             adapter v3: a StructuredOutput input the CLI could not parse is used when
                             json.loads(raw, strict=False) accepts it; after a rejected StructuredOutput call, the
                             request's later attempts run at --max-turns 2 and may take the second message's
                             StructuredOutput call (first attempts keep v2's --max-turns 1). What it did is recorded
                             per attempt in calls.jsonl (cli_max_turns, ...) and per run in results.jsonl
                             ("cli_reply_recovery"); see claude_cli.py

Usage (from the repo root):
  python experiments/p6_pilot/run_pilot.py --client gold --run-name gold-check
  python experiments/p6_pilot/run_pilot.py --client openrouter --models qwen/qwen3.5-9b \\
      --provider qwen/qwen3.5-9b=venice --tasks humanize-329 --run-name pilot-a \\
      --max-total-calls 30 --dry-run
  python experiments/p6_pilot/run_pilot.py --client gold --backend oci \\
      --tasks experiments/mutation_tasks/tasks.mutations.json sqlparse-mut-001 --run-name mut-gold
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
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

from reticle.context import (  # noqa: E402
    BaselineContextPolicy, PressureRecentContextPolicy, PressureRecentContextPolicyV2, PressureRecentContextPolicyV3,
    PressureRecentContextPolicyV4, TranscriptStore,
)
from reticle.tools.primitives import TOOLSET_VERSION  # noqa: E402
from reticle.execution import IsolatedOCIBackend  # noqa: E402
from reticle.context.board import ReticleBoardPolicy  # noqa: E402
from reticle.evaluation import AcceptancePlan, AcceptanceRunner, CriterionContract  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import AgentController, AgentLimits, ModelClientError, ModelResponse  # noqa: E402
from reticle.runtime.nudges import (  # noqa: E402
    COMMIT_NUDGE_TEMPLATE, COMMIT_NUDGE_VERSION, MIDPOINT_NUDGE_TEMPLATE, MIDPOINT_NUDGE_VERSION, CommitmentNudge,
    MidpointNudge, commit_nudge_text, midpoint_nudge_text,
)
from reticle.runtime.source_edits import SOURCE_RULE_VERSION, SourceEditTracker  # noqa: E402
from reticle.tools import TOOL_SCHEMAS, ToolSuite  # noqa: E402
from reticle.tools.check_oracle import (  # noqa: E402
    DEFAULT_MAX_CALLS, ORACLE_VERSION, CheckOracleTools, HiddenTestOracle, check_schema,
)
from reticle.tools.finish_guard import (  # noqa: E402
    FINISH_GUARD_MESSAGE, FINISH_GUARD_VERSION, REASONS, FinishGuard, FinishGuardTools,
)
from reticle.runtime.reasoning import EvidenceOntology, reasoning_contract  # noqa: E402
from reticle.tools.reasoning import ReasoningTools, REASONING_SCHEMAS, tool_contract  # noqa: E402
from reticle.tools.commitment import (  # noqa: E402
    COMMITMENT_TOOLS_VERSION, CommitmentLog, CommitmentTools, commitment_schemas,
)
from reticle.tools.repro_verifier import (  # noqa: E402
    DEFAULT_MAX_CALLS as VERIFIER_DEFAULT_MAX_CALLS, VERIFIER_VERSION, ReproTestVerifier, verifier_schema,
    write_bundle as write_verifier_bundle,
)

HERE = Path(__file__).resolve().parent
DEFAULT_TASK_FILE = HERE / "tasks.json"
sys.path.insert(0, str(HERE))
from claude_cli import (  # noqa: E402
    MODEL_MISMATCH, REPLY_RECOVERY, RETRY_MAX_TURNS, ClaudeCliClient, cli_contract, cli_version, model_id_problem,
)
from interpreters import task_python  # noqa: E402
REPOS = ROOT / ".runtime" / "bug-mining" / "repos"

# $RETICLE_TASK_PYTHON, else .runtime/bugs-venv's interpreter (Scripts/python.exe on Windows, bin/python on
# POSIX). Under trusted-local the path is in the execution contract, so it is part of the protocol hash.
TASK_PYTHON = task_python(ROOT)

BASE_URL = "https://openrouter.ai/api/v1"
# 2: complete tool outputs with bounded views and read_output/search_output
# 3: selectable execution backend (pinned OCI image), cache files excluded from revisions
# 4: pressure-recent-v1 arm; the provider client reserves and reconciles every HTTP attempt in the
#    durable task ledger; per-run attempt/tool/active-time/cost task budgets; opt-in repeat stop;
#    at most two retries per request; the campaign attempt cap is a recorded model error, not an abort
# 5: optional chunked runs: after a request exhausts its retries on provider errors, wait (paused
#    time) and resume the same durable session, up to a declared number of resumes
# 6: pressure-recent-v2 arm (remaining resources in every request); toolset version in the protocol
# 7: pressure-recent-v3 arm; toolset v3 names (glob_files, search_text) in repeat detection
# 8: claude-cli client (local Claude Code CLI, stateless, no built-in tools); its invocation contract
#    is recorded as the model's routing, so it is part of the protocol hash
#    Later in v8, without a bump: --tasks FILE.json and mutation-task materialisation. Tasks without mutation
#    fields are exported and hashed exactly as before; a mutation task's contract enters the protocol hash.
#    Later in v8, without a bump: the S6 treatments (--completion, --nudge, --oracle). Off, nothing changes
#    (card 007's recorded hashes still replay); on, each one's record enters the protocol hash under
#    "treatments". A bump would change every incumbent hash and block the cards pinned to v8 without any
#    change in what an incumbent runs.
#    Later in v8, without a bump, for the same reason: the claude-cli client option --cli-reply-recovery. Off,
#    the CLI contract and every hash are exactly as before; on, the contract (adapter v3, --max-turns 2 on
#    retries after a rejected StructuredOutput call, the recovery rules) changes the hash through provider_routing.
#    Later in v8, without a bump (2026-09-30, after the `sonnet` alias drifted to claude-sonnet-5-5 with CLI
#    2.1.286): live claude-cli runs take full model IDs only (--dry-run still plans an alias, so old hashes
#    replay); a response from any other model than the requested one stops the run as model_mismatch
#    (an adapter failure, voided, never a task outcome) and ends the invocation; claude-cli results record
#    reported_models. On exp/ontology-pilot nothing hashed changed. On integration/2026-10 this guard is merged
#    with the cloud port's model pin (claude_cli.py, MODEL PIN), whose CLI contract adds "model_pin" for a full
#    model id: a full-id card's hash differs from the one exp/ontology-pilot planned (an alias contract, and so
#    card 007's recorded hashes, are unchanged).
RUNNER_VERSION = 8
CLI_TIMEOUT_SECONDS = 300  # per attempt, as the OpenRouter client's HTTP timeout
CLI_MAX_TURNS = 1  # the reply is the model's first message; the CLI stops before a second model turn
DEFAULT_OCI_IMAGE = "localhost/reticle-p6-task:py313-v1"
ARMS = {
    "bounded-transcript-v2": BaselineContextPolicy,
    "pressure-recent-v1": PressureRecentContextPolicy,
    "pressure-recent-v2": PressureRecentContextPolicyV2,
    "pressure-recent-v3": PressureRecentContextPolicyV3,
    # E1 cache layout 008: status last, page-wise omission. No runner version change: no existing arm
    # changes, and the arm name is already part of the protocol hash.
    "pressure-recent-v4": PressureRecentContextPolicyV4,
    "reticle-board-v2": ReticleBoardPolicy,
}
OBSERVATION_TOOLS = {
    "glob_files", "search_text",  # toolset v3
    "list_files", "read_file", "outline", "search", "read_output", "search_output",
    "history", "search_history", "read_artifact", "read_note",
}
# Stop labels read from the controller's error prefix. model_mismatch is the claude-cli adapter's model guard.
GUARD_STOPS = ("diagnostic_termination", "attempt_cap_reached", MODEL_MISMATCH)
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3  # the first attempt plus at most two retries (plan section 5.3)
MANAGED_ROOT_FILES = ("conftest.py", "pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml")
# How a task that alters the export (mutation_patch, hidden_paths) is materialized; part of its task contract.
# v1 (352c1ae-fd9a108): patched and hidden paths in place; the mutated file and its directory kept the time of
#     git apply, so `ls -lt` or `find -newer` in the workspace named the mutated file.
# v2: built in a staging directory, copied into the workspace, every file and directory stamped with the commit time.
MATERIALIZER_VERSION = "mutation-workspace-v2"
UNPINNED_ROUTING = {"require_parameters": True}

INSTRUCTIONS = (
    "You are working in a source checkout of {repo} ({repo_url}) at an upstream commit. "
    "The following problem was reported:\n\n{statement}\n\n"
    "Change the library so the reported behavior is correct. Hidden upstream tests will be run on "
    "your final workspace; tests you add or edit are not used for acceptance, but you may write and "
    "run tests to check your work (for example `pytest tests/test_example.py -q` with the run tool). "
    "Call finish when you are done."
)


TREATMENT_FLAGS = ("--completion", "--nudge", "--nudge-fraction", "--oracle", "--verifier", "--verifier-manifest",
                   "--reasoning")
VERIFIER_RUNNER = HERE / "run_repro_test.py"


def add_treatment_arguments(parser) -> None:
    group = parser.add_argument_group("treatments (off by default; each one that is on enters the protocol hash)")
    group.add_argument("--reasoning", choices=["memory", "symbolic", "injected"], default=None,
                       help="durable evidence ontology; symbolic also offers advisory inference rules; injected "
                            "also appends a bounded advisory summary to edit and run results")
    group.add_argument("--completion", choices=["finish-guard"], default=None,
                       help="finish-guard: reject the first finish after a source edit, once, unless a "
                            "command that failed before the edit passes after it")
    group.add_argument("--nudge", choices=["midpoint", "commit"], default=None,
                       help="midpoint: one harness message when --nudge-fraction of the responses are spent "
                            "without a source edit; commit: one harness message at --nudge-fraction, edits or not, "
                            "asking for a committed hypothesis and a tested prediction (adds two recording tools)")
    group.add_argument("--nudge-fraction", type=float, default=None, metavar="F",
                       help="share of the response budget after which the --nudge message is due (default 0.5)")
    group.add_argument("--oracle", default=None, metavar="hidden-tests[:K]",
                       help="a check() tool: hidden fail_to_pass counts only, at most K calls per run "
                            f"(default {DEFAULT_MAX_CALLS})")
    group.add_argument("--verifier", default=None, metavar="repro-test[:K]",
                       help="a check() tool over the task's frozen reproduction test (--verifier-manifest): counts "
                            f"only, at most K calls per run (default {VERIFIER_DEFAULT_MAX_CALLS}); not with --oracle")
    group.add_argument("--verifier-manifest", default=None, metavar="MANIFEST.json",
                       help="the manifest of frozen reproduction tests (repro_verifiers.py generate); its sha256 "
                            "enters the protocol hash")


def treatments_record(args) -> dict:
    """The description of every treatment that is on, as hashed and recorded; {} when all are off."""
    record = {}
    if getattr(args, "reasoning", None):
        record["reasoning"] = {**reasoning_contract(args.reasoning), "tools": tool_contract()}
    if args.completion == "finish-guard":
        record["completion"] = {
            "name": "finish-guard", "version": FINISH_GUARD_VERSION, "source_rule": SOURCE_RULE_VERSION,
            "rule": "fail-then-pass", "rejection": FINISH_GUARD_MESSAGE, "reasons": REASONS,
        }
    if args.nudge_fraction is not None and args.nudge is None:
        raise SystemExit("--nudge-fraction needs --nudge midpoint or --nudge commit")
    if args.nudge == "midpoint":
        fraction = 0.5 if args.nudge_fraction is None else args.nudge_fraction
        if not 0 < fraction < 1:
            raise SystemExit(f"--nudge-fraction must be between 0 and 1, not {fraction}")
        record["nudge"] = {
            "name": "midpoint", "version": MIDPOINT_NUDGE_VERSION, "source_rule": SOURCE_RULE_VERSION,
            "fraction": fraction, "template": MIDPOINT_NUDGE_TEMPLATE, "text": midpoint_nudge_text(fraction),
            "role": "system", "placement": "after the latest tool results, once per run",
        }
    if args.nudge == "commit":
        fraction = 0.5 if args.nudge_fraction is None else args.nudge_fraction
        if not 0 < fraction < 1:
            raise SystemExit(f"--nudge-fraction must be between 0 and 1, not {fraction}")
        record["nudge"] = {
            "name": "commit", "version": COMMIT_NUDGE_VERSION, "fraction": fraction,
            "template": COMMIT_NUDGE_TEMPLATE, "text": commit_nudge_text(fraction), "role": "system",
            "placement": "after the latest tool results, once per run, whether or not a source file was edited",
            "tools": {"version": COMMITMENT_TOOLS_VERSION,
                      "names": [schema["function"]["name"] for schema in commitment_schemas()]},
        }
    if args.oracle is not None:
        match = re.fullmatch(r"hidden-tests(?::(\d+))?", args.oracle)
        calls = int(match.group(1) or DEFAULT_MAX_CALLS) if match else 0
        if calls < 1:
            raise SystemExit(f"--oracle must be hidden-tests or hidden-tests:K with K >= 1, not {args.oracle!r}")
        record["oracle"] = {
            "name": "hidden-tests", "version": ORACLE_VERSION, "max_calls": calls,
            "returns": ["failing", "passing", "calls_left"], "scope": "fail_to_pass",
        }
    if args.verifier_manifest is not None and args.verifier is None:
        raise SystemExit("--verifier-manifest needs --verifier repro-test[:K]")
    if args.verifier is not None:
        if args.oracle is not None:
            raise SystemExit("--verifier and --oracle both offer check(); use one")
        match = re.fullmatch(r"repro-test(?::(\d+))?", args.verifier)
        calls = int(match.group(1) or VERIFIER_DEFAULT_MAX_CALLS) if match else 0
        if calls < 1:
            raise SystemExit(f"--verifier must be repro-test or repro-test:K with K >= 1, not {args.verifier!r}")
        if args.verifier_manifest is None:
            raise SystemExit("--verifier needs --verifier-manifest")
        manifest = resolve_repo_path(args.verifier_manifest)
        record["verifier"] = {
            "name": "repro-test", "version": VERIFIER_VERSION, "max_calls": calls,
            "returns": ["failing", "passing", "calls_left"],
            "scope": "one reproduction test per task, written before the campaign from the statement and the "
                     "pre-edit workspace, frozen in the manifest",
            "runner_sha256_lf": sha256_lf(VERIFIER_RUNNER),
            "manifest": shown_path(manifest),
            "manifest_sha256_lf": sha256_lf(manifest) if manifest.is_file() else None,
        }
    return record


def resolve_repo_path(value) -> Path:
    """A path as given, or relative to the repository root when it is relative and absent from the working dir."""
    path = Path(value)
    if not path.is_absolute() and not path.exists():
        path = ROOT / path
    return path.resolve()


def shown_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_lf(path: Path) -> str:
    """sha256 of a text file's content with LF line endings (the same on every checkout, whatever core.autocrlf
    wrote to the working copy)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_verifier_manifest(treatments: dict) -> dict:
    """The verifier manifest a run uses; it must still have the sha256 recorded in the treatment (and the hash)."""
    verifier = treatments["verifier"]
    path = resolve_repo_path(verifier["manifest"])
    if verifier["manifest_sha256_lf"] is None or not path.is_file():
        raise SystemExit(f"verifier manifest {verifier['manifest']} does not exist; generate it first "
                         "(experiments/p6_pilot/repro_verifiers.py generate)")
    if sha256_lf(path) != verifier["manifest_sha256_lf"]:
        raise SystemExit(f"verifier manifest {verifier['manifest']} changed since the protocol was hashed")
    return {"path": path, **json.loads(path.read_text(encoding="utf-8"))}


def build_task_verifier(manifest: dict, task_id: str, bundle: Path, python: str, timeout_seconds: float) -> Path:
    """The run's verifier bundle for one task from the manifest; the test's sha256 is checked against it."""
    entry = (manifest.get("tasks") or {}).get(task_id)
    if entry is None:
        raise SystemExit(f"verifier manifest {shown_path(manifest['path'])} has no entry for {task_id}")
    test_file = None
    if entry.get("status") == "available":
        test_file = (Path(manifest["path"]).parent / entry["file"]).resolve()
        if sha256_lf(test_file) != entry["sha256_lf"]:
            raise SystemExit(f"verifier test {entry['file']} does not match its manifest sha256")
    return write_verifier_bundle(bundle, test_file=test_file, python=python, timeout_seconds=timeout_seconds,
                                 runner=VERIFIER_RUNNER, collected=entry.get("collected"))


def treatments_from_args(argv) -> dict:
    """The treatments a list of runner arguments turns on (other arguments are ignored); for run_card.py,
    which plans a card arm's hash from its extra_args."""
    parser = argparse.ArgumentParser(add_help=False)
    add_treatment_arguments(parser)
    known, _ = parser.parse_known_args(list(argv))
    return treatments_record(known)


# claude-cli client options: not treatments (they change how a reply is obtained, not what the model is offered),
# off by default; one that is on changes the CLI contract recorded as the model's routing, so it enters the
# protocol hash there. Other clients accept and ignore them (a card's scripted controls take its arm's extra_args).
CLIENT_FLAGS = ("--cli-reply-recovery",)


def add_client_arguments(parser) -> None:
    group = parser.add_argument_group("claude-cli client options (off by default; one that is on enters the "
                                      "protocol hash through the CLI contract)")
    group.add_argument("--cli-reply-recovery", choices=[REPLY_RECOVERY], default=None,
                       help=f"{REPLY_RECOVERY}: when the CLI cannot parse the model's StructuredOutput input, use "
                            "it if json.loads(raw, strict=False) accepts it; after a rejected StructuredOutput "
                            f"call, run the request's later attempts at --max-turns {RETRY_MAX_TURNS} so the CLI "
                            "returns its rejection for one more model turn; adapter v3 (claude_cli.py)")


def client_options_from_args(argv) -> dict:
    """The claude-cli client options a list of runner arguments turns on ({} when none); for run_card.py."""
    parser = argparse.ArgumentParser(add_help=False)
    add_client_arguments(parser)
    known, _ = parser.parse_known_args(list(argv))
    return {"reply_recovery": known.cli_reply_recovery} if known.cli_reply_recovery else {}


def cli_routing_contract(model: str, version: str, client_options=None) -> dict:
    """The CLI contract recorded as a claude-cli model's routing; exactly v2's with no client option on."""
    recovery = (client_options or {}).get("reply_recovery")
    if recovery is None:
        return cli_contract(model, max_turns=CLI_MAX_TURNS, timeout=CLI_TIMEOUT_SECONDS, version=version)
    return cli_contract(model, max_turns=CLI_MAX_TURNS, timeout=CLI_TIMEOUT_SECONDS, version=version,
                        reply_recovery=recovery)


def model_tool_schemas(treatments: dict) -> list:
    """The tool schemas the model is offered: the toolset's, plus check() when the oracle or the verifier is on,
    then the reasoning tools when the evidence ontology is on, then the commitment tools when the commitment nudge
    is on (the order build_tools' mixins give)."""
    extra = []
    if "oracle" in treatments:
        extra.append(check_schema(treatments["oracle"]["max_calls"]))
    if "verifier" in treatments:
        extra.append(verifier_schema(treatments["verifier"]["max_calls"]))
    if "reasoning" in treatments:
        extra.extend(REASONING_SCHEMAS)
    if (treatments.get("nudge") or {}).get("name") == "commit":
        extra.extend(commitment_schemas())
    return [*TOOL_SCHEMAS, *extra] if extra else TOOL_SCHEMAS


def protocol_hash(arm: str, routing: dict, execution: dict, guards: dict, task_contracts=(), treatments=None) -> str:
    inputs = {
        "runner_version": RUNNER_VERSION, "arm": arm, "instructions": INSTRUCTIONS, "tools": TOOL_SCHEMAS,
        "evaluator": hashlib.sha256((HERE / "evaluate_task.py").read_bytes()).hexdigest(),
        "managed_root_files": MANAGED_ROOT_FILES, "provider_routing": routing, "execution": execution,
        "guards": guards, "toolset_version": TOOLSET_VERSION,
    }
    if task_contracts:  # only tasks that alter the exported tree (mutation tasks); upstream P6 hashes are unchanged
        inputs["task_contracts"] = sorted(task_contracts, key=lambda contract: contract["task_id"])
    if treatments:  # only runs with a treatment on; an incumbent's inputs are exactly as before
        inputs["treatments"] = treatments
        inputs["tools"] = model_tool_schemas(treatments)
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def load_tasks(selection=None):
    """(task file, tasks) for --tasks [FILE.json] [TASK_ID ...]; file order is kept."""
    selection = list(selection or [])
    files = [item for item in selection if item.lower().endswith(".json")]
    if len(files) > 1:
        raise SystemExit(f"--tasks names more than one task file: {files}")
    path = DEFAULT_TASK_FILE
    if files:
        path = Path(files[0])
        if not path.is_absolute() and not path.exists():
            path = ROOT / path
        if not path.is_file():
            raise SystemExit(f"Task file not found: {files[0]}")
    tasks = json.loads(path.read_text(encoding="utf-8"))["tasks"]
    wanted = [item for item in selection if item not in files]
    if wanted:
        unknown = set(wanted) - {t["task_id"] for t in tasks}
        if unknown:
            raise SystemExit(f"Unknown tasks in {path.name}: {sorted(unknown)}")
        tasks = [t for t in tasks if t["task_id"] in wanted]
    return path.resolve(), tasks


def task_file_record(path: Path) -> dict:
    """The task file's path and the sha256 of its content with LF line endings (as committed; the same on
    every checkout, whatever core.autocrlf wrote to the working copy)."""
    try:
        shown = path.relative_to(ROOT).as_posix()
    except ValueError:
        shown = str(path)
    return {"path": shown, "sha256_lf": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def task_contract(task: dict):
    """What a task changes in the exported tree the model is given; None for an upstream P6 task."""
    if not (task.get("mutation_patch") or task.get("hidden_paths") or task.get("hidden_tests")):
        return None
    patch = task.get("mutation_patch")
    return {
        "task_id": task["task_id"],
        "materializer": MATERIALIZER_VERSION,
        "mutation_kind": task.get("mutation_kind"),
        "mutation_file": task.get("mutation_file"),
        "hidden_tests": bool(task.get("hidden_tests")),
        "hidden_paths": list(task.get("hidden_paths") or []),
        "mutation_patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else None,
        "statement_sha256": hashlib.sha256(task["statement"].encode("utf-8")).hexdigest(),
    }


def resolve_execution(backend_name: str, image: str):
    """Return (backend or None for trusted-local, recorded execution contract). Never falls back."""
    if backend_name == "trusted-local":
        return None, {"backend": "trusted-local", "guest_python": str(TASK_PYTHON),
                      "authority": "trusted-local, not host-isolated"}
    engine = IsolatedOCIBackend(image).engine
    inspected = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", image],
                               capture_output=True, text=True)
    if inspected.returncode or not inspected.stdout.strip():
        raise SystemExit(f"OCI image {image} is not available: {inspected.stderr.strip()}")
    image_id = inspected.stdout.strip()
    backend = IsolatedOCIBackend(image_id, engine=engine)
    available, detail = backend.availability()
    if not available:
        raise SystemExit(detail)
    return backend, {"backend": "isolated-oci", "image": image, "image_id": image_id, "guest_python": "python",
                     "container_user_arguments": backend.user_arguments(),
                     "authority": "isolated OCI: task workspace mount only, no network, unprivileged user"}


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


def apply_mutation(workspace: Path, patch: str) -> None:
    """git apply a task's mutation_patch to the exported tree, then check that the patch is present.

    The workspace is not a repository but sits inside one (runs/ is in this checkout). The ceiling stops git
    from discovering that repository, whose .gitattributes would otherwise rewrite the patched file's line
    endings; autocrlf off keeps LF files LF on Windows.
    """
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    environment["GIT_CEILING_DIRECTORIES"] = str(workspace.resolve().parent)
    command = ["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn"]
    for check, failure in (([], "does not apply"), (["--reverse", "--check"], "is not present after git apply")):
        completed = subprocess.run([*command, *check, "-"], input=patch.encode("utf-8"), cwd=workspace,
                                   env=environment, capture_output=True)
        if completed.returncode:
            raise RuntimeError(f"mutation_patch {failure}: {completed.stderr.decode('utf-8', 'replace')[-500:]}")


def remove_hidden_paths(workspace: Path, hidden_paths, hidden_tests: bool) -> None:
    """Delete the paths the model must not see (a mutation task's test root); each must exist in the export."""
    if hidden_tests and not hidden_paths:
        raise ValueError("hidden_tests is set but hidden_paths is empty")
    root = workspace.resolve()
    for name in hidden_paths:
        target = (root / name).resolve()
        if Path(name).is_absolute() or target == root or root not in target.parents:
            raise ValueError(f"hidden path {name!r} is not inside the workspace")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise ValueError(f"hidden path {name!r} is not in the exported tree")


def stamp_tree(root: Path, timestamp: float) -> None:
    """Give the root and every file and directory under it one access and modification time."""
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            os.utime(path, (timestamp, timestamp))


def materialize_workspace(task: dict, repo: Path, workspace: Path) -> None:
    """Export the pre-fix tree without git history, so later commits are not visible.

    For a mutation task the export is the healthy tree: its mutation_patch is applied and its hidden_paths
    are removed, so the model gets the bug without the tests that detect it. build_evaluator installs those
    test roots from fix_commit for acceptance. That tree is built in a sibling staging directory and copied
    into the workspace, and every file and directory gets the commit time (as git archive gives the rest), so
    no timestamp marks the edited file or the removed paths.
    """
    exported = io.BytesIO(git(repo, "archive", "--format=tar", task["base_commit"]))
    if task_contract(task) is None:
        workspace.mkdir(parents=True)
        with tarfile.open(fileobj=exported) as archive:
            archive.extractall(workspace, filter="data")
        provision_version_stub(workspace)
        return
    if workspace.exists():
        raise FileExistsError(f"workspace already exists: {workspace}")
    staging = workspace.with_name(workspace.name + ".staging")
    staging.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=exported) as archive:
            archive.extractall(staging, filter="data")
            commit_time = max(member.mtime for member in archive.getmembers())
        if task.get("mutation_patch"):
            apply_mutation(staging, task["mutation_patch"])
        remove_hidden_paths(staging, task.get("hidden_paths") or [], bool(task.get("hidden_tests")))
        provision_version_stub(staging)
        shutil.copytree(staging, workspace, symlinks=True)
        stamp_tree(workspace, commit_time)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_evaluator(task: dict, repo: Path, bundle: Path, pytest_timeout: int, python: str) -> str:
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
        "python": python,  # interpreter as seen by the evaluator process (guest path under OCI)
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

    def check(self) -> None:
        if self.used >= self.maximum:
            raise BudgetExceeded(f"--max-total-calls {self.maximum} reached")

    def take(self) -> None:
        self.check()
        self.used += 1


class RepeatGuardTools(ToolSuite):
    """The shared tools, flagging three identical observation calls without a workspace change."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen: dict = {}
        self.diagnostic = None

    def dispatch(self, name, arguments, call_id):
        outcome = super().dispatch(name, arguments, call_id)
        if name in OBSERVATION_TOOLS:
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed = arguments
            key = json.dumps([name, parsed, self.runtime.workspace.revision()], sort_keys=True, default=str)
            self.seen[key] = self.seen.get(key, 0) + 1
            if self.seen[key] >= 3 and self.diagnostic is None:
                self.diagnostic = f"three identical {name} calls without a workspace change"
        return outcome


class GuardedClient:
    """Stops that are not task resources: repeated observations and the campaign attempt cap.

    Attempts, tool actions, active time, and cost are durable task budgets enforced by the
    controller's ledger. Each stop here ends the run as a recorded model error, so resume
    never sees an ambiguous request.
    """

    def __init__(self, inner, tools, stop_on_repeats=False):
        self.inner, self.tools, self.stop_on_repeats = inner, tools, stop_on_repeats

    @property
    def reports_provider_attempts(self) -> bool:
        return getattr(self.inner, "reports_provider_attempts", False) is True

    def complete(self, messages, tools, **kwargs) -> ModelResponse:
        if self.stop_on_repeats and getattr(self.tools, "diagnostic", None):
            raise ModelClientError(f"diagnostic_termination: {self.tools.diagnostic}")
        try:
            return self.inner.complete(messages, tools, **kwargs)
        except BudgetExceeded as exc:
            raise ModelClientError(f"attempt_cap_reached: {exc}") from None


def guard_stop_label(agent: dict) -> str:
    """The guard that stopped a run, or the controller stop reason."""
    error = agent.get("error") or ""
    return next((label for label in GUARD_STOPS if error.startswith(label)), agent.get("stop_reason", ""))


def is_provider_stop(agent: dict) -> bool:
    """A request that exhausted its retries on retryable provider failures (429/5xx, network, error bodies)."""
    return agent.get("stop_reason") == "model_error" and (agent.get("error") or "").startswith("failed after")


def build_tools(runtime, treatments: dict, base_class, *, evaluator_root=None, oracle_timeout_seconds=None,
                verifier_root=None, **suite_arguments):
    """The run's tool suite with each tool-level treatment that is on composed in as a mixin, and the per-run
    state object of every treatment (each has record()). With no treatment it is base_class itself. The oracle
    runs the evaluator bundle at evaluator_root, the verifier the bundle at verifier_root, through the suite's
    backend. Each mixin appends its schemas after those of the classes after it in the MRO, so the commitment
    tools (first in the list) come last, as model_tool_schemas lists them."""
    mixins, extra, state = [], {}, {}
    if "reasoning" in treatments:
        state["reasoning"] = extra["reasoning"] = EvidenceOntology(runtime, treatments["reasoning"]["mode"])
        mixins.append(ReasoningTools)
    if "completion" in treatments:
        state["completion"] = extra["finish_guard"] = FinishGuard(runtime, SourceEditTracker(runtime.workspace))
        mixins.append(FinishGuardTools)
    if "oracle" in treatments:
        timeout = {} if oracle_timeout_seconds is None else {"timeout_seconds": oracle_timeout_seconds}
        state["oracle"] = extra["oracle"] = HiddenTestOracle(
            runtime, suite_arguments.get("backend"), evaluator_root, max_calls=treatments["oracle"]["max_calls"],
            **timeout)
        mixins.append(CheckOracleTools)
    if "verifier" in treatments:
        timeout = {} if oracle_timeout_seconds is None else {"timeout_seconds": oracle_timeout_seconds}
        state["verifier"] = extra["oracle"] = ReproTestVerifier(
            runtime, suite_arguments.get("backend"), verifier_root, max_calls=treatments["verifier"]["max_calls"],
            **timeout)
        mixins.append(CheckOracleTools)
    if (treatments.get("nudge") or {}).get("name") == "commit":
        state["commitment"] = extra["commitment"] = CommitmentLog(runtime)
        mixins.insert(0, CommitmentTools)
    tool_class = type(f"Treated{base_class.__name__}", (*mixins, base_class), {}) if mixins else base_class
    return tool_class(runtime, **suite_arguments, **extra), state


def build_interventions(runtime, treatments: dict, state: dict) -> list:
    """The agent-loop treatments that are on, for the controller; each one's state is added to state."""
    interventions = []
    if (treatments.get("nudge") or {}).get("name") == "midpoint":
        state["nudge"] = MidpointNudge(SourceEditTracker(runtime.workspace), treatments["nudge"]["fraction"])
        interventions.append(state["nudge"])
    elif (treatments.get("nudge") or {}).get("name") == "commit":
        state["nudge"] = CommitmentNudge(treatments["nudge"]["fraction"])
        interventions.append(state["nudge"])
    return interventions


def run_invocations(runtime, envelope, tools, client, limits, policy_factory, max_resumes=0,
                    wait_seconds=0.0, sleep=time.sleep, interventions=()) -> list:
    """Run the controller, resuming the same durable session after provider stops.

    The transcript, task budgets, and pending work persist across invocations. The wait is paused
    time and is not charged to active_seconds. Every other stop reason ends the run immediately.
    """
    invocations = []
    while True:
        agent = AgentController(runtime, envelope, tools, client, limits, policy=policy_factory(),
                                interventions=interventions).run().to_dict()
        invocations.append(agent)
        if not is_provider_stop(agent) or len(invocations) > max_resumes:
            return invocations
        runtime.journal.append("runner_resume_scheduled", {
            "task_id": envelope.task_id, "after_invocation": len(invocations),
            "wait_seconds": wait_seconds, "error": agent.get("error"),
        })
        sleep(wait_seconds)


class OpenRouterClient:
    """Every HTTP attempt is appended to calls.jsonl. When the controller passes a
    ProviderAttemptRecorder, each attempt is also reserved before dispatch and reconciled after."""

    reports_provider_attempts = True

    def __init__(self, api_key: str, model: str, calls_path: Path, run_id: str, budget: CallBudget,
                 max_tokens: int, routing: dict, timeout: int = 300, base_url: str = BASE_URL,
                 backoff_seconds: float = 5.0):
        self.api_key, self.model, self.calls_path, self.run_id = api_key, model, calls_path, run_id
        self.budget, self.max_tokens, self.routing, self.timeout = budget, max_tokens, routing, timeout
        self.base_url, self.backoff_seconds = base_url.rstrip("/"), backoff_seconds
        self.call_index = 0

    def complete(self, messages, tools, *, attempts=None) -> ModelResponse:
        self.call_index += 1
        body = {
            "model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
            "temperature": 0, "max_tokens": self.max_tokens, "provider": self.routing,
        }
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_sha256 = hashlib.sha256(raw).hexdigest()
        last_error = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # Check the campaign cap, then reserve the task resources, then consume the campaign
            # unit, so neither ledger records an attempt that was never dispatched.
            self.budget.check()
            attempt_id = attempts.begin({
                "call_index": self.call_index, "attempt": attempt, "request_sha256": request_sha256,
            }) if attempts is not None else None
            self.budget.take()
            entry = {"time": utc_now(), "run_id": self.run_id, "model": self.model, "call_index": self.call_index,
                     "attempt": attempt, "provider_attempt_id": attempt_id, "request_sha256": request_sha256,
                     "request": body}
            started = time.time()
            data, retry, failure = None, False, None
            try:
                request = urllib.request.Request(f"{self.base_url}/chat/completions", data=raw, method="POST", headers={
                    "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                entry["response"] = data
                if data.get("error") or not data.get("choices"):
                    last_error, retry, failure = json.dumps(data.get("error") or data)[:500], True, "error_body"
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1_000]
                entry.update(http_status=exc.code, error=detail)
                last_error, retry = f"HTTP {exc.code}: {detail[:300]}", exc.code in RETRYABLE_HTTP
                failure = f"http_{exc.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                entry["error"] = repr(exc)
                last_error, retry, failure = repr(exc), True, "network_error"
            except ValueError as exc:  # a response body that is not JSON
                entry["error"] = repr(exc)
                last_error, retry, failure = repr(exc), True, "invalid_json"
            finally:
                entry["latency_s"] = round(time.time() - started, 2)
                append_jsonl(self.calls_path, entry)
            if failure is not None:
                if attempts is not None:
                    cost = ((data or {}).get("usage") or {}).get("cost")
                    attempts.finish(attempt_id, outcome=failure, cost=cost, metadata={"error": last_error[:300]})
                if not retry:
                    raise ModelClientError(last_error)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(min(60, self.backoff_seconds * 2 ** (attempt - 1)))
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


class ScriptedRunClient:
    """Runs one command through the run tool without editing files, then finishes."""

    def __init__(self, command: str, summary: str):
        self.command, self.summary, self.calls = command, summary, 0

    def complete(self, messages, tools) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            call = {"id": "scripted_run", "type": "function", "function": {
                "name": "run", "arguments": json.dumps({"command": self.command, "timeout_seconds": 600})}}
        else:
            call = {"id": "scripted_finish", "type": "function", "function": {
                "name": "finish", "arguments": json.dumps({"summary": self.summary})}}
        return ModelResponse({"role": "assistant", "content": None, "tool_calls": [call]})


def scripted_client(kind: str, task: dict, repo: Path):
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
    if kind == "tester":
        roots = sorted({path.split("/", 1)[0] for path in task["evaluator_test_files"] if "/" in path})
        return ScriptedRunClient(f"pytest -q {' '.join(roots)}", "ran the existing tests without changes")
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
    parser.add_argument("--client", required=True,
                        choices=["openrouter", "claude-cli", "gold", "noop", "breaker", "gamer", "tester"])
    parser.add_argument("--backend", default="trusted-local", choices=["trusted-local", "oci"])
    parser.add_argument("--oci-image", default=DEFAULT_OCI_IMAGE)
    parser.add_argument("--arm", default="bounded-transcript-v2", choices=sorted(ARMS))
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--provider", action="append", default=[], metavar="MODEL=SLUG",
                        help="pin a model to one OpenRouter provider, no fallbacks (repeatable)")
    parser.add_argument("--tasks", nargs="*", default=None, metavar="FILE.json|TASK_ID",
                        help="an argument ending in .json names the task file (default experiments/p6_pilot/"
                             "tasks.json); the others select task ids from it (default: all)")
    parser.add_argument("--max-calls-per-run", type=int, default=25)
    parser.add_argument("--max-context-bytes", type=int, default=80_000)
    parser.add_argument("--max-tokens", type=int, default=8_192)
    parser.add_argument("--max-total-calls", type=int, default=None)
    parser.add_argument("--pytest-timeout", type=int, default=600)
    parser.add_argument("--max-attempts-per-run", type=int, default=None,
                        help="durable task budget: HTTP attempts per run, retries included")
    parser.add_argument("--max-tool-actions-per-run", type=int, default=None, help="durable task budget")
    parser.add_argument("--elapsed-cap-seconds", type=float, default=None,
                        help="durable task budget: active seconds per run, checked at each dispatch")
    parser.add_argument("--cost-ceiling-usd", type=float, default=None,
                        help="durable task budget: USD per run; each attempt first reserves a worst case")
    parser.add_argument("--attempt-cost-reservation-usd", type=float, default=None,
                        help="per-attempt reservation with --cost-ceiling-usd (default: pinned endpoint worst case)")
    parser.add_argument("--resume-after-provider-stop", type=int, default=0, metavar="N",
                        help="resume the same session up to N times after a request exhausts its retries on provider errors")
    parser.add_argument("--resume-wait-seconds", type=float, default=300.0,
                        help="paused wait before each resume (not charged to active_seconds)")
    parser.add_argument("--stop-on-repeats", action="store_true",
                        help="stop a run after three identical observation calls without a workspace change")
    parser.add_argument("--dry-run", action="store_true")
    add_treatment_arguments(parser)
    add_client_arguments(parser)
    args = parser.parse_args()
    treatments = treatments_record(args)
    client_options = ({"reply_recovery": args.cli_reply_recovery}
                      if args.cli_reply_recovery and args.client == "claude-cli" else {})

    task_file, tasks = load_tasks(args.tasks)
    contracts = [c for c in (task_contract(t) for t in tasks) if c is not None]
    verifier_manifest = load_verifier_manifest(treatments) if "verifier" in treatments and not args.dry_run else None
    live = args.client in ("openrouter", "claude-cli")
    if live:
        if not args.models:
            raise SystemExit(f"--models is required for the {args.client} client")
        models = args.models
    else:
        models = [f"{args.client}-client"]
    pins = {}
    for item in args.provider:
        model, _, provider_slug = item.partition("=")
        if args.client == "claude-cli":
            raise SystemExit("--provider applies to the openrouter client only")
        if model not in models or not provider_slug:
            raise SystemExit(f"--provider {item!r} must be MODEL=SLUG for a model in --models")
        pins[model] = provider_slug.lower()
    if args.client == "claude-cli":
        for model in models:
            problem = model_id_problem(model)
            if problem and not args.dry_run:
                raise SystemExit(f"--models: {problem}")
            if problem:  # a dry run may still plan an alias, so the hashes of runs made before the rule replay
                print(f"warning: {problem}; a live run would refuse it")
        version = cli_version()
        routing = {model: cli_routing_contract(model, version, client_options) for model in models}
    else:
        routing = {model: ({"order": [pins[model]], "allow_fallbacks": False, "require_parameters": True}
                           if model in pins else dict(UNPINNED_ROUTING)) for model in models}
    arm = args.arm
    backend, execution = resolve_execution(args.backend, args.oci_image)
    guards = {"stop_on_repeats": args.stop_on_repeats,
              "resume_after_provider_stop": args.resume_after_provider_stop,
              "resume_wait_seconds": args.resume_wait_seconds if args.resume_after_provider_stop else None}
    arm_hash = protocol_hash(arm, routing, execution, guards, contracts, treatments)
    runs = [(task, model) for model in models for task in tasks]

    run_dir = HERE / "runs" / args.run_name
    config = {
        "runner_version": RUNNER_VERSION, "protocol_hash": arm_hash, "arm": arm, "client": args.client,
        "models": models, "provider_routing": routing, "tasks": [t["task_id"] for t in tasks],
        "task_file": task_file_record(task_file), "task_contracts": contracts,
        "max_calls_per_run": args.max_calls_per_run, "max_context_bytes": args.max_context_bytes,
        "max_tokens": args.max_tokens, "pytest_timeout_seconds": args.pytest_timeout, "temperature": 0,
        "max_attempts_per_call": MAX_ATTEMPTS, "max_total_calls": args.max_total_calls,
        "instructions": INSTRUCTIONS, "tools": model_tool_schemas(treatments), "toolset_version": TOOLSET_VERSION,
        "execution": execution, "guards": guards,
    }
    if treatments:  # absent when every treatment is off, so an incumbent's config.json is unchanged
        config["treatments"] = treatments

    worst_case_per_call = {}
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
        print(f"per-run guards: {json.dumps(guards)}; backend {execution['backend']}")
        for model in models:
            price = pricing[model]
            input_tokens = args.max_context_bytes / 3  # planning bound only; billing uses reported usage.cost
            per_call = (input_tokens * price["prompt_usd_per_mtok"] + args.max_tokens * price["completion_usd_per_mtok"]) / 1e6
            worst_case_per_call[model] = per_call
            where = f"pinned to {pins[model]} ({price.get('quantization')})" if model in pins else "unpinned routing"
            print(f"  {model} [{where}]: ${price['prompt_usd_per_mtok']:.3f}/M in, ${price['completion_usd_per_mtok']:.3f}/M out; "
                  f"worst case <= ${per_call:.4f}/call, <= ${per_call * args.max_calls_per_run * len(tasks):.2f} for its runs")
            if args.max_total_calls:
                print(f"    with --max-total-calls={args.max_total_calls} HTTP attempts: worst case <= "
                      f"${per_call * args.max_total_calls:.4f} for this invocation")
        config["pricing_at_plan_time"] = pricing
        if not args.dry_run:
            if args.max_total_calls is None:
                raise SystemExit("--max-total-calls is required for live runs")
            api_key = load_openrouter_key()
            if not api_key:
                raise SystemExit("OPENROUTER_API_KEY not found in experiments/.env, .env, or the environment.")
    elif args.client == "claude-cli":
        print(f"{len(runs)} runs ({len(tasks)} tasks x {len(models)} models), arm {arm}, protocol {arm_hash}")
        print(f"claude-cli {routing[models[0]]['cli_version']}: at most {args.max_calls_per_run} responses per run; "
              f"every CLI attempt counts toward --max-total-calls={args.max_total_calls}; billing unknown "
              f"(local subscription login, no API key)")
        print(f"per-run guards: {json.dumps(guards)}; backend {execution['backend']}")
        if not args.dry_run and args.max_total_calls is None:
            raise SystemExit("--max-total-calls is required for live runs")
    elif args.dry_run:
        print(f"{len(runs)} runs with the {args.client} client, arm {arm}; no API calls")

    run_budgets = {}
    for model in models:
        reservation = args.attempt_cost_reservation_usd
        if args.cost_ceiling_usd is not None and reservation is None:
            if model not in worst_case_per_call:
                raise SystemExit("--attempt-cost-reservation-usd is required with --cost-ceiling-usd "
                                 "for scripted clients")
            reservation = math.ceil(worst_case_per_call[model] * 1_000_000) / 1_000_000
        budgets = {"model_responses": args.max_calls_per_run, "context_bytes": args.max_context_bytes}
        optional = {
            "model_attempts": args.max_attempts_per_run, "tool_actions": args.max_tool_actions_per_run,
            "active_seconds": args.elapsed_cap_seconds, "cost_usd": args.cost_ceiling_usd,
            "model_attempt_cost_reservation": reservation if args.cost_ceiling_usd is not None else None,
        }
        budgets.update({key: value for key, value in optional.items() if value is not None})
        run_budgets[model] = budgets
    config["budgets_per_run"] = run_budgets
    print(f"task budgets per run: {json.dumps(run_budgets)}")
    if treatments:
        print("treatments (in the protocol hash): " + "; ".join(
            f"{surface} {value['name']} {value['version']}" + (f" mode={value['mode']}" if "mode" in value else "")
            for surface, value in sorted(treatments.items())))
    if client_options:
        print(f"claude-cli reply recovery {client_options['reply_recovery']} (adapter "
              f"{routing[models[0]]['adapter_version']}: --max-turns {CLI_MAX_TURNS}, {RETRY_MAX_TURNS} on retries "
              f"after a rejected StructuredOutput call; in the protocol hash)")
    elif args.cli_reply_recovery:
        print(f"--cli-reply-recovery applies to the claude-cli client only; the {args.client} client ignores it")
    if args.dry_run:
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
        version = build_evaluator(task, repo, bundle, args.pytest_timeout, execution["guest_python"])
        verifier_root = None
        if verifier_manifest is not None:
            verifier_root = build_task_verifier(verifier_manifest, task["task_id"], run_root / "verifier",
                                                execution["guest_python"], args.pytest_timeout)
        runtime = LocalRuntime(run_root / "session", workspace)
        initial_revision = runtime.workspace.revision()
        src = workspace / "src"
        if backend is None:
            python_path = str(src if src.is_dir() else workspace)
        else:
            python_path = "/workspace/src" if src.is_dir() else "/workspace"  # guest path of the same tree
        tools, treatment_state = build_tools(
            runtime, treatments, RepeatGuardTools if args.stop_on_repeats else ToolSuite,
            evaluator_root=bundle, oracle_timeout_seconds=args.pytest_timeout + 120,  # as final acceptance
            verifier_root=verifier_root,
            interpreter=execution["guest_python"], backend=backend, environment={
                "PYTHONPATH": python_path, "PYTHONIOENCODING": "utf-8"})
        interventions = build_interventions(runtime, treatments, treatment_state)
        envelope = TaskEnvelope(
            task_id=task["task_id"],
            description=INSTRUCTIONS.format(repo=task["repo"], repo_url=task["repo_url"], statement=task["statement"]),
            criteria=[{"id": "hidden-upstream-tests", "kind": "executable", "visibility": "hidden"}],
            authority={"filesystem": "task workspace", "execution": execution["authority"],
                       "network": "not provided to tasks"},
            budgets=run_budgets[model],
        )
        if args.client == "openrouter":
            inner = OpenRouterClient(api_key, model, calls_path, run_id, budget, args.max_tokens, routing[model])
        elif args.client == "claude-cli":
            inner = ClaudeCliClient(model, calls_path, run_id, budget, max_attempts=MAX_ATTEMPTS,
                                    timeout=CLI_TIMEOUT_SECONDS, max_turns=CLI_MAX_TURNS,
                                    **({"reply_recovery": client_options["reply_recovery"]} if client_options else {}))
        else:
            inner = scripted_client(args.client, task, repo)
        client = GuardedClient(inner, tools, args.stop_on_repeats)
        attempts_before = len(read_jsonl(calls_path))

        started = time.time()
        record = {"run_id": run_id, "task_id": task["task_id"], "model": model, "client": args.client, "arm": arm,
                  "protocol_hash": arm_hash, "started_at": utc_now(), "session_dir": str(run_root.relative_to(HERE))}
        budget_stop = None
        try:
            invocations = run_invocations(
                runtime, envelope, tools, client, AgentLimits(args.max_calls_per_run, args.max_context_bytes),
                ARMS[arm], args.resume_after_provider_stop, args.resume_wait_seconds, interventions=interventions,
            )
        except BudgetExceeded as exc:
            budget_stop = str(exc)
            invocations = [{"stop_reason": "pilot_call_budget_exhausted", "error": budget_stop}]
        record["agent"] = invocations[-1]  # its task_resources are cumulative across invocations
        record["invocations"] = [{"stop_reason": i.get("stop_reason"), "error": i.get("error"),
                                  "model_calls": i.get("model_calls"), "provider_attempts": i.get("provider_attempts"),
                                  "tool_calls": i.get("tool_calls")} for i in invocations]
        record["totals"] = {key: sum(i.get(key) or 0 for i in invocations)
                            for key in ("model_calls", "provider_attempts", "tool_calls")}
        record["stop"] = guard_stop_label(record["agent"])
        if record["stop"] == "attempt_cap_reached":
            budget_stop = record["agent"].get("error")
        # None when no call reported a cost (scripted clients), so a missing bill never reads as $0.
        costs = [(i.get("usage_reported") or {}).get("cost") for i in invocations
                 if (i.get("calls_missing_usage") or {}).get("cost", 0) < (i.get("model_calls") or 0)]
        record["reported_cost_usd"] = round(sum(costs), 8) if costs else None
        if treatments:  # absent for an incumbent run, whose record is unchanged
            record["treatments"] = {surface: state.record() for surface, state in treatment_state.items()}
        if client_options:  # absent unless reply recovery is on: what it did in this run's attempts
            record["cli_reply_recovery"] = inner.recovery_summary()
        run_calls = read_jsonl(calls_path)[attempts_before:]
        record["http_attempts"] = len(run_calls)
        if args.client == "claude-cli":  # every model ID the CLI reported for this run (one, unless drifted)
            record["reported_models"] = sorted({m for row in run_calls for m in row.get("reported_models") or []})
            if record["stop"] == MODEL_MISMATCH:
                record["model_mismatch"] = {"expected": model, "reported": record["reported_models"]}
        record["tool_results"] = [
            {"call_id": m.get("tool_call_id"), "head": m["content"][:300], "tail": m["content"][-300:]}
            for m in TranscriptStore(runtime).load() if m.get("role") == "tool"
        ]
        decision = AcceptanceRunner(runtime, backend).evaluate(
            acceptance_plan(task, version), evaluator_root=bundle, timeout_seconds=args.pytest_timeout + 120)
        record["initial_workspace_revision"] = initial_revision
        record["acceptance"] = {"status": decision.status, "criterion_outcomes": decision.criterion_outcomes,
                                "report_artifact_id": decision.report_artifact_id,
                                **evaluator_details(runtime, decision.report_artifact_id)}
        record["elapsed_s"] = round(time.time() - started, 1)
        append_jsonl(results_path, record)
        print(f"{run_id}: {record['stop']} -> {decision.status} {decision.criterion_outcomes}", flush=True)
        if budget_stop:
            print(f"Stopping: {budget_stop}")
            break
        if record["stop"] == MODEL_MISMATCH:  # every later run would meet the same model; void this one and stop
            print(f"Stopping: {record['agent'].get('error')}")
            break


if __name__ == "__main__":
    main()
