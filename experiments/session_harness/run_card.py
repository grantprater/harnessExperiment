"""Executable run cards (S6d): validate a machine-readable card, plan its runner invocations, run them.

A card (experiments/session_harness/cards/*.json; structure in cards/card.schema.json, meaning in
cards/SCHEMA.md) declares arms, tasks, rollouts, arm order, budgets, stop rules, measurements, a
decision rule, and a report path. This script expands it into one runner invocation per
task x rollout x arm, plus the card's controls, in a recorded order, and runs them one at a time by
shelling out to the runner (experiments/p6_pilot/run_pilot.py). It never calls a model itself.

Modes (exactly one):
  --validate  schema and semantic checks only
  --plan      print every invocation and its expected protocol hash, and the blockers that make
              --execute refuse; nothing runs. With --replay RUN_DIR, compare the planned invocation of
              that name (or the plan's only invocation) with a recorded run's config.json
  --execute   take the live-run lock (fail if held), check the machine (an OCI arm needs its pinned engine
              running; a card with none needs no engine) and log its facts, preflight each live arm with the
              runner's own --dry-run, run the invocations sequentially, then write the report skeleton.
              --resume skips invocations that already have a completed record. With
              budgets.campaign.list_price_cap_usd, stops before the next attempt once the CLI list-price
              estimates of the campaign's calls reach the cap
  --report    rewrite the report skeleton from whatever results exist; nothing runs

Usage (from the repo root):
  python experiments/session_harness/run_card.py experiments/session_harness/cards/007.json --plan --limit 5
  python experiments/session_harness/run_card.py experiments/session_harness/cards/006-replay.json --plan \\
      --replay experiments/p6_pilot/runs/pc-reticle-sonnet-2
  python experiments/session_harness/run_card.py CARD --execute [--resume]

Exit codes: 0 done; 2 invalid, blocked, or refused; 3 checkpoint stop (consecutive failures or campaign
cap); 4 integrity stop (protocol mismatch, evidence loss, budget violation, failed control); 5 lock held.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = Path(__file__).resolve().parent / "cards" / "card.schema.json"
LIVE_CLIENTS = ("openrouter", "claude-cli")
EXECUTABLE_STATUSES = ("approved", "running")
EXIT_OK, EXIT_REFUSED, EXIT_CHECKPOINT, EXIT_INTEGRITY, EXIT_LOCKED = 0, 2, 3, 4, 5
DEFAULT_RUN_NAME_TEMPLATE = "{prefix}-{task}-r{rollout}-{arm}"
# config.json fields added to runner v8 after some runs were recorded (S6a: --tasks FILE.json); a replay of an
# older run reports them as not recorded instead of as differences.
LATER_CONFIG_FIELDS = frozenset({"task_file", "task_contracts"})
HASH_LINE = re.compile(r"protocol ([0-9a-f]{12})\b")
# Flags the runner call is built from. A card cannot pass them through extra_args.
RESERVED_FLAGS = frozenset({
    "--client", "--backend", "--oci-image", "--arm", "--run-name", "--models", "--provider", "--tasks",
    "--max-calls-per-run", "--max-context-bytes", "--max-tokens", "--max-total-calls", "--pytest-timeout",
    "--max-attempts-per-run", "--max-tool-actions-per-run", "--elapsed-cap-seconds", "--cost-ceiling-usd",
    "--attempt-cost-reservation-usd", "--resume-after-provider-stop", "--resume-wait-seconds",
    "--stop-on-repeats", "--dry-run",
})
# Measurement vocabulary. RESULT_MEASUREMENTS come from results.jsonl; JOURNAL_MEASUREMENTS need the
# session journal (S6b) and are listed as pending in the report skeleton.
RESULT_MEASUREMENTS = {
    "accepted": "Runs: Status",
    "stop_reason": "Runs: Stop",
    "responses_used": "Runs: Responses",
    "provider_attempts": "Runs: Attempts (provider)",
    "tool_calls": "Runs: Tool calls",
    "active_seconds": "Runs: Active s",
    "wall_seconds": "Runs: Wall s",
    "criterion_outcomes": "Runs: Criteria",
    "tokens": "Runs: Tokens in/out",
    "diagnostic_termination": "Runs: Stop = diagnostic_termination",
}
JOURNAL_MEASUREMENTS = {
    "first_edit_response": "response index of the first workspace edit",
    "rejected_calls": "tool calls the runtime rejected",
    "repeat_flags": "three identical observation calls without a workspace change (post hoc when the guard is off)",
    "edit_in_gold_files": "whether the edits touch the task's gold_source_files",
    "verification_before_finish": "a test run after the last edit and before finish",
    "references_remaining_budget": "whether the final response mentions the remaining budget",
}
CAMPAIGN_MEASUREMENTS = {
    "acceptance_rate_ci": "Summary by arm",
    "per_task_outcomes": "Per-task outcomes",
    "outcome_distribution": "Per-task outcomes: distribution",
    "evolution_set": "Per-task outcomes: derived categories (the evolution set itself is chosen by hand)",
    "paired_table": "Paired units",
}
PARAMETRIC_MEASUREMENT = re.compile(r"^(acceptance_by|acceptance_by_size):([A-Za-z0-9_]+)$|^delta:([a-z0-9-]+):([a-z0-9-]+)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalised_sha256(path: Path) -> str:
    """sha256 of a text file with CRLF folded to LF (the content git stores), so it matches across platforms."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def resolve_path(value: str) -> Path:
    return (ROOT / value).resolve()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def number_arg(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------------------------
# Structural validation: a stdlib interpreter for the JSON Schema keywords card.schema.json uses.
# ---------------------------------------------------------------------------------------------

_PLAIN_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list}


