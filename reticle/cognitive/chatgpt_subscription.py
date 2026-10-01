"""Responses adapter for Reticle's own loop using a ChatGPT subscription."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from reticle.cognitive.chatgpt_auth import ChatGPTAuth, RESOURCE
from reticle.runtime.controller import ModelClientError, ModelResponse


def responses_payload(model, messages, tools):
    inputs = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            inputs.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                           "output": message.get("content") or ""})
            continue
        content = message.get("content")
        if content:
            inputs.append({"role": "developer" if role == "system" else role, "content": content})
        for call in message.get("tool_calls") or []:
            inputs.append({"type": "function_call", "call_id": call["id"],
                           "name": call["function"]["name"], "namespace": "reticle",
                           "arguments": call["function"]["arguments"]})
    body = {"model": model, "input": inputs, "store": False, "stream": True}
    if tools:
        functions = []
        for tool in tools:
            if tool.get("type") != "function":
                raise ValueError("Subscription adapter supports function tools only")
            function = tool["function"]
            functions.append({"type": "function", "name": function["name"],
                              "description": function.get("description", ""),
                              "parameters": function["parameters"], "strict": False})
        body["tools"] = [{"type": "namespace", "name": "reticle", "description": "Reticle harness tools",
                          "tools": functions}]
        body["tool_choice"] = "auto"
    return body


def read_completed(response):
    """Parse SSE records, including multi-line data; reject truncated streams.

    Only response.completed is accepted, so partial tool arguments are never executed.
    """
    lines, output_items = [], {}
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line:
            if line.startswith("data:"):
                lines.append(line[5:].lstrip(" "))
            continue
        if not lines:
            continue
        data = "\n".join(lines)
        lines = []
        if data == "[DONE]":
            continue
        event = json.loads(data)
        if event.get("type") == "response.output_item.done":
            output_items[event["output_index"]] = event["item"]
        if event.get("type") == "response.completed":
            completed = event["response"]
            if completed.get("status") != "completed":
                raise ModelClientError("Subscription response did not complete")
            # The plan route can send output only in output_item.done events;
            # its terminal response contains usage but an empty output array.
            if not completed.get("output") and output_items:
                completed = {**completed, "output": [output_items[index] for index in sorted(output_items)]}
            return completed
        if event.get("type") in ("error", "response.failed", "response.incomplete"):
            raise ModelClientError("Subscription stream failed: " + str(event.get("type")))
    raise ModelClientError("Subscription stream ended without response.completed")


def model_response(data, request_hash):
    content, calls = [], []
    for item in data.get("output", []):
        if item["type"] == "message":
            content.extend(part["text"] for part in item.get("content", []) if part.get("type") == "output_text")
        elif item["type"] == "function_call":
            if item.get("namespace") not in (None, "reticle"):
                raise ModelClientError("Unexpected tool namespace")
            calls.append({"id": item["call_id"], "type": "function", "function": {
                "name": item["name"], "arguments": item["arguments"]}})
    reported = data.get("usage")
    usage = None if reported is None else {
        "prompt_tokens": reported.get("input_tokens"), "completion_tokens": reported.get("output_tokens"),
        "total_tokens": reported.get("total_tokens"),
    }
    return ModelResponse({"role": "assistant", "content": "\n".join(content) or None, "tool_calls": calls},
                         usage, {"provider": "chatgpt-subscription", "model": data.get("model"),
                                 "generation_id": data.get("id"), "attempts": 1,
                                 "request_sha256": request_hash, "billing": "shared_chatgpt_plan",
                                 "responses_usage": reported})


class ChatGPTSubscriptionClient:
    reports_provider_attempts = True

    def __init__(self, model, *, auth=None, calls_path=None, run_id=None, budget=None, timeout=300):
        self.model = model
        self.auth = auth or ChatGPTAuth()
        self.calls_path = Path(calls_path) if calls_path else None
        self.run_id, self.budget, self.timeout = run_id, budget, timeout
        self.call_index = 0

    def complete(self, messages, tools, *, attempts=None):
        body = responses_payload(self.model, messages, tools)
        raw = json.dumps(body, ensure_ascii=False).encode()
        request_hash = hashlib.sha256(raw).hexdigest()
        # Refresh/validate before reserving an inference attempt. No automatic retries:
        # an interrupted stream can have consumed plan usage.
        token = self.auth.access_token()
        if self.budget:
            self.budget.check()
        self.call_index += 1
        attempt_id = attempts.begin({"request_sha256": request_hash, "call_index": self.call_index,
                                     "attempt": 1}) if attempts else None
        if self.budget:
            self.budget.take()
        entry = {"run_id": self.run_id, "model": self.model, "call_index": self.call_index, "attempt": 1,
                 "provider_attempt_id": attempt_id, "request_sha256": request_hash, "request": body,
                 "billing": "shared_chatgpt_plan", "time": datetime.now(timezone.utc).isoformat()}
        started = time.monotonic()
        try:
            request = urllib.request.Request(RESOURCE + "/responses", raw, method="POST", headers={
                "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "text/event-stream"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = read_completed(response)
            result = model_response(data, request_hash)
            entry["response"] = data
            return result
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, ModelClientError) as exc:
            status = getattr(exc, "code", None)
            failure = f"http_{status}" if status else "stream_or_network_error"
            entry["error"] = failure
            if attempts:
                attempts.finish(attempt_id, outcome=failure, metadata={"error": failure})
            if isinstance(exc, ModelClientError):
                raise
            raise ModelClientError(f"ChatGPT subscription request failed ({failure})") from None
        finally:
            entry["latency_s"] = round(time.monotonic() - started, 3)
            if self.calls_path:
                self.calls_path.parent.mkdir(parents=True, exist_ok=True)
                with self.calls_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
