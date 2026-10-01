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
MCP server may be connected, and apiKeySource must not name an API key or auth token from the
environment (auth_problem; ANTHROPIC_* variables are removed from the child environment, so no key
the harness holds is passed). The local subscription login reports "none"; any other login the CLI
has (a cloud session's, for example) is accepted and its apiKeySource recorded with every attempt.
Billing per attempt is therefore unknown; the CLI's total_cost_usd is a list-price estimate and is
kept only as metadata, never as a reported cost.

MODEL PIN (one guard; two names from two branches, reconciled on integration/2026-10): a full model id
(claude-..., not an alias such as sonnet) is passed to --model unchanged and pinned: the init event must
report a model, and the init event, every assistant message and the result's modelUsage must report
exactly that id, or the attempt fails before its reply is used, so no tool call of a substituted model
is ever dispatched. The failure kind and stop label is `model_mismatch` (MODEL_MISMATCH; the runner's
stop, run_card's void adapter failure); its message also names `model_pin_violation` (MODEL_PIN_VIOLATION,
the cloud port's name, which run_card and native_control match), and it is never retried. Live runs take
full ids only (model_id_problem; run_pilot.py refuses an alias unless --dry-run, so old alias hashes still
replay): CLI 2.1.286 moved `sonnet` from claude-sonnet-5 to claude-sonnet-5-5 without any change in the
protocol hash (card 010, 2026-09-30). An alias given to this client directly is not checked. Every attempt
records the models the CLI reported, by source (reported_model) and as one sorted list (reported_models).

`--bare` is not used: it accepts only ANTHROPIC_API_KEY or an apiKeyHelper (OAuth is never read),
so it cannot run on a subscription login. `--safe-mode --setting-sources "" --strict-mcp-config
--disable-slash-commands --tools ""` is the equivalent isolation that keeps the login. The CLI still
adds a short environment note (working directory, platform, date, model name, account e-mail); the
working directory is an empty temporary folder.

`--output-format stream-json --verbose` is used instead of `json`: its final `result` event is the
same object `json` prints, and it also carries the init event that lists the tools actually exposed.

REPLY RECOVERY (opt-in, `reply_recovery="lenient-json+second-turn-on-retry"`, adapter v3; off, every request and
record is exactly v2's). Sometimes the CLI cannot parse the model's StructuredOutput input as JSON; it then reports
the input as {"__unparsedToolInput": {"raw": ...}} and rejects the call, and at --max-turns 1 the reply is lost
(card 019: 27 such attempts, 5 runs restarted). With recovery on:
  - the first attempt of every request is v2's CLI invocation (--max-turns 1); its reply is the first message
    exactly as in v2 whenever v2 would use it, else, when that message's StructuredOutput input was unparsed, the
    raw text if json.loads(raw, strict=False) accepts it (control characters inside strings; nothing looser, no
    guessing at truncated JSON), recorded as structured_output_repair "lenient-json";
  - only after an attempt whose StructuredOutput call was rejected (unparsed, or not {content, tool_calls}) do the
    request's later attempts run at --max-turns 2 (recorded as cli_max_turns). The CLI then returns its own
    rejection to the model, and when the first message is unusable under the rules above, the reply is the
    StructuredOutput call of the second message (structured_output_retries 1); a second message is never a
    source of direct tool calls.
Every rejected StructuredOutput call is recorded with its full raw text. A second turn cannot run anything: the
init check still requires the tools to be exactly [StructuredOutput], and every other tool_use in the stream must
have been refused by the CLI (an error tool_result) or the attempt fails as tool_isolation_violation. Cost: only
the retry attempts run a second turn, and one whose first message is usable discards it (cli_model_messages).

Tool probe (asks the nested CLI, with the adapter's exact flags and no Reticle tools, what it can call; one
response, one attempt, every adapter check applied, including the model pin for a full id):
  python experiments/p6_pilot/claude_cli.py --probe-tools OUT_DIR [MODEL]
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
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
# v3 (opt-in, only with reply recovery; v2 requests and hashes are unchanged): a StructuredOutput call the CLI
#     could not parse is repaired with json.loads(raw, strict=False); after a rejected StructuredOutput call, the
#     request's later attempts run at --max-turns 2 and may take the second message's StructuredOutput call
#     (module docstring, REPLY RECOVERY). Card 019 (CLI 2.1.284) lost 5 runs to three unparsed StructuredOutput
#     inputs in a row; card 007 (CLI 2.1.283) had 9 unparsed inputs, each recovered by the next attempt.
RECOVERY_ADAPTER_VERSION = "claude-cli-adapter-v3"
REPLY_RECOVERY = "lenient-json+second-turn-on-retry"
RETRY_MAX_TURNS = 2  # attempts after a rejected StructuredOutput call; every first attempt keeps v2's 1
UNPARSED_INPUT_KEY = "__unparsedToolInput"  # how the CLI reports tool input it could not parse as JSON
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
# A full Claude model ID. Aliases (sonnet, opus, haiku, default, opusplan, ...) and *-latest IDs are refused.
FULL_MODEL_ID = re.compile(r"claude-[a-z0-9][a-z0-9.-]*[a-z0-9]")
MODEL_MISMATCH = "model_mismatch"  # the failure kind and the prefix of its error message
MODEL_PIN_VIOLATION = "model_pin_violation"  # the same guard's cloud-port name; every mismatch message contains it
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
# Comma-separated names of session variables (CLAUDE_CODE_* and the like) to keep in the child environment, for a
# machine whose CLI login lives in one (a cloud session may). Never an ANTHROPIC_* name: those are always removed.
# Empty by default; the names kept are recorded with every attempt.
PASS_ENV_VARIABLE = "RETICLE_CLI_PASS_ENV"
CREDENTIAL_PREFIX = "ANTHROPIC_"
# apiKeySource values that mean an API key or auth token taken from the environment or an API key helper. Any
# other value (the local login's "none", a managed or remote login) is accepted and recorded.
API_KEY_SOURCES = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "apiKeyHelper"})

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


def kept_session_variables(environ=None) -> List[str]:
    """The names $RETICLE_CLI_PASS_ENV asks to keep, without any ANTHROPIC_* name."""
    environ = os.environ if environ is None else environ
    names = {name.strip() for name in environ.get(PASS_ENV_VARIABLE, "").split(",") if name.strip()}
    return sorted(name for name in names if not name.upper().startswith(CREDENTIAL_PREFIX))


def child_environment(extra: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, str], List[str]]:
    """This process's environment without session links or API credentials; returns (env, removed names).
    ANTHROPIC_* is always removed; a session variable named in $RETICLE_CLI_PASS_ENV is kept."""
    environment, removed = {}, []
    kept = set(kept_session_variables())
    for name, value in os.environ.items():
        credential = name.upper().startswith(CREDENTIAL_PREFIX)
        session = name.upper() in SESSION_VARIABLES or name.upper().startswith(SESSION_PREFIXES)
        if credential or (session and name not in kept):
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
    return parse_stream_models(stdout)[:6]


