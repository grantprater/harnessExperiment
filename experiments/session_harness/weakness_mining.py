"""Failure signatures and clusters for recorded repair runs (S6b weakness mining), from the session journal.

Per run this computes, from the journal only (events.jsonl and the artifact store it references):

- the verifier cause: why the evaluator's verdict came out as it did (one value, first match wins; see
  `verifier_cause`);
- the causal status: flags for rejected calls, repeated calls, the repeat stop, an edit outside the gold
  files, and no verification before finish;
- rule phase labels, one per assistant response (explore, reproduce, edit, verify, finish, stuck, other;
  the rules never emit `diagnose`, which needs judgement), and the run labels of
  `labels/SCHEMA.md` (first edit response, verified before finish, edit in gold files, mechanism).

The failure signature is (verifier cause, causal status, mechanism). Runs are clustered on the exact
signature and clusters are ranked by distinct-task support, then run support.

Inputs other than the journal: the task file supplies `gold_source_files` (the hidden gold patch's files are
not in the journal; only `edit_outside_gold` and `edit_in_gold_files` need them). `results.jsonl` is read only
to cross-check the journal's stop reason and acceptance; `calls.jsonl` is not read. A Claude Code native run
directory (`stream.jsonl` + `result.json`, from `native_control.py`) has no Reticle journal; it is read from
its stream and result file instead and marked as such.

Usage:
  python experiments/session_harness/weakness_mining.py RUN_DIR [RUN_DIR ...] [--tasks FILE ...] [--json]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_FILES = (
    ROOT / "experiments" / "p6_pilot" / "tasks.json",
    ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json",
)

PHASES = ("explore", "reproduce", "diagnose", "edit", "verify", "finish", "stuck", "other")
# A response with several calls takes the most advanced phase among its non-repeated calls.
PRECEDENCE = ("finish", "edit", "verify", "reproduce", "diagnose", "explore", "other")

EXPLORE_TOOLS = {
    "list_files", "glob_files", "read_file", "outline", "search", "search_text", "read_output", "search_output",
    "Read", "Grep", "Glob", "LS",  # Claude Code
}
EDIT_TOOLS = {"write_file", "replace_text", "Write", "Edit", "MultiEdit", "NotebookEdit"}
CREATE_TOOLS = {"write_file", "Write"}  # may create a new file; the others need an existing one
RUN_TOOLS = {"run", "Bash", "PowerShell"}
FINISH_TOOLS = {"finish"}
# Everything else (history, search_history, read_artifact, note, read_note, TodoWrite, ...) is `other`.

EXPLORE_COMMANDS = {
    "ls", "dir", "cat", "head", "tail", "less", "more", "grep", "rg", "find", "pwd", "echo", "wc", "tree",
    "type", "which", "where", "git", "get-childitem", "get-content", "select-string",
}
SCRATCH_NAME = re.compile(r"^(test_|tests?_|repro|reproduce|debug|check|scratch|tmp|temp|try|verify)|_test\.py$",
                          re.IGNORECASE)
CD_PREFIX = re.compile(r"^\s*cd\s+(\"[^\"]*\"|'[^']*'|\S+)\s*(&&|;)\s*")

INFRASTRUCTURE_CAUSES = {"adapter_error", "provider_error", "evaluator_error"}
PROVIDER_FAILURES = re.compile(r"^(http_\d+|network_error|error_body|invalid_json)$")


@dataclass
class Call:
    tool: str
    arguments: Any
    status: Optional[str]  # success | rejected | error | ... (None when no result was recorded)
    content: str = ""
    call_id: Optional[str] = None
    revision: Optional[str] = None  # workspace revision when the call ran (Reticle journal only)
    mutations_before: int = 0  # successful edit/run calls earlier in the run (a revision proxy)


@dataclass
class Response:
    index: int
    text: str
    calls: List[Call] = field(default_factory=list)


@dataclass
class Trajectory:
    run: str
    task_id: str
    source: str  # reticle-journal | claude-code-stream
    responses: List[Response]
    stop_reason: str
    stop_error: Optional[str]
    stop_class: str  # finish | budget | timeout | repeat_stop | adapter_error | provider_error
    finish_called: bool
    acceptance_status: Optional[str]
    criterion_outcomes: Dict[str, str]
    evaluator_error: bool
    results_check: Optional[str] = None  # agreement of journal-derived stop/acceptance with results.jsonl
    statement: str = ""  # the task statement the model saw (for labelling prompts)


# ---------------------------------------------------------------------------------------------------------
# Reading a Reticle session journal without touching it


def read_events(session_dir: Path) -> List[dict]:
    with (session_dir / "events.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_artifact(session_dir: Path, artifact_id: str) -> bytes:
    if not re.fullmatch(r"art_[0-9a-zA-Z]+", artifact_id):
        raise ValueError(f"invalid artifact id: {artifact_id}")
    meta = json.loads((session_dir / "store" / "artifacts" / f"{artifact_id}.json").read_text(encoding="utf-8"))
    digest = meta["content_hash"]
    return (session_dir / "store" / "blobs" / digest[:2] / digest[2:]).read_bytes()


def _parse_arguments(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return raw if raw is not None else {}


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def _classify_model_error(error: str, attempt_outcomes: List[str]) -> str:
    if error.startswith("diagnostic_termination"):
        return "repeat_stop"
    if error.startswith("attempt_cap_reached"):
        return "budget"
    failure = next((outcome for outcome in reversed(attempt_outcomes) if outcome != "response"), "")
    if failure == "timeout":
        return "timeout"
    if PROVIDER_FAILURES.match(failure):
        return "provider_error"
    return "adapter_error"  # cli_error, invalid_reply, invalid_stream, tool isolation, unavailable CLI, ...


def stop_class_for(stop_reason: str, error: Optional[str], attempt_outcomes: List[str],
                   exhausted_resource: Optional[str]) -> str:
    if stop_reason == "finish_requested":
        return "finish"
    if stop_reason in {"model_call_limit", "context_budget_exhausted", "pilot_call_budget_exhausted"}:
        return "budget"
    if stop_reason == "task_deadline_reached":
        return "timeout"
    if stop_reason == "task_budget_exhausted":
        return "timeout" if exhausted_resource == "active_seconds" else "budget"
    if stop_reason == "model_error":
        return _classify_model_error(error or "", attempt_outcomes)
    return "adapter_error"  # needs_reconciliation or an unknown stop: the runtime, not the model


def session_dir_for(run_dir: Path) -> Path:
    candidates = sorted((run_dir / "sessions").glob("*/session/events.jsonl"))
    if len(candidates) != 1:
        raise ValueError(f"{run_dir}: expected one session journal, found {len(candidates)}")
    return candidates[0].parent


def load_reticle_run(run_dir: Path, session_dir: Optional[Path] = None) -> Trajectory:
    session_dir = session_dir or session_dir_for(run_dir)
    events = read_events(session_dir)
    task_id, statement, outcomes = None, "", {}
    attempt_outcomes: List[str] = []
    exhausted_resource = run_result = decision = None
    evaluator_error = False
    for event in events:
        kind, payload = event["kind"], event.get("payload") or {}
        if kind == "task_contract" and task_id is None:
            task_id = (payload.get("task") or {}).get("task_id")
            statement = (payload.get("task") or {}).get("description") or ""
        elif kind == "action_outcome":
            result = payload.get("result") or {}
            if result.get("call_id"):
                outcomes[result["call_id"]] = result
        elif kind == "provider_attempt_finished":
            attempt_outcomes.append(payload.get("outcome") or "")
        elif kind == "task_budget_exhausted":
            exhausted_resource = payload.get("resource")
        elif kind == "agent_run_result":
            run_result = payload.get("result") or {}
        elif kind == "evaluation_measurement" and payload.get("infrastructure_error"):
            evaluator_error = True
        elif kind == "acceptance_decision":
            decision = payload.get("decision") or {}

    responses: List[Response] = []
    by_call_id: Dict[str, Call] = {}
    for event in events:
        if event["kind"] != "transcript_message":
            continue
        message = json.loads(read_artifact(session_dir, event["payload"]["artifact_id"]).decode("utf-8"))
        if message.get("role") == "assistant":
            response = Response(len(responses) + 1, _text(message.get("content")))
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                call = Call(function.get("name") or "", _parse_arguments(function.get("arguments")), None,
                            call_id=tool_call.get("id"))
                outcome = outcomes.get(call.call_id or "")
                if outcome:
                    call.revision = outcome.get("workspace_revision_before")
                response.calls.append(call)
                by_call_id[call.call_id or ""] = call
            responses.append(response)
        elif message.get("role") == "tool":
            call = by_call_id.get(message.get("tool_call_id") or "")
            if call is not None:
                call.status = (message.get("_reticle_output") or {}).get("status") or (
                    (outcomes.get(call.call_id or "") or {}).get("status"))
                call.content = _text(message.get("content"))
    _number_mutations(responses)

    run_result = run_result or {}
    stop_reason = run_result.get("stop_reason") or "unknown"
    decision = decision or {}
    status = decision.get("status")
    trajectory = Trajectory(
        run=run_dir.name, task_id=task_id or run_result.get("task_id") or "?", source="reticle-journal",
        responses=responses, stop_reason=stop_reason, stop_error=run_result.get("error"),
        stop_class=stop_class_for(stop_reason, run_result.get("error"), attempt_outcomes, exhausted_resource),
        finish_called=stop_reason == "finish_requested" or any(
            c.tool in FINISH_TOOLS and c.status == "success" for r in responses for c in r.calls),
        acceptance_status=status, criterion_outcomes=dict(decision.get("criterion_outcomes") or {}),
        evaluator_error=evaluator_error or status not in {"accepted", "rejected"}, statement=statement,
    )
    trajectory.results_check = _check_results(run_dir, trajectory)
    return trajectory


def _check_results(run_dir: Path, trajectory: Trajectory) -> Optional[str]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((r for r in reversed(rows) if r.get("task_id") == trajectory.task_id), None)
    if row is None:
        return "no row"
    stop = (row.get("agent") or {}).get("stop_reason")
    status = (row.get("acceptance") or {}).get("status")
    mismatches = [name for name, same in (("stop", stop == trajectory.stop_reason),
                                          ("acceptance", status == trajectory.acceptance_status)) if not same]
    return "agrees" if not mismatches else "differs: " + ", ".join(mismatches)


# ---------------------------------------------------------------------------------------------------------
# Reading a Claude Code native run (native_control.py output)


def load_native_run(run_dir: Path) -> Trajectory:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    workspace = ((result.get("init") or {}).get("cwd") or "").replace("\\", "/").rstrip("/")
    responses: List[Response] = []
    by_message: Dict[str, Response] = {}
    by_use_id: Dict[str, Call] = {}
    with (run_dir / "stream.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line).get("event") or {}
            message = event.get("message") or {}
            if event.get("type") == "assistant":
                response = by_message.get(message.get("id"))
                if response is None:
                    response = Response(len(responses) + 1, "")
                    by_message[message.get("id")] = response
                    responses.append(response)
                for block in message.get("content") or []:
                    if block.get("type") == "text":
                        response.text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        call = Call(block.get("name") or "", _relative_paths(block.get("input") or {}, workspace),
                                    None, call_id=block.get("id"))
                        response.calls.append(call)
                        by_use_id[call.call_id or ""] = call
            elif event.get("type") == "user":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        call = by_use_id.get(block.get("tool_use_id") or "")
                        if call is not None:
                            call.status = "error" if block.get("is_error") else "success"
                            call.content = _text(block.get("content"))
    _number_mutations(responses)

    cli = result.get("result") or {}
    if result.get("timed_out"):
        stop_reason, stop_class = "timed_out", "timeout"
    elif cli.get("subtype") == "success":
        stop_reason, stop_class = "end_turn", "finish"
    elif cli.get("subtype") == "error_max_turns":
        stop_reason, stop_class = "error_max_turns", "budget"
    else:
        stop_reason, stop_class = str(cli.get("subtype") or "unknown"), "adapter_error"
    acceptance = result.get("acceptance") or {}
    status = acceptance.get("status")
    config_path = run_dir / "config.json"
    statement = json.loads(config_path.read_text(encoding="utf-8")).get("prompt", "") if config_path.exists() else ""
    return Trajectory(
        run=run_dir.name, task_id=result.get("task_id") or "?", source="claude-code-stream", responses=responses,
        stop_reason=stop_reason, stop_error=None, stop_class=stop_class, finish_called=stop_class == "finish",
        acceptance_status=status, criterion_outcomes=dict(acceptance.get("criterion_outcomes") or {}),
        evaluator_error=bool(acceptance.get("measurement_errors")) or status not in {"accepted", "rejected"},
        statement=statement,
    )


def _relative_paths(arguments: dict, workspace: str) -> dict:
    """Claude Code tools take absolute paths; express the workspace's files relative to it."""
    value = dict(arguments)
    for key in ("file_path", "path", "notebook_path"):
        path = value.get(key)
        if isinstance(path, str) and workspace:
            normal = path.replace("\\", "/")
            if normal.lower().startswith(workspace.lower()):
                value[key] = normal[len(workspace):].lstrip("/") or "."
    return value


