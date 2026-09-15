"""General file, search, edit, execution, and note tools over the runtime substrate.

Tools return their complete output. Every result is journaled and registered under a short
output handle (``out_N``); context policies decide how much of it to show, and
``read_output`` / ``search_output`` retrieve any part of an earlier result exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import fnmatch
import json
import shlex
from typing import Any, Callable, Dict, Iterator, List, Optional
from uuid import uuid4

from reticle.execution import ExecutionController, ExecutionRequest, TrustedLocalBackend
from reticle.runtime.observations import ObservationService
from reticle.runtime.queries import SessionQueryService
from reticle.runtime.session import LocalRuntime
from reticle.runtime.workspace import StaleWorkspaceError


SKIPPED_DIRECTORIES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "node_modules",
}
PYTHON_ALIASES = {"python", "python3", "py"}
SHELL_OPERATORS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "2>", "2>&1"}


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    status: str  # a ToolResultEnvelope status
    finished: bool = False
    handle: Optional[str] = None  # output handle for read_output / search_output


class ToolArgumentError(ValueError):
    pass


def _function(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _function(
        "list_files",
        "List files under a workspace directory recursively, optionally filtered by a glob.",
        {
            "path": {"type": "string", "description": "Directory relative to the workspace root. Default '.'."},
            "pattern": {"type": "string", "description": "Glob on the relative path or file name, e.g. '*.py'. Default '*'."},
        },
        [],
    ),
    _function(
        "read_file",
        "Read a text file with line numbers. Give start_line and end_line to read a region.",
        {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
        ["path"],
    ),
    _function(
        "outline",
        "List the classes and functions of a Python file with line numbers.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _function(
        "search",
        "Find lines containing a literal string in workspace files.",
        {
            "query": {"type": "string"},
            "path": {"type": "string", "description": "File or directory. Default '.'."},
            "pattern": {"type": "string", "description": "Glob on the relative path or file name. Default '*'."},
        },
        ["query"],
    ),
    _function(
        "replace_text",
        "Replace exact text in a file. Fails without changing the file if old_text is absent, "
        "or occurs more than once while replace_all is false.",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        ["path", "old_text", "new_text"],
    ),
    _function(
        "write_file",
        "Create or overwrite a file with the given content.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    _function(
        "run",
        "Run one command in the workspace root without a shell (no pipes or redirection; use forward "
        "slashes in paths). 'python' and 'pytest' use the task's Python environment.",
        {
            "command": {"type": "string", "description": "For example: pytest tests/test_example.py -q"},
            "timeout_seconds": {"type": "integer"},
        },
        ["command"],
    ),
    _function(
        "read_output",
        "Read part of an earlier tool result by its output id (for example out_12). Results that "
        "were shown partially say which id and range to request. Give start_line/end_line, or "
        "start_byte/end_byte for very long lines.",
        {
            "id": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "start_byte": {"type": "integer"},
            "end_byte": {"type": "integer"},
        },
        ["id"],
    ),
    _function(
        "search_output",
        "Find lines containing a literal string in an earlier tool result by its output id.",
        {"id": {"type": "string"}, "query": {"type": "string"}},
        ["id", "query"],
    ),
    _function(
        "history",
        "Page through authorized durable session history. The response includes a stable next_cursor.",
        {
            "after_sequence": {"type": "integer"},
            "before_sequence": {"type": "integer"},
            "as_of_sequence": {"type": "integer"},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer"},
            "cursor": {"type": "string"},
        },
        [],
    ),
    _function(
        "search_history",
        "Find literal text in authorized prior actions and observations without knowing an output ID.",
        {
            "query": {"type": "string"},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string"},
            "as_of_sequence": {"type": "integer"},
            "limit": {"type": "integer"},
            "cursor": {"type": "string"},
        },
        ["query"],
    ),
    _function(
        "read_artifact",
        "Read an authorized session artifact by ID, optionally using an exact byte range.",
        {
            "id": {"type": "string"},
            "start_byte": {"type": "integer"},
            "end_byte": {"type": "integer"},
        },
        ["id"],
    ),
    _function(
        "note",
        "Save a named plain-text note that persists across turns. Pinned notes are placed in context "
        "when space allows.",
        {"name": {"type": "string"}, "content": {"type": "string"}, "pin": {"type": "boolean"}},
        ["name", "content"],
    ),
    _function("read_note", "Read a saved note by name.", {"name": {"type": "string"}}, ["name"]),
    _function(
        "finish",
        "Declare the work complete. The final workspace is then checked independently.",
        {"summary": {"type": "string"}},
        ["summary"],
    ),
]


def _occurrences(text: str, needle: str) -> Iterator[int]:
    start = text.find(needle)
    while start >= 0:
        yield start
        start = text.find(needle, start + 1)


class ToolSuite:
    """Dispatch model tool calls. Failures become tool results, never controller exceptions."""

    def __init__(
        self,
        runtime: LocalRuntime,
        *,
        interpreter: str,
        backend=None,
        environment: Optional[Dict[str, str]] = None,
        default_timeout_seconds: float = 120,
        max_timeout_seconds: float = 600,
        output_limit_bytes: int = 2_000_000,
    ):
        self.runtime = runtime
        self.interpreter = interpreter
        self.backend = backend or TrustedLocalBackend()
        self.environment = dict(environment or {})
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.output_limit_bytes = output_limit_bytes
        self.observations = ObservationService(runtime)
        self.queries = SessionQueryService(runtime)
        self._next_handle: Optional[int] = None
        self._handlers: Dict[str, Callable[[Dict[str, Any]], ToolOutcome]] = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "outline": self._outline,
            "search": self._search,
            "replace_text": self._replace_text,
            "write_file": self._write_file,
            "read_output": self._read_output,
            "search_output": self._search_output,
            "history": self._history,
            "search_history": self._search_history,
            "read_artifact": self._read_artifact,
            "note": self._note,
            "read_note": self._read_note,
            "finish": self._finish,
        }

    def schemas(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(TOOL_SCHEMAS))

    def dispatch(self, name: str, arguments: Any, call_id: str) -> ToolOutcome:
        outcome = self._dispatch(name, arguments, call_id)
        return replace(outcome, handle=self._register_output(call_id, name, outcome.content))

    def _dispatch(self, name: str, arguments: Any, call_id: str) -> ToolOutcome:
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                message = f"ERROR: arguments are not valid JSON ({exc.msg} at position {exc.pos}); nothing was run."
                return self._journaled(call_id, name, {"raw_arguments": arguments}, lambda: ToolOutcome(message, "rejected"))
        else:
            parsed = arguments
        if not isinstance(parsed, dict):
            return self._journaled(
                call_id, name, {"raw_arguments": parsed},
                lambda: ToolOutcome("ERROR: arguments must be a JSON object; nothing was run.", "rejected"),
            )
        if name == "run":
            return self._run(parsed, call_id)
        handler = self._handlers.get(name)
        if handler is None:
            available = ", ".join(sorted([*self._handlers, "run"]))
            return self._journaled(
                call_id, name, parsed,
                lambda: ToolOutcome(f"ERROR: unknown tool '{name}'. Available tools: {available}.", "rejected"),
            )
        return self._journaled(call_id, name, parsed, lambda: handler(parsed))

    def _register_output(self, call_id: str, name: str, content: str) -> str:
        if self._next_handle is None:
            self._next_handle = 1 + sum(1 for e in self.runtime.journal.read_all() if e.kind == "tool_output")
        handle = f"out_{self._next_handle}"
        self._next_handle += 1
        raw = content.encode("utf-8")
        artifact = self.runtime.record_observation(raw, "text/plain; charset=utf-8", labels=["tool-output", name, handle])
        self.runtime.journal.append("tool_output", {
            "handle": handle, "artifact_id": artifact.artifact_id, "call_id": call_id, "tool": name,
            "byte_length": len(raw), "line_count": len(content.splitlines()),
        })
        return handle

    def _resolve_output(self, handle: str) -> bytes:
        for event in self.runtime.journal.read_all():
            if event.kind == "tool_output" and event.payload.get("handle") == handle:
                return self.runtime.artifacts.read(event.payload["artifact_id"])
        raise ToolArgumentError(f"unknown output id '{handle}'")

    def _journaled(
        self, call_id: str, name: str, arguments: Dict[str, Any], action: Callable[[], ToolOutcome]
    ) -> ToolOutcome:
        operation_id = f"tool-{uuid4().hex}"
        before = self.runtime.workspace.revision()
        self.runtime.begin_action(operation_id, name, {"call_id": call_id, "arguments": arguments})
        effect_class = (
            "workspace_mutation" if name in {"replace_text", "write_file"}
            else "session_mutation" if name in {"note", "finish"}
            else "read_only"
        )
        try:
            workspace_tool = name in {
                "list_files", "outline", "read_file", "replace_text", "search", "write_file"
            }
            if workspace_tool:
                with ExecutionController.workspace_boundary(
                    self.runtime, effect_class == "workspace_mutation"
                ):
                    self.runtime.mark_action_dispatched(operation_id, effect_class)
                    outcome = action()
            else:
                self.runtime.mark_action_dispatched(operation_id, effect_class)
                outcome = action()
        except ToolArgumentError as exc:
            outcome = ToolOutcome(f"ERROR: {exc}", "rejected")
        except PermissionError as exc:
            outcome = ToolOutcome(f"ERROR: {exc}", "rejected")
        except (ValueError, KeyError, OSError, StaleWorkspaceError, UnicodeDecodeError) as exc:
            outcome = ToolOutcome(f"ERROR: {type(exc).__name__}: {exc}", "error")
        after = self.runtime.workspace.revision()
        self.runtime.record_tool_result(
            operation_id,
            call_id,
            outcome.status,
            before,
            after,
            stdout=outcome.content.encode("utf-8"),
            error_kind=None if outcome.status == "success" else outcome.status,
        )
        return outcome

    @staticmethod
    def _text(arguments: Dict[str, Any], key: str, default: Optional[str] = None, required: bool = False) -> str:
        value = arguments.get(key)
        if value is None:
            if required:
                raise ToolArgumentError(f"missing required argument '{key}'")
            return default
        if not isinstance(value, str):
            raise ToolArgumentError(f"argument '{key}' must be a string")
        return value

    @staticmethod
    def _int(arguments: Dict[str, Any], key: str) -> Optional[int]:
        value = arguments.get(key)
        if value is None:
            return None
        if isinstance(value, bool):
            raise ToolArgumentError(f"argument '{key}' must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ToolArgumentError(f"argument '{key}' must be an integer") from None

    @staticmethod
    def _bool(arguments: Dict[str, Any], key: str) -> bool:
        value = arguments.get(key, False)
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)

    def _files(self, path: str, pattern: str) -> List[str]:
        root = self.runtime.workspace.root
        base = self.runtime.workspace._resolve(path)
        if base.is_file():
            candidates = [base]
        elif base.is_dir():
            candidates = [
                item for item in sorted(base.rglob("*"))
                if item.is_file()
                and not any(part in SKIPPED_DIRECTORIES for part in item.relative_to(root).parts)
            ]
        else:
            raise ValueError(f"no such file or directory: {path}")
        return [
            item.relative_to(root).as_posix() for item in candidates
            if fnmatch.fnmatch(item.relative_to(root).as_posix(), pattern) or fnmatch.fnmatch(item.name, pattern)
        ]

    def _list_files(self, arguments: Dict[str, Any]) -> ToolOutcome:
        files = self._files(self._text(arguments, "path", "."), self._text(arguments, "pattern", "*"))
        listing = "\n".join(files) if files else "(no matching files)"
        return ToolOutcome(f"{len(files)} file(s):\n{listing}", "success")

    def _read_file(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        start = self._int(arguments, "start_line")
        end = self._int(arguments, "end_line")
        view = self.observations.observe(path, "full")
        lines = view.content.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        first = 1 if start is None else max(1, start)
        last = total if end is None else min(total, end)
        if total and first > last:
            raise ToolArgumentError(f"invalid line range {first}-{last}; {path} has {total} lines")
        numbered = "\n".join(f"{number:>5}| {lines[number - 1]}" for number in range(first, last + 1))
        return ToolOutcome(f"{path} (lines {first}-{last} of {total})\n{numbered}", "success")

    def _outline(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        view = self.observations.observe(path, "outline")
        body = view.content.decode("utf-8", errors="replace") or "(no classes or functions found)"
        return ToolOutcome(f"Outline of {path}:\n{body}", "success")

    def _search(self, arguments: Dict[str, Any]) -> ToolOutcome:
        query = self._text(arguments, "query", required=True)
        if not query:
            raise ToolArgumentError("query must not be empty")
        root = self.runtime.workspace.root
        needle = query.encode("utf-8")
        matches: List[str] = []
        for relative in self._files(self._text(arguments, "path", "."), self._text(arguments, "pattern", "*")):
            raw = (root / relative).read_bytes()
            if b"\x00" in raw or needle not in raw:
                continue
            for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if query in line:
                    matches.append(f"{relative}:{number}: {line.strip()}")
        body = "\n".join(matches) if matches else "(no matches)"
        return ToolOutcome(f"{len(matches)} match(es) for {query!r}:\n{body}", "success")

    def _replace_text(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        old = self._text(arguments, "old_text", required=True)
        new = self._text(arguments, "new_text", required=True)
        if not old:
            raise ToolArgumentError("old_text must not be empty")
        replace_all = self._bool(arguments, "replace_all")
        observation = self.runtime.workspace.read(path)
        text = observation.content.decode("utf-8")
        count = text.count(old)
        if count == 0:
            return ToolOutcome(
                f"ERROR: old_text was not found in {path}; no change made. Re-read the file and copy "
                "the exact text, including indentation.",
                "error",
            )
        if count > 1 and not replace_all:
            lines = sorted({text.count("\n", 0, index) + 1 for index in _occurrences(text, old)})
            return ToolOutcome(
                f"ERROR: old_text occurs {count} times in {path} (at lines {lines[:20]}); no change made. "
                "Include more surrounding text, or set replace_all.",
                "error",
            )
        first_index = text.index(old)
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        self.runtime.workspace.write(path, updated.encode("utf-8"), expected_content_hash=observation.content_hash)
        updated_lines = updated.splitlines()
        start_line = updated.count("\n", 0, first_index) + 1
        low = max(1, start_line - 2)
        high = min(len(updated_lines), start_line + new.count("\n") + 2)
        snippet = "\n".join(f"{number:>5}| {updated_lines[number - 1]}" for number in range(low, high + 1))
        replaced = count if replace_all else 1
        return ToolOutcome(f"Replaced {replaced} occurrence(s) in {path}. Lines {low}-{high} now:\n{snippet}", "success")

    def _write_file(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        content = self._text(arguments, "content", required=True)
        target = self.runtime.workspace._resolve(path)
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = content.encode("utf-8")
        self.runtime.workspace.write(path, raw)
        verb = "Overwrote" if existed else "Created"
        return ToolOutcome(f"{verb} {path} ({len(raw)} bytes, {len(content.splitlines())} lines).", "success")

    def _read_output(self, arguments: Dict[str, Any]) -> ToolOutcome:
        handle = self._text(arguments, "id", required=True).strip()
        raw = self._resolve_output(handle)
        start_byte, end_byte = self._int(arguments, "start_byte"), self._int(arguments, "end_byte")
        if start_byte is not None or end_byte is not None:
            low = max(0, start_byte or 0)
            high = len(raw) if end_byte is None else min(len(raw), end_byte)
            if low > high:
                raise ToolArgumentError(f"invalid byte range {low}-{high}; {handle} has {len(raw)} bytes")
            return ToolOutcome(
                f"{handle} bytes {low}-{high} of {len(raw)}:\n{raw[low:high].decode('utf-8', errors='replace')}", "success"
            )
        lines = raw.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        start, end = self._int(arguments, "start_line"), self._int(arguments, "end_line")
        first = 1 if start is None else max(1, start)
        last = total if end is None else min(total, end)
        if total and first > last:
            raise ToolArgumentError(f"invalid line range {first}-{last}; {handle} has {total} lines")
        body = "\n".join(lines[first - 1:last])
        return ToolOutcome(f"{handle} lines {first}-{last} of {total}:\n{body}", "success")

    def _search_output(self, arguments: Dict[str, Any]) -> ToolOutcome:
        handle = self._text(arguments, "id", required=True).strip()
        query = self._text(arguments, "query", required=True)
        if not query:
            raise ToolArgumentError("query must not be empty")
        lines = self._resolve_output(handle).decode("utf-8", errors="replace").splitlines()
        matches = [f"L{number}: {line}" for number, line in enumerate(lines, 1) if query in line]
        body = "\n".join(matches) if matches else "(no matches)"
        return ToolOutcome(f"{len(matches)} match(es) for {query!r} in {handle} ({len(lines)} lines):\n{body}", "success")

    @staticmethod
    def _history_kinds(arguments: Dict[str, Any]) -> Optional[List[str]]:
        kinds = arguments.get("kinds")
        if kinds is None:
            return None
        if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
            raise ToolArgumentError("argument 'kinds' must be an array of strings")
        return kinds

    def _history(self, arguments: Dict[str, Any]) -> ToolOutcome:
        limit = self._int(arguments, "limit")
        page = self.queries.history(
            after_sequence=self._int(arguments, "after_sequence") or 0,
            before_sequence=self._int(arguments, "before_sequence"),
            as_of_sequence=self._int(arguments, "as_of_sequence"),
            kinds=self._history_kinds(arguments),
            limit=20 if limit is None else limit,
            cursor=self._text(arguments, "cursor"),
        )
        # Indented so a bounded context view can page the result by line.
        return ToolOutcome(json.dumps(page.to_dict(), sort_keys=True, ensure_ascii=False, indent=1), "success")

    def _search_history(self, arguments: Dict[str, Any]) -> ToolOutcome:
        limit = self._int(arguments, "limit")
        page = self.queries.search(
            self._text(arguments, "query", required=True),
            kinds=self._history_kinds(arguments),
            source=self._text(arguments, "source"),
            as_of_sequence=self._int(arguments, "as_of_sequence"),
            limit=20 if limit is None else limit,
            cursor=self._text(arguments, "cursor"),
        )
        # Indented so a bounded context view can page the result by line.
        return ToolOutcome(json.dumps(page.to_dict(), sort_keys=True, ensure_ascii=False, indent=1), "success")

    def _read_artifact(self, arguments: Dict[str, Any]) -> ToolOutcome:
        result = self.queries.read_artifact(
            self._text(arguments, "id", required=True).strip(),
            start_byte=self._int(arguments, "start_byte") or 0,
            end_byte=self._int(arguments, "end_byte"),
        )
        return ToolOutcome(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=1), "success")

    def _argv(self, command: str) -> List[str]:
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            raise ToolArgumentError(f"could not parse command: {exc}") from None
        if not argv:
            raise ToolArgumentError("command is empty")
        if any(token in SHELL_OPERATORS for token in argv):
            raise ToolArgumentError("shell operators are not supported; run one command per call")
        head = argv[0].lower()
        if head in PYTHON_ALIASES:
            return [self.interpreter, *argv[1:]]
        if head == "pytest":
            return [self.interpreter, "-m", "pytest", *argv[1:]]
        return argv

    def _run(self, arguments: Dict[str, Any], call_id: str) -> ToolOutcome:
        try:
            command = self._text(arguments, "command", required=True)
            argv = self._argv(command)
            requested_timeout = self._int(arguments, "timeout_seconds")
        except ToolArgumentError as exc:
            message = f"ERROR: {exc}; nothing was run."
            return self._journaled(call_id, "run", arguments, lambda: ToolOutcome(message, "rejected"))
        timeout = float(requested_timeout) if requested_timeout and requested_timeout > 0 else self.default_timeout_seconds
        timeout = min(timeout, self.max_timeout_seconds)
        record = ExecutionController(self.runtime, self.backend).execute(
            ExecutionRequest(
                command=argv,
                working_directory=self.runtime.workspace.root,
                timeout_seconds=timeout,
                output_limit_bytes=self.output_limit_bytes,
                environment=self.environment,
                mutates_workspace=True,
            ),
            call_id=call_id,
        )
        execution, result = record.execution, record.tool_result
        parts = [f"$ {command}", f"status: {execution.status}; exit code: {execution.exit_code}; {execution.duration_ms} ms"]
        if execution.diagnostic:
            parts.append(f"diagnostic: {execution.diagnostic}")
        if execution.output_truncated:
            parts.append(f"[output exceeded {self.output_limit_bytes} bytes; the process was stopped]")
        for label, data in (("stdout", execution.stdout), ("stderr", execution.stderr)):
            if data:
                parts.append(f"--- {label} ---\n{data.decode('utf-8', errors='replace')}")
        return ToolOutcome("\n".join(parts), result.status)

    def _note(self, arguments: Dict[str, Any]) -> ToolOutcome:
        name = self._text(arguments, "name", required=True).strip()
        if not name:
            raise ToolArgumentError("name must not be empty")
        content = self._text(arguments, "content", required=True)
        reference = f"notes/{name}"
        written = self.runtime.scratch.write(reference, content, labels=["note"])
        pinned = self._bool(arguments, "pin")
        if pinned:
            self.runtime.scratch.pin(reference)
        suffix = "; pinned" if pinned else ""
        return ToolOutcome(
            f"Saved note '{name}' (version {written.reference.version}, {written.artifact.artifact_id}){suffix}.",
            "success",
        )

    def _read_note(self, arguments: Dict[str, Any]) -> ToolOutcome:
        name = self._text(arguments, "name", required=True).strip()
        read = self.runtime.scratch.read(f"notes/{name}")
        return ToolOutcome(read.content.decode("utf-8", errors="replace"), "success")

    def _finish(self, arguments: Dict[str, Any]) -> ToolOutcome:
        return ToolOutcome("Finish recorded. The final workspace will be evaluated independently.", "success", finished=True)