def parse_stream_models(stdout: str):
    """parse_stream's six values, then the models the assistant messages report (in order, without repeats)."""
    init = result = rate_limit = None
    bad, turns, first_blocks, first_id, models = 0, [], [], None, []
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
                if message.get("model") and message["model"] not in models:
                    models.append(message["model"])
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
    return init, result, rate_limit, bad, turns, first_blocks, models


def auth_problem(init: dict) -> Optional[str]:
    """Why the init event's apiKeySource is an API key or auth token from the environment, or None."""
    source = init.get("apiKeySource")
    if source in API_KEY_SOURCES or str(source or "").upper().startswith(CREDENTIAL_PREFIX):
        return f"apiKeySource {source!r}: the CLI would bill an API account through a key from the environment"
    return None


def model_id_problem(model: str) -> Optional[str]:
    """Why `model` is not a pinned full model ID, or None. The claude-cli client takes full IDs only."""
    if not isinstance(model, str) or not FULL_MODEL_ID.fullmatch(model) or model.endswith("-latest"):
        return (f"claude-cli model {model!r} is not a full model ID: pass e.g. claude-sonnet-5, never an alias "
                f"(sonnet, opus, haiku, ...) that the installed CLI resolves")
    return None


def isolation_problem(init: dict) -> Optional[str]:
    tools = set(init.get("tools") or [])
    if tools - REPLY_CHANNEL_TOOLS:
        return f"nested CLI exposes tools {sorted(tools - REPLY_CHANNEL_TOOLS)}"
    if init.get("mcp_servers"):
        return f"nested CLI connected MCP servers {init.get('mcp_servers')}"
    problem = auth_problem(init)
    return f"nested CLI {problem}" if problem else None