def load_run(run_dir: Path) -> Trajectory:
    run_dir = Path(run_dir)
    if (run_dir / "stream.jsonl").exists() and (run_dir / "result.json").exists():
        return load_native_run(run_dir)
    return load_reticle_run(run_dir)


def _number_mutations(responses: List[Response]) -> None:
    count = 0
    for response in responses:
        for call in response.calls:
            call.mutations_before = count
            if call.status not in (None, "rejected") and (call.tool in EDIT_TOOLS or call.tool in RUN_TOOLS):
                count += 1


# ---------------------------------------------------------------------------------------------------------
# Rule phase labels


def call_path(call: Call) -> Optional[str]:
    if not isinstance(call.arguments, dict):
        return None
    path = call.arguments.get("path") or call.arguments.get("file_path") or call.arguments.get("notebook_path")
    if not isinstance(path, str):
        return None
    return str(PurePosixPath(path.replace("\\", "/").removeprefix("./")))


def call_command(call: Call) -> str:
    command = call.arguments.get("command") if isinstance(call.arguments, dict) else None
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    command = command or ""
    while CD_PREFIX.match(command):
        command = CD_PREFIX.sub("", command, count=1)
    return command.strip()


def is_scratch_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) <= 1 or parts[0] in {"tests", "test", "testing"} or bool(SCRATCH_NAME.search(parts[-1]))


