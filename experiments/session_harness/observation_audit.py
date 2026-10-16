"""Observation audit (observation-audit-001): where do the model's observation bytes go, and when does it locate the bug?

For each recorded repair run on the mutation bank this measures, from the recorded transcript only (no model calls):

1. volume: bytes (and ~tokens = bytes / 4) of every tool result the model was shown, by tool;
2. locating: the response at which the mutated line (the gold site), the gold function and the gold file first
   became visible to the model, and the bytes shown before and after that point;
3. relevance: the share of shown bytes that are lines of the gold function, the rest of the gold file, other
   library files, other workspace files, or not source at all (program output, listings, headers), and a
   "used later" proxy;
4. re-reads: source lines shown again after an earlier observation already showed them, split by whether an
   earlier copy was still in the request's context or the context policy had omitted every earlier copy;
5. edits: whether the run edited the gold site / gold function / other files (for the failure reading);
6. context carried: tool-result bytes summed over every request that still contained them, against the prompt
   bytes the runner recorded; whole-file reads; how targeted the locating observation was; the first response
   whose own text or tool arguments name the gold function (an attention proxy);
7. an oracle-guided ladder counterfactual: whole-repo outline (`repo_outline.py`) + the gold function's source,
   against the bytes each run actually spent before locating.

Sources
- Reticle runs (cards 007, 019, 020): `calls.jsonl`. Every model request is recorded in full; a tool result is
  taken from the first request that carries it, which is the request for the response after the one that issued
  the call. Omissions by the context policy are read from the same requests (a tool message absent from a later
  request was omitted). `results.jsonl` supplies stop reason and acceptance. The session journal is not needed.
- Claude Code native runs (card 018): `stream.jsonl` + `result.json`, read with `weakness_mining.load_native_run`.
  Claude Code keeps one continuous conversation, so no result is ever treated as omitted.
- Task bank: `experiments/mutation_tasks/tasks.mutations.json` (mutation patch, file, function).
- Workspace text: an export of the sqlparse base commit (`--workspace`), hidden paths removed and the task's
  mutation patch applied (`repo_outline.workspace_files`), i.e. the files the model saw at the start of its run.

Indexing convention: responses are numbered 1..N in call order. A call issued in response k is first visible to
the model in response k + 1; "seen at k + 1" is what every *_seen field reports (`*_call` is k).

Attribution of shown text to workspace lines: each line of a tool result is stripped of a line-number or
`path:line:` prefix; a line is attributed to (file, line) when (a) a prefix or traceback frame names the file and
line and the text matches (or matches within 200 lines in that file, after edits), (b) its text (>= 8 chars)
occurs exactly once in the workspace, or (c) it continues a run of attributed lines (the next or previous line of
the same file). Everything else, including text the model created (repro scripts, program output), is
"unattributed". Lines changed by the model's own edits mostly stay unattributed.

Located = a site line was attributed in a shown result. The site is the mutation's `+` lines in the workspace; for
a pure deletion (removed guard) it is the line before and after the deletion point. Function touched = any line of
the gold function shown, or the gold function named with its address (an `outline` of the gold file, a traceback
frame `in <name>` in the gold file). Function read = at least min(5, function length) distinct lines of it shown.

Usage:
  python experiments/session_harness/observation_audit.py --workspace BASE_DIR \
      --card c007=experiments/p6_pilot/runs [--card c019=DIR ...] [--native c018=experiments/session_harness/native_runs] \
      [--json OUT.json] [--markdown OUT.md] [--trajectories 001,032,057,061,022]
Inputs for cards 019 and 020 live on result branches; extract them read-only first, e.g.
  git archive origin/cloud-results-019 experiments/p6_pilot/runs | tar -x -C SCRATCH/c019 --wildcards '*c019-*'
  git archive origin/cloud-results-020 experiments/p6_pilot/runs | tar -x -C SCRATCH/c020 --wildcards '*c020-*'
and pass --card c019=SCRATCH/c019/experiments/p6_pilot/runs. BASE_DIR:
  git -C .runtime/bug-mining/repos/sqlparse archive f66d12c | tar -x -C SCRATCH/sqlparse-base
`--card NAME=DIR` reads DIR/NAME-sqlparse-mut-* runs (controls skipped; for restarted runs `-a2/-a3` only the last
attempt counts; runs without `results.jsonl` are listed as unfinished and skipped). A run directory suffix after
`-rN-` (e.g. `-check-oracle`) is its arm. Single-threaded, a few seconds per card.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import statistics
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repo_outline  # noqa: E402

ROOT = HERE.parents[1]
DEFAULT_TASKS = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"

EDIT_TOOLS = {"replace_text", "write_file", "Edit", "Write", "MultiEdit"}
NON_OBSERVATION = {"finish"}
RUN_EDIT = re.compile(r"\bsed\s+-i\b|open\([^)]*['\"][wa]['\"]|write_text\(|>\s*\S+\.py\b|\bpatch\b", re.I)
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{4,}")
HEADER = re.compile(r"^\[tool result status=(?P<status>\w+); output=(?P<handle>\S+?)\]\n?")
READ_HEADER = re.compile(r"^(?P<path>\S+) \(lines (?P<a>\d+)-(?P<b>\d+) of \d+\)$")
HANDLE_HEADER = re.compile(r"^(?P<handle>out_\d+) lines \d+-\d+ of \d+:$")
OUTLINE_HEADER = re.compile(r"^Outline of (?P<path>\S+):$")
OUTLINE_ENTRY = re.compile(r"^L(?P<line>\d+): (?:class|function|method|def) (?P<name>\w+)")
REPLACED_HEADER = re.compile(r"^Replaced \d+ occurrence\(s\) in (?P<path>\S+)\. Lines")
PATH_LINE = re.compile(r"^(?P<path>[\w./\\:-]+?\.[A-Za-z]+):(?P<line>\d+):(?: in (?P<fn>\w+)$)?(?P<text>.*)$")
NUMBERED = re.compile(r"^\s*(?P<line>\d+)(?:\| ?|\t|→)(?P<text>.*)$")
TRACE_FRAME = re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<fn>[\w<>]+)')
SEARCH_OUT = re.compile(r"^L\d+: ")
GREP_CONTEXT = re.compile(r"^(?P<path>[\w./\\:-]+?\.[A-Za-z]+)-(?P<line>\d+)-(?P<text>.*)$")
BARE_NUMBERED = re.compile(r"^(?P<line>\d+)[:-](?P<text>.*)$")
FILE_TOKEN = re.compile(r"[\w./\-]+\.(?:py|rst|md|toml|txt|cfg)\b")
TOKENS_PER_BYTE = 0.25
SPECIFIC_FILES = 2  # an identifier is "specific" when at most this many workspace files contain it


# ----------------------------------------------------------------------------------------------- workspace

@dataclass
class Workspace:
    task: dict
    files: Dict[str, List[str]]  # path -> lines (1-based via index + 1)
    index: Dict[str, List[Tuple[str, int]]]
    by_name: Dict[str, List[str]]
    gold_file: str
    func_range: Tuple[int, int]
    func_name: str
    site: Set[int]
    statement_idents: Set[str]
    ident_files: Dict[str, int]  # identifier -> number of workspace files containing it

    def text(self, path: str, line: int) -> Optional[str]:
        lines = self.files.get(path)
        if lines is None or not 1 <= line <= len(lines):
            return None
        return lines[line - 1].strip()

    def norm_path(self, raw: str) -> Optional[str]:
        path = raw.replace("\\", "/").strip().strip("'\"")
        if path in self.files:
            return path
        if path.startswith("./") and path[2:] in self.files:
            return path[2:]
        for candidate in self.by_name.get(path.rsplit("/", 1)[-1], []):
            if path.endswith("/" + candidate):
                return candidate
        return None


def site_lines(task: dict) -> Set[int]:
    """Workspace (post-mutation) line numbers of the mutation site."""
    site: Set[int] = set()
    for hunk in re.split(r"(?m)^@@ ", task["mutation_patch"])[1:]:
        header, _, body = hunk.partition("\n")
        new_line = int(re.search(r"\+(\d+)", header).group(1))
        deletion_at: Optional[int] = None
        for raw in body.splitlines():
            tag = raw[:1] if raw else " "
            if tag == "+":
                site.add(new_line)
                new_line += 1
            elif tag == "-":
                deletion_at = new_line
            elif tag == " ":
                new_line += 1
        if not site and deletion_at is not None:
            site.update({deletion_at - 1, deletion_at})
    return site


def build_workspace(base: Path, task: dict) -> Workspace:
    texts = repo_outline.workspace_files(base, task)
    files = {path: text.splitlines() for path, text in texts.items()}
    index: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    by_name: Dict[str, List[str]] = defaultdict(list)
    for path, lines in files.items():
        by_name[path.rsplit("/", 1)[-1]].append(path)
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped:
                index[stripped].append((path, number))
    ident_files: Counter = Counter()
    for text in texts.values():
        ident_files.update(set(IDENT.findall(text)))
    outline = repo_outline.build_outline({p: t for p, t in texts.items() if p == task["mutation_file"]})
    symbol = repo_outline.find_symbol(outline, task["mutation_file"], task["mutated_function"])
    return Workspace(task, files, dict(index), dict(by_name), task["mutation_file"],
                     (symbol.line, symbol.end_line), symbol.name, site_lines(task),
                     set(IDENT.findall(task["statement"])), dict(ident_files))


# ----------------------------------------------------------------------------------------------- trajectories

@dataclass
class Call:
    call_id: str
    tool: str
    arguments: dict
    issued: int  # response index that issued it
    content: Optional[str] = None  # what the model was shown; None if never shown
    status: Optional[str] = None
    handle: Optional[str] = None


@dataclass
class Run:
    card: str
    arm: str
    name: str
    task_id: str
    source: str
    responses: int
    texts: Dict[int, str]  # response index -> model text + tool-call arguments
    calls: List[Call]
    present: Dict[int, Set[str]]  # response index -> tool_call_ids present in its request
    prompt_bytes: int
    stop: str
    accepted: bool
    outcome: str


def _arm(name: str) -> str:
    match = re.search(r"-r\d+(?:-a\d+)?-(?!a\d+$)(?P<arm>[a-z][\w-]*)$", name)
    return match.group("arm") if match else "incumbent"


def load_reticle(run_dir: Path, card: str) -> Optional[Run]:
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        return None
    result = json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])
    by_index: Dict[int, dict] = {}
    for line in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        response = record.get("response") or {}
        if response.get("choices"):
            by_index[record["call_index"]] = record  # the last successful attempt of each call index
    calls: Dict[str, Call] = {}
    order: List[Call] = []
    texts: Dict[int, str] = {}
    present: Dict[int, Set[str]] = {}
    prompt_bytes = 0
    for number, call_index in enumerate(sorted(by_index), 1):
        record = by_index[call_index]
        request = record["request"]
        prompt_bytes += int(request.get("prompt_bytes") or 0)
        ids: Set[str] = set()
        for message in request["messages"]:
            if message.get("role") == "tool":
                ids.add(message.get("tool_call_id"))
                call = calls.get(message.get("tool_call_id"))
                if call is not None and call.content is None:
                    content = message.get("content") or ""
                    header = HEADER.match(content)
                    if header:
                        call.status, call.handle = header.group("status"), header.group("handle")
                        content = content[header.end():]
                    call.content = content
        present[number] = ids
        message = record["response"]["choices"][0]["message"]
        pieces = [message.get("content") or ""]
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": function.get("arguments")}
            call = Call(tool_call["id"], function.get("name") or "?", arguments if isinstance(arguments, dict) else {},
                        number)
            calls[call.call_id] = call
            order.append(call)
            pieces.append(json.dumps(call.arguments, ensure_ascii=False))
        texts[number] = "\n".join(pieces)
    stop = result.get("stop") or (result.get("agent") or {}).get("stop_reason") or "?"
    accepted = (result.get("acceptance") or {}).get("status") == "accepted"
    outcome = "accepted" if accepted else ("rejected-finish" if stop == "finish_requested" else "rejected-budget")
    return Run(card, _arm(run_dir.name), run_dir.name, result["task_id"], "reticle", len(by_index), texts, order,
               present, prompt_bytes, stop, accepted, outcome)


def load_native(run_dir: Path, card: str) -> Optional[Run]:
    import weakness_mining  # noqa: E402  (same directory)

    if not (run_dir / "result.json").exists():
        return None
    trajectory = weakness_mining.load_native_run(run_dir)
    calls: List[Call] = []
    texts: Dict[int, str] = {}
    for response in trajectory.responses:
        pieces = [response.text]
        for index, call in enumerate(response.calls):
            arguments = call.arguments if isinstance(call.arguments, dict) else {}
            calls.append(Call(call.call_id or f"{response.index}_{index}", call.tool, arguments, response.index,
                              call.content if call.status is not None else None, call.status))
            pieces.append(json.dumps(arguments, ensure_ascii=False))
        texts[response.index] = "\n".join(pieces)
    count = len(trajectory.responses)
    seen: Set[str] = set()
    present: Dict[int, Set[str]] = {}
    for number in range(1, count + 2):
        present[number] = set(seen)
        seen.update(c.call_id for c in calls if c.issued == number)
    # A result the model received after its last assistant message was never acted on; drop it like Reticle's.
    for call in calls:
        if call.issued >= count:
            call.content = None
    accepted = trajectory.acceptance_status == "accepted"
    outcome = "accepted" if accepted else ("rejected-finish" if trajectory.stop_class == "finish" else "rejected-budget")
    return Run(card, "native", run_dir.name, trajectory.task_id, "claude-code", count, texts, calls, present, 0,
               trajectory.stop_reason, accepted, outcome)


def discover(directory: Path, card: str) -> Tuple[List[Path], List[str]]:
    """Run directories of a card: controls and superseded restarts skipped; returns (dirs, skipped notes)."""
    chosen: Dict[str, Tuple[int, Path]] = {}
    skipped: List[str] = []
    for path in sorted(directory.glob(f"{card}-sqlparse-mut-*")):
        if not path.is_dir() or ".void-" in path.name:
            continue
        match = re.match(rf"{card}-(?P<task>sqlparse-mut-\d+)-(?P<roll>r\d+)(?:-a(?P<att>\d+))?(?P<rest>-.*)?$",
                         path.name)
        if not match:
            continue
        key = f"{match.group('task')}-{match.group('roll')}{match.group('rest') or ''}"
        attempt = int(match.group("att") or 1)
        if key in chosen:
            older = chosen[key] if chosen[key][0] < attempt else (attempt, path)
            skipped.append(f"{older[1].name} (superseded restart)")
            if chosen[key][0] > attempt:
                continue
        chosen[key] = (attempt, path)
    return [path for _, path in sorted(chosen.values(), key=lambda item: item[1].name)], skipped


# ----------------------------------------------------------------------------------------------- attribution

@dataclass
class Observation:
    call: Call
    seen: int
    nbytes: int
    lines: List[Tuple[Optional[str], Optional[int], int]]  # (file, line, bytes) per shown line
    touched_function: bool = False
    named_gold_file: bool = False
    truncated: bool = False


def attribute(content: str, call: Call, ws: Workspace, handles: Dict[str, str]) -> Observation:
    raw_lines = content.split("\n")
    # text (None for headers/frames, "" for blank lines), hinted file, hinted line, bytes
    parsed: List[Tuple[Optional[str], Optional[str], Optional[int], int]] = []
    current: Optional[str] = None
    path_argument = call.arguments.get("path") or call.arguments.get("file_path")
    if call.tool in {"read_file", "Read", "replace_text", "Edit", "outline", "Grep", "search_text"} and             isinstance(path_argument, str):
        current = ws.norm_path(path_argument)
    if call.tool in {"run", "Bash", "PowerShell"}:
        named_files = {ws.norm_path(t) for t in FILE_TOKEN.findall(str(call.arguments.get("command", "")))} - {None}
        current = named_files.pop() if len(named_files) == 1 else None
    if call.tool in {"read_output", "search_output"} and isinstance(call.arguments.get("id"), str):
        current = handles.get(call.arguments["id"].strip())
    touched = False
    named = False
    outline_file: Optional[str] = None
    pending_frame: Optional[Tuple[str, int]] = None
    for raw in raw_lines:
        size = len(raw.encode("utf-8")) + 1
        text, file, line = raw, None, None
        header = READ_HEADER.match(raw) or REPLACED_HEADER.match(raw) or OUTLINE_HEADER.match(raw)
        if header:
            current = ws.norm_path(header.group("path")) or current
            outline_file = current if raw.startswith("Outline of") else None
            if current == ws.gold_file:
                named = True
            parsed.append((None, None, None, size))
            continue
        handle_header = HANDLE_HEADER.match(raw)
        if handle_header:
            current = handles.get(handle_header.group("handle"), current)
            parsed.append((None, None, None, size))
            continue
        entry = OUTLINE_ENTRY.match(raw)
        if entry and outline_file:
            if outline_file == ws.gold_file and entry.group("name") == ws.func_name and \
                    abs(int(entry.group("line")) - ws.func_range[0]) <= 3:
                touched = True
            parsed.append((None, None, None, size))
            continue
        frame = TRACE_FRAME.search(raw)
        if frame:
            frame_file = ws.norm_path(frame.group("path"))
            if frame_file:
                pending_frame = (frame_file, int(frame.group("line")))
                if frame_file == ws.gold_file and frame.group("fn") == ws.func_name:
                    touched = True
            parsed.append((None, None, None, size))
            continue
        if SEARCH_OUT.match(raw):
            text = raw.split(": ", 1)[1] if ": " in raw else raw
        match = PATH_LINE.match(raw) or GREP_CONTEXT.match(raw)
        bare = BARE_NUMBERED.match(raw) if not match else None
        if match and ws.norm_path(match.group("path")):
            file, line = ws.norm_path(match.group("path")), int(match.group("line"))
            text = match.group("text") or ""
            if text.startswith(":"):
                text = text[1:]
            if match.groupdict().get("fn"):
                if file == ws.gold_file and match.group("fn") == ws.func_name:
                    touched = True
                text = ""
        else:
            numbered = NUMBERED.match(raw)
            if numbered and current:
                file, line, text = current, int(numbered.group("line")), numbered.group("text")
            elif bare and current:
                file, line, text = current, int(bare.group("line")), bare.group("text")
            elif bare:
                text = bare.group("text")
            elif pending_frame:
                file, line = pending_frame
        pending_frame = None if not frame else pending_frame
        if ws.norm_path(raw.strip()) == ws.gold_file:
            named = True
        stripped = re.sub(r"^[>+\-]?\s*", "", text).strip() if not (file and line) else text.strip()
        parsed.append((stripped, file, line, size))

    resolved: List[Tuple[Optional[str], Optional[int]]] = []
    for text, file, line, _ in parsed:
        resolved.append(_resolve(text, file, line, ws))
    # alignment passes: extend attributed runs to neighbouring lines of the same file (blank lines skipped over)
    for step, order in ((-1, range(len(parsed))), (1, range(len(parsed) - 1, -1, -1))):
        for i in order:
            if resolved[i][0] is not None or not parsed[i][0]:
                continue
            j, distance = i + step, 1
            while 0 <= j < len(parsed) and parsed[j][0] == "" and resolved[j][0] is None:
                j, distance = j + step, distance + 1
            if 0 <= j < len(parsed) and resolved[j][0] is not None:
                file, line = resolved[j]
                candidate = line - step * distance
                if ws.text(file, candidate) == parsed[i][0]:
                    resolved[i] = (file, candidate)
    lines = [(f, n, parsed[i][3]) for i, (f, n) in enumerate(resolved)]
    truncated = "[output out_" in content and "More: read_output" in content
    return Observation(call, call.issued + 1, len(content.encode("utf-8")), lines, touched, named, truncated)


def _resolve(text: str, file: Optional[str], line: Optional[int], ws: Workspace) -> Tuple[Optional[str], Optional[int]]:
    if not text:
        return None, None
    if file and line:
        if ws.text(file, line) == text:
            return file, line
        nearby = [n for f, n in ws.index.get(text, []) if f == file and abs(n - line) <= 200]
        if nearby:
            return file, min(nearby, key=lambda n: abs(n - line))
        return None, None
    candidates = ws.index.get(text, [])
    if len(candidates) == 1 and len(text) >= 8:
        return candidates[0]
    return None, None


# ----------------------------------------------------------------------------------------------- metrics

def whole_file_read(call: Call) -> bool:
    """A read of a whole file: read_file/Read without a line range, or a bare `cat FILE` command."""
    a = call.arguments
    if call.tool == "read_file":
        return a.get("start_line") in (None, "", 1, "1") and a.get("end_line") in (None, "")
    if call.tool == "Read":
        return not a.get("offset") and not a.get("limit")
    if call.tool in {"run", "Bash", "PowerShell"}:
        return bool(re.match(r"^\s*(?:cat|type|get-content)\s+\S+\s*$", str(a.get("command", "")), re.I))
    return False


def edit_targets(call: Call, ws: Workspace) -> Tuple[Optional[str], Set[int]]:
    """(file, workspace lines the edit's old text covers) for a text edit; lines empty if not locatable."""
    path = call.arguments.get("path") or call.arguments.get("file_path")
    file = ws.norm_path(path) if isinstance(path, str) else None
    old = call.arguments.get("old_text") or call.arguments.get("old_string") or ""
    if call.tool == "MultiEdit":
        old = "\n".join(e.get("old_string", "") for e in call.arguments.get("edits") or [])
    covered: Set[int] = set()
    if file and old:
        previous: Optional[int] = None
        for raw in old.split("\n"):
            text = raw.strip()
            if not text:
                if previous:
                    previous += 1
                continue
            hits = [n for f, n in ws.index.get(text, []) if f == file]
            if not hits and len(text) >= 6:  # a fragment of a line (Claude Code's Edit often uses one)
                hits = [n for n, source in enumerate(ws.files.get(file, []), 1) if text in source]
            if previous and previous + 1 in hits:
                n = previous + 1
            elif len(hits) == 1:
                n = hits[0]
            elif hits and previous:
                n = min(hits, key=lambda h: abs(h - previous))
            else:
                n = None
            if n:
                covered.add(n)
                previous = n
    return file, covered


def analyse(run: Run, ws: Workspace) -> dict:
    handles: Dict[str, str] = {}
    observations: List[Observation] = []
    for call in run.calls:
        if call.tool in NON_OBSERVATION:
            continue
        if call.content is None:
            continue
        observation = attribute(call.content, call, ws, handles)
        if call.handle and call.tool == "read_file":
            path = call.arguments.get("path")
            if isinstance(path, str) and ws.norm_path(path):
                handles[call.handle] = ws.norm_path(path)
        observations.append(observation)

    first, last = ws.func_range
    func_lines = set(range(first, last + 1))
    need = min(5, len(func_lines))
    total = sum(o.nbytes for o in observations)
    by_tool: Counter = Counter()
    for o in observations:
        by_tool[o.call.tool] += o.nbytes

    site_seen = func_touch = func_read = file_seen = file_named = None
    seen_func: Set[int] = set()
    seen_lines: Dict[Tuple[str, int], List[str]] = defaultdict(list)  # (file, line) -> call ids that showed it
    categories: Counter = Counter()
    per_obs_categories: Dict[int, Counter] = {}
    reread_bytes = reread_in_context = reread_after_omission = 0
    reread_obs_in_context = reread_obs_after_omission = 0
    repeats: Counter = Counter()
    repeat_calls = 0
    for o in sorted(observations, key=lambda o: (o.seen, run.calls.index(o.call))):
        key = (o.call.tool, json.dumps(o.call.arguments, sort_keys=True))
        if repeats[key]:
            repeat_calls += 1
        repeats[key] += 1
        present = run.present.get(o.call.issued, set())
        o_reread_ctx = o_reread_om = 0
        o_attr = 0
        mine = per_obs_categories.setdefault(id(o), Counter())
        for file, line, size in o.lines:
            if file is None:
                mine["unattributed"] += size
                continue
            o_attr += size
            if file == ws.gold_file and line in func_lines:
                mine["gold function"] += size
                seen_func.add(line)
            elif file == ws.gold_file:
                mine["gold file, other lines"] += size
            elif file.startswith("sqlparse/") and file.endswith(".py"):
                mine["other library files"] += size
            else:
                mine["other workspace files"] += size
            if file == ws.gold_file:
                file_seen = file_seen or o.seen
                if line in ws.site:
                    site_seen = site_seen or o.seen
                if line in func_lines:
                    func_touch = func_touch or o.seen
            earlier = seen_lines[(file, line)]
            if earlier:
                reread_bytes += size
                if any(cid in present for cid in earlier):
                    reread_in_context += size
                    o_reread_ctx += size
                else:
                    reread_after_omission += size
                    o_reread_om += size
        for file, line, _ in o.lines:
            if file is not None:
                seen_lines[(file, line)].append(o.call.call_id)
        if o_attr and (o_reread_ctx + o_reread_om) / o_attr >= 0.5:
            if o_reread_om > o_reread_ctx:
                reread_obs_after_omission += 1
            else:
                reread_obs_in_context += 1
        if o.touched_function:
            func_touch = func_touch or o.seen
        if file_named is None and (o.named_gold_file or any(f == ws.gold_file for f, _, _ in o.lines)):
            file_named = o.seen
        if func_read is None and len(seen_func) >= need:
            func_read = o.seen

    for o in observations:
        categories.update(per_obs_categories[id(o)])
    # the observation that first showed the site: how targeted was it?
    locating = None
    for o in sorted(observations, key=lambda o: (o.seen, run.calls.index(o.call))):
        if any(f == ws.gold_file and n in ws.site for f, n, _ in o.lines):
            locating = o
            break
    whole_file_bytes = sum(o.nbytes for o in observations if whole_file_read(o.call))
    before = sum(o.nbytes for o in observations if site_seen and o.seen <= site_seen)
    if not site_seen:
        before = total
    categories_before: Counter = Counter()
    for o in observations:
        if site_seen and o.seen <= site_seen:
            categories_before.update(per_obs_categories[id(o)])
    # context carried: every request re-sends the tool results still in it (Reticle: stateless per request)
    by_id = {o.call.call_id: o for o in observations}
    carried = carried_no_gold = 0
    for number in range(1, run.responses + 1):
        for call_id in run.present.get(number, ()):
            o = by_id.get(call_id)
            if o is None:
                continue
            carried += o.nbytes
            if not any(f == ws.gold_file for f, _, _ in o.lines):
                carried_no_gold += o.nbytes

    # attention proxy: the first response whose own text or tool arguments name the gold function (its bare name
    # when specific, else its class, e.g. `process` -> `StripWhitespaceFilter`)
    parts = ws.task["mutated_function"].split(".")
    key = parts[-1]
    if ws.ident_files.get(key, 0) > SPECIFIC_FILES and len(parts) > 1:
        key = parts[-2]
    model_named = next((k for k in sorted(run.texts) if re.search(rf"\b{re.escape(key)}\b", run.texts[k])), None)

    # used-later proxies
    later_text: Dict[int, str] = run.texts
    mentioned_before: Set[str] = set(ws.statement_idents)
    used_obs_bytes = 0
    quoted_bytes = attributed = 0
    by_seen: Dict[int, List[Observation]] = defaultdict(list)
    for o in observations:
        by_seen[o.seen].append(o)
    for number in range(1, run.responses + 2):
        future = "\n".join(later_text[k] for k in later_text if k >= number)
        for o in by_seen.get(number, []):
            identifiers: Set[str] = set()
            for file, line, size in o.lines:
                if file is None:
                    continue
                text = ws.text(file, line) or ""
                attributed += size
                if len(text) >= 15 and text in future:
                    quoted_bytes += size
                identifiers.update(IDENT.findall(text))
            fresh = {name for name in identifiers - mentioned_before if ws.ident_files.get(name, 0) <= SPECIFIC_FILES}
            if any(re.search(rf"\b{re.escape(name)}\b", future) for name in fresh):
                used_obs_bytes += o.nbytes
        mentioned_before.update(IDENT.findall(later_text.get(number, "")))

    edits = []
    for call in run.calls:
        if call.tool in EDIT_TOOLS and call.status != "error":
            file, covered = edit_targets(call, ws)
            edits.append({"response": call.issued, "file": file or call.arguments.get("path")
                          or call.arguments.get("file_path"),
                          "site": bool(covered & ws.site), "function": bool(covered & func_lines),
                          "gold_file": file == ws.gold_file})
        elif call.tool in {"run", "Bash"} and RUN_EDIT.search(str(call.arguments.get("command", ""))):
            edits.append({"response": call.issued, "file": "(run command)", "site": False, "function": False,
                          "gold_file": ws.gold_file in str(call.arguments.get("command", ""))})
    library_edits = [e for e in edits if isinstance(e["file"], str) and e["file"].startswith("sqlparse/")]
    first_edit = min((e["response"] for e in library_edits), default=None)
    edited_site = any(e["site"] for e in edits)
    edited_function = any(e["function"] for e in edits)
    if site_seen is None:
        reading = "never-located"
    elif not edited_function and not edited_site:
        reading = "located-edited-elsewhere" if library_edits else "located-no-library-edit"
    else:
        reading = "edited-gold-function" + ("+site" if edited_site else "")

    return {
        "card": run.card, "arm": run.arm, "run": run.name, "task": run.task_id[-3:], "source": run.source,
        "outcome": run.outcome, "stop": run.stop, "responses": run.responses,
        "observations": len(observations), "obs_bytes": total, "obs_tokens": round(total * TOKENS_PER_BYTE),
        "bytes_by_tool": dict(by_tool), "prompt_bytes": run.prompt_bytes,
        "site_seen": site_seen, "func_touched_seen": func_touch, "func_read_seen": func_read,
        "gold_file_content_seen": file_seen, "gold_file_named_seen": file_named,
        "bytes_before_site": before, "bytes_after_site": total - before,
        "categories": dict(categories), "categories_before_site": dict(categories_before),
        "carried_obs_bytes": carried, "carried_no_gold_bytes": carried_no_gold,
        "whole_file_read_bytes": whole_file_bytes,
        "model_named_function_at": model_named,
        "function_key": key,
        "gold_function_bytes": sum(len(line.encode("utf-8")) + 1
                                   for line in ws.files[ws.gold_file][ws.func_range[0] - 1:ws.func_range[1]]),
        "locating_tool": locating.call.tool if locating else None,
        "locating_bytes": locating.nbytes if locating else None,
        "locating_whole_file": whole_file_read(locating.call) if locating else None,
        "locating_gold_function_share": (
            round(sum(s for f, n, s in locating.lines if f == ws.gold_file and ws.func_range[0] <= n <= ws.func_range[1])
                  / max(1, sum(s for f, _, s in locating.lines if f)), 2) if locating else None),
        "reread_bytes": reread_bytes, "reread_in_context_bytes": reread_in_context,
        "reread_after_omission_bytes": reread_after_omission,
        "reread_obs_in_context": reread_obs_in_context, "reread_obs_after_omission": reread_obs_after_omission,
        "identical_repeat_calls": repeat_calls,
        "used_later_obs_bytes": used_obs_bytes, "quoted_later_bytes": quoted_bytes, "attributed_bytes": attributed,
        "truncated_results": sum(1 for o in observations if o.truncated),
        "read_output_calls": sum(1 for o in observations if o.call.tool in {"read_output", "search_output"}),
        "outline_calls": sum(1 for o in observations if o.call.tool == "outline"),
        "outline_of_gold_file": any(o.call.tool == "outline" and o.touched_function for o in observations),
        "edits": edits, "first_library_edit": first_edit, "edited_site": edited_site,
        "edited_function": edited_function,
        "edited_outside_gold": any(isinstance(e["file"], str) and e["file"].startswith("sqlparse/")
                                   and not e["gold_file"] for e in library_edits),
        "reading": reading,
        "gold": {"file": ws.gold_file, "function": ws.task["mutated_function"], "range": list(ws.func_range),
                 "site": sorted(ws.site)},
    }


# ----------------------------------------------------------------------------------------------- report

def _median(values: Iterable[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _fmt(value, digits=0) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return f"{value:,}"


def _kb(value) -> str:
    return "-" if value is None else f"{value / 1000:,.1f}"


def tables(rows: List[dict]) -> str:
    out: List[str] = []
    groups: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["card"], r["arm"], r["outcome"])].append(r)
        groups[(r["card"], r["arm"], "all")].append(r)
    order = sorted(groups, key=lambda k: (k[0], k[1], ["all", "accepted", "rejected-finish", "rejected-budget"].index(k[2])))

    out.append("### Volume and locating (medians per run; KB = 1,000 bytes; ~tokens = bytes / 4)\n")
    out.append("| Card | Arm | Outcome | Runs | Responses | Shown KB | ~k tokens | Prompt KB sent | Located (site seen) | "
               "Site seen at | Fn read at | File content at | KB before locating | Share before |")
    out.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for key in order:
        g = groups[key]
        located = sum(1 for r in g if r["site_seen"])
        share = [r["bytes_before_site"] / r["obs_bytes"] for r in g if r["site_seen"] and r["obs_bytes"]]
        out.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(g)} | {_fmt(_median(r['responses'] for r in g), 1)} | "
            f"{_kb(_median(r['obs_bytes'] for r in g))} | {_fmt(_median(r['obs_tokens'] / 1000 for r in g), 1)} | "
            f"{_kb(_median(r['prompt_bytes'] for r in g)) if g[0]['source'] == 'reticle' else '-'} | "
            f"{located}/{len(g)} | {_fmt(_median(r['site_seen'] for r in g), 1)} | "
            f"{_fmt(_median(r['func_read_seen'] for r in g), 1)} | {_fmt(_median(r['gold_file_content_seen'] for r in g), 1)} | "
            f"{_kb(_median(r['bytes_before_site'] for r in g if r['site_seen']))} | "
            f"{_fmt(_median(share) * 100 if share else None, 0)}% |")

    out.append("\n### Shown bytes by tool (sum over runs, % of card/arm total)\n")
    tool_groups: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    for r in rows:
        tool_groups[(r["card"], r["arm"])].update(r["bytes_by_tool"])
    tools = sorted({t for c in tool_groups.values() for t in c}, key=lambda t: -sum(c[t] for c in tool_groups.values()))
    out.append("| Card | Arm | Total KB | " + " | ".join(tools) + " |")
    out.append("|---|---|--:|" + "--:|" * len(tools))
    for key, counter in sorted(tool_groups.items()):
        whole = sum(counter.values()) or 1
        out.append(f"| {key[0]} | {key[1]} | {_kb(whole)} | " + " | ".join(
            (f"{counter[t] * 100 / whole:.0f}%" if counter[t] else "-") for t in tools) + " |")

    out.append("\n### Relevance and re-reads (sums over runs, % of shown bytes)\n")
    cats = ["gold function", "gold file, other lines", "other library files", "other workspace files", "unattributed"]
    out.append("| Card | Arm | Outcome | Runs | " + " | ".join(cats) +
               " | Re-read (in context) | Re-read (after omission) | Identical repeat calls | Used later (obs) | Quoted later (of attributed) |")
    out.append("|---|---|---|--:|" + "--:|" * len(cats) + "--:|--:|--:|--:|--:|")
    for key in order:
        g = groups[key]
        whole = sum(r["obs_bytes"] for r in g) or 1
        category = Counter()
        for r in g:
            category.update(r["categories"])
        attributed = sum(r["attributed_bytes"] for r in g) or 1
        out.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(g)} | " +
            " | ".join(f"{category[c] * 100 / whole:.0f}%" for c in cats) +
            f" | {sum(r['reread_in_context_bytes'] for r in g) * 100 / whole:.0f}% | "
            f"{sum(r['reread_after_omission_bytes'] for r in g) * 100 / whole:.0f}% | "
            f"{sum(r['identical_repeat_calls'] for r in g)} | "
            f"{sum(r['used_later_obs_bytes'] for r in g) * 100 / whole:.0f}% | "
            f"{sum(r['quoted_later_bytes'] for r in g) * 100 / attributed:.0f}% |")

    out.append("\n### Context carried and what the pre-locating bytes were\n")
    out.append("Carried = tool-result bytes summed over every request that still contained them (what the model "
               "re-reads each response; Claude Code's continuous conversation carries every earlier result). "
               "Before-locating composition is over located runs only.\n")
    out.append("| Card | Arm | Outcome | Runs | Carried KB (median) | Carried / prompt | Carried from results with no gold-file line | "
               "Before locating: gold file | other library | other workspace | unattributed |")
    out.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for key in order:
        g = groups[key]
        prompt = sum(r["prompt_bytes"] for r in g)
        carried = sum(r["carried_obs_bytes"] for r in g) or 1
        before = Counter()
        for r in g:
            if r["site_seen"]:
                before.update(r["categories_before_site"])
        whole = sum(before.values()) or 1
        gold = before["gold function"] + before["gold file, other lines"]
        out.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(g)} | {_kb(_median(r['carried_obs_bytes'] for r in g))} | "
            f"{(f'{carried * 100 / prompt:.0f}%') if prompt else '-'} | "
            f"{sum(r['carried_no_gold_bytes'] for r in g) * 100 / carried:.0f}% | {gold * 100 / whole:.0f}% | "
            f"{before['other library files'] * 100 / whole:.0f}% | {before['other workspace files'] * 100 / whole:.0f}% | "
            f"{before['unattributed'] * 100 / whole:.0f}% |")

    out.append("\n### Failure reading of rejected runs\n")
    out.append("| Card | Arm | never-located | located, no library edit | located, edited elsewhere | "
               "edited gold function (not site) | edited gold function + site |")
    out.append("|---|---|--:|--:|--:|--:|--:|")
    readings: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    for r in rows:
        if r["outcome"] != "accepted":
            readings[(r["card"], r["arm"])][r["reading"]] += 1
    for key, counter in sorted(readings.items()):
        out.append(f"| {key[0]} | {key[1]} | {counter['never-located']} | {counter['located-no-library-edit']} | "
                   f"{counter['located-edited-elsewhere']} | {counter['edited-gold-function']} | "
                   f"{counter['edited-gold-function+site']} |")
    return "\n".join(out) + "\n"