def pins_model(model: str) -> bool:
    """A full model id (claude-...) is pinned and checked; an alias (sonnet, opus, ...) is not."""
    return str(model).startswith("claude-")


def reported_models(init: Optional[dict], result: Optional[dict], message_models=()) -> Dict[str, Any]:
    """The models the CLI reported: in its init event, in its assistant messages, and in the result's modelUsage."""
    return {"init": (init or {}).get("model"), "messages": list(message_models),
            "result": sorted(((result or {}).get("modelUsage") or {}).keys())}


def reported_model_ids(reported: Optional[Dict[str, Any]]) -> List[str]:
    """Every model id in a reported_models() record (init, assistant messages, result modelUsage), sorted."""
    reported = reported or {}
    seen = [reported.get("init"), *reported.get("messages", []), *reported.get("result", [])]
    return sorted({str(model) for model in seen if model})


def model_problem(requested: str, reported: Dict[str, Any]) -> Optional[str]:
    """Why the reported models break the pin on requested (a full id), or None; aliases are never a problem.
    The message starts with model_mismatch (the runner's stop label) and names model_pin_violation."""
    if not pins_model(requested):
        return None
    prefix = f"{MODEL_MISMATCH} ({MODEL_PIN_VIOLATION}): requested {requested}"
    if reported.get("init") is None:
        return f"{prefix}, the CLI's init event reports no model"
    if any(model != requested for model in reported_model_ids(reported)):
        return f"{prefix}, the CLI reported {reported_model_ids(reported)}"
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


def stream_messages(stdout: str) -> Tuple[List[List[dict]], Dict[str, dict]]:
    """(each model message's content blocks, in order; the CLI's tool results by tool_use_id). Reply recovery only."""
    messages: List[List[dict]] = []
    positions: Dict[Any, int] = {}  # message id -> index in messages
    results: Dict[str, dict] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line) if line.strip() else None
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") not in ("assistant", "user"):
            continue
        message = event.get("message") or {}
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
        if event["type"] == "assistant":
            # One model message can arrive as several events sharing its id (thinking, text, each tool_use),
            # with the CLI's tool results in between; grouped by id as parse_stream_models groups the first.
            if message.get("id") not in positions:
                positions[message.get("id")] = len(messages)
                messages.append([])
            messages[positions[message.get("id")]].extend(blocks)
        else:
            for block in blocks:
                if block.get("type") == "tool_result":
                    results[str(block.get("tool_use_id"))] = {"is_error": bool(block.get("is_error")),
                                                              "content": str(block.get("content"))}
    return messages, results


def unexecuted_tool_problem(messages: List[List[dict]], results: Dict[str, dict]) -> Optional[str]:
    """Why the stream shows a tool other than StructuredOutput being run (a non-error result), or None."""
    for blocks in messages:
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") not in REPLY_CHANNEL_TOOLS:
                outcome = results.get(str(block.get("id")))
                if outcome is not None and not outcome["is_error"]:
                    return f"nested CLI ran tool {block.get('name')!r} (non-error tool_result)"
    return None


class ReplyRejected(ValueError):
    """No usable reply; .rejections describes every StructuredOutput call that was refused."""

    def __init__(self, message: str, rejections: List[dict]):
        super().__init__(message)
        self.rejections = rejections


def unparsed_raw(value: Any) -> Optional[str]:
    """The raw text of a StructuredOutput input the CLI could not parse ({"__unparsedToolInput": {"raw": ...}})."""
    if isinstance(value, dict) and set(value) == {UNPARSED_INPUT_KEY} and isinstance(value[UNPARSED_INPUT_KEY], dict):
        raw = value[UNPARSED_INPUT_KEY].get("raw")
        return raw if isinstance(raw, str) else None
    return None