def created_new_file(call: Call) -> bool:
    content = call.content.lstrip()
    return call.tool in CREATE_TOOLS and (content.startswith("Created ") or content.startswith("File created"))


def call_key(call: Call) -> str:
    return json.dumps([call.tool, call.arguments], sort_keys=True, default=str)


@dataclass
class RuleLabels:
    phases: List[str]  # one per response
    base_edits: List[dict]  # successful edits of files that were not created in the run
    first_edit_response: Optional[int]
    verified_after_last_edit: bool
    stuck_responses: List[int]
    rejected_calls: int
    verify_responses: List[int] = field(default_factory=list)  # responses with a verify call that was not rejected


def label_trajectory(trajectory: Trajectory) -> RuleLabels:
    created: set = set()  # files the run created (scratch or new source)
    scratch: set = set()
    seen: Dict[str, List[Call]] = {}
    base_edits: List[dict] = []
    phases: List[str] = []
    stuck_responses: List[int] = []
    verify_positions: List[int] = []
    verify_responses: List[int] = []
    last_edit_position, position = 0, 0
    for response in trajectory.responses:
        call_phases = []
        for call in response.calls:
            position += 1
            key = call_key(call)
            repeat = any(
                earlier.status == "rejected"
                or (earlier.revision == call.revision if earlier.revision and call.revision
                    else earlier.mutations_before == call.mutations_before)
                for earlier in seen.get(key, []))
            seen.setdefault(key, []).append(call)
            phase = _call_phase(call, created, scratch, bool(base_edits))
            if phase == "edit" and call.status == "success":
                path = call_path(call)
                if created_new_file(call):
                    created.add(path)
                elif path not in created:
                    base_edits.append({"response": response.index, "path": path})
                    last_edit_position = position
            elif phase == "reproduce" and created_new_file(call):
                created.add(call_path(call))
                scratch.add(call_path(call))
            if phase == "verify" and call.status != "rejected":
                verify_positions.append(position)
                if response.index not in verify_responses:
                    verify_responses.append(response.index)
            call_phases.append((phase, repeat))
        if not call_phases:
            last = response.index == len(trajectory.responses)
            phases.append("finish" if last and trajectory.stop_class == "finish" else "other")
            continue
        fresh = [phase for phase, repeat in call_phases if not repeat]
        if not fresh:
            phases.append("stuck")
            stuck_responses.append(response.index)
            continue
        phases.append(min(fresh, key=PRECEDENCE.index))
    return RuleLabels(
        phases=phases, base_edits=base_edits,
        first_edit_response=base_edits[0]["response"] if base_edits else None,
        verified_after_last_edit=bool(base_edits) and any(p > last_edit_position for p in verify_positions),
        stuck_responses=stuck_responses,
        rejected_calls=sum(1 for r in trajectory.responses for c in r.calls if c.status == "rejected"),
        verify_responses=verify_responses,
    )