def _is_type(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "null":
        return value is None
    return isinstance(value, _PLAIN_TYPES[name])


def schema_errors(value, schema: dict, root: dict, path: str = "$") -> List[str]:
    if "$ref" in schema:
        return schema_errors(value, root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root, path)
    if "anyOf" in schema:
        attempts = [schema_errors(value, option, root, path) for option in schema["anyOf"]]
        if any(not errors for errors in attempts):
            return []
        closest = min(attempts, key=len)
        return [f"{path}: matches no allowed form; nearest: {'; '.join(closest)}"]
    errors: List[str] = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: must be {json.dumps(schema['const'])}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: must be one of {schema['enum']}"]
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_is_type(value, name) for name in names):
            return [f"{path}: expected {'/'.join(names)}"]
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{path}: missing '{key}'" for key in schema.get("required", []) if key not in value]
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: needs at least {schema['minProperties']} entries")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], root, f"{path}.{key}")
            elif extra is False:
                errors.append(f"{path}: unknown field '{key}'")
            elif isinstance(extra, dict):
                errors += schema_errors(item, extra, root, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += schema_errors(item, schema["items"], root, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    elif _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be > {schema['exclusiveMinimum']}")
    return errors


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def is_unresolved(value) -> bool:
    return isinstance(value, dict) and set(value) == {"unresolved"}


def unresolved_fields(value, path: str = "$") -> List[Tuple[str, str]]:
    """Every {"unresolved": reason} placeholder in the card, and task sets declared unresolved."""
    found = []
    if is_unresolved(value):
        return [(path, value["unresolved"])]
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "unresolved" and isinstance(item, str):
                found.append((path, item))
            else:
                found += unresolved_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += unresolved_fields(item, f"{path}[{index}]")
    return found


def validate_card(card) -> List[str]:
    """Structural errors first; semantic errors only when the structure is sound."""
    schema = load_schema()
    errors = schema_errors(card, schema, schema)
    if errors:
        return errors
    arms = {arm["name"]: arm for arm in card["arms"]}
    if len(arms) != len(card["arms"]):
        errors.append("arms: names must be unique")
    controls = card.get("controls", [])
    if len({c["name"] for c in controls}) != len(controls):
        errors.append("controls: names must be unique")
    if len({b["name"] for b in card["blocks"]}) != len(card["blocks"]):
        errors.append("blocks: names must be unique")
    budgets = card["budgets"]["per_run"]
    for arm in card["arms"]:
        where = f"arms.{arm['name']}"
        if arm["client"] in LIVE_CLIENTS:
            if not arm.get("model"):
                errors.append(f"{where}: a {arm['client']} arm needs a model")
            if budgets.get("model_attempts") is None:
                errors.append(f"{where}: live arms need budgets.per_run.model_attempts (the runner's attempt cap)")
        elif arm.get("model"):
            errors.append(f"{where}: scripted clients take no model")
        if arm.get("provider") and arm["client"] != "openrouter":
            errors.append(f"{where}: provider pins apply to the openrouter client only")
        if arm["client"] == "claude-cli" and card["environment"]["claude_cli_version"] is None:
            errors.append(f"{where}: pin environment.claude_cli_version or mark it unresolved")
        guards = arm["guards"]
        if guards["resume_after_provider_stop"] == 0 and guards["resume_wait_seconds"] is not None:
            errors.append(f"{where}.guards: resume_wait_seconds must be null when resume_after_provider_stop is 0")
        if guards["resume_after_provider_stop"] > 0 and guards["resume_wait_seconds"] is None:
            errors.append(f"{where}.guards: resume_wait_seconds is required when resuming")
        for item in arm.get("extra_args", []):
            flag = item.split("=", 1)[0]
            if flag in RESERVED_FLAGS:
                errors.append(f"{where}.extra_args: {flag} is set from structured card fields")
    template = card.get("run_name_template", DEFAULT_RUN_NAME_TEMPLATE)
    try:
        template.format(prefix="p", task="t", rollout=1, arm="a", block="b")
        if "{task}" not in template or "{rollout}" not in template:
            errors.append("run_name_template: must contain {task} and {rollout}")
    except (KeyError, IndexError, ValueError) as exc:
        errors.append(f"run_name_template: {exc!r}; placeholders are prefix, task, rollout, arm, block")
    if budgets.get("cost_usd") is not None and budgets.get("attempt_cost_reservation_usd") is None:
        errors.append("budgets.per_run: cost_usd needs attempt_cost_reservation_usd (explicit, not priced at run time)")
    timeouts = budgets["command_timeout_seconds"]
    if timeouts["default"] > timeouts["max"]:
        errors.append("budgets.per_run.command_timeout_seconds: default exceeds max")
    sets = card["tasks"]["sets"]
    for name, spec in sets.items():
        sources = [key for key in ("ids", "rule", "ref", "from_sets", "unresolved") if key in spec]
        if len(sources) != 1:
            errors.append(f"tasks.sets.{name}: needs exactly one of ids, rule, ref, from_sets, unresolved (has {sources})")
        for other in spec.get("from_sets", []):
            if other not in sets:
                errors.append(f"tasks.sets.{name}: from_sets names unknown set {other!r}")
    errors += _set_cycles(sets)
    for block in card["blocks"]:
        where = f"blocks.{block['name']}"
        if block["task_set"] not in sets:
            errors.append(f"{where}: unknown task set {block['task_set']!r}")
        for arm_name in block["arms"]:
            if arm_name not in arms:
                errors.append(f"{where}: unknown arm {arm_name!r}")
        if len(set(block["arms"])) != len(block["arms"]):
            errors.append(f"{where}: an arm appears twice")
        if block["arm_order"]["rule"] == "seeded" and not isinstance(block["arm_order"].get("seed"), int):
            errors.append(f"{where}.arm_order: a seeded order needs an integer seed")
    for control in controls:
        where = f"controls.{control['name']}"
        if control["task_set"] not in sets:
            errors.append(f"{where}: unknown task set {control['task_set']!r}")
        if control["like_arm"] not in arms:
            errors.append(f"{where}: unknown arm {control['like_arm']!r}")
    rules = card["stop_rules"]
    if len(rules["retry_backoff_seconds"]) < rules["max_retries_per_invocation"]:
        errors.append("stop_rules: retry_backoff_seconds needs one entry per allowed retry")
    for name in card["measurements"]["per_run"]:
        if name not in RESULT_MEASUREMENTS and name not in JOURNAL_MEASUREMENTS:
            errors.append(f"measurements.per_run: unknown measurement {name!r} (see SCHEMA.md)")
    for name in card["measurements"]["campaign"]:
        match = PARAMETRIC_MEASUREMENT.match(name)
        if name in CAMPAIGN_MEASUREMENTS:
            continue
        if not match:
            errors.append(f"measurements.campaign: unknown measurement {name!r} (see SCHEMA.md)")
        elif match.group(3) and (match.group(3) not in arms or match.group(4) not in arms):
            errors.append(f"measurements.campaign: {name!r} names an unknown arm")
    if card["report"]["path"] == card["markdown"]:
        errors.append("report.path: must not overwrite the markdown card")
    return errors


def _set_cycles(sets: dict) -> List[str]:
    errors, state = [], {}

    def visit(name, trail):
        if state.get(name) == "done" or name not in sets:
            return
        if state.get(name) == "active":
            errors.append(f"tasks.sets: from_sets cycle {' -> '.join(trail + [name])}")
            return
        state[name] = "active"
        for other in sets[name].get("from_sets", []):
            visit(other, trail + [name])
        state[name] = "done"

    for name in sets:
        visit(name, [])
    return errors


# ---------------------------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------------------------

@dataclass
class TaskUniverse:
    path: Path
    tasks: Dict[str, dict]
    order: List[str]
    sha256: str

    @classmethod
    def load(cls, path: Path) -> "TaskUniverse":
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["tasks"] if isinstance(data, dict) else data
        return cls(path, {t["task_id"]: t for t in items}, [t["task_id"] for t in items], normalised_sha256(path))

    def in_file_order(self, ids) -> List[str]:
        wanted = set(ids)
        return [task_id for task_id in self.order if task_id in wanted]


def _field_key(value) -> str:
    return json.dumps(sorted(value) if isinstance(value, list) else value, sort_keys=True)


def select_stratified_distinct(universe: TaskUniverse, rule: dict) -> List[str]:
    """Seeded selection: drop excluded tasks, keep one task per distinct `distinct_by` value, then take
    tasks round-robin across `stratify_by` strata (strata order and within-stratum order both seeded)."""
    rng = random.Random(rule["seed"])
    pool = [universe.tasks[task_id] for task_id in sorted(universe.order)]
    pool = [t for t in pool if not any(t.get(flag) is True for flag in rule.get("exclude_if_true", []))]
    rng.shuffle(pool)
    seen, representatives = set(), []
    for field_name in (rule["distinct_by"], rule["stratify_by"]):
        missing = [t["task_id"] for t in pool if field_name not in t]
        if missing:
            raise ValueError(f"{len(missing)} tasks have no field {field_name!r} (first: {missing[0]})")
    for task in pool:
        key = _field_key(task[rule["distinct_by"]])
        if key not in seen:
            seen.add(key)
            representatives.append(task)
    strata: Dict[str, List[dict]] = {}
    for task in representatives:
        strata.setdefault(str(task[rule["stratify_by"]]), []).append(task)
    order = sorted(strata)
    rng.shuffle(order)
    chosen: List[str] = []
    while len(chosen) < rule["count"] and any(strata[name] for name in order):
        for name in order:
            if strata[name] and len(chosen) < rule["count"]:
                chosen.append(strata[name].pop(0)["task_id"])
    if len(chosen) < rule["count"]:
        raise ValueError(f"only {len(chosen)} tasks satisfy the rule; {rule['count']} requested")
    return chosen


def resolve_task_sets(card: dict, universe: Optional[TaskUniverse]) -> Tuple[Dict[str, Optional[List[str]]], List[str]]:
    """Resolve every named set to task ids, or None with a blocker explaining why."""
    specs, resolved, blockers = card["tasks"]["sets"], {}, []

    def resolve(name: str) -> Optional[List[str]]:
        if name in resolved:
            return resolved[name]
        spec, ids = specs[name], None
        try:
            if "unresolved" in spec:
                blockers.append(f"task set {name}: unresolved: {spec['unresolved']}")
            elif universe is None:
                blockers.append(f"task set {name}: the task file is unavailable")
            elif "ids" in spec:
                ids = list(spec["ids"])
            elif "rule" in spec:
                ids = select_stratified_distinct(universe, spec["rule"])
            elif "ref" in spec:
                ids = _resolve_reference(name, spec["ref"], blockers)
            elif "from_sets" in spec:
                parts = [resolve(other) for other in spec["from_sets"]]
                if all(part is not None for part in parts):
                    ids = list(dict.fromkeys(task_id for part in parts for task_id in part))
        except ValueError as exc:
            blockers.append(f"task set {name}: {exc}")
            ids = None
        if ids is not None and universe is not None:
            unknown = [task_id for task_id in ids if task_id not in universe.tasks]
            if unknown:
                blockers.append(f"task set {name}: ids not in {display_path(universe.path)}: {unknown}")
                ids = None
        if ids is not None and "take" in spec:
            take = spec["take"]
            if take["count"] > len(ids):
                blockers.append(f"task set {name}: take {take['count']} from only {len(ids)} tasks")
                ids = None
            else:
                ids = random.Random(take["seed"]).sample(ids, take["count"])
        resolved[name] = ids
        return ids

    for set_name in specs:
        resolve(set_name)
    return resolved, blockers


def _resolve_reference(name: str, ref: dict, blockers: List[str]) -> Optional[List[str]]:
    path = resolve_path(ref["path"])
    if not path.exists():
        blockers.append(f"task set {name}: {ref['path']} does not exist yet (key {ref['key']!r})")
        return None
    if ref.get("sha256") and normalised_sha256(path) != ref["sha256"]:
        blockers.append(f"task set {name}: {ref['path']} sha256 differs from the pinned value")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = data.get(ref["key"]) if isinstance(data, dict) else None
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        blockers.append(f"task set {name}: {ref['path']} has no non-empty id list under {ref['key']!r}")
        return None
    return ids


# ---------------------------------------------------------------------------------------------
# The runner: its own protocol hash, computed from the card's pinned environment
# ---------------------------------------------------------------------------------------------

class RunnerAdapter:
    """Loads the runner script as a private module and computes, without probing the machine, the
    protocol hash and recorded config the runner would produce for an arm.

    Hash inputs come from three places: the runner source (runner version, instructions, tool schemas,
    evaluator bytes, managed root files, toolset version, CLI adapter contract), the card (policy,
    client, model, provider pin, backend, image, guards), and the machine (Claude CLI version, OCI image
    ID, OCI engine). The card pins the machine facts; --execute checks them with the runner's --dry-run.
    """

    _cache: Dict[Path, "RunnerAdapter"] = {}

    def __init__(self, script: Path):
        self.script = script
        self.source = script.read_text(encoding="utf-8")
        name = "_card_runner_" + hashlib.sha256(str(script).encode("utf-8")).hexdigest()[:12]
        spec = importlib.util.spec_from_file_location(name, script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        self.module = module
        self.runs_root = script.parent / "runs"
        self.default_task_file = Path(getattr(module, "DEFAULT_TASK_FILE", script.parent / "tasks.json")).resolve()

    def selects_task_file(self) -> bool:
        """Whether --tasks accepts FILE.json (runner v8 after S6a); earlier runners read only their default."""
        return hasattr(self.module, "load_tasks")

    def task_contracts(self, tasks: List[dict]) -> List[dict]:
        """The runner's own task contracts, in the order given (file order); empty for runners without them."""
        function = getattr(self.module, "task_contract", None)
        if function is None:
            return []
        return [contract for contract in (function(task) for task in tasks) if contract is not None]

    def task_file_record(self, path: Path) -> Optional[dict]:
        function = getattr(self.module, "task_file_record", None)
        return function(path) if function is not None else None

    @classmethod
    def load(cls, script: Path) -> "RunnerAdapter":
        script = script.resolve()
        if script not in cls._cache:
            cls._cache[script] = cls(script)
        return cls._cache[script]

    def supports_flag(self, flag: str) -> bool:
        return f'"{flag}"' in self.source

    def command_timeouts(self) -> Optional[Tuple[float, float]]:
        suite = getattr(self.module, "ToolSuite", None)
        if suite is None:
            return None
        parameters = inspect.signature(suite.__init__).parameters
        try:
            return parameters["default_timeout_seconds"].default, parameters["max_timeout_seconds"].default
        except KeyError:
            return None

    def execution(self, backend: dict) -> dict:
        """The runner's own resolve_execution, with the card's image ID and engine standing in for probes."""
        module = self.module
        if backend["kind"] == "trusted-local":
            return module.resolve_execution("trusted-local", getattr(module, "DEFAULT_OCI_IMAGE", ""))[1]
        image_id, engine = backend["image_id"], backend["engine"]
        real_backend = module.IsolatedOCIBackend

        class PinnedBackend(real_backend):
            def __init__(self, image, engine=None):  # noqa: D401 - the card's engine, never discovered
                super().__init__(image, engine=pinned_engine)

            def availability(self):
                return True, "pinned in the card (not probed)"

        class PinnedProcesses:
            CompletedProcess = subprocess.CompletedProcess

            @staticmethod
            def run(command, *args, **kwargs):
                if list(command[1:3]) == ["image", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=image_id + "\n", stderr="")
                raise RuntimeError(f"offline resolution would run {command!r}; the card must pin that input")

        pinned_engine = engine
        saved = module.IsolatedOCIBackend, module.subprocess
        module.IsolatedOCIBackend, module.subprocess = PinnedBackend, PinnedProcesses
        try:
            return module.resolve_execution("oci", backend["image"])[1]
        finally:
            module.IsolatedOCIBackend, module.subprocess = saved

    def routing(self, client: str, model: Optional[str], provider: Optional[str], cli_version: Optional[str]) -> dict:
        module = self.module
        if client == "claude-cli":
            return {model: module.cli_contract(model, max_turns=module.CLI_MAX_TURNS,
                                               timeout=module.CLI_TIMEOUT_SECONDS, version=cli_version)}
        if client == "openrouter":
            if provider:
                return {model: {"order": [provider.lower()], "allow_fallbacks": False, "require_parameters": True}}
            return {model: dict(module.UNPINNED_ROUTING)}
        return {f"{client}-client": dict(module.UNPINNED_ROUTING)}

    def treatments(self, extra_args: List[str]) -> Tuple[dict, List[str]]:
        """(the treatments an arm's extra_args turn on, as the runner records and hashes them; the extra_args
        flags that are not treatment flags). Runners without treatments see every flag as other."""
        flags = [a.split("=", 1)[0] for a in extra_args if a.startswith("--")]
        known = set(getattr(self.module, "TREATMENT_FLAGS", ()))
        function = getattr(self.module, "treatments_from_args", None)
        treatments = function(extra_args) if function is not None and extra_args else {}
        return treatments, [flag for flag in flags if flag not in known]

    def protocol_hash(self, policy: str, routing: dict, execution: dict, guards: dict, contracts=(),
                      treatments=None) -> str:
        if treatments:  # only runners that define treatments accept them
            return self.module.protocol_hash(policy, routing, execution, guards, contracts, treatments)
        if contracts:  # only runners that define task contracts produce any
            return self.module.protocol_hash(policy, routing, execution, guards, contracts)
        return self.module.protocol_hash(policy, routing, execution, guards)

    def other_line_ending_hash(self, policy: str, routing: dict, execution: dict,
                               guards: dict, contracts=(), treatments=None) -> Optional[Tuple[str, str]]:
        """The runner hashes evaluate_task.py's bytes as checked out, so a checkout with the other line
        endings (git autocrlf on Windows versus Linux) records a different hash for the same protocol.
        Returns (other line ending, the hash it would give), or None if the runner hashes no such file."""
        module = self.module
        try:
            source = inspect.getsource(module.protocol_hash)
        except (OSError, TypeError):
            return None
        here = getattr(module, "HERE", None)
        evaluator = Path(here) / "evaluate_task.py" if here is not None else None
        if evaluator is None or "evaluate_task.py" not in source or not evaluator.exists():
            return None
        raw = evaluator.read_bytes()
        crlf, lf = bytes([13, 10]), bytes([10])
        if crlf in raw:
            other, label = raw.replace(crlf, lf), "LF"
        else:
            other, label = raw.replace(lf, crlf), "CRLF"
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "evaluate_task.py").write_bytes(other)
            saved, module.HERE = module.HERE, Path(scratch)
            try:
                return label, self.protocol_hash(policy, routing, execution, guards, contracts, treatments)
            finally:
                module.HERE = saved


def guards_record(arm: dict) -> dict:
    guards = arm["guards"]
    wait = guards["resume_wait_seconds"]
    return {"stop_on_repeats": guards["stop_on_repeats"],
            "resume_after_provider_stop": guards["resume_after_provider_stop"],
            "resume_wait_seconds": float(wait) if guards["resume_after_provider_stop"] and wait is not None else None}


def run_model(client: str, arm: dict) -> str:
    return arm["model"] if client in LIVE_CLIENTS else f"{client}-client"


def per_run_budgets(card: dict) -> dict:
    budgets = card["budgets"]["per_run"]
    recorded = {"model_responses": budgets["responses"], "context_bytes": budgets["context_bytes"]}
    optional = {
        "model_attempts": budgets.get("model_attempts"),
        "tool_actions": budgets.get("tool_actions"),
        "active_seconds": float(budgets["active_seconds"]) if budgets.get("active_seconds") is not None else None,
        "cost_usd": budgets.get("cost_usd"),
        "model_attempt_cost_reservation": (budgets.get("attempt_cost_reservation_usd")
                                           if budgets.get("cost_usd") is not None else None),
    }
    recorded.update({key: value for key, value in optional.items() if value is not None})
    return recorded


# ---------------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------------

@dataclass
class Invocation:
    index: int
    kind: str  # "control" or "run"
    name: str  # arm or control name
    client: str
    arm: dict  # the arm, or the control's like_arm
    task_ids: List[str]
    run_name: str
    block: Optional[str] = None
    rollout: Optional[int] = None
    expect: Optional[str] = None
    args: List[str] = field(default_factory=list)
    script: Optional[Path] = None
    expected_hash: Optional[str] = None
    expected_config: Optional[dict] = None

    @property
    def unit(self) -> Optional[str]:
        return f"{self.block}:{self.task_ids[0]}:r{self.rollout}" if self.kind == "run" else None

    def attempt_allocation(self, card: dict) -> int:
        if self.client not in LIVE_CLIENTS:
            return 0
        return (card["budgets"]["per_run"].get("model_attempts") or 0) * len(self.task_ids)


@dataclass
class Plan:
    card: dict
    card_path: Path
    card_sha256: str
    universe: Optional[TaskUniverse]
    sets: Dict[str, Optional[List[str]]]
    invocations: List[Invocation]
    blockers: List[str]
    arm_hashes: Dict[str, List[str]]  # distinct expected hashes of the arm's runs (one per task contract set)
    arm_notes: Dict[str, str]
    runner: Optional[RunnerAdapter]
    line_ending_hashes: Dict[str, Tuple[str, str]] = field(default_factory=dict)

    @property
    def runs(self) -> List[Invocation]:
        return [inv for inv in self.invocations if inv.kind == "run"]

    @property
    def controls(self) -> List[Invocation]:
        return [inv for inv in self.invocations if inv.kind == "control"]


def arm_order(block: dict, task_id: str, rollout: int) -> List[str]:
    """Fixed: the block's listed order. Seeded: an independent shuffle per (block, task, rollout) unit,
    so resuming, or adding tasks, never reorders another unit."""
    arms = list(block["arms"])
    rule = block["arm_order"]
    if rule["rule"] == "seeded" and len(arms) > 1:
        random.Random(f"{rule['seed']}:{block['name']}:{task_id}:{rollout}").shuffle(arms)
    return arms


def expand_units(blocks: List[dict], sets: Dict[str, Optional[List[str]]], schedule: str = "rollout-major"):
    """(block, task, rollout, ordered arms) for every unit, blocks in card order. Rollout-major runs
    rollout 1 of every task before rollout 2, so an early stop leaves balanced partial evidence."""
    units = []
    for block in blocks:
        tasks = sets.get(block["task_set"]) or []
        rollouts = range(1, block["rollouts"] + 1)
        pairs = ([(r, t) for r in rollouts for t in tasks] if schedule == "rollout-major"
                 else [(r, t) for t in tasks for r in rollouts])
        units += [(block["name"], task_id, rollout, arm_order(block, task_id, rollout)) for rollout, task_id in pairs]
    return units


def runner_args(card: dict, default_task_file: Optional[Path], client: str, arm: dict, task_ids: List[str],
                run_name: str) -> List[str]:
    """The runner call. A task file other than the runner's default goes first in --tasks (--tasks FILE.json IDS)."""
    budgets = card["budgets"]["per_run"]
    args = ["--client", client]
    if client in LIVE_CLIENTS:
        args += ["--models", arm["model"]]
        if arm.get("provider"):
            args += ["--provider", f"{arm['model']}={arm['provider']}"]
    args += ["--arm", arm["policy"], "--backend", "oci" if arm["backend"]["kind"] == "oci" else "trusted-local"]
    if arm["backend"]["kind"] == "oci":
        args += ["--oci-image", arm["backend"]["image"]]
    args.append("--tasks")
    if default_task_file is None or resolve_path(card["tasks"]["file"]) != default_task_file:
        args.append(card["tasks"]["file"])
    args += [*task_ids, "--run-name", run_name,
             "--max-calls-per-run", number_arg(budgets["responses"]),
             "--max-context-bytes", number_arg(budgets["context_bytes"]),
             "--max-tokens", number_arg(budgets["max_tokens"]),
             "--pytest-timeout", number_arg(budgets["pytest_timeout_seconds"])]
    if budgets.get("model_attempts") is not None:
        args += ["--max-attempts-per-run", number_arg(budgets["model_attempts"])]
        if client in LIVE_CLIENTS:
            args += ["--max-total-calls", number_arg(budgets["model_attempts"] * len(task_ids))]
    if budgets.get("tool_actions") is not None:
        args += ["--max-tool-actions-per-run", number_arg(budgets["tool_actions"])]
    if budgets.get("active_seconds") is not None:
        args += ["--elapsed-cap-seconds", number_arg(budgets["active_seconds"])]
    if budgets.get("cost_usd") is not None:
        args += ["--cost-ceiling-usd", number_arg(budgets["cost_usd"]),
                 "--attempt-cost-reservation-usd", number_arg(budgets["attempt_cost_reservation_usd"])]
    guards = arm["guards"]
    if guards["stop_on_repeats"]:
        args.append("--stop-on-repeats")
    if guards["resume_after_provider_stop"]:
        args += ["--resume-after-provider-stop", number_arg(guards["resume_after_provider_stop"]),
                 "--resume-wait-seconds", number_arg(guards["resume_wait_seconds"])]
    return args + list(arm.get("extra_args", []))


def with_run_name(args: List[str], run_name: str) -> List[str]:
    updated = list(args)
    updated[updated.index("--run-name") + 1] = run_name
    return updated


def build_plan(card: dict, card_path: Path) -> Plan:
    """Expand a structurally valid card. Anything that would stop --execute becomes a blocker."""
    blockers: List[str] = []
    if card["status"] not in EXECUTABLE_STATUSES:
        blockers.append(f"card status is {card['status']!r}; --execute needs {' or '.join(EXECUTABLE_STATUSES)}")
    blockers += [f"prerequisite not done: {p['text']}" for p in card.get("prerequisites", []) if not p["done"]]
    blockers += [f"unresolved {path}: {reason}" for path, reason in unresolved_fields(
        {k: v for k, v in card.items() if k != "tasks"})]

    universe = None
    task_path = resolve_path(card["tasks"]["file"])
    if task_path.exists():
        universe = TaskUniverse.load(task_path)
        pinned = card["tasks"].get("file_sha256")
        if pinned and pinned != universe.sha256:
            blockers.append(f"task file {card['tasks']['file']} sha256 {universe.sha256[:12]} differs from the pinned "
                            f"{pinned[:12]}")
    else:
        blockers.append(f"task file {card['tasks']['file']} does not exist")
    sets, set_blockers = resolve_task_sets(card, universe)
    blockers += set_blockers

    adapters: Dict[str, Optional[RunnerAdapter]] = {}
    arm_notes: Dict[str, str] = {}

    def adapter_for(runner: dict, owner: str) -> Optional[RunnerAdapter]:
        if is_unresolved(runner):
            arm_notes[owner] = f"runner unresolved: {runner['unresolved']}"
            return None
        script = resolve_path(runner["script"])
        key = str(script)
        if key not in adapters:
            if not script.exists():
                blockers.append(f"runner {runner['script']} does not exist")
                adapters[key] = None
            else:
                try:
                    adapters[key] = RunnerAdapter.load(script)
                except Exception as exc:  # the runner failed to import; nothing can be planned against it
                    blockers.append(f"runner {runner['script']} failed to load: {type(exc).__name__}: {exc}")
                    adapters[key] = None
            adapter = adapters[key]
            if adapter is not None and adapter.module.RUNNER_VERSION != runner["runner_version"]:
                blockers.append(f"runner {runner['script']} is v{adapter.module.RUNNER_VERSION}; the card pins "
                                f"v{runner['runner_version']}")
        return adapters[key]

    main_runner = adapter_for(card["runner"], "card")
    cli_version = card["environment"]["claude_cli_version"]
    arm_parts: Dict[Tuple[str, str], Tuple[Optional[RunnerAdapter], Optional[dict]]] = {}

    def protocol_for(arm: dict, client: str, owner: str):
        """(adapter, the task-independent protocol parts: routing, execution, guards) for an arm and client."""
        key = (arm["name"], client)
        if key in arm_parts:
            return arm_parts[key]
        adapter = adapter_for(arm.get("runner", card["runner"]), owner)
        result = (adapter, None)
        if adapter is not None:
            module = adapter.module
            problems, pending = [], []  # pending inputs are already blockers via their unresolved placeholders
            if arm["policy"] not in getattr(module, "ARMS", {}):
                problems.append(f"the runner offers no context policy {arm['policy']!r}")
            if module.TOOLSET_VERSION != arm["toolset"]:
                problems.append(f"the runner's toolset is {module.TOOLSET_VERSION}, the card needs {arm['toolset']}")
            if client == "claude-cli" and not isinstance(cli_version, str):
                pending.append("hash needs the Claude CLI version pinned")
            if arm["backend"]["kind"] == "oci" and is_unresolved(arm["backend"]["image_id"]):
                pending.append("hash needs the OCI image ID pinned")
            try:
                treatments, _ = adapter.treatments(list(arm.get("extra_args", [])))
            except SystemExit as exc:  # the runner refuses a treatment value; --execute would fail the same way
                problems.append(f"extra_args: {exc}")
            blockers.extend(f"{owner}: {problem}" for problem in problems)
            if problems or pending:
                arm_notes[owner] = "; ".join(problems + pending)
            else:
                parts = {"routing": adapter.routing(client, arm.get("model"), arm.get("provider"), cli_version),
                         "execution": adapter.execution(arm["backend"]), "guards": guards_record(arm),
                         "treatments": treatments}
                result = (adapter, parts)
        arm_parts[key] = result
        return result

    arms = {arm["name"]: arm for arm in card["arms"]}
    for arm in card["arms"]:
        adapter, parts = protocol_for(arm, arm["client"], f"arm {arm['name']}")
        if arm.get("extra_args"):
            # Treatment flags the runner declares (TREATMENT_FLAGS) are hashed here as the runner hashes them;
            # any other flag is seen only by the --execute preflight.
            treatments = parts["treatments"] if parts is not None else {}
            other = adapter.treatments(list(arm["extra_args"]))[1] if parts is not None else ["?"]
            notes = [f"treatments in the planned hash: " + ", ".join(
                f"{value['name']} {value['version']}" for _, value in sorted(treatments.items()))] if treatments else []
            if other:
                notes.append("extra_args may change the hash; verified only at --execute")
            arm_notes[f"arm {arm['name']}"] = "; ".join(notes)
        if adapter is not None and universe is not None and not adapter.selects_task_file() and \
                resolve_path(card["tasks"]["file"]) != adapter.default_task_file:
            blockers.append(f"runner {display_path(adapter.script)} reads only {display_path(adapter.default_task_file)}; "
                            f"it cannot select {card['tasks']['file']}")

    timeouts = main_runner.command_timeouts() if main_runner else None
    declared_timeouts = card["budgets"]["per_run"]["command_timeout_seconds"]
    if timeouts and (declared_timeouts["default"], declared_timeouts["max"]) != timeouts:
        blockers.append(f"the runner fixes the command timeout at {timeouts[0]:g} s (max {timeouts[1]:g} s); the card "
                        f"declares {declared_timeouts['default']:g} s (max {declared_timeouts['max']:g} s) and the "
                        f"runner has no flag for it")

    invocations: List[Invocation] = []
    prefix = card["run_prefix"]
    template = card.get("run_name_template", DEFAULT_RUN_NAME_TEMPLATE)
    task_file_path = resolve_path(card["tasks"]["file"])
    line_ending_hashes: Dict[str, Tuple[str, str]] = {}

    def add(kind, name, client, arm, task_ids, run_name, **extra):
        adapter, parts = protocol_for(arm, client, f"{kind} {name}")
        invocation = Invocation(len(invocations) + 1, kind, name, client, arm, task_ids, slug(run_name), **extra)
        invocation.script = adapter.script if adapter else None
        default_tasks = adapter.default_task_file if adapter else None
        invocation.args = runner_args(card, default_tasks, client, arm, task_ids, invocation.run_name)
        if parts is not None and universe is not None and all(t in universe.tasks for t in task_ids):
            module = adapter.module
            ordered = universe.in_file_order(task_ids)  # the runner keeps file order
            contracts = adapter.task_contracts([universe.tasks[t] for t in ordered])
            protocol = adapter.protocol_hash(arm["policy"], parts["routing"], parts["execution"], parts["guards"],
                                             contracts, parts["treatments"])
            invocation.expected_hash = protocol
            if kind == "run" and arm["name"] not in line_ending_hashes:
                variant = adapter.other_line_ending_hash(arm["policy"], parts["routing"], parts["execution"],
                                                         parts["guards"], contracts, parts["treatments"])
                if variant:
                    line_ending_hashes[arm["name"]] = variant
            live = client in LIVE_CLIENTS
            model = run_model(client, arm)
            invocation.expected_config = {
                "runner_version": module.RUNNER_VERSION, "protocol_hash": protocol, "arm": arm["policy"],
                "client": client, "models": [model], "provider_routing": parts["routing"], "tasks": ordered,
                "max_calls_per_run": card["budgets"]["per_run"]["responses"],
                "max_context_bytes": card["budgets"]["per_run"]["context_bytes"],
                "max_tokens": card["budgets"]["per_run"]["max_tokens"],
                "pytest_timeout_seconds": card["budgets"]["per_run"]["pytest_timeout_seconds"],
                "max_total_calls": (card["budgets"]["per_run"]["model_attempts"] * len(task_ids)) if live else None,
                "toolset_version": module.TOOLSET_VERSION, "execution": parts["execution"], "guards": parts["guards"],
                "budgets_per_run": {model: per_run_budgets(card)},
            }
            record = adapter.task_file_record(task_file_path)
            if record is not None:  # runners that record the task file also record the task contracts
                invocation.expected_config.update({"task_file": record, "task_contracts": contracts})
            if parts["treatments"]:  # the runner records treatments only when one is on
                invocation.expected_config["treatments"] = parts["treatments"]
        invocations.append(invocation)

    for control in card.get("controls", []):
        task_ids = sets.get(control["task_set"])
        if task_ids:
            add("control", control["name"], control["client"], arms[control["like_arm"]], list(task_ids),
                control.get("run_name") or f"{prefix}-control-{control['name']}", expect=control["expect"])
    for block_name, task_id, rollout, order in expand_units(card["blocks"], sets, card.get("schedule", "rollout-major")):
        for arm_name in order:
            arm = arms[arm_name]
            add("run", arm_name, arm["client"], arm, [task_id],
                template.format(prefix=prefix, task=task_id, rollout=rollout, arm=arm_name, block=block_name),
                block=block_name, rollout=rollout)

    arm_hashes: Dict[str, List[str]] = {}
    for arm in card["arms"]:
        mine = [inv for inv in invocations if inv.kind == "run" and inv.name == arm["name"]]
        arm_hashes[arm["name"]] = sorted({inv.expected_hash for inv in mine if inv.expected_hash})
        declared = arm.get("expected_protocol_hash")
        wrong = sorted({inv.expected_hash for inv in mine if inv.expected_hash and inv.expected_hash != declared})
        if declared and wrong:
            blockers.append(f"arm {arm['name']}: computed protocol {', '.join(wrong)} differs from the card's {declared}")

    names = [inv.run_name for inv in invocations]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        blockers.append(f"run names collide: {duplicates}")
    for inv in invocations:
        adapter = RunnerAdapter._cache.get(inv.script) if inv.script else None
        if adapter is None:
            continue
        flags = {a.split("=", 1)[0] for a in inv.args if a.startswith("--")}
        missing = sorted(flag for flag in flags if not adapter.supports_flag(flag))
        for flag in missing:
            message = f"runner {display_path(inv.script)} does not accept {flag}"
            if message not in blockers:
                blockers.append(message)
    campaign = card["budgets"]["campaign"]
    runs = [inv for inv in invocations if inv.kind == "run"]
    if len(runs) > campaign["max_runs"]:
        blockers.append(f"the plan has {len(runs)} runs; the card's campaign allows {campaign['max_runs']}")
    planned_attempts = sum(inv.attempt_allocation(card) for inv in runs)
    if campaign.get("max_model_attempts") is not None and planned_attempts > campaign["max_model_attempts"]:
        blockers.append(f"the plan allocates {planned_attempts} model attempts; the campaign cap is "
                        f"{campaign['max_model_attempts']}")
    card_sha = normalised_sha256(card_path) if card_path.exists() else ""
    return Plan(card, card_path, card_sha, universe, sets, invocations, blockers, arm_hashes, arm_notes, main_runner,
                line_ending_hashes)


def load_card(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------------------------

def command_line(inv: Invocation, python: str = "python") -> str:
    script = display_path(inv.script) if inv.script else "<runner unresolved>"
    return shlex.join([python, script, *inv.args])


def describe_hashes(hashes: Optional[List[str]]) -> str:
    """One hash, a short list, or a count: mutation tasks give one protocol hash per task contract."""
    if not hashes:
        return "n/a"
    if len(hashes) <= 2:
        return ", ".join(hashes)
    return f"{len(hashes)} distinct (one per task contract; see each invocation)"


def describe_backend(backend: dict) -> str:
    if backend["kind"] == "trusted-local":
        return f"trusted-local ({isolation_of(backend)})"
    image_id = backend["image_id"]
    short = "unresolved" if is_unresolved(image_id) else image_id.split(":")[-1][:12]
    return f"oci {backend['image']}@{short} ({backend['engine']})"


def print_plan(plan: Plan, limit: Optional[int] = None, out: Callable[[str], None] = print) -> None:
    card = plan.card
    out(f"card {card['id']} ({display_path(plan.card_path)}, sha256 {plan.card_sha256[:12]}); status {card['status']}")
    runner = card["runner"]
    version = f"v{plan.runner.module.RUNNER_VERSION}" if plan.runner else "not loaded"
    out(f"runner {runner['script']} ({version}; card pins v{runner['runner_version']})")
    if plan.universe:
        pinned = card["tasks"].get("file_sha256")
        state = "pinned, matches" if pinned == plan.universe.sha256 else ("pinned, DIFFERS" if pinned else "not pinned")
        out(f"task file {card['tasks']['file']}: {len(plan.universe.order)} tasks, sha256 {plan.universe.sha256[:12]} ({state})")
    out("task sets:")
    for name, spec in card["tasks"]["sets"].items():
        source = next(key for key in ("ids", "rule", "ref", "from_sets", "unresolved") if key in spec)
        detail = {"rule": lambda: f"rule {spec['rule']['kind']} seed {spec['rule']['seed']}",
                  "ref": lambda: f"ref {spec['ref']['path']}#{spec['ref']['key']}",
                  "from_sets": lambda: f"union of {spec['from_sets']}",
                  "ids": lambda: "explicit ids", "unresolved": lambda: "unresolved"}[source]()
        if "take" in spec:
            detail += f", take {spec['take']['count']} (seed {spec['take']['seed']})"
        ids = plan.sets.get(name)
        out(f"  {name} ({detail}): " + (f"{len(ids)} tasks: {', '.join(ids)}" if ids is not None else "unresolved"))
    out("arms (expected protocol hash from the card's pins; --execute checks it with the runner's --dry-run):")
    for arm in card["arms"]:
        protocol = describe_hashes(plan.arm_hashes.get(arm["name"]))
        declared = arm.get("expected_protocol_hash")
        pin = f", card declares {declared}" if declared else ""
        note = plan.arm_notes.get(f"arm {arm['name']}")
        out(f"  {arm['name']}: {arm['client']} {arm.get('model') or ''} | {arm['policy']} | {arm['toolset']} | "
            f"{describe_backend(arm['backend'])} | guards {json.dumps(guards_record(arm))} | protocol {protocol}{pin}"
            + (f" [{note}]" if note else ""))
    for inv in plan.controls:
        out(f"  control {inv.name}: {inv.client} like {inv.arm['name']}, expect {inv.expect} | protocol "
            f"{inv.expected_hash or 'n/a'}")
    if plan.line_ending_hashes:
        label = next(iter(plan.line_ending_hashes.values()))[0]
        firsts = {inv.name: inv.expected_hash for inv in reversed(plan.runs)}
        out(f"  note: the runner hashes evaluate_task.py's bytes as checked out; with {label} line endings (another "
            f"checkout or OS) each arm's first run would record " + ", ".join(
                f"{name} {variant[1]} (not {firsts.get(name)})" for name, variant in plan.line_ending_hashes.items()))
    for block in card["blocks"]:
        count = len(plan.sets.get(block["task_set"]) or [])
        order = block["arm_order"]
        rule = "fixed" if order["rule"] == "fixed" else f"seeded (seed {order['seed']})"
        out(f"block {block['name']}: {count} tasks x {block['rollouts']} rollouts x {len(block['arms'])} arms = "
            f"{count * block['rollouts'] * len(block['arms'])} runs; arm order {rule}; "
            f"schedule {card.get('schedule', 'rollout-major')}")
    attempts = sum(inv.attempt_allocation(card) for inv in plan.runs)
    campaign = card["budgets"]["campaign"]
    out(f"budget: {len(plan.runs)} runs (cap {campaign['max_runs']}); at most {attempts} model attempts planned "
        f"(campaign cap {campaign.get('max_model_attempts')})")
    out(f"invocations: {len(plan.invocations)} ({len(plan.controls)} controls + {len(plan.runs)} runs)")
    shown = plan.invocations if limit is None else plan.invocations[:limit]
    for inv in shown:
        where = (f"control {inv.name} ({len(inv.task_ids)} tasks)" if inv.kind == "control"
                 else f"{inv.block} {inv.task_ids[0]} r{inv.rollout} {inv.name}")
        out(f"  [{inv.index}] {where}  run {inv.run_name}  protocol {inv.expected_hash or 'n/a'}")
        out(f"      {command_line(inv)}")
    if limit is not None and len(plan.invocations) > limit:
        out(f"  ... {len(plan.invocations) - limit} more")
    if plan.blockers:
        out(f"blockers ({len(plan.blockers)}; --execute refuses until they are resolved):")
        for blocker in plan.blockers:
            out(f"  - {blocker}")
    else:
        out("blockers: none")


def plan_json(plan: Plan) -> dict:
    return {
        "card": plan.card["id"], "card_sha256": plan.card_sha256, "blockers": plan.blockers,
        "sets": plan.sets, "arm_hashes": plan.arm_hashes,
        "invocations": [{"index": inv.index, "kind": inv.kind, "name": inv.name, "block": inv.block,
                         "task_ids": inv.task_ids, "rollout": inv.rollout, "run_name": inv.run_name,
                         "runner": display_path(inv.script) if inv.script else None, "args": inv.args,
                         "expected_protocol_hash": inv.expected_hash} for inv in plan.invocations],
    }


def replay_check(plan: Plan, run_dir: Path, out: Callable[[str], None] = print) -> bool:
    """Compare one planned invocation with a recorded run's config.json, field by field: the invocation whose run
    name is the directory's name, else the plan's only invocation."""
    named = [inv for inv in plan.invocations if inv.run_name == run_dir.name]
    if named:
        invocation = named[0]
    elif len(plan.invocations) == 1:
        invocation = plan.invocations[0]
    else:
        out(f"replay: no planned invocation is named {run_dir.name}, and the card plans {len(plan.invocations)}")
        return False
    expected = invocation.expected_config
    if expected is None:
        out("replay: the plan has no expected config (see blockers)")
        return False
    recorded = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    ok, unrecorded = True, []
    out(f"replay of {display_path(run_dir)} against invocation [{invocation.index}] {invocation.run_name} "
        f"(recorded at source {recorded.get('source_revision', {}).get('commit', '?')[:12]}):")
    for key, value in expected.items():
        if key not in recorded and key in LATER_CONFIG_FIELDS:
            unrecorded.append(key)
            continue
        same = recorded.get(key) == value
        ok &= same
        shown = json.dumps(value)[:70] if key != "protocol_hash" else value
        out(f"  {'match ' if same else 'DIFFER'} {key}: {shown}"
            + ("" if same else f"  (recorded {json.dumps(recorded.get(key))[:70]})"))
    if unrecorded:
        out(f"  not recorded by that runner revision (added later): {', '.join(unrecorded)}")
    results = run_dir / "results.jsonl"
    if results.exists():
        hashes = sorted({json.loads(line)["protocol_hash"] for line in results.read_text(encoding="utf-8").splitlines()
                         if line.strip()})
        out(f"  results.jsonl protocol hashes: {hashes}")
        ok &= hashes == [expected["protocol_hash"]]
    compared = len(expected) - len(unrecorded)
    out(f"replay: {'identical' if ok else 'DIFFERENT'} in {compared} recorded fields (planned {expected['protocol_hash']}, "
        f"recorded {recorded.get('protocol_hash')})")
    return ok


# ---------------------------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------------------------

def isolation_of(backend: dict) -> str:
    """What isolates an arm's candidate commands: the OCI container, or for trusted-local what the card declares
    (host: none beyond the host account; vm-sandbox: a disposable VM such as a cloud session's). Recorded in the
    campaign log; not a runner input, so not in the protocol hash."""
    if backend["kind"] == "oci":
        return "oci-container"
    return backend.get("isolation", "host")


def engine_problems(plan: "Plan") -> List[str]:
    """Why an OCI arm of the plan cannot run on this machine: its pinned engine is not on PATH, or does not answer
    `ENGINE version` (for example a docker client without a daemon). Empty when every arm is trusted-local."""
    problems = []
    engines = sorted({inv.arm["backend"]["engine"] for inv in plan.invocations if inv.arm["backend"]["kind"] == "oci"})
    for engine in engines:
        executable = shutil.which(engine)
        if executable is None:
            problems.append(f"the card pins an OCI backend on {engine}, which is not on PATH: this machine has no "
                            f"container engine for it. OCI cards cannot run here; use a trusted-local card (a "
                            f"different protocol, e.g. cards/019.json) or a machine with {engine}")
            continue
        try:
            completed = subprocess.run([executable, "version"], capture_output=True, text=True, timeout=30)
            answer = completed.returncode, (completed.stderr or completed.stdout).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            answer = None, repr(exc)
        if answer[0] != 0:
            problems.append(f"the card pins an OCI backend on {engine}, but `{engine} version` fails ({answer[1][-200:]}): "
                            f"the engine is not running. OCI cards cannot run here until it does")
    return problems


def machine_facts(plan: "Plan", python: str) -> dict:
    """Host facts for the campaign log: the isolation of every arm, the OS, CPUs, Pythons and CLI version."""
    facts = {
        "isolation": {arm["name"]: isolation_of(arm["backend"]) for arm in plan.card["arms"]},
        "os": platform.platform(), "system": platform.system(), "machine": platform.machine(),
        "cpu_count": os.cpu_count(), "driver_python": platform.python_version(), "runner_python": python,
        "task_python": None, "claude_cli_version": None,
    }
    module = plan.runner.module if plan.runner else None
    if module is not None and hasattr(module, "TASK_PYTHON"):
        facts["task_python"] = str(module.TASK_PYTHON)
    if module is not None and any(inv.client == "claude-cli" for inv in plan.invocations):
        try:
            facts["claude_cli_version"] = module.cli_version()
        except (SystemExit, OSError, subprocess.SubprocessError) as exc:
            facts["claude_cli_version"] = f"unavailable: {exc}"
    return facts


class LockHeld(Exception):
    pass


def default_lock_path() -> Path:
    """The main checkout's .runtime/locks/live-run.lock, shared by every worktree of the repository."""
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        base = Path(common).parent
    except (OSError, subprocess.SubprocessError):
        base = ROOT
    return base / ".runtime" / "locks" / "live-run.lock"


class LiveRunLock:
    """An exclusive-create lock file. A held lock is never broken automatically, even if stale."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.owned = False

    def acquire(self, owner: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LockHeld(f"{self.path} is held by {self.holder()}; wait, or remove it by hand if that "
                           f"process is gone") from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({**owner, "pid": os.getpid(), "acquired_at": utc_now()}, handle)
        self.owned = True

    def holder(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return f"pid {data.get('pid')} ({data.get('card') or data.get('owner') or 'unknown'}, since {data.get('acquired_at')})"
        except (OSError, ValueError):
            return "an unreadable holder"

    def release(self) -> None:
        if self.owned:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.owned = False


# ---------------------------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------------------------

def read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class Outcome:
    kind: str  # ok | failure | integrity
    detail: str
    records: List[dict] = field(default_factory=list)


class Campaign:
    """Paths and evidence for one card: attempt directories, the append-only campaign log, per-attempt logs."""

    def __init__(self, plan: Plan):
        self.plan = plan
        runs_root = plan.runner.runs_root if plan.runner else ROOT / "experiments" / "p6_pilot" / "runs"
        self.directory = runs_root / f"card-{plan.card['id']}"
        self.log_path = self.directory / "campaign.jsonl"

    @staticmethod
    def runs_root(inv: Invocation) -> Path:
        return inv.script.parent / "runs"

    def attempt_names(self, inv: Invocation) -> List[str]:
        names, attempt = [], 1
        while True:
            name = inv.run_name if attempt == 1 else f"{inv.run_name}-a{attempt}"
            if not (self.runs_root(inv) / name).exists():
                return names
            names.append(name)
            attempt += 1

    def next_attempt_name(self, inv: Invocation) -> str:
        names = self.attempt_names(inv)
        if names and not (self.runs_root(inv) / names[-1] / "results.jsonl").exists():
            return names[-1]  # interrupted: the runner keeps the old session and reruns in place
        return inv.run_name if not names else f"{inv.run_name}-a{len(names) + 1}"

    def records(self, inv: Invocation, name: str) -> List[dict]:
        wanted = set(inv.task_ids)
        return [r for r in read_jsonl(self.runs_root(inv) / name / "results.jsonl") if r.get("task_id") in wanted]

    def calls(self) -> List[dict]:
        """Every attempt record (calls.jsonl) of every attempt directory of the plan's invocations."""
        rows = []
        for inv in self.plan.invocations:
            if inv.script is None:
                continue
            for name in self.attempt_names(inv):
                rows += read_jsonl(self.runs_root(inv) / name / "calls.jsonl")
        return rows

    def used_attempts(self) -> int:
        return len(self.calls())

    def list_price_usd(self) -> float:
        """The sum of the CLI's list-price estimates (result total_cost_usd) over the campaign's attempts; attempts
        without one (scripted clients, failed spawns, OpenRouter) add nothing. Not a bill: see claude_cli.py."""
        return round(sum(float((row.get("cli_result") or {}).get("total_cost_usd") or 0) for row in self.calls()), 6)

    def log(self, event: str, **fields) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": utc_now(), "event": event, **fields}, ensure_ascii=False) + "\n")


def classify(plan: Plan, campaign: Campaign, inv: Invocation, name: str, exit_code) -> Outcome:
    """Plan section 5.3: integrity problems stop the campaign; provider/model errors may be retried."""
    run_dir = campaign.runs_root(inv) / name
    config_path = run_dir / "config.json"
    if config_path.exists() and inv.expected_config is not None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        differing = sorted(k for k, v in inv.expected_config.items() if config.get(k) != v)
        if differing:
            return Outcome("integrity", f"corrupted_protocol: {name}/config.json differs from the card in {differing} "
                                        f"(recorded protocol {config.get('protocol_hash')}, expected {inv.expected_hash})")
    records = campaign.records(inv, name)
    for record in records:
        if inv.expected_hash and record.get("protocol_hash") != inv.expected_hash:
            return Outcome("integrity", f"corrupted_protocol: {name} recorded protocol {record.get('protocol_hash')}, "
                                        f"expected {inv.expected_hash}", records)
    if len({r["task_id"] for r in records}) < len(inv.task_ids):
        if exit_code == 0:
            return Outcome("integrity", f"evidence_loss: {name} exited 0 without a result record for every task", records)
        return Outcome("failure", f"runner_error: {name} exited {exit_code} without a complete result record", records)
    budgets = plan.card["budgets"]["per_run"]
    for record in records:
        totals = record.get("totals") or {}
        if inv.client in LIVE_CLIENTS and (totals.get("model_calls") or 0) > budgets["responses"]:
            return Outcome("integrity", f"budget_violation: {name} used {totals.get('model_calls')} responses "
                                        f"(limit {budgets['responses']})", records)
        limit = budgets.get("model_attempts")
        if inv.client in LIVE_CLIENTS and limit is not None and (totals.get("provider_attempts") or 0) > limit:
            return Outcome("integrity", f"budget_violation: {name} used {totals.get('provider_attempts')} provider "
                                        f"attempts (limit {limit})", records)
    if inv.kind == "control":
        wrong = [r["task_id"] for r in records
                 if (r.get("acceptance", {}).get("status") == "accepted") != (inv.expect == "accepted")]
        if wrong:
            return Outcome("integrity", f"control_failed: {inv.name} expected {inv.expect} but not on {wrong}", records)
        return Outcome("ok", f"control {inv.name}: all {len(records)} {inv.expect}", records)
    failures = [r for r in records if is_model_failure(r)]
    pinned = [r for r in failures if "model_pin_violation" in ((r.get("agent") or {}).get("error") or "")]
    if pinned:  # the CLI answered with another model than the card pins: a corrupted protocol, never retried
        return Outcome("integrity", f"corrupted_protocol: {(pinned[0].get('agent') or {}).get('error', '')[:300]}", records)
    if failures:
        error = (failures[0].get("agent") or {}).get("error") or ""
        return Outcome("failure", f"model_error: {error[:200]}", records)
    record = records[0]
    return Outcome("ok", f"{record.get('stop')} -> {record.get('acceptance', {}).get('status')}", records)


def campaign_spend(campaign: "Campaign", events: Optional[List[dict]] = None) -> dict:
    """The nested model cost (CLI list price) and call count of a campaign, and its wall time from the first
    campaign_start to the last campaign event (None before a start)."""
    events = read_jsonl(campaign.log_path) if events is None else events
    times = []
    for event in events:
        try:
            times.append((event["event"], datetime.fromisoformat(event["time"])))
        except (KeyError, ValueError):
            continue
    starts = [time for name, time in times if name == "campaign_start"]
    wall = round((max(time for _, time in times) - starts[0]).total_seconds(), 1) if starts else None
    return {"nested_cost_usd": campaign.list_price_usd(), "nested_calls": len(campaign.calls()), "wall_seconds": wall}


def is_model_failure(record: dict) -> bool:
    """A provider/model error (the runner's stop label model_error), as opposed to a task outcome or guard."""
    return record.get("stop") == "model_error"


def completed_attempt(campaign: Campaign, inv: Invocation) -> Optional[str]:
    for name in campaign.attempt_names(inv):
        records = campaign.records(inv, name)
        if len({r["task_id"] for r in records}) == len(inv.task_ids) and not any(is_model_failure(r) for r in records):
            return name
    return None


def run_process(python: str, inv: Invocation, name: str, log_path: Path, timeout: Optional[float]):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [python, str(inv.script), *with_run_name(inv.args, name)]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"# {utc_now()} {shlex.join(command)}\n")
        handle.flush()
        try:
            return subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            handle.write(f"# killed after {timeout} s (invocation_wall_seconds)\n")
            return "timeout"


def preflight(plan: Plan, campaign: Campaign, python: str, out) -> Optional[Tuple[int, str]]:
    """Run the runner's own --dry-run once per live arm: it probes the real CLI version and OCI image and
    prints the protocol hash it would record. Scripted clients print no hash; the post-run check covers them."""
    seen = set()
    for inv in plan.invocations:
        key = (str(inv.script), inv.arm["name"], inv.client)
        if inv.client not in LIVE_CLIENTS or key in seen:
            continue
        seen.add(key)
        args = with_run_name(inv.args, f"{inv.run_name}-preflight") + ["--dry-run"]
        completed = subprocess.run([python, str(inv.script), *args], cwd=ROOT, capture_output=True, text=True,
                                   timeout=600)
        match = HASH_LINE.search(completed.stdout)
        observed = match.group(1) if match else None
        campaign.log("preflight", arm=inv.arm["name"], exit_code=completed.returncode, expected=inv.expected_hash,
                     observed=observed, stderr=completed.stderr[-500:])
        if completed.returncode != 0:
            return EXIT_REFUSED, f"preflight: the runner's --dry-run for arm {inv.arm['name']} failed: {completed.stderr.strip()[-300:]}"
        if observed != inv.expected_hash:
            return EXIT_INTEGRITY, (f"preflight: arm {inv.arm['name']} would record protocol {observed}; the card "
                                    f"expects {inv.expected_hash} (machine drift: CLI version, image ID, or engine?)")
        out(f"preflight {inv.arm['name']}: protocol {observed} matches")
    return None


def execute(plan: Plan, *, resume: bool = False, python: str = sys.executable, lock_path: Optional[Path] = None,
            sleep: Callable[[float], None] = time.sleep, out: Callable[[str], None] = print) -> int:
    if plan.blockers:
        out("refused: the plan has blockers:")
        for blocker in plan.blockers:
            out(f"  - {blocker}")
        return EXIT_REFUSED
    lock = LiveRunLock(lock_path or default_lock_path())
    try:
        lock.acquire({"card": plan.card["id"], "argv": sys.argv})
    except LockHeld as exc:
        out(f"refused: {exc}")
        return EXIT_LOCKED
    try:
        return _execute_locked(plan, resume, python, sleep, out)
    finally:
        lock.release()


def _execute_locked(plan: Plan, resume: bool, python: str, sleep, out) -> int:
    card, campaign = plan.card, Campaign(plan)
    existing = [inv.run_name for inv in plan.invocations if campaign.attempt_names(inv)]
    if existing and not resume:
        out(f"refused: {len(existing)} planned run directories already exist (first: {existing[0]}); pass --resume")
        return EXIT_REFUSED
    problems = engine_problems(plan)
    if problems:
        reason = "refused: " + "; ".join(problems)
        campaign.log("stop", reason=reason)
        out(reason)
        return EXIT_REFUSED
    campaign.log("host", **machine_facts(plan, python))
    stop = preflight(plan, campaign, python, out)
    if stop:
        campaign.log("stop", reason=stop[1])
        out(stop[1])
        return stop[0]
    rules = card["stop_rules"]
    campaign.log("campaign_start", card=card["id"], card_sha256=plan.card_sha256, resume=resume,
                 invocations=len(plan.invocations), sets=plan.sets, pid=os.getpid())
    consecutive, wall = 0, card["budgets"]["per_run"].get("invocation_wall_seconds")
    cap = card["budgets"]["campaign"].get("max_model_attempts")
    price_cap = card["budgets"]["campaign"].get("list_price_cap_usd")
    checked_units = set()

    def finish(code: int, reason: str) -> int:
        campaign.log({EXIT_OK: "campaign_end", EXIT_CHECKPOINT: "checkpoint_stop"}.get(code, "integrity_stop"),
                     reason=reason)
        path = write_report(plan)
        out(f"{reason}\nreport skeleton: {display_path(path)}")
        return code

    def over_cap(inv: Invocation) -> Optional[str]:
        """Before every attempt: the attempt must fit the campaign cap, and the first attempt in a unit
        (task x rollout) must leave room for every arm of the unit (plan 5.5: launch a pair only when both fit).
        With a list-price cap, the campaign's summed CLI list-price estimate must still be below it."""
        if price_cap is not None and inv.client in LIVE_CLIENTS:
            spent = campaign.list_price_usd()
            if spent >= price_cap:
                return (f"list-price cap: the campaign's calls total ${spent:.2f} at CLI list price, the card's cap is "
                        f"${price_cap:.2f}")
        if cap is None:
            return None
        pending = [inv]
        if inv.unit and inv.unit not in checked_units:
            checked_units.add(inv.unit)
            pending = [other for other in plan.runs if other.unit == inv.unit and not completed_attempt(campaign, other)]
        need, used = sum(other.attempt_allocation(card) for other in pending), campaign.used_attempts()
        if used + need > cap:
            return (f"campaign cap: {used} of {cap} model attempts used; the next "
                    f"{'unit' if len(pending) > 1 else 'attempt'} needs {need}")
        return None

    for inv in plan.invocations:
        done = completed_attempt(campaign, inv)
        if done:
            outcome = classify(plan, campaign, inv, done, 0)
            if outcome.kind == "integrity":
                return finish(EXIT_INTEGRITY, outcome.detail)
            campaign.log("skip", run=done, detail=outcome.detail)
            continue
        # Retries count across resumes (from the log), so --resume never grants an invocation fresh retries.
        retries = sum(1 for event in read_jsonl(campaign.log_path) if event["event"] == "invocation_end"
                      and event.get("base") == inv.run_name and event.get("outcome") == "failure")
        if retries > rules["max_retries_per_invocation"]:
            campaign.log("skip_exhausted", base=inv.run_name, failed_attempts=retries)
            continue
        while True:
            reason = over_cap(inv)
            if reason:
                return finish(EXIT_CHECKPOINT, reason)
            name = campaign.next_attempt_name(inv)
            campaign.log("invocation_start", index=inv.index, base=inv.run_name, run=name, retry=retries,
                         command=[display_path(inv.script), *with_run_name(inv.args, name)])
            started = time.time()
            exit_code = run_process(python, inv, name, campaign.directory / "logs" / f"{name}.log", wall)
            outcome = classify(plan, campaign, inv, name, exit_code)
            campaign.log("invocation_end", index=inv.index, base=inv.run_name, run=name, exit_code=exit_code,
                         outcome=outcome.kind,
                         detail=outcome.detail, elapsed_s=round(time.time() - started, 1))
            out(f"[{inv.index}/{len(plan.invocations)}] {name}: {outcome.kind} ({outcome.detail})")
            if outcome.kind == "integrity":
                return finish(EXIT_INTEGRITY, f"integrity stop: {outcome.detail}")
            if outcome.kind == "ok":
                consecutive = 0
                break
            consecutive += 1
            if consecutive >= rules["consecutive_failures_to_stop"]:
                return finish(EXIT_CHECKPOINT, f"checkpoint: {consecutive} consecutive failed attempts "
                                               f"(last: {outcome.detail}); resume with --resume")
            if retries >= rules["max_retries_per_invocation"]:
                campaign.log("invocation_failed", index=inv.index, run=name, detail=outcome.detail)
                break
            wait = rules["retry_backoff_seconds"][retries]
            campaign.log("backoff", index=inv.index, seconds=wait, after=name)
            sleep(wait)
            retries += 1
    return finish(EXIT_OK, f"campaign complete: {len(plan.invocations)} invocations")


# ---------------------------------------------------------------------------------------------
# Report skeleton
# ---------------------------------------------------------------------------------------------

REPORT_MARKER = "<!-- run_card skeleton sha256="


def wilson(accepted: int, total: int, z: float = 1.96) -> Optional[Tuple[float, float]]:
    if total == 0:
        return None
    p = accepted / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def collect(plan: Plan) -> List[dict]:
    """One entry per invocation: its attempts, final records, and status."""
    campaign, entries = Campaign(plan), []
    failures: Dict[str, int] = {}
    for event in read_jsonl(campaign.log_path):
        if event["event"] == "invocation_end" and event.get("outcome") == "failure":
            failures[event.get("base")] = failures.get(event.get("base"), 0) + 1
    allowed = plan.card["stop_rules"]["max_retries_per_invocation"]
    for inv in plan.invocations:
        attempts = campaign.attempt_names(inv) if inv.script else []
        done = completed_attempt(campaign, inv) if inv.script else None
        last = attempts[-1] if attempts else None
        records = campaign.records(inv, done or last) if (done or last) else []
        if done:
            status = "completed"
        elif failures.get(inv.run_name, 0) > allowed:
            status = "retries exhausted"
        elif not attempts:
            status = "pending"
        elif records:
            status = "failed"
        else:
            status = "interrupted"
        entries.append({"inv": inv, "attempts": attempts, "final": done or last, "records": records, "status": status})
    return entries


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value).replace("|", "\\|")


def _rate(k: int, n: int) -> str:
    return f"{k}/{n}" if n else "0/0"


def write_report(plan: Plan) -> Path:
    card, entries = plan.card, collect(plan)
    body = render_report(plan, entries)
    target = resolve_path(card["report"]["path"])
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        first, _, rest = existing.partition("\n")
        unedited = first.startswith(REPORT_MARKER) and hashlib.sha256(rest.encode("utf-8")).hexdigest() == \
            first[len(REPORT_MARKER):].split(" ")[0]
        if not unedited:
            target = target.with_name(target.stem + ".skeleton.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{REPORT_MARKER}{digest} -->\n{body}", encoding="utf-8")
    sets_path = card["report"].get("sets_path")
    if sets_path:
        write_sets(resolve_path(sets_path), plan, entries)
    return target


def outcome_table(plan: Plan, entries: List[dict]) -> Dict[str, Dict[str, List[bool]]]:
    """task -> arm -> accepted flags of completed runs."""
    table: Dict[str, Dict[str, List[bool]]] = {}
    for entry in entries:
        inv = entry["inv"]
        if inv.kind != "run" or entry["status"] != "completed":
            continue
        accepted = entry["records"][0].get("acceptance", {}).get("status") == "accepted"
        table.setdefault(inv.task_ids[0], {}).setdefault(inv.name, []).append(accepted)
    return table


def categories(flags: List[bool]) -> str:
    if not flags:
        return "none"
    if all(flags):
        return "all_accepted"
    return "none_accepted" if not any(flags) else "mixed"


def write_sets(path: Path, plan: Plan, entries: List[dict]) -> None:
    """Machine-derived categories under "derived"; hand-chosen lists (evolution_set, held_in, ...) are kept."""
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    table, derived = outcome_table(plan, entries), {}
    for arm in plan.card["arms"]:
        groups: Dict[str, List[str]] = {"all_accepted": [], "mixed": [], "none_accepted": []}
        for task_id, arms in table.items():
            if arm["name"] in arms:
                groups[categories(arms[arm["name"]])].append(task_id)
        derived[arm["name"]] = groups
    data["derived"] = {"card": plan.card["id"], "generated_at": utc_now(), "per_arm": derived}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def render_report(plan: Plan, entries: List[dict]) -> str:
    card, lines = plan.card, []
    add = lines.append
    try:
        link = os.path.relpath(plan.card_path, resolve_path(card["report"]["path"]).parent).replace(os.sep, "/")
    except ValueError:  # different drives
        link = plan.card_path.as_posix()
    add(f"# Report skeleton: {card['id']}")
    add("")
    add(f"Generated by `experiments/session_harness/run_card.py` at {utc_now()} from "
        f"[`{display_path(plan.card_path)}`]({link}) "
        f"(sha256 `{plan.card_sha256[:12]}`); human card: `{card['markdown']}`. Tables are rebuilt from each run's "
        f"`results.jsonl`; sections marked *to write* are the analyst's. Once this file is edited, regeneration "
        f"writes `*.skeleton.md` beside it instead.")
    add("")
    add(f"Hypothesis: {card['hypothesis']}")
    add("")
    add("## Protocol")
    add("")
    add("| Arm | Client / model | Policy | Toolset | Backend | Guards | Expected protocol | Recorded |")
    add("|---|---|---|---|---|---|---|---|")
    recorded: Dict[str, set] = {}
    for entry in entries:
        for record in entry["records"]:
            recorded.setdefault(entry["inv"].name, set()).add(record.get("protocol_hash"))
    for arm in card["arms"]:
        add(f"| {arm['name']} | {arm['client']} {arm.get('model') or ''} | {arm['policy']} | {arm['toolset']} | "
            f"{_cell(describe_backend(arm['backend']))} | `{json.dumps(guards_record(arm))}` | "
            f"{describe_hashes(plan.arm_hashes.get(arm['name']))} | "
            f"{describe_hashes(sorted(h for h in recorded.get(arm['name'], []) if h)) if recorded.get(arm['name']) else '-'} |")
    add("")
    add("## Tasks")
    add("")
    if plan.universe:
        add(f"Task file `{card['tasks']['file']}`: {len(plan.universe.order)} tasks, sha256 `{plan.universe.sha256[:12]}`.")
        add("")
    add("| Set | Source | Tasks |")
    add("|---|---|---|")
    for name, spec in card["tasks"]["sets"].items():
        source = next(key for key in ("ids", "rule", "ref", "from_sets", "unresolved") if key in spec)
        described = json.dumps(spec[source]) if source != "ids" else "explicit"
        if "take" in spec:
            described += f", take {json.dumps(spec['take'])}"
        ids = plan.sets.get(name)
        add(f"| {name} | {_cell(described)} | {', '.join(ids) if ids is not None else 'unresolved'} |")
    add("")
    for block in card["blocks"]:
        order = block["arm_order"]
        add(f"Block `{block['name']}`: set `{block['task_set']}`, arms {block['arms']}, {block['rollouts']} rollout(s), "
            f"arm order {order['rule']}" + (f" (seed {order['seed']})" if order["rule"] == "seeded" else "") + ".")
    add("")
    controls = [e for e in entries if e["inv"].kind == "control"]
    if controls:
        add("## Controls")
        add("")
        add("| Control | Like arm | Tasks | Expected | Accepted | Status | Run |")
        add("|---|---|---|---|---|---|---|")
        for entry in controls:
            inv = entry["inv"]
            accepted = sum(r.get("acceptance", {}).get("status") == "accepted" for r in entry["records"])
            add(f"| {inv.name} | {inv.arm['name']} | {len(inv.task_ids)} | {inv.expect} | "
                f"{_rate(accepted, len(entry['records']))} | {entry['status']} | {entry['final'] or '-'} |")
        add("")
    add("## Runs")
    add("")
    add("| # | Block | Task | Rollout | Arm | Run | Attempts | Stop | Status | Responses | Attempts (provider) | "
        "Tool calls | Active s | Wall s | Tokens in/out | Criteria |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for entry in entries:
        inv = entry["inv"]
        if inv.kind != "run":
            continue
        record = entry["records"][0] if entry["records"] else {}
        totals, agent = record.get("totals") or {}, record.get("agent") or {}
        consumed = (agent.get("task_resources") or {}).get("consumed") or {}
        usage = agent.get("usage_reported") or {}
        acceptance = record.get("acceptance") or {}
        status = acceptance.get("status") if entry["status"] == "completed" else entry["status"]
        tokens = (f"{int(usage['prompt_tokens'])}/{int(usage.get('completion_tokens') or 0)}"
                  if usage.get("prompt_tokens") is not None else "")
        add(f"| {inv.index} | {inv.block} | {inv.task_ids[0]} | {inv.rollout} | {inv.name} | {entry['final'] or '-'} | "
            f"{len(entry['attempts'])} | {_cell(record.get('stop'))} | {_cell(status)} | "
            f"{_cell(totals.get('model_calls'))} | {_cell(totals.get('provider_attempts'))} | "
            f"{_cell(totals.get('tool_calls'))} | {_cell(consumed.get('active_seconds'))} | "
            f"{_cell(record.get('elapsed_s'))} | {tokens} | {_cell(json.dumps(acceptance.get('criterion_outcomes')) if acceptance else '')} |")
    add("")
    table = outcome_table(plan, entries)
    add("## Summary by arm")
    add("")
    add("| Arm | Planned | Completed | Accepted | Rate | 95% interval (Wilson) | Failed attempts |")
    add("|---|---|---|---|---|---|---|")
    for arm in card["arms"]:
        mine = [e for e in entries if e["inv"].kind == "run" and e["inv"].name == arm["name"]]
        flags = [flag for arms in table.values() for flag in arms.get(arm["name"], [])]
        interval = wilson(sum(flags), len(flags))
        failed = sum(max(0, len(e["attempts"]) - (1 if e["status"] == "completed" else 0)) for e in mine)
        rate = f"{sum(flags) / len(flags):.2f}" if flags else "-"
        shown = f"{interval[0]:.2f}-{interval[1]:.2f}" if interval else "-"
        add(f"| {arm['name']} | {len(mine)} | {len(flags)} | {sum(flags)} | {rate} | {shown} | {failed} |")
    add("")
    add("## Per-task outcomes")
    add("")
    arm_names = [arm["name"] for arm in card["arms"]]
    add("| Task | Sets | " + " | ".join(arm_names) + " |")
    add("|---|---|" + "---|" * len(arm_names))
    for task_id in sorted(table):
        member = [name for name, ids in plan.sets.items() if ids and task_id in ids]
        add(f"| {task_id} | {', '.join(member)} | " + " | ".join(
            _rate(sum(table[task_id].get(a, [])), len(table[task_id].get(a, []))) for a in arm_names) + " |")
    add("")
    for arm in arm_names:
        groups: Dict[str, List[str]] = {}
        for task_id, arms in table.items():
            if arm in arms:
                groups.setdefault(categories(arms[arm]), []).append(task_id)
        if groups:
            add(f"Arm `{arm}` distribution: " + "; ".join(f"{k} {len(v)}" for k, v in sorted(groups.items()))
                + (f"; mixed (contrastive) tasks: {', '.join(sorted(groups.get('mixed', [])))}" if groups.get("mixed") else ""))
    add("")
    measured = card["measurements"]
    extra_sections = []
    add("## Measurements declared by the card")
    add("")
    add("| Measurement | Where | Status |")
    add("|---|---|---|")
    for name in measured["per_run"]:
        if name in RESULT_MEASUREMENTS:
            add(f"| {name} | {RESULT_MEASUREMENTS[name]} | filled from results.jsonl |")
        else:
            add(f"| {name} | {JOURNAL_MEASUREMENTS[name]} | pending: not in results.jsonl; derive from the session journal (S6b) |")
    for name in measured["campaign"]:
        match = PARAMETRIC_MEASUREMENT.match(name)
        if name in CAMPAIGN_MEASUREMENTS:
            add(f"| {name} | {CAMPAIGN_MEASUREMENTS[name]} | filled |")
        elif match and match.group(1):
            add(f"| {name} | Acceptance by `{match.group(2)}` | filled |")
            extra_sections.append(("by", match.group(1), match.group(2)))
        elif match:
            add(f"| {name} | Delta `{match.group(3)}` minus `{match.group(4)}` by task set | filled |")
            extra_sections.append(("delta", match.group(3), match.group(4)))
    add("")
    for kind, first, second in extra_sections:
        if kind == "by":
            add(f"### Acceptance by {'size of ' if first == 'acceptance_by_size' else ''}`{second}`")
            add("")
            add("| Value | Arm | Accepted | Rate |")
            add("|---|---|---|---|")
            buckets: Dict[Tuple[str, str], List[bool]] = {}
            for task_id, arms in table.items():
                task = plan.universe.tasks.get(task_id, {}) if plan.universe else {}
                value = task.get(second)
                key = str(len(value)) if first == "acceptance_by_size" and isinstance(value, list) else str(value)
                for arm, flags in arms.items():
                    buckets.setdefault((key, arm), []).extend(flags)
            for (value, arm), flags in sorted(buckets.items()):
                add(f"| {value} | {arm} | {_rate(sum(flags), len(flags))} | {sum(flags) / len(flags):.2f} |")
            add("")
        else:
            add(f"### Delta `{first}` - `{second}`")
            add("")
            add("Mean over tasks where both arms completed at least one run of (acceptance rate of "
                f"`{first}` minus that of `{second}`), per task set containing the task.")
            add("")
            add("| Task set | Tasks with both arms | Delta |")
            add("|---|---|---|")
            for set_name, ids in plan.sets.items():
                deltas = [sum(table[t][first]) / len(table[t][first]) - sum(table[t][second]) / len(table[t][second])
                          for t in (ids or []) if t in table and table[t].get(first) and table[t].get(second)]
                if deltas:
                    add(f"| {set_name} | {len(deltas)} | {sum(deltas) / len(deltas):+.3f} |")
            add("")
    if "paired_table" in measured["campaign"]:
        add("### Paired units")
        add("")
        add("| Block | Task | Rollout | Order | Outcomes | Complete |")
        add("|---|---|---|---|---|---|")
        units: Dict[str, List[dict]] = {}
        for entry in entries:
            if entry["inv"].kind == "run":
                units.setdefault(entry["inv"].unit, []).append(entry)
        for unit, members in units.items():
            first = members[0]["inv"]
            outcomes = ", ".join(f"{m['inv'].name}: {(m['records'][0].get('acceptance') or {}).get('status') if m['status'] == 'completed' else m['status']}"
                                 for m in members)
            complete = all(m["status"] == "completed" for m in members)
            add(f"| {first.block} | {first.task_ids[0]} | {first.rollout} | {' > '.join(m['inv'].name for m in members)} | "
                f"{outcomes} | {'yes' if complete else 'INCOMPLETE'} |")
        add("")
    add("## Campaign log")
    add("")
    campaign = Campaign(plan)
    events = read_jsonl(campaign.log_path)
    failures = [e for e in events if e["event"] == "invocation_end" and e.get("outcome") != "ok"]
    backoffs = [e for e in events if e["event"] == "backoff"]
    stops = [e for e in events if e["event"] in ("checkpoint_stop", "integrity_stop", "stop", "campaign_end")]
    add(f"Log: `{display_path(campaign.log_path)}`. {sum(e['event'] == 'invocation_start' for e in events)} "
        f"invocation attempts, {len(failures)} not ok, {len(backoffs)} backoffs "
        f"({', '.join(str(e['seconds']) + ' s' for e in backoffs) or 'none'}).")
    add("")
    for event in failures:
        add(f"- {event['time']} {event['run']}: {event['outcome']} ({event['detail']})")
    for event in stops:
        add(f"- {event['time']} {event['event']}: {event.get('reason', '')}")
    incomplete = sorted({e["inv"].unit for e in entries if e["inv"].kind == "run" and e["status"] != "completed"})
    add("")
    add(f"Incomplete units: {len(incomplete)}" + (f" (first: {incomplete[0]})" if incomplete else "") + ".")
    add("")
    price_cap = card["budgets"]["campaign"].get("list_price_cap_usd")
    if price_cap is not None:  # cards with a spend guard (the cloud cards); other reports are unchanged
        spend = campaign_spend(campaign, events)
        add("## Spend and time")
        add("")
        add(f"- nested model cost (CLI list price): ${spend['nested_cost_usd']:.2f} over {spend['nested_calls']} CLI "
            f"calls (the sum of `cli_result.total_cost_usd` in the campaign's `calls.jsonl`; card cap ${price_cap:.2f})")
        wall = spend["wall_seconds"]
        add(f"- wall time: " + ("n/a" if wall is None else f"{wall:.0f} s ({wall / 3600:.2f} h), first campaign_start "
                                                          f"to last campaign event"))
        add("- The supervising session's own usage is not included; the account's usage for the session's period "
            "minus the nested cost estimates it.")
        add("")
    add("## Decision rule (from the card)")
    add("")
    add(f"> {card['decision_rule']}")
    add("")
    add("## Analysis")
    add("")
    add("*to write*: outcome against the decision rule, trajectory review, what was not measured.")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("card", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--resume", action="store_true", help="with --execute: skip invocations already completed")
    parser.add_argument("--limit", type=int, default=None, help="with --plan: print only the first N invocations")
    parser.add_argument("--json", action="store_true", help="with --plan: print the plan as JSON")
    parser.add_argument("--replay", type=Path, default=None, metavar="RUN_DIR",
                        help="with --plan: compare the single planned run with RUN_DIR/config.json")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the runner (default: this one)")
    parser.add_argument("--lock", type=Path, default=None, help="lock file (default: <main checkout>/.runtime/locks/live-run.lock)")
    args = parser.parse_args(argv)

    card_path = args.card if args.card.is_absolute() else (Path.cwd() / args.card)
    card = load_card(card_path)
    errors = validate_card(card)
    if errors:
        print(f"{card_path}: {len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return EXIT_REFUSED
    if args.validate:
        print(f"{card_path}: valid")
        return EXIT_OK
    plan = build_plan(card, card_path.resolve())
    if args.plan:
        if args.json:
            print(json.dumps(plan_json(plan), indent=2))
        else:
            print_plan(plan, args.limit)
        if args.replay is not None:
            run_dir = args.replay if args.replay.is_absolute() else Path.cwd() / args.replay
            return EXIT_OK if replay_check(plan, run_dir) else EXIT_INTEGRITY
        return EXIT_OK
    if args.report:
        print(f"report skeleton: {display_path(write_report(plan))}")
        return EXIT_OK
    return execute(plan, resume=args.resume, python=args.python, lock_path=args.lock)


if __name__ == "__main__":
    sys.exit(main())