def cli_reported_bytes(result: Optional[dict]) -> Optional[int]:
    """The input size the CLI's InputValidationError states ("You sent (first 200 of N bytes)"), if any."""
    text = (result or {}).get("content") or ""
    marker = text.find(" bytes)")
    start = text.rfind(" of ", 0, marker) if marker > 0 else -1
    digits = text[start + 4:marker] if start >= 0 else ""
    return int(digits) if digits.isdigit() else None


def recovered_reply(messages: List[List[dict]], results: Dict[str, dict], call_index: int,
                    second_turn: bool = False):
    """(message, model call ids, channel, ignored direct calls, recovery record) under reply recovery.

    The first message is the reply exactly as in v2 when v2 could use it. When its StructuredOutput call is
    unusable, the raw input the CLI could not parse is tried with json.loads(raw, strict=False); on a second-turn
    attempt (--max-turns 2), then the next message's StructuredOutput call (written after the CLI's rejection),
    under the same two rules. Raises ReplyRejected when no StructuredOutput call is usable.
    """
    first = messages[0]
    if not second_turn:  # a --max-turns 1 attempt: the first message only, as in v2
        messages = messages[:1]
    if not any(b.get("type") == "tool_use" and b.get("name") in REPLY_CHANNEL_TOOLS for b in first):
        message, ids, channel, ignored = first_message_reply(first, call_index)  # v2: direct calls or text
        return message, ids, channel, ignored, {"repair": None, "retries": 0, "rejections": []}
    rejections: List[dict] = []
    for position, blocks in enumerate(messages, 1):
        uses = [b for b in blocks if b.get("type") == "tool_use"]
        structured = [b for b in uses if b.get("name") in REPLY_CHANNEL_TOOLS]
        if not structured:  # a later message is used only through its StructuredOutput call
            continue
        block, repair = structured[0], None
        value = block.get("input")
        raw = unparsed_raw(value)
        rejection: Dict[str, Any] = {"message": position}
        if raw is not None:
            rejection.update(raw=raw, raw_bytes=len(raw.encode("utf-8")),
                             cli_reported_bytes=cli_reported_bytes(results.get(str(block.get("id")))))
            try:
                json.loads(raw)
                rejection["strict_json"] = True  # the CLI failed on text that is valid JSON
            except ValueError:
                rejection["strict_json"] = False
            try:
                value, repair = json.loads(raw, strict=False), "lenient-json"
            except ValueError as exc:
                rejections.append(dict(rejection, kind="unparsed", error=f"lenient JSON: {exc}"))
                continue
        try:
            message, ids = reply_message(value, call_index)
        except ValueError as exc:
            rejections.append(dict(rejection, kind="unparsed" if raw is not None else "invalid", error=str(exc)))
            continue
        if repair:
            rejection.update(kind="unparsed", repaired="lenient-json")
            rejections.append(rejection)
        ignored = [str(b.get("name")) for b in uses if b not in structured]
        return message, ids, "structured_output", ignored, {
            "repair": repair, "retries": position - 1, "rejections": rejections}
    raise ReplyRejected(rejections[-1]["error"] if rejections else "no usable StructuredOutput call", rejections)


def check_recovery(reply_recovery: Optional[str], max_turns: int) -> None:
    if reply_recovery is not None and reply_recovery != REPLY_RECOVERY:
        raise ValueError(f"unknown reply recovery {reply_recovery!r}; the adapter offers {REPLY_RECOVERY!r}")
    if reply_recovery is not None and max_turns != 1:
        raise ValueError(f"reply recovery keeps v2's --max-turns 1 for first attempts, not {max_turns}")