def _call_phase(call: Call, created: set, scratch: set, edited_base: bool) -> str:
    if call.tool in FINISH_TOOLS:
        return "finish"
    if call.tool in EXPLORE_TOOLS:
        return "explore"
    if call.tool in EDIT_TOOLS:
        path = call_path(call) or ""
        if path in scratch:
            return "reproduce"
        if path in created:
            return "edit"
        if call.tool in CREATE_TOOLS and (created_new_file(call) or call.status != "success") and is_scratch_path(path):
            return "reproduce"
        return "edit"
    if call.tool in RUN_TOOLS:
        words = call_command(call).split()
        first = PurePosixPath(words[0].replace("\\", "/")).name.lower() if words else ""
        if first in EXPLORE_COMMANDS:
            return "explore"
        return "verify" if edited_base else "reproduce"
    return "other"


# ---------------------------------------------------------------------------------------------------------
# Run labels, signature, clusters


def mechanism_for(trajectory: Trajectory, labels: RuleLabels) -> str:
    if not trajectory.responses:
        return "no_response"
    if labels.base_edits:
        return "edit_verified" if labels.verified_after_last_edit else "edit_unverified"
    if "reproduce" in labels.phases:
        return "reproduce_no_edit"
    if "explore" in labels.phases:
        return "explore_only"
    return "no_action"


