"""The local Claude Code CLI as a stateless model client for the P6 runner (`--client claude-cli`).

Each model request is one headless `claude -p` process that sees only what the Reticle context
policy selected. The OpenAI-style messages are rendered into one prompt (stdin), the tool schemas
go in the system prompt as a catalog, and --json-schema offers the reply format {"content", "tool_calls"}.
The reply is the model's first message (--max-turns 1): its StructuredOutput call, or, if it calls the
harness tools directly instead, those calls; the model never sees the CLI's rejection of such calls.
The CLI's built-in tools, MCP servers, skills, setting sources, CLAUDE.md/memory, and saved sessions
are all disabled, so the model can act only through the Reticle tools; nothing carries over between
invocations.

Every invocation is checked against the CLI's own init event before its reply is used: the only
tool it may expose is StructuredOutput (the channel --json-schema uses for the reply), no
MCP server may be connected, and apiKeySource must be "none" (the local subscription login; no API
key is read or passed, and ANTHROPIC_* variables are removed from the child environment). Billing
per attempt is therefore unknown; the CLI's total_cost_usd is a list-price estimate and is kept
only as metadata, never as a reported cost.

`--bare` is not used: it accepts only ANTHROPIC_API_KEY or an apiKeyHelper (OAuth is never read),
so it cannot run on a subscription login. `--safe-mode --setting-sources "" --strict-mcp-config
--disable-slash-commands --tools ""` is the equivalent isolation that keeps the login. The CLI still
adds a short environment note (working directory, platform, date, model name, account e-mail); the
working directory is an empty temporary folder.

`--output-format stream-json --verbose` is used instead of `json`: its final `result` event is the
same object `json` prints, and it also carries the init event that lists the tools actually exposed.

Tool probe (asks the nested CLI, with the adapter's exact flags and no Reticle tools, what it can call):
  python experiments/p6_pilot/claude_cli.py --probe-tools OUT_DIR
"""

from __future__ import annotations

from datetime import datetime, timezone
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

try:
    from reticle.runtime.controller import ModelClientError, ModelResponse
except ImportError:  # run as a script from the repository root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from reticle.runtime.controller import ModelClientError, ModelResponse

# v1: tools listed as OpenAI function schemas under "Tools"; the model called them as native functions,
#     the CLI rejected each call, and the reply ran out of CLI turns (E3-positive-control-006, Arm R run 1)
#     (all 8 replays of that request with the same or a reworded prompt also called the harness tools
#     directly first; in the 3 that recovered, the model had seen the CLI's "No such tool" rejections)
# v2: the reply is the model's FIRST message, and the CLI stops after it (--max-turns 1), so the model
#     never sees the CLI's own rejection of a harness tool name. Its tool calls are taken from a
#     StructuredOutput call (the --json-schema channel) or, when it calls the harness tools directly,
#     from those direct calls. Tools are listed as a text catalog (name, description, argument schema).
ADAPTER_VERSION = "claude-cli-adapter-v2"
REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "content": {"type": ["string", "null"]},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["id", "name", "arguments"],
            },
        },
    },
    "required": ["content", "tool_calls"],
}
REPLY_CHANNEL_TOOLS = frozenset({"StructuredOutput"})  # how --json-schema returns the reply; not an action
# Flags that isolate the nested CLI from user configuration and remove every built-in tool.
ISOLATION_ARGUMENTS = [
    "--safe-mode", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
    "--no-session-persistence", "--tools", "",
]
# Variables that link a child to this machine's running Claude Code session, and credentials that
# would bill an API account instead of the local login.
SESSION_VARIABLES = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")
SESSION_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_")

