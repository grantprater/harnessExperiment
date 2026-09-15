"""General file, search, edit, execution, and note tools over the runtime substrate.

Every call is journaled with its exact result. Large results are shown as truthful
previews that name the artifact holding the exact bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
import shlex
from typing import Any, Callable, Dict, Iterator, List, Optional
from uuid import uuid4

from reticle.execution import ExecutionController, ExecutionRequest, TrustedLocalBackend
from reticle.runtime.observations import ObservationService
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
        preview_bytes: int = 12_000,
        default_timeout_seconds: float = 120,
        max_timeout_seconds: float = 600,
        output_limit_bytes: int = 2_000_000,
        max_listed_files: int = 500,
        max_search_matches: int = 200,
    ):
        self.runtime = runtime
        self.interpreter = interpreter
        self.backend = backend or TrustedLocalBackend()
        self.environment = dict(environment or {})
        self.preview_bytes = preview_bytes
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.output_limit_bytes = output_limit_bytes
        self.max_listed_files = max_listed_files
        self.max_search_matches = max_search_matches
        self.observations = ObservationService(runtime)
        self._handlers: Dict[str, Callable[[Dict[str, Any]], ToolOutcome]] = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "outline": self._outline,
            "search": self._search,
            "replace_text": self._replace_text,
            "write_file": self._write_file,
            "note": self._note,
            "read_note": self._read_note,
            "finish": self._finish,
        }

    def schemas(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(TOOL_SCHEMAS))

    def dispatch(self, name: str, arguments: Any, call_id: str) -> ToolOutcome:
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

    def _journaled(
        self, call_id: str, name: str, arguments: Dict[str, Any], action: Callable[[], ToolOutcome]
    ) -> ToolOutcome:
        operation_id = f"tool-{uuid4().hex}"
        before = self.runtime.workspace.revision()
        self.runtime.begin_action(operation_id, name, {"call_id": call_id, "arguments": arguments})
        try:
            outcome = action()
        except ToolArgumentError as exc:
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

    def _preview(self, text: str, exact_ref: str, hint: str = "") -> str:
        raw = text.encode("utf-8")
        if len(raw) <= self.preview_bytes:
            return text
        shown = raw[:self.preview_bytes].decode("utf-8", errors="ignore")
        return f"{shown}\n[truncated: {len(raw) - self.preview_bytes} bytes omitted{hint}; exact: {exact_ref}]"

    def _head_tail(self, data: bytes, ref: Optional[str]) -> str:
        budget = max(1, self.preview_bytes // 2)
        if len(data) <= budget:
            return data.decode("utf-8", errors="replace")
        head_bytes = min(1_500, budget // 3)
        tail_bytes = budget - head_bytes
        head = data[:head_bytes].decode("utf-8", errors="ignore")
        tail = data[-tail_bytes:].decode("utf-8", errors="ignore")
        omitted = len(data) - head_bytes - tail_bytes
        return f"{head}\n[... {omitted} bytes omitted; exact: {ref} ...]\n{tail}"

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
        shown = files[:self.max_listed_files]
        listing = "\n".join(shown) if shown else "(no matching files)"
        if len(files) > len(shown):
            listing += f"\n[{len(files) - len(shown)} more files not listed; narrow the path or pattern]"
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
        text = f"{path} (lines {first}-{last} of {total})\n{numbered}"
        return ToolOutcome(self._preview(text, view.raw_artifact.artifact_id, "; read a smaller line range"), "success")

    def _outline(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        view = self.observations.observe(path, "outline")
        body = view.content.decode("utf-8", errors="replace") or "(no classes or functions found)"
        return ToolOutcome(self._preview(f"Outline of {path}:\n{body}", view.view_artifact.artifact_id), "success")

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
                    matches.append(f"{relative}:{number}: {line.strip()[:300]}")
        artifact = self.runtime.record_observation(
            "\n".join(matches).encode("utf-8"), "text/plain; charset=utf-8", labels=["search-results", query]
        )
        shown = matches[:self.max_search_matches]
        body = "\n".join(shown) if shown else "(no matches)"
        if len(matches) > len(shown):
            body += f"\n[{len(matches) - len(shown)} more matches not shown; exact: {artifact.artifact_id}]"
        return ToolOutcome(self._preview(f"{len(matches)} match(es) for {query!r}:\n{body}", artifact.artifact_id), "success")

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
        high = min(len(updated_lines), start_line + new.count("\n") + 2, low + 80)
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
        for label, data, ref in (("stdout", execution.stdout, result.stdout_ref), ("stderr", execution.stderr, result.stderr_ref)):
            if data:
                parts.append(f"--- {label} ---\n{self._head_tail(data, ref)}")
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
        return ToolOutcome(self._preview(read.content.decode("utf-8", errors="replace"), read.artifact.artifact_id), "success")

    def _finish(self, arguments: Dict[str, Any]) -> ToolOutcome:
        return ToolOutcome("Finish recorded. The final workspace will be evaluated independently.", "success", finished=True)