def verifier_cause(trajectory: Trajectory, labels: RuleLabels) -> str:
    """First match wins: accepted, evaluator_error, infrastructure stops, then the evaluator's criteria."""
    if trajectory.acceptance_status == "accepted":
        return "accepted"
    if trajectory.evaluator_error:
        return "evaluator_error"
    if trajectory.stop_class in {"adapter_error", "provider_error", "timeout"}:
        return trajectory.stop_class
    if trajectory.criterion_outcomes.get("pass-to-pass") == "fail":
        return "pass_to_pass_regression"
    if labels.base_edits:
        return "fail_to_pass_failed"
    if trajectory.stop_class == "budget":
        return "budget"
    return "no_edit"


def causal_flags(trajectory: Trajectory, labels: RuleLabels, gold_files: Optional[set]) -> List[str]:
    flags = []
    if labels.rejected_calls:
        flags.append("rejected_calls")
    if labels.stuck_responses:
        flags.append("repeated_call")
    if trajectory.stop_class == "repeat_stop":
        flags.append("repeat_stop")
    if gold_files is None:
        flags.append("gold_unknown")
    elif any(edit["path"] not in gold_files for edit in labels.base_edits):
        flags.append("edit_outside_gold")
    if trajectory.finish_called and not labels.verified_after_last_edit:
        flags.append("no_verification_before_finish")
    return flags


def analyse(trajectory: Trajectory, gold_files: Optional[set]) -> dict:
    labels = label_trajectory(trajectory)
    flags = causal_flags(trajectory, labels, gold_files)
    record = {
        "run": trajectory.run,
        "task_id": trajectory.task_id,
        "source": trajectory.source,
        "responses": len(trajectory.responses),
        "tool_calls": sum(len(r.calls) for r in trajectory.responses),
        "stop_reason": trajectory.stop_reason,
        "stop_class": trajectory.stop_class,
        "acceptance": trajectory.acceptance_status,
        "criterion_outcomes": trajectory.criterion_outcomes,
        "verifier_cause": verifier_cause(trajectory, labels),
        "causal_status": "+".join(flags) or "none",
        "mechanism": mechanism_for(trajectory, labels),
        "rejected_calls": labels.rejected_calls,
        "stuck_responses": labels.stuck_responses,
        "first_edit_response": labels.first_edit_response,
        "verified_before_finish": labels.verified_after_last_edit,
        "edit_in_gold_files": None if gold_files is None else any(e["path"] in gold_files for e in labels.base_edits),
        "edited_files": sorted({e["path"] for e in labels.base_edits}),
        "phases": labels.phases,
        "results_check": trajectory.results_check,
    }
    record["signature"] = " | ".join((record["verifier_cause"], record["causal_status"], record["mechanism"]))
    return record