SYSTEM_PROMPT = """\
You are the model inside the Reticle agent harness. You cannot run commands or read files yourself; the \
harness does that for you. Each request ends after your first message: the harness takes the tool calls \
in that message (preferably one StructuredOutput call whose tool_calls list names harness tools, or direct \
calls to the harness tools listed at the end), runs them in order, and shows their results in its next \
request. Nothing is executed while you write the message, so do not wait for results within it.

Every request is self-contained. It holds the conversation as the harness chose to present it; earlier \
parts may be omitted under context pressure, as the harness messages explain. Messages appear oldest \
first, each introduced by a header line starting with "#####". "system" messages come from the harness \
(runtime contract, remaining resources); "user" gives the task; "assistant" entries are your own earlier \
replies with the tool calls you requested; "tool result" entries are the outputs of those calls, matched \
by call id.

StructuredOutput fields:
- "content": a short note for the transcript, or null;
- "tool_calls": the harness tool requests to run now, in order. Each has "id" (any string; the harness \
assigns its own call ids), "name" (one of the harness tools below), and "arguments" (an object matching \
that tool's parameters). Request finish when the task is complete.

Harness tools. Each entry gives the name, the description, and the JSON Schema of its arguments.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, value) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def child_environment(extra: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, str], List[str]]:
    """This process's environment without session links or API credentials; returns (env, removed names)."""
    environment, removed = {}, []
    for name, value in os.environ.items():
        if name.upper() in SESSION_VARIABLES or name.upper().startswith(SESSION_PREFIXES):
            removed.append(name)
        else:
            environment[name] = value
    environment.update(extra or {})
    return environment, sorted(removed)


def resolve_executable(name: str = "claude") -> Optional[str]:
    return shutil.which(name)


def cli_version(executable: str = "claude") -> str:
    path = resolve_executable(executable)
    if path is None:
        raise SystemExit(f"{executable} is not on PATH")
    completed = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60,
                               env=child_environment()[0])
    return completed.stdout.strip()


def _text(content) -> str:
    if isinstance(content, list):  # content parts
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return "" if content is None else str(content)


def render_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """The adapter protocol, then each harness tool as a catalog entry (not a function definition)."""
    entries = []
    for tool in tools:
        function = tool.get("function") or tool
        entries.append(f"\n### {function.get('name')}\n{function.get('description', '')}\n"
                       f"arguments: {json.dumps(function.get('parameters', {}), ensure_ascii=False)}")
    return SYSTEM_PROMPT + "".join(entries) + "\n"


def render_conversation(messages: List[Dict[str, Any]]) -> str:
    """The provider messages, oldest first, as one plain-text prompt."""
    tool_names: Dict[Any, str] = {}
    blocks = []
    for index, message in enumerate(messages, 1):
        role = message.get("role")
        if role == "assistant":
            lines = [_text(message.get("content"))] if _text(message.get("content")) else []
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                tool_names[call.get("id")] = str(function.get("name"))
                lines.append(f"tool call {call.get('id')}: {function.get('name')} {function.get('arguments')}")
            header = f"##### [{index}] assistant (your earlier reply)"
            body = "\n".join(lines) if lines else "(no text and no tool call)"
        elif role == "tool":
            call_id = message.get("tool_call_id")
            header = f"##### [{index}] tool result for call {call_id} ({tool_names.get(call_id, 'unknown tool')})"
            body = _text(message.get("content"))
        else:
            header = f"##### [{index}] {role}"
            body = _text(message.get("content"))
        blocks.append(f"{header}\n{body}")
    blocks.append("##### end of conversation\nReply now with your next tool calls as the required JSON object.")
    return "\n\n".join(blocks)


def parse_stream(stdout: str) -> Tuple[Optional[dict], Optional[dict], Optional[dict], int, List[dict], List[dict]]:
    """(init, result, last rate-limit info, unparseable lines, CLI-internal turns, first assistant message blocks)."""
    init = result = rate_limit = None
    bad, turns, first_blocks, first_id = 0, [], [], None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(event, dict):
            bad += 1
        elif event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "result":
            result = event
        elif event.get("type") == "rate_limit_event":
            rate_limit = event.get("rate_limit_info")
        elif event.get("type") in ("assistant", "user"):
            message = event.get("message") or {}
            if event.get("type") == "assistant":
                # One model message can arrive as several events sharing its id (thinking, text, each tool_use).
                first_id = message.get("id") if first_id is None else first_id
                if message.get("id") == first_id:
                    first_blocks.extend(b for b in message.get("content") or [] if isinstance(b, dict))
            # Compact record of what happened inside the CLI (tool use, rejections), for diagnosis.
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    turns.append({"tool_use": block.get("name"),
                                  "input": json.dumps(block.get("input"), ensure_ascii=False)[:300]})
                elif block.get("type") == "tool_result":
                    turns.append({"tool_result": str(block.get("content"))[:300], "is_error": bool(block.get("is_error"))})
                elif block.get("type") == "text" and block.get("text"):
                    turns.append({"text": block["text"][:300]})
    return init, result, rate_limit, bad, turns, first_blocks


