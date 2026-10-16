"""General file, search, edit, execution, and note tools over the runtime substrate.

Tools return their complete output. Every result is journaled and registered under a short
output handle (``out_N``); context policies decide how much of it to show, and
``read_output`` / ``search_output`` retrieve any part of an earlier result exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import fnmatch
import json
import re
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
    ".reticle", ".runtime", ".claude",
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
        "glob_files",
        "Recursively list workspace-relative file paths that match a glob, in sorted order. The glob is matched "
        "against each file's relative path and against its file name, using Python fnmatch rules, case-sensitive: "
        "'*' and '?' also match '/', and '[abc]' matches one listed character. It never matches file contents. "
        "Cache and VCS directories (.git, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .tox, .venv, "
        "node_modules) are skipped.",
        {
            "glob": {"type": "string", "description": "Required. For example '*.py', 'tests/*', or 'setup.cfg'."},
            "path": {
                "type": "string",
                "description": "Directory (or single file) to list under, relative to the workspace root. Default '.'.",
            },
        },
        ["glob"],
    ),
    _function(
        "read_file",
        "Read a text file with 1-based line numbers. start_line and end_line are inclusive; omit start_line to begin "
        "at line 1 and end_line to read to the end. The header reports the range returned and the file's total "
        "lines. Long results are shown partially with an output id for paging.",
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
        "search_text",
        "Search case-sensitive literal text by default, or Python regex with regex=true. Returns one line "
        "per matching line as path:line: text, with 1-based line numbers; context_lines adds surrounding lines. file_glob only "
        "selects which files are searched.",
        {
            "query": {"type": "string", "description": "Required. Literal text, or a Python pattern when regex=true."},
            "regex": {"type": "boolean"},
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 100},
            "path": {
                "type": "string",
                "description": "File or directory to search, relative to the workspace root. Default '.'.",
            },
            "file_glob": {
                "type": "string",
                "description": "Optional glob selecting files by relative path or file name (same rules as "
                               "glob_files), e.g. '*.py'. It never matches file contents. Default '*'.",
            },
        },
        ["query"],
    ),
    _function(
        "replace_text",
        "Replace literal text in a file, treating LF and CRLF line endings as equivalent. Preserve existing "
        "bytes outside the replacement and use local line endings for new_text. Other whitespace must match "
        "exactly. Fails without changing the file if old_text is absent, or if it occurs "
        "more than once while replace_all is false; set replace_all to replace every occurrence. Reports how many "
        "occurrences were replaced and shows the edited lines.",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        ["path", "old_text", "new_text"],
    ),
    _function(
        "apply_patch",
        "Apply a single-file unified diff to an existing file. Exact line positions and context must match; "
        "all hunks are validated before writing. LF/CRLF differences are tolerated and local endings preserved. "
        "Supply path and patch (optional ---/+++ headers followed by @@ hunks). Use write_file to create files.",
        {"path": {"type": "string"}, "patch": {"type": "string"}},
        ["path", "patch"],
    ),
    _function(
        "write_file",
        "Create a file, or overwrite it completely if it already exists, with the given content. Missing parent "
        "directories are created. Paths are relative to the workspace root.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    _function(
        "run",
        "Run command or commands in sequence (stopping on failure by default). cwd selects a workspace directory. "
        "Without a shell: no pipes, redirection, chaining (&&, ;), cd, or "
        "variable expansion; use workspace-relative paths with forward slashes. 'python' and 'pytest' use the "
        "task's Python environment. Shows the command, status (including timeout), exit code, stdout, and stderr; "
        "long output is shown partially with an output id for paging. A successful exit does not mean the task "
        "is accepted.",
        {
            "command": {"type": "string", "description": "For example: pytest tests/test_example.py -q"},
            "commands": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50,
                         "description": "Supply command or commands, not both. Each runs in a separate process."},
            "cwd": {"type": "string", "description": "Workspace-relative working directory; default '.'"},
            "stop_on_error": {"type": "boolean", "description": "Default true for command sequences."},
            "timeout_seconds": {"type": "integer"},
        },
        [],
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
        "Search an earlier output for literal text or optional Python regex, with surrounding context.",
        {"id": {"type": "string"}, "query": {"type": "string"}, "regex": {"type": "boolean"},
         "context_lines": {"type": "integer", "minimum": 0, "maximum": 100}},
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


# Legacy tools: not in the model-facing schema; dispatch keeps their toolset-v2 behavior (with a note) so
# recordings that used them remain replayable.
LEGACY_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _function(
        "list_files",
        "List files under a workspace directory recursively, optionally filtered by a file-name glob.",
        {
            "path": {"type": "string", "description": "Directory relative to the workspace root. Default '.'."},
            "file_glob": {
                "type": "string",
                "description": "Optional glob on the relative path or file name, e.g. '*.py'. Default '*'.",
            },
        },
        [],
    ),
    _function(
        "search",
        "Find lines containing a literal string (plain text, not a regex) in workspace files.",
        {
            "query": {"type": "string", "description": "Required. The literal text to find, e.g. 'def get_real_name'."},
            "path": {"type": "string", "description": "File or directory to search. Default '.'."},
            "file_glob": {
                "type": "string",
                "description": "Optional file-name glob selecting which files to search, e.g. '*.py'. "
                               "It never matches file contents. Default '*'.",
            },
        },
        ["query"],
    ),
]
LEGACY_TOOL_NAMES = {"list_files": "glob_files", "search": "search_text"}

RUNTIME_UPDATE_SCHEMA = _function(
    'activate_runtime',
    'Snapshot and validate an edited harness, then queue activation after this user turn completes. '
    'The current turn keeps its existing version. Only available in supervised runtime-update mode. '
    'Protected core files must match the initial runtime. Continue working and call finish normally.',
    {'source_root': {'type': 'string', 'description': 'Workspace-relative repository containing reticle; default dot.'},
     'reason': {'type': 'string'}}, [],
)

# v2: `file_glob` naming, argument guidance with examples, notes for ignored arguments, literal-match note.
# v3: `glob_files(glob, path)` and `search_text(query, path, file_glob)` replace list_files/search (legacy
# dispatch kept); unknown arguments to schema tools are rejected with guidance instead of ignored; results
# state matching mode and scope; globs are case-sensitive on every platform; `run` rejections explain chaining
# and `cd` and show the command to run instead; tool descriptions state line-range, overwrite, parent-directory,
# no-shell, and acceptance semantics. Regex matching is not offered.
# v4: single-file unified diffs, optional regex/context, cwd, and command sequences.
TOOLSET_VERSION = "reticle-tools-v4"
ARGUMENT_ALIASES = {"search": {"pattern": "file_glob"}, "list_files": {"pattern": "file_glob"}}
UNKNOWN_ARGUMENT_HINTS = {
    ("search_text", "pattern"): " 'pattern' is not a search_text argument: put the text to find in query and "
                                "select files with file_glob.",
    ("search_text", "glob"): " search_text selects files with file_glob.",
    ("glob_files", "pattern"): " 'pattern' is not a glob_files argument: pass the glob as glob.",
    ("glob_files", "file_glob"): " glob_files takes the glob as glob.",
    ("glob_files", "query"): " glob_files never matches file contents; use search_text to find text.",
}
TOOL_EXAMPLES = {
    "glob_files": {"glob": "*.py", "path": "src"},
    "search_text": {"query": "def get_real_name(", "file_glob": "*.py"},
    "list_files": {"path": "src", "file_glob": "*.py"},
    "read_file": {"path": "src/module.py", "start_line": 1, "end_line": 80},
    "outline": {"path": "src/module.py"},
    "search": {"query": "def get_real_name", "file_glob": "*.py"},
    "replace_text": {"path": "src/module.py", "old_text": "return a", "new_text": "return b"},
    "apply_patch": {"path": "src/module.py", "patch": "@@ -1 +1 @@\n-old\n+new\n"},
    "write_file": {"path": "notes/plan.txt", "content": "..."},
    "run": {"command": "pytest tests/test_example.py -q"},
    "read_output": {"id": "out_3", "start_line": 1, "end_line": 60},
    "search_output": {"id": "out_3", "query": "Error"},
    "search_history": {"query": "src/module.py"},
    "read_artifact": {"id": "art_0123"},
    "note": {"name": "plan", "content": "..."},
    "read_note": {"name": "plan"},
    "finish": {"summary": "Fixed ..."},
}
_TOOL_PARAMETERS = {
    schema["function"]["name"]: schema["function"]["parameters"]
    for schema in [*TOOL_SCHEMAS, *LEGACY_TOOL_SCHEMAS, RUNTIME_UPDATE_SCHEMA]
}


def argument_signature(name: str) -> Optional[str]:
    parameters = _TOOL_PARAMETERS.get(name)
    if parameters is None:
        return None
    required = set(parameters.get("required", []))
    names = [f"{key} (required)" if key in required else key for key in parameters.get("properties", {})]
    return ", ".join(names) or "no arguments"


def argument_guidance(name: str) -> str:
    """Accepted arguments and an example call, appended to a rejected call so the next call can recover."""
    signature = argument_signature(name)
    if signature is None:
        return ""
    example = TOOL_EXAMPLES.get(name)
    return f" {name} accepts: {signature}." + (f" Example: {json.dumps(example)}" if example else "")


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
        self.runtime_updates = None
        self._handlers: Dict[str, Callable[[Dict[str, Any]], ToolOutcome]] = {
            "glob_files": self._glob_files,
            "search_text": self._search_text,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "outline": self._outline,
            "search": self._search,
            "replace_text": self._replace_text,
            "apply_patch": self._apply_patch,
            "write_file": self._write_file,
            "read_output": self._read_output,
            "search_output": self._search_output,
            "history": self._history,
            "search_history": self._search_history,
            "read_artifact": self._read_artifact,
            "note": self._note,
            "read_note": self._read_note,
            "finish": self._finish,
            "activate_runtime": self._activate_runtime,
        }

    def schemas(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps([*TOOL_SCHEMAS, *([RUNTIME_UPDATE_SCHEMA] if self.runtime_updates else [])]))

    def _activate_runtime(self, arguments):
        if self.runtime_updates is None:
            raise ToolArgumentError('runtime updates require --runtime-updates')
        source = self.runtime.workspace._resolve(self._text(arguments, 'source_root', '.'))
        reason = self._text(arguments, 'reason', '')
        version = self.runtime_updates.request(str(source), reason)
        return ToolOutcome(f'Runtime {version} validated and queued for the next user turn. '
                           'This turn continues with its existing runtime.', 'success')

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
        known = (_TOOL_PARAMETERS.get(name) or {}).get("properties", {})
        aliases = ARGUMENT_ALIASES.get(name, {})
        unknown = sorted(key for key in parsed if key not in known and key not in aliases)
        if name in LEGACY_TOOL_NAMES:
            note = f"Note: '{name}' is the legacy name of '{LEGACY_TOOL_NAMES[name]}'.\n"
            if unknown:
                note += (f"Note: ignored unknown argument(s) {', '.join(unknown)}; "
                         f"{name} accepts: {argument_signature(name)}.\n")
            return self._journaled(call_id, name, parsed, lambda: self._with_note(handler(parsed), note))
        if unknown:
            hints = "".join(UNKNOWN_ARGUMENT_HINTS.get((name, key), "") for key in unknown)
            message = (f"ERROR: unknown argument(s) {', '.join(unknown)}; nothing was done.{hints}"
                       f"{argument_guidance(name)}")
            return self._journaled(call_id, name, parsed, lambda: ToolOutcome(message, "rejected"))
        return self._journaled(call_id, name, parsed, lambda: handler(parsed))

    @staticmethod
    def _with_note(outcome: ToolOutcome, note: str) -> ToolOutcome:
        return replace(outcome, content=note + outcome.content)

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
            "workspace_mutation" if name in {"replace_text", "write_file", "apply_patch", "run_sequence", "style_apply"}
            else "session_mutation" if name in {"note", "finish", "reasoning_update", "activate_runtime",
                                                "extension_stage", "extension_rollback", "style_extract"}
            else "read_only"
        )
        try:
            workspace_tool = name in {
                "glob_files", "list_files", "outline", "read_file", "replace_text", "search", "search_text", "write_file", "apply_patch",
                "style_extract", "style_check", "style_apply"
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
            outcome = ToolOutcome(f"ERROR: {str(exc).rstrip('.')}.{argument_guidance(name)}", "rejected")
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

    def _files(self, path: str, pattern: str, case_sensitive: bool = False) -> List[str]:
        """Sorted workspace-relative files under path whose relative path or name matches the glob.

        Legacy tools use fnmatch (case-insensitive on Windows); toolset-v3 tools are case-sensitive everywhere.
        """
        match = fnmatch.fnmatchcase if case_sensitive else fnmatch.fnmatch
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
            if match(item.relative_to(root).as_posix(), pattern) or match(item.name, pattern)
        ]

    def _glob_files(self, arguments: Dict[str, Any]) -> ToolOutcome:
        glob = self._text(arguments, "glob", required=True)
        if not glob:
            raise ToolArgumentError("glob must not be empty")
        path = self._text(arguments, "path", ".")
        files = self._files(path, glob, case_sensitive=True)
        rules = "fnmatch rules, case-sensitive, matched against relative path and file name; cache/VCS directories skipped"
        if not files:
            return ToolOutcome(f"0 file(s) match glob {glob!r} under {path!r} ({rules}).", "success")
        return ToolOutcome(f"{len(files)} file(s) match glob {glob!r} under {path!r}:\n" + "\n".join(files), "success")

    def _search_text(self, arguments: Dict[str, Any]) -> ToolOutcome:
        if arguments.get("query") is None:
            selector = "; 'file_glob' only selects which files are searched" if arguments.get("file_glob") is not None else ""
            raise ToolArgumentError(f"missing required argument 'query': search_text finds exact text inside files{selector}")
        query = self._text(arguments, "query", required=True)
        if not query:
            raise ToolArgumentError("query must not be empty")
        path = self._text(arguments, "path", ".")
        file_glob = self._text(arguments, "file_glob", "*")
        files = self._files(path, file_glob, case_sensitive=True)
        root = self.runtime.workspace.root
        matcher, context = self._search_options(arguments, query)
        matches: List[str] = []
        count = 0
        binary = 0
        for relative in files:
            raw = (root / relative).read_bytes()
            if b"\x00" in raw:
                binary += 1
                continue
            lines = raw.decode("utf-8", errors="replace").splitlines()
            hits = {i for i, line in enumerate(lines) if matcher(line)}
            count += len(hits)
            selected = sorted({j for i in hits for j in range(max(0, i-context), min(len(lines), i+context+1))})
            previous = -2
            for i in selected:
                if context and previous >= 0 and i > previous + 1:
                    matches.append("--")
                separator = ":" if i in hits else "-"
                matches.append(f"{relative}:{i+1}{separator} {lines[i].rstrip()}")
                previous = i
        mode = "Python regex" if self._bool(arguments, "regex") else "exact text"
        scope = (f"{mode}, case-sensitive; path {path!r}, file_glob {file_glob!r}; {len(files)} file(s) searched"
                 + (f", {binary} binary file(s) skipped" if binary else ""))
        if not matches:
            return ToolOutcome(f"0 match(es) for {query!r} ({scope}).", "success")
        return ToolOutcome(f"{count} match(es) for {query!r} ({scope}):\n" + "\n".join(matches), "success")

    def _search_options(self, arguments, query):
        context = self._int(arguments, "context_lines") or 0
        if not 0 <= context <= 100:
            raise ToolArgumentError("context_lines must be between 0 and 100")
        if self._bool(arguments, "regex"):
            try:
                pattern = re.compile(query)
            except re.error as exc:
                raise ToolArgumentError(f"invalid regex: {exc}") from None
            return lambda line: pattern.search(line) is not None, context
        return lambda line: query in line, context

    def _apply_patch(self, arguments):
        from reticle.tools.patching import apply_unified_diff
        path = self._text(arguments, "path", required=True)
        patch = self._text(arguments, "patch", required=True)
        observation = self.runtime.workspace.read(path)
        try:
            updated = apply_unified_diff(observation.content, patch)
        except ValueError as exc:
            raise ToolArgumentError(str(exc)) from None
        self.runtime.workspace.write(path, updated, expected_content_hash=observation.content_hash)
        return ToolOutcome(f"Applied patch to {path} ({len(updated)} bytes).", "success")

    def _file_glob(self, arguments: Dict[str, Any]) -> tuple[str, str]:
        """The file-name glob and a note when the pre-v2 name `pattern` was used for it."""
        if arguments.get("file_glob") is not None:
            return self._text(arguments, "file_glob", "*"), ""
        if arguments.get("pattern") is not None:
            return (self._text(arguments, "pattern", "*"),
                    "Note: 'pattern' is now named 'file_glob'; it was applied as the file-name glob.\n")
        return "*", ""

    def _list_files(self, arguments: Dict[str, Any]) -> ToolOutcome:
        file_glob, note = self._file_glob(arguments)
        files = self._files(self._text(arguments, "path", "."), file_glob)
        listing = "\n".join(files) if files else "(no matching files)"
        return ToolOutcome(f"{note}{len(files)} file(s):\n{listing}", "success")

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
        if arguments.get("query") is None:
            given = next((key for key in ("file_glob", "pattern") if arguments.get(key) is not None), None)
            selector = f"; '{given}' only selects which files are searched" if given else ""
            raise ToolArgumentError(
                f"missing required argument 'query': search finds literal text inside files{selector}"
            )
        query = self._text(arguments, "query", required=True)
        if not query:
            raise ToolArgumentError("query must not be empty")
        file_glob, note = self._file_glob(arguments)
        root = self.runtime.workspace.root
        needle = query.encode("utf-8")
        matches: List[str] = []
        for relative in self._files(self._text(arguments, "path", "."), file_glob):
            raw = (root / relative).read_bytes()
            if b"\x00" in raw or needle not in raw:
                continue
            for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if query in line:
                    matches.append(f"{relative}:{number}: {line.strip()}")
        body = "\n".join(matches) if matches else "(no matches; query is matched as literal text, not a regex)"
        return ToolOutcome(f"{note}{len(matches)} match(es) for {query!r}:\n{body}", "success")

    def _replace_text(self, arguments: Dict[str, Any]) -> ToolOutcome:
        path = self._text(arguments, "path", required=True)
        old = self._text(arguments, "old_text", required=True)
        new = self._text(arguments, "new_text", required=True)
        if not old:
            raise ToolArgumentError("old_text must not be empty")
        replace_all = self._bool(arguments, "replace_all")
        observation = self.runtime.workspace.read(path)
        text = observation.content.decode("utf-8")
        # Match only newline differences; indentation and all other characters remain literal.
        # Match against the original text so untouched spans retain their exact bytes.
        pattern = re.compile(r"\r?\n".join(re.escape(part) for part in old.replace("\r\n", "\n").split("\n")))
        matches = list(pattern.finditer(text))
        count = len(matches)
        if count == 0:
            return ToolOutcome(
                f"ERROR: old_text was not found in {path}; no change made. Re-read the file and copy "
                "the exact text, including indentation.",
                "error",
            )
        if count > 1 and not replace_all:
            lines = sorted({text.count("\n", 0, match.start()) + 1 for match in matches})
            return ToolOutcome(
                f"ERROR: old_text occurs {count} times in {path} (at lines {lines[:20]}); no change made. "
                "Include more surrounding text, or set replace_all.",
                "error",
            )
        first_index = matches[0].start()
        pieces = []
        cursor = 0
        for match in matches if replace_all else matches[:1]:
            # Prefer the matched region's convention, then the containing line, then
            # the preceding line. A file with no line endings defaults to LF.
            newline = re.search(r"\r?\n", match.group()) or re.search(r"\r?\n", text[match.start():])
            if newline is None:
                preceding = list(re.finditer(r"\r?\n", text[:match.start()]))
                newline = preceding[-1] if preceding else None
            ending = newline.group() if newline else "\n"
            replacement = new.replace("\r\n", "\n").replace("\n", ending)
            pieces.extend((text[cursor:match.start()], replacement))
            cursor = match.end()
        pieces.append(text[cursor:])
        updated = "".join(pieces)
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
        matcher, context = self._search_options(arguments, query)
        hits = {i for i, line in enumerate(lines) if matcher(line)}
        selected = sorted({j for i in hits for j in range(max(0, i-context), min(len(lines), i+context+1))})
        body = "\n".join(f"L{i+1}{':' if i in hits else '-'} {lines[i]}" for i in selected) or "(no matches)"
        return ToolOutcome(f"{len(hits)} match(es) for {query!r} in {handle} ({len(lines)} lines):\n{body}", "success")

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
        operators = sorted({token for token in argv if token in SHELL_OPERATORS})
        if operators:
            message = (f"shell operator(s) {' '.join(operators)} are not supported: run executes a single command "
                       "without a shell (no chaining, pipes, or redirection)")
            if len(argv) > 3 and argv[0] == "cd" and argv[2] == "&&" and not any(t in SHELL_OPERATORS for t in argv[3:]):
                message += ("; choose a workspace directory with cwd instead of cd. "
                            f"Run instead: {json.dumps({'command': shlex.join(argv[3:]), 'cwd': argv[1]})}")
            raise ToolArgumentError(message)
        if argv[0] == "cd":
            raise ToolArgumentError(
                "cd is not available: use the cwd argument to choose a workspace directory"
            )
        head = argv[0].lower()
        if head in PYTHON_ALIASES:
            return [self.interpreter, *argv[1:]]
        if head == "pytest":
            return [self.interpreter, "-m", "pytest", *argv[1:]]
        return argv

    def _run(self, arguments: Dict[str, Any], call_id: str) -> ToolOutcome:
        unknown = sorted(key for key in arguments if key not in _TOOL_PARAMETERS["run"]["properties"])
        try:
            if unknown:
                raise ToolArgumentError(f"unknown argument(s) {', '.join(unknown)}")
            cwd = self.runtime.workspace._resolve(self._text(arguments, "cwd", "."))
            if not cwd.is_dir():
                raise ToolArgumentError("cwd must be an existing workspace directory")
            sequence = arguments.get("commands")
            if sequence is not None:
                if "command" in arguments:
                    raise ToolArgumentError("supply command or commands, not both")
                if not isinstance(sequence, list) or not 1 <= len(sequence) <= 50 or any(not isinstance(c, str) for c in sequence):
                    raise ToolArgumentError("commands must contain 1 to 50 command strings")
                for item in sequence:
                    self._argv(item)
            else:
                command = self._text(arguments, "command", required=True)
                argv = self._argv(command)
            requested_timeout = self._int(arguments, "timeout_seconds")
        except (ToolArgumentError, ValueError) as exc:
            detail = str(exc)
            # A rejection that already shows the command to run instead needs no second example.
            guidance = "" if "Run instead:" in detail else argument_guidance("run")
            message = f"ERROR: {detail}; nothing was run.{guidance}"
            return self._journaled(call_id, "run", arguments, lambda: ToolOutcome(message, "rejected"))
        if sequence is not None:
            return self._journaled(call_id, "run_sequence", arguments,
                                   lambda: self._run_commands(arguments, call_id))
        timeout = float(requested_timeout) if requested_timeout and requested_timeout > 0 else self.default_timeout_seconds
        timeout = min(timeout, self.max_timeout_seconds)
        record = ExecutionController(self.runtime, self.backend).execute(
            ExecutionRequest(
                command=argv,
                working_directory=cwd,
                workspace_root=self.runtime.workspace.root,
                timeout_seconds=timeout,
                output_limit_bytes=self.output_limit_bytes,
                environment=self.environment,
                mutates_workspace=True,
            ),
            call_id=call_id,
        )
        execution, result = record.execution, record.tool_result
        parts = [f"$ {command}", f"status: {execution.status}; exit code: {execution.exit_code}; {execution.duration_ms} ms",
                 f"cwd: {cwd.relative_to(self.runtime.workspace.root).as_posix()}"]
        if execution.diagnostic:
            parts.append(f"diagnostic: {execution.diagnostic}")
        if execution.output_truncated:
            parts.append(f"[output exceeded {self.output_limit_bytes} bytes; the process was stopped]")
        for label, data in (("stdout", execution.stdout), ("stderr", execution.stderr)):
            if data:
                parts.append(f"--- {label} ---\n{data.decode('utf-8', errors='replace')}")
        return ToolOutcome("\n".join(parts), result.status)

    def _run_commands(self, arguments, call_id):
        sequence = arguments['commands']
        stop = self._bool({'stop': arguments.get('stop_on_error', True)}, 'stop')
        outcomes = []
        for index, command in enumerate(sequence, 1):
            single = {k: v for k, v in {**arguments, 'command': command}.items()
                      if k not in {'commands', 'stop_on_error'}}
            outcome = self._run(single, f'{call_id}-{index}')
            outcomes.append(outcome)
            if outcome.status != 'success' and stop:
                break
        failed = next((o.status for o in outcomes if o.status != 'success'), 'success')
        return ToolOutcome(f'Executed {len(outcomes)} of {len(sequence)} commands.\n' +
                           '\n'.join(o.content for o in outcomes), failed)

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