def cluster(records: Iterable[dict]) -> List[dict]:
    groups: Dict[str, List[dict]] = {}
    for record in records:
        groups.setdefault(record["signature"], []).append(record)
    clusters = []
    for signature, members in groups.items():
        first = members[0]
        clusters.append({
            "signature": signature,
            "verifier_cause": first["verifier_cause"],
            "causal_status": first["causal_status"],
            "mechanism": first["mechanism"],
            "runs": len(members),
            "tasks": len({m["task_id"] for m in members}),
            "minable": first["verifier_cause"] not in INFRASTRUCTURE_CAUSES | {"accepted"},
            "members": [m["run"] for m in members],
        })
    return sorted(clusters, key=lambda c: (not c["minable"], c["verifier_cause"] == "accepted",
                                           -c["tasks"], -c["runs"], c["signature"]))


def load_gold_files(task_files: Iterable[Path]) -> Dict[str, set]:
    gold: Dict[str, set] = {}
    for path in task_files:
        if Path(path).exists():
            for task in json.loads(Path(path).read_text(encoding="utf-8"))["tasks"]:
                gold[task["task_id"]] = set(task.get("gold_source_files") or [])
    return gold


def phase_string(phases: List[str]) -> str:
    runs: List[List[Any]] = []
    for phase in phases:
        if runs and runs[-1][0] == phase:
            runs[-1][1] += 1
        else:
            runs.append([phase, 1])
    return " ".join(f"{phase}x{count}" if count > 1 else phase for phase, count in runs) or "-"


def render_tables(records: List[dict], clusters: List[dict]) -> str:
    lines = ["| # | Verifier cause | Causal status | Mechanism | Runs | Tasks | Minable | Runs in cluster |",
             "|---:|---|---|---|---:|---:|---|---|"]
    for number, item in enumerate(clusters, 1):
        lines.append(f"| {number} | `{item['verifier_cause']}` | `{item['causal_status']}` | `{item['mechanism']}` | "
                     f"{item['runs']} | {item['tasks']} | {'yes' if item['minable'] else 'no'} | "
                     f"{', '.join(item['members'])} |")
    lines += ["", "| Run | Task | Source | Stop (class) | Acceptance | Rejected | Stuck responses | First edit | "
              "Edit in gold | Verified before finish | Phases (rule) | results.jsonl |",
              "|---|---|---|---|---|---:|---|---:|---|---|---|---|"]
    for r in records:
        lines.append(
            f"| {r['run']} | {r['task_id']} | {r['source']} | `{r['stop_reason']}` ({r['stop_class']}) | "
            f"{r['acceptance']} | {r['rejected_calls']} | {', '.join(map(str, r['stuck_responses'])) or '-'} | "
            f"{r['first_edit_response'] or '-'} | {r['edit_in_gold_files']} | {r['verified_before_finish']} | "
            f"{phase_string(r['phases'])} | {r['results_check'] or 'n/a'} |")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="run directories (Reticle or native)")
    parser.add_argument("--tasks", nargs="*", type=Path, default=list(DEFAULT_TASK_FILES),
                        help="task files that supply gold_source_files")
    parser.add_argument("--json", action="store_true", help="also print one JSON record per run")
    args = parser.parse_args(argv)
    gold = load_gold_files(args.tasks)
    records = []
    for run_dir in args.runs:
        trajectory = load_run(run_dir)
        records.append(analyse(trajectory, gold.get(trajectory.task_id)))
    if args.json:
        for record in records:
            print(json.dumps(record))
        print()
    print(render_tables(records, cluster(records)))


if __name__ == "__main__":
    main()