def cli_contract(model: str, *, max_turns: int, timeout: int, version: str,
                 reply_recovery: Optional[str] = None) -> Dict[str, Any]:
    """The invocation contract recorded in the run protocol (the analogue of provider routing).
    Without reply_recovery it is exactly v2's contract, so every recorded hash still replays."""
    check_recovery(reply_recovery, max_turns)
    contract = {
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
    if pins_model(model):  # only a full id; an alias's contract (every recorded card) is exactly as before
        contract["model_pin"] = {
            "requested": model, "failure": "model_pin_violation, not retried; the reply is never used",
            "rule": "the init event, every assistant message and the result's modelUsage report exactly this id",
        }
    if reply_recovery is not None:  # only with the option on; an incumbent contract is exactly as before
        contract["adapter_version"] = RECOVERY_ADAPTER_VERSION
        contract["reply"] = ("the model's first message: a StructuredOutput call, else its direct tool calls; when "
                             "the CLI could not parse that StructuredOutput call, its raw input if lenient JSON "
                             "accepts it; on a retry after a rejected StructuredOutput call, else the second "
                             "message's StructuredOutput call")
        contract["reply_recovery"] = {
            "name": REPLY_RECOVERY, "first_attempt_max_turns": max_turns, "retry_max_turns": RETRY_MAX_TURNS,
            "escalation": "after an attempt whose StructuredOutput call was rejected (unparsed, or not {content, "
                          "tool_calls}), the request's later attempts run at retry_max_turns",
            "lenient_json": f"json.loads(raw, strict=False) of the input the CLI reports as {UNPARSED_INPUT_KEY}; "
                            "nothing looser, no completion of truncated JSON; every attempt",
            "second_turn": "on a retry_max_turns attempt, the StructuredOutput call of the second model message, "
                           "after the CLI rejected the first message's; never its direct tool calls",
            "tool_guard": "init tools exactly [StructuredOutput]; every other tool_use must get an error tool_result",
            "recorded": ["cli_max_turns", "structured_output_repair", "structured_output_retries",
                         "structured_output_rejections", "cli_model_messages"],
        }
    return contract


class ClaudeCliClient:
    """Same interface and attempt accounting as OpenRouterClient; one CLI process per attempt.

    Every attempt is appended to calls.jsonl and, when the controller passes a
    ProviderAttemptRecorder, reserved before dispatch and reconciled after with unknown cost.
    """

    reports_provider_attempts = True

    def __init__(self, model: str, calls_path: Path, run_id: str, budget, *, max_attempts: int = 3,
                 timeout: int = 300, backoff_seconds: float = 5.0, max_turns: int = 1,
                 executable: str = "claude", workdir: Optional[Path] = None, reply_recovery: Optional[str] = None):
        check_recovery(reply_recovery, max_turns)
        self.model, self.calls_path, self.run_id, self.budget = model, Path(calls_path), run_id, budget
        self.max_attempts, self.timeout, self.backoff_seconds = max_attempts, timeout, backoff_seconds
        self.max_turns, self.executable = max_turns, executable
        self.workdir = Path(workdir) if workdir else None
        self.call_index = 0
        self.reply_recovery = reply_recovery
        self.adapter_version = RECOVERY_ADAPTER_VERSION if reply_recovery else ADAPTER_VERSION
        # Per-client (per-run) counts of what recovery did; see recovery_summary().
        self.recovery_counts = {"replies": 0, "lenient_json": 0, "second_turn": 0, "unrecovered_attempts": 0,
                                "rejected_structured_output": 0, "second_turn_attempts": 0,
                                "discarded_model_messages": 0}

    def recovery_summary(self) -> Optional[Dict[str, int]]:
        """What reply recovery did in this client's attempts, or None when it is off."""
        return dict(self.recovery_counts) if self.reply_recovery else None

    def _workdir(self) -> Path:
        if self.workdir is None:
            self.workdir = Path(tempfile.mkdtemp(prefix="reticle-claude-cli-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self.workdir

    def arguments(self, system_prompt_file: Path, max_turns: Optional[int] = None) -> List[str]:
        return ["-p", "--model", self.model, "--output-format", "stream-json", "--verbose",
                "--max-turns", str(self.max_turns if max_turns is None else max_turns), *ISOLATION_ARGUMENTS,
                "--json-schema", json.dumps(REPLY_SCHEMA, separators=(",", ":")),
                "--system-prompt-file", str(system_prompt_file)]

    def complete(self, messages, tools, *, attempts=None) -> ModelResponse:
        self.call_index += 1
        system_prompt, prompt = render_system_prompt(tools), render_conversation(messages)
        system_sha = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        prompt_bytes = prompt.encode("utf-8")
        request_sha256 = hashlib.sha256(json.dumps(
            {"model": self.model, "system": system_prompt, "prompt": prompt, "adapter": self.adapter_version},
            ensure_ascii=False).encode("utf-8")).hexdigest()
        workdir = self._workdir()
        system_file = workdir / f"system-{system_sha[:16]}.txt"
        if not system_file.exists():
            system_file.write_text(system_prompt, encoding="utf-8")
        arguments = self.arguments(system_file)
        environment, removed = child_environment()
        kept = [name for name in kept_session_variables() if name in environment]
        last_error = "no attempt made"
        # Reply recovery: set once an attempt's StructuredOutput call was rejected; the request's later attempts
        # then run at --max-turns 2. Never set without recovery, so v2's attempts all use self.max_turns.
        second_turn = False
        first_arguments = arguments
        for attempt in range(1, self.max_attempts + 1):
            arguments = self.arguments(system_file, RETRY_MAX_TURNS) if second_turn else first_arguments
            # Same order as OpenRouterClient: campaign cap, task reservation, campaign unit.
            self.budget.check()
            attempt_id = attempts.begin({
                "call_index": self.call_index, "attempt": attempt, "request_sha256": request_sha256,
            }) if attempts is not None else None
            self.budget.take()
            entry = {"time": utc_now(), "run_id": self.run_id, "model": self.model, "call_index": self.call_index,
                     "attempt": attempt, "provider_attempt_id": attempt_id, "request_sha256": request_sha256,
                     "request": {"messages": messages, "tools": tools, "arguments": arguments,
                                 "adapter_version": self.adapter_version, "system_prompt_sha256": system_sha,
                                 "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                                 "prompt_bytes": len(prompt_bytes), "removed_environment": removed,
                                 "kept_environment": kept},
                     "billing": "unknown"}
            if self.reply_recovery:  # v3 only: which attempts ran a second turn
                entry["cli_max_turns"] = RETRY_MAX_TURNS if second_turn else self.max_turns
                self.recovery_counts["second_turn_attempts"] += second_turn
            started = time.time()
            failure, retry, message, result, init, model_ids = None, False, None, None, None, []
            channel, ignored, reported = None, [], None
            try:
                executable = resolve_executable(self.executable)
                if executable is None:
                    raise FileNotFoundError(f"{self.executable} is not on PATH")
                completed = subprocess.run([executable, *arguments], input=prompt_bytes, capture_output=True,
                                           cwd=str(workdir), env=environment, timeout=self.timeout)
                stdout = completed.stdout.decode("utf-8", errors="replace")
                stderr = completed.stderr.decode("utf-8", errors="replace")
                init, result, rate_limit, bad_lines, turns, first_blocks, message_models = parse_stream_models(stdout)
                reported = reported_models(init, result, message_models)
                entry.update(exit_code=completed.returncode, rate_limit=rate_limit, unparsed_lines=bad_lines,
                             cli_turns=turns, reported_model=reported)
                if stderr.strip():
                    entry["stderr_tail"] = stderr[-2_000:]
                if init is not None:
                    entry["cli_init"] = {key: init.get(key) for key in (
                        "model", "tools", "mcp_servers", "apiKeySource", "claude_code_version", "permissionMode",
                        "skills", "slash_commands", "cwd")}
                if result is not None:
                    entry["cli_result"] = result
                entry["reported_models"] = reported_model_ids(reported)
                problem = isolation_problem(init) if init is not None else None
                if self.reply_recovery:  # v3 only: the stream by message, and no tool other than the reply ran
                    stream, tool_results = stream_messages(stdout)
                    entry["cli_model_messages"] = len(stream)
                    problem = problem or unexecuted_tool_problem(stream, tool_results)
                pin = model_problem(self.model, reported) if init is not None else None
                if problem:  # checked first: a reply from a non-isolated CLI is never used
                    last_error, retry, failure = problem, False, "tool_isolation_violation"
                elif pin:  # nor a reply from a model other than the pinned one; a retry would only repeat it
                    entry["model_mismatch"] = {"expected": self.model, "reported": entry["reported_models"]}
                    last_error, retry, failure = pin, False, MODEL_MISMATCH
                elif init is None or (result is None and not first_blocks):
                    last_error = (f"no {'init' if init is None else 'result'} event (exit {completed.returncode}): "
                                  f"{(stderr or stdout)[-300:]}")
                    retry, failure = True, "invalid_stream"
                elif not first_blocks:  # the model produced no message: an API, auth, or CLI failure
                    detail = str(result.get("result") or result.get("errors") or result.get("subtype"))
                    last_error = f"CLI error ({result.get('subtype')}, {result.get('terminal_reason')}): {detail[:300]}"
                    auth = "log in" in detail.lower() or "login" in detail.lower()
                    retry, failure = not auth, ("cli_auth_error" if auth else "cli_error")
                else:  # the reply is the first message, whatever the CLI did after it (v3: unless recovered)
                    try:
                        if self.reply_recovery:
                            message, model_ids, channel, ignored, recovery = recovered_reply(
                                stream, tool_results, self.call_index, second_turn=second_turn)
                        else:
                            message, model_ids, channel, ignored = first_message_reply(first_blocks, self.call_index)
                    except ValueError as exc:
                        last_error, retry, failure = str(exc), True, "invalid_reply"
                        if self.reply_recovery:
                            rejections = getattr(exc, "rejections", [])
                            entry["structured_output_rejections"] = rejections
                            self.recovery_counts["unrecovered_attempts"] += 1
                            self.recovery_counts["rejected_structured_output"] += len(rejections)
                            # A rejected StructuredOutput call (not a malformed direct call) escalates the
                            # request's later attempts to --max-turns 2.
                            second_turn = second_turn or bool(rejections)
                    else:
                        entry.update(reply_channel=channel, ignored_direct_calls=ignored)
                        if self.reply_recovery:
                            entry.update(structured_output_repair=recovery["repair"],
                                         structured_output_retries=recovery["retries"],
                                         structured_output_rejections=recovery["rejections"])
                            counts = self.recovery_counts
                            counts["replies"] += 1
                            counts["lenient_json"] += recovery["repair"] == "lenient-json"
                            counts["second_turn"] += recovery["retries"]
                            counts["rejected_structured_output"] += len(recovery["rejections"])
                            counts["discarded_model_messages"] += max(0, len(stream) - recovery["retries"] - 1)
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
            metadata = {
                "provider": "claude-cli", "model": init.get("model"), "generation_id": result.get("session_id"),
                "reported_model": reported, "api_key_source": init.get("apiKeySource"),
                "finish_reason": result.get("stop_reason"), "attempts": attempt, "request_sha256": request_sha256,
                "num_turns": result.get("num_turns"), "cli_version": init.get("claude_code_version"),
                "billing": "unknown", "cli_list_price_estimate_usd": result.get("total_cost_usd"),
                "reply_channel": channel, "ignored_direct_calls": ignored, "cli_subtype": result.get("subtype"),
                "cli_usage": usage, "model_call_ids": model_ids, "reported_models": reported_model_ids(reported),
            }
            if self.reply_recovery:  # v2 metadata is unchanged
                metadata.update(structured_output_repair=entry["structured_output_repair"],
                                structured_output_retries=entry["structured_output_retries"],
                                cli_model_messages=entry["cli_model_messages"], cli_max_turns=entry["cli_max_turns"])
            return ModelResponse(message, reported_usage, metadata)
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


def probe_tools(out_dir: Path, model: str = "claude-sonnet-5") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ClaudeCliClient(model, out_dir / "probe-calls.jsonl", "tool-probe", _SingleAttempt(), max_attempts=1)
    response = client.complete([{"role": "user", "content": PROBE_PROMPT}], [])
    row = json.loads((out_dir / "probe-calls.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    return {"answer": response.message.get("content"), "tool_calls": response.message.get("tool_calls", []),
            "init_tools": row["cli_init"]["tools"], "mcp_servers": row["cli_init"]["mcp_servers"],
            "apiKeySource": row["cli_init"]["apiKeySource"], "model": row["cli_init"]["model"],
            "requested_model": model, "reported_model": row.get("reported_model"),
            "kept_environment": row["request"].get("kept_environment"),
            "cli_version": row["cli_init"]["claude_code_version"], "num_turns": response.metadata["num_turns"],
            "cli_list_price_estimate_usd": response.metadata.get("cli_list_price_estimate_usd"),
            "latency_s": row.get("latency_s")}


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or sys.argv[1] != "--probe-tools":
        raise SystemExit(__doc__)
    print(json.dumps(probe_tools(Path(sys.argv[2]), *sys.argv[3:]), indent=2, ensure_ascii=False))