def isolation_problem(init: dict) -> Optional[str]:
    tools = set(init.get("tools") or [])
    if tools - REPLY_CHANNEL_TOOLS:
        return f"nested CLI exposes tools {sorted(tools - REPLY_CHANNEL_TOOLS)}"
    if init.get("mcp_servers"):
        return f"nested CLI connected MCP servers {init.get('mcp_servers')}"
    if init.get("apiKeySource") != "none":
        return f"nested CLI apiKeySource is {init.get('apiKeySource')!r}, not the local login ('none')"
    return None


def reply_message(structured: Any, call_index: int) -> Tuple[Dict[str, Any], List[Any]]:
    """Convert the structured reply to an OpenAI-style assistant message; raises ValueError if malformed."""
    if not isinstance(structured, dict) or not isinstance(structured.get("tool_calls"), list):
        raise ValueError(f"structured output is not {{content, tool_calls}}: {json.dumps(structured)[:300]}")
    content = structured.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("structured output content is not a string or null")
    calls, model_ids = [], []
    for position, call in enumerate(structured["tool_calls"], 1):
        if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict):
            raise ValueError(f"malformed tool call: {json.dumps(call)[:300]}")
        model_ids.append(call.get("id"))
        # Unique within a run: model-chosen ids often repeat across stateless requests.
        calls.append({"id": f"cli_{call_index}_{position}", "type": "function",
                      "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}})
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return message, model_ids


def first_message_reply(blocks: List[dict], call_index: int) -> Tuple[Dict[str, Any], List[Any], str, List[str]]:
    """(message, model call ids, reply channel, ignored direct calls) from the model's first message.

    A StructuredOutput call is the reply when present; direct calls in the same message are then ignored.
    Otherwise the message's direct tool calls (and its text as content) are the reply. Raises ValueError.
    """
    uses = [b for b in blocks if b.get("type") == "tool_use"]
    structured = [b for b in uses if b.get("name") in REPLY_CHANNEL_TOOLS]
    if structured:
        message, ids = reply_message(structured[0].get("input"), call_index)
        return message, ids, "structured_output", [str(b.get("name")) for b in uses if b not in structured]
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text"))
    message, ids = reply_message({"content": text or None, "tool_calls": [
        {"id": b.get("id"), "name": b.get("name"), "arguments": b.get("input")} for b in uses]}, call_index)
    return message, ids, "direct_tool_use" if uses else "text", []


def cli_contract(model: str, *, max_turns: int, timeout: int, version: str) -> Dict[str, Any]:
    """The invocation contract recorded in the run protocol (the analogue of provider routing)."""
    return {
        "client": "claude-cli", "cli_version": version, "model": model,
        "arguments": ["-p", "--model", model, "--output-format", "stream-json", "--verbose",
                      "--max-turns", str(max_turns), *ISOLATION_ARGUMENTS, "--json-schema", "<reply schema>",
                      "--system-prompt-file", "<system prompt>"],
        "reply_schema": REPLY_SCHEMA, "adapter_version": ADAPTER_VERSION,
        "reply": "the model's first message: a StructuredOutput call, else its direct tool calls",
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "timeout_seconds": timeout, "billing": "unknown (local Claude Code subscription login)",
        "removed_environment": {"names": list(SESSION_VARIABLES), "prefixes": list(SESSION_PREFIXES)},
    }


class ClaudeCliClient:
    """Same interface and attempt accounting as OpenRouterClient; one CLI process per attempt.

    Every attempt is appended to calls.jsonl and, when the controller passes a
    ProviderAttemptRecorder, reserved before dispatch and reconciled after with unknown cost.
    """

    reports_provider_attempts = True

    def __init__(self, model: str, calls_path: Path, run_id: str, budget, *, max_attempts: int = 3,
                 timeout: int = 300, backoff_seconds: float = 5.0, max_turns: int = 1,
                 executable: str = "claude", workdir: Optional[Path] = None):
        self.model, self.calls_path, self.run_id, self.budget = model, Path(calls_path), run_id, budget
        self.max_attempts, self.timeout, self.backoff_seconds = max_attempts, timeout, backoff_seconds
        self.max_turns, self.executable = max_turns, executable
        self.workdir = Path(workdir) if workdir else None
        self.call_index = 0

    def _workdir(self) -> Path:
        if self.workdir is None:
            self.workdir = Path(tempfile.mkdtemp(prefix="reticle-claude-cli-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self.workdir

    def arguments(self, system_prompt_file: Path) -> List[str]:
        return ["-p", "--model", self.model, "--output-format", "stream-json", "--verbose",
                "--max-turns", str(self.max_turns), *ISOLATION_ARGUMENTS,
                "--json-schema", json.dumps(REPLY_SCHEMA, separators=(",", ":")),
                "--system-prompt-file", str(system_prompt_file)]

    def complete(self, messages, tools, *, attempts=None) -> ModelResponse:
        self.call_index += 1
        system_prompt, prompt = render_system_prompt(tools), render_conversation(messages)
        system_sha = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        prompt_bytes = prompt.encode("utf-8")
        request_sha256 = hashlib.sha256(json.dumps(
            {"model": self.model, "system": system_prompt, "prompt": prompt, "adapter": ADAPTER_VERSION},
            ensure_ascii=False).encode("utf-8")).hexdigest()
        workdir = self._workdir()
        system_file = workdir / f"system-{system_sha[:16]}.txt"
        if not system_file.exists():
            system_file.write_text(system_prompt, encoding="utf-8")
        arguments = self.arguments(system_file)
        environment, removed = child_environment()
        last_error = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            # Same order as OpenRouterClient: campaign cap, task reservation, campaign unit.
            self.budget.check()
            attempt_id = attempts.begin({
                "call_index": self.call_index, "attempt": attempt, "request_sha256": request_sha256,
            }) if attempts is not None else None
            self.budget.take()
            entry = {"time": utc_now(), "run_id": self.run_id, "model": self.model, "call_index": self.call_index,
                     "attempt": attempt, "provider_attempt_id": attempt_id, "request_sha256": request_sha256,
                     "request": {"messages": messages, "tools": tools, "arguments": arguments,
                                 "adapter_version": ADAPTER_VERSION, "system_prompt_sha256": system_sha,
                                 "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                                 "prompt_bytes": len(prompt_bytes), "removed_environment": removed},
                     "billing": "unknown"}
            started = time.time()
            failure, retry, message, result, init, model_ids = None, False, None, None, None, []
            channel, ignored = None, []
            try:
                executable = resolve_executable(self.executable)
                if executable is None:
                    raise FileNotFoundError(f"{self.executable} is not on PATH")
                completed = subprocess.run([executable, *arguments], input=prompt_bytes, capture_output=True,
                                           cwd=str(workdir), env=environment, timeout=self.timeout)
                stdout = completed.stdout.decode("utf-8", errors="replace")
                stderr = completed.stderr.decode("utf-8", errors="replace")
                init, result, rate_limit, bad_lines, turns, first_blocks = parse_stream(stdout)
                entry.update(exit_code=completed.returncode, rate_limit=rate_limit, unparsed_lines=bad_lines,
                             cli_turns=turns)
                if stderr.strip():
                    entry["stderr_tail"] = stderr[-2_000:]
                if init is not None:
                    entry["cli_init"] = {key: init.get(key) for key in (
                        "model", "tools", "mcp_servers", "apiKeySource", "claude_code_version", "permissionMode",
                        "skills", "slash_commands", "cwd")}
                if result is not None:
                    entry["cli_result"] = result
                problem = isolation_problem(init) if init is not None else None
                if problem:  # checked first: a reply from a non-isolated CLI is never used
                    last_error, retry, failure = problem, False, "tool_isolation_violation"
                elif init is None or (result is None and not first_blocks):
                    last_error = (f"no {'init' if init is None else 'result'} event (exit {completed.returncode}): "
                                  f"{(stderr or stdout)[-300:]}")
                    retry, failure = True, "invalid_stream"
                elif not first_blocks:  # the model produced no message: an API, auth, or CLI failure
                    detail = str(result.get("result") or result.get("errors") or result.get("subtype"))
                    last_error = f"CLI error ({result.get('subtype')}, {result.get('terminal_reason')}): {detail[:300]}"
                    auth = "log in" in detail.lower() or "login" in detail.lower()
                    retry, failure = not auth, ("cli_auth_error" if auth else "cli_error")
                else:  # the reply is the first message, whatever the CLI did after it
                    try:
                        message, model_ids, channel, ignored = first_message_reply(first_blocks, self.call_index)
                    except ValueError as exc:
                        last_error, retry, failure = str(exc), True, "invalid_reply"
                    else:
                        entry.update(reply_channel=channel, ignored_direct_calls=ignored)
                        entry["response"] = {"id": (result or {}).get("session_id"), "model": init.get("model"),
                                             "provider": "claude-cli", "choices": [{
                                                 "message": message, "finish_reason": (result or {}).get("stop_reason")}]}
            except subprocess.TimeoutExpired:
                last_error, retry, failure = f"CLI timed out after {self.timeout} s", True, "timeout"
                entry["error"] = last_error
            except OSError as exc:  # the executable could not be started
                last_error, retry, failure = repr(exc), False, "cli_unavailable"
                entry["error"] = last_error
            finally:
                entry["latency_s"] = round(time.time() - started, 2)
                if failure is not None:
                    entry["failure"] = failure
                append_jsonl(self.calls_path, entry)
            if failure is not None:
                if attempts is not None:
                    attempts.finish(attempt_id, outcome=failure, cost=None,
                                    metadata={"error": last_error[:300], "billing": "unknown"})
                if not retry:
                    raise ModelClientError(last_error)
                if attempt < self.max_attempts:
                    time.sleep(min(60, self.backoff_seconds * 2 ** (attempt - 1)))
                continue
            result = result or {}
            usage = result.get("usage") or {}
            reported_usage = {
                # No "cost": the attempt's bill is unknown, so the ledger records unknown billing.
                "prompt_tokens": sum(int(usage.get(k) or 0) for k in (
                    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                "completion_tokens": int(usage.get("output_tokens") or 0),
            }
            return ModelResponse(message, reported_usage, {
                "provider": "claude-cli", "model": init.get("model"), "generation_id": result.get("session_id"),
                "finish_reason": result.get("stop_reason"), "attempts": attempt, "request_sha256": request_sha256,
                "num_turns": result.get("num_turns"), "cli_version": init.get("claude_code_version"),
                "billing": "unknown", "cli_list_price_estimate_usd": result.get("total_cost_usd"),
                "reply_channel": channel, "ignored_direct_calls": ignored, "cli_subtype": result.get("subtype"),
                "cli_usage": usage, "model_call_ids": model_ids,
            })
        raise ModelClientError(f"failed after {self.max_attempts} attempts: {last_error}")


class _SingleAttempt:
    def __init__(self):
        self.used = 0

    def check(self):
        if self.used >= 1:
            raise RuntimeError("probe attempt already used")

    def take(self):
        self.check()
        self.used += 1


PROBE_PROMPT = (
    "Do not do anything else. List, by exact name, every tool or function you can invoke yourself in this "
    "session, other than the JSON reply format. Write NONE if there are none. Then say whether your context "
    "contains any CLAUDE.md, memory file, skill list, or MCP server instructions (YES with names, or NO). "
    "Put the whole answer in content and return an empty tool_calls list."
)


def probe_tools(out_dir: Path, model: str = "sonnet") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ClaudeCliClient(model, out_dir / "probe-calls.jsonl", "tool-probe", _SingleAttempt(), max_attempts=1)
    response = client.complete([{"role": "user", "content": PROBE_PROMPT}], [])
    row = json.loads((out_dir / "probe-calls.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    return {"answer": response.message.get("content"), "tool_calls": response.message.get("tool_calls", []),
            "init_tools": row["cli_init"]["tools"], "mcp_servers": row["cli_init"]["mcp_servers"],
            "apiKeySource": row["cli_init"]["apiKeySource"], "model": row["cli_init"]["model"],
            "cli_version": row["cli_init"]["claude_code_version"], "num_turns": response.metadata["num_turns"]}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--probe-tools":
        raise SystemExit(__doc__)
    print(json.dumps(probe_tools(Path(sys.argv[2])), indent=2, ensure_ascii=False))
