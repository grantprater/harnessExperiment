"""Jev as a trajectory phase labeller: the questions, the request, the HTTP call, and the reply parsing.

Jev (`typesafe/jev-1.13`) is a judge model behind OpenRouter's decisions endpoint: it takes a text `state` and a set
of typed questions and returns an answer per question. `label_phases.py --labeller jev` sends, as the state, the
same rendered request the Claude labeller gets as its user message (`label_phases.render_request`); the schema
rules that Claude reads in its system prompt reach Jev as question instructions and one-line rubrics instead.

Three questions per response, decomposed rather than one broad question:

- `phase` (choice): the schema's phase, with each option's rubric taken from `labels/SCHEMA.md`;
- `edited_existing_source` (noul, yes/no): did the response successfully change a pre-existing repository file;
- `verified_after_edit` (noul): did the response run code after the run's first edit of a pre-existing file.

The API key is read from the environment variable `OPENROUTER_API_KEY` at call time. It is never logged or written.
Standard library only (urllib); the transport is a parameter so tests stub it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional

import weakness_mining as wm

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"

STATE_DESCRIPTION = (
    "The state is one response from a coding agent's recorded trajectory. The agent was asked to repair a bug in a "
    "Python repository through a tool interface. The state holds the task statement, a one-line summary of each "
    "earlier response in the same run, and the response to label: its text, its tool calls, and the result of each "
    "call.")

# One line per option, from the phase table of labels/SCHEMA.md.
PHASE_RUBRIC = {
    "explore": "it lists, searches, or reads files, or runs a look-only command (ls, cat, grep, git), to find or "
               "understand relevant code, tests, or behaviour",
    "reproduce": "before any edit of a pre-existing file, it writes a new scratch script or test, or runs a command "
                 "that exercises the code, to observe the reported behaviour; later edits of that scratch file stay "
                 "reproduce",
    "diagnose": "it reads, searches, or prints code the agent has already located as the suspected cause, to test or "
                "narrow a stated hypothesis about the fault",
    "edit": "it changes a file that existed before the run (source, tests, configuration), or creates a new "
            "non-scratch source file",
    "verify": "it runs a command that exercises the code (tests, a script, python -c) after the run's first edit of a "
              "pre-existing file",
    "finish": "it calls finish; or, in a run without a finish tool, it is the run's last response, text only, and the "
              "run ended normally",
    "stuck": "every tool call in the response repeats an earlier call of the same run exactly (same tool, same "
             "arguments) and that earlier call was rejected, or has run with no workspace change since",
    "other": "anything else: history, notes, output paging with no clear purpose; a text-only response that does not "
             "end the run",
}
assert set(PHASE_RUBRIC) == set(wm.PHASES)

QUESTIONS: Dict[str, dict] = {
    "phase": {
        "type": "choice",
        "instructions": (
            STATE_DESCRIPTION + " Which phase is the response to label in? Apply the first rule that fits. "
            "1. stuck: every tool call in the response repeats an earlier call of the same run exactly (same tool, "
            "same arguments) and that earlier call was rejected, or has run with no workspace change since. "
            "2. Otherwise take the most advanced phase among the response's non-repeated calls, in this order: "
            "finish > edit > verify > reproduce > diagnose > explore > other. "
            "A rejected call keeps the phase of what it tried to do."),
        "criteria": dict(PHASE_RUBRIC),
    },
    "edited_existing_source": {
        "type": "noul",
        "instructions": (
            STATE_DESCRIPTION + " Does the response to label successfully change a file that existed in the "
            "repository before the run started (source, tests, or configuration)?"),
        "criteria": {
            "true": "at least one tool call in the response to label writes to or replaces text in a pre-existing "
                    "repository file, and its result reports success",
            "false": "no call in the response to label changes a pre-existing file: its calls only list, read, "
                     "search, or run commands, create a new scratch file, edit a file the run itself created, or "
                     "were rejected",
        },
    },
    "verified_after_edit": {
        "type": "noul",
        "instructions": (
            STATE_DESCRIPTION + " Does the response to label run a command that exercises the code (tests, a "
            "script, python -c) after the run has already edited a pre-existing repository file, in this response "
            "or an earlier one?"),
        "criteria": {
            "true": "a pre-existing repository file was successfully edited earlier in the run or earlier in this "
                    "response, and this response then runs tests, a script, or python -c, and that call was not "
                    "rejected",
            "false": "no pre-existing file had been edited before this response's commands, or the response runs no "
                     "command that exercises the code (it only reads, searches, runs look-only commands, or edits), "
                     "or its command was rejected",
        },
    },
}
QUESTIONS_SHA256 = hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode("utf-8")).hexdigest()

Transport = Callable[[str, dict, Dict[str, str], float], dict]


def request_body(state: str, model: str = MODEL) -> dict:
    return {"model": model, "state": state, "questions": QUESTIONS}


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set in the environment")
    return key


def post_json(url: str, body: dict, headers: Dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # keep the status and the body's start; the key is only in the headers
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None


def parse_answers(reply: dict) -> dict:
    """Extract the recorded fields from one decisions reply; raise ValueError on any missing or malformed answer."""
    answers = reply.get("answers") if isinstance(reply, dict) else None
    if not isinstance(answers, dict):
        raise ValueError(f"no answers in reply: {json.dumps(reply)[:200]}")
    phase_answer = answers.get("phase") or {}
    phase = str(phase_answer.get("choice", "")).strip().lower()
    if phase_answer.get("type") != "choice" or phase not in wm.PHASES:
        raise ValueError(f"bad phase answer: {phase_answer!r}")
    nouls = {}
    for name in ("edited_existing_source", "verified_after_edit"):
        answer = answers.get(name) or {}
        value = answer.get("noul")
        if answer.get("type") != "noul" or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"bad {name} answer: {answer!r}")
        nouls[name] = float(value)
    usage = reply.get("usage") or {}
    return {
        "phase": phase,
        "probabilities": {str(k).lower(): float(v) for k, v in (phase_answer.get("probabilities") or {}).items()},
        "confidence": phase_answer.get("confidence"),
        "edited_existing_source": nouls["edited_existing_source"],
        "verified_after_edit": nouls["verified_after_edit"],
        "cost": usage.get("cost"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "model": reply.get("model"),
    }


def ask(state: str, transport: Transport = post_json, key: Optional[str] = None, model: str = MODEL,
        attempts: int = 2, timeout: float = 60, retry_wait: float = 2.0) -> dict:
    """One decisions call (retried once on any failure); returns the parsed answers plus attempts and latency."""
    headers = {"Authorization": f"Bearer {key or api_key()}", "Content-Type": "application/json"}
    body = request_body(state, model)
    last_error = ""
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            parsed = parse_answers(transport(ENDPOINT, body, headers, timeout))
        except (OSError, RuntimeError, ValueError) as exc:  # URLError and timeouts are OSErrors
            last_error = repr(exc)[:300]
            if attempt < attempts:
                time.sleep(retry_wait)
            continue
        return {**parsed, "attempts": attempt, "latency_s": round(time.time() - started, 3)}
    raise RuntimeError(f"Jev call failed {attempts} times: {last_error}")