def ladder_table(rows: List[dict], outline: Dict[str, dict]) -> str:
    """Located runs: actual cost of locating vs an oracle-guided ladder (whole outline + gold function read)."""
    out = ["| Card | Arm | Located runs | Median KB before locating | Outline KB (whole repo) | "
           "Median ladder KB (outline + gold fn) | Runs cheaper than the ladder | Median responses to locate | "
           "Median whole-file-read share of shown bytes |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["card"], r["arm"])].append(r)
    for key, g in sorted(groups.items()):
        located = [r for r in g if r["site_seen"]]
        size = {r["run"]: outline[r["task"]]["outline_bytes"] for r in located}
        ladder = {r["run"]: size[r["run"]] + r["gold_function_bytes"] for r in located}
        cheaper = sum(1 for r in located if r["bytes_before_site"] < ladder[r["run"]])
        out.append(
            f"| {key[0]} | {key[1]} | {len(located)}/{len(g)} | {_kb(_median(r['bytes_before_site'] for r in located))} | "
            f"{_kb(_median(size.values()))} | {_kb(_median(ladder.values()))} | {cheaper}/{len(located)} | "
            f"{_fmt(_median(r['site_seen'] for r in located), 1)} | "
            f"{_fmt(_median(r['whole_file_read_bytes'] * 100 / r['obs_bytes'] for r in g if r['obs_bytes']), 0)}% |")
    return "\n".join(out) + "\n"


def task_table(rows: List[dict], outline: Dict[str, dict]) -> str:
    """Per task: the pre-declared outline rank against what the runs actually did (Reticle cards pooled by arm)."""
    groups: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        label = "native" if r["source"] == "claude-code" else ("reticle" if r["arm"] == "incumbent" else r["arm"])
        groups[r["task"]][label].append(r)
    labels = sorted({label for g in groups.values() for label in g}, key=lambda l: (l != "reticle", l))
    header = "| Task | Outline fn rank | File rank | Gold-file outline B | " + " | ".join(
        f"{l}: acc | {l}: located | {l}: site seen at | {l}: KB before site" for l in labels) + " |"
    out = [header, "|---|--:|--:|--:|" + "--:|--:|--:|--:|" * len(labels)]
    for task in sorted(groups):
        o = outline.get(task, {})
        cells = [f"{task}", _fmt(o.get("best_rank")), _fmt(o.get("file_rank")), _fmt(o.get("gold_file_outline_bytes"))]
        for label in labels:
            g = groups[task].get(label, [])
            if not g:
                cells += ["-"] * 4
                continue
            cells += [f"{sum(r['outcome'] == 'accepted' for r in g)}/{len(g)}",
                      f"{sum(1 for r in g if r['site_seen'])}/{len(g)}",
                      _fmt(_median(r["site_seen"] for r in g), 1),
                      _kb(_median(r["bytes_before_site"] for r in g if r["site_seen"]))]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def trajectories(rows: List[dict], tasks: Sequence[str]) -> str:
    out = ["| Run | Outcome | Resp | Site seen | Fn read | File seen | Model names fn | First lib edit | Edit files | "
           "Edited fn/site | Shown KB | KB before site | Reading |",
           "|---|---|--:|--:|--:|--:|--:|--:|---|:-:|--:|--:|---|"]
    for r in sorted(rows, key=lambda r: (r["task"], r["card"], r["run"])):
        if r["task"] not in tasks:
            continue
        files = sorted({(e["file"] or "?").replace("sqlparse/", "") for e in r["edits"]})
        out.append(
            f"| {r['run']} | {r['outcome']} | {r['responses']} | {_fmt(r['site_seen'])} | {_fmt(r['func_read_seen'])} | "
            f"{_fmt(r['gold_file_content_seen'])} | {_fmt(r['model_named_function_at'])} | "
            f"{_fmt(r['first_library_edit'])} | {', '.join(files) or '-'} | "
            f"{'fn' if r['edited_function'] else '-'}/{'site' if r['edited_site'] else '-'} | {_kb(r['obs_bytes'])} | "
            f"{_kb(r['bytes_before_site']) if r['site_seen'] else '(never)'} | {r['reading']} |")
    return "\n".join(out) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, required=True, help="export of the sqlparse base commit")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--card", action="append", default=[], metavar="NAME=DIR")
    parser.add_argument("--native", action="append", default=[], metavar="NAME=DIR")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--trajectories", default="001,032,057,061,022")
    args = parser.parse_args(argv)
    tasks = repo_outline.load_tasks(args.tasks)
    workspaces: Dict[str, Workspace] = {}
    rows: List[dict] = []
    notes: List[str] = []
    for spec, loader in [(s, load_reticle) for s in args.card] + [(s, load_native) for s in args.native]:
        card, _, directory = spec.partition("=")
        dirs, skipped = discover(Path(directory), card)
        notes.extend(f"{card}: skipped {s}" for s in skipped)
        for run_dir in dirs:
            run = loader(run_dir, card)
            if run is None:
                notes.append(f"{card}: {run_dir.name} has no result yet (unfinished), skipped")
                continue
            if run.task_id not in workspaces:
                workspaces[run.task_id] = build_workspace(args.workspace, tasks[run.task_id])
            rows.append(analyse(run, workspaces[run.task_id]))
    outline = {task_id[-3:]: repo_outline.analyse_task(args.workspace, tasks[task_id])
               for task_id in sorted({f"sqlparse-mut-{r['task']}" for r in rows})}
    text = tables(rows) + "\n### Locating cost vs an oracle-guided outline ladder\n\n" + ladder_table(rows, outline) + \
        "\n### Per task: outline rank vs observed locating\n\n" + task_table(rows, outline) + \
        "\n### Trajectories of the persistent failures\n\n" + \
        trajectories(rows, args.trajectories.split(",")) + "\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
