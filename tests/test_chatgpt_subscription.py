"""Offline protocol and credential tests for the subscription route."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

from reticle.cognitive.chatgpt_auth import ChatGPTAuth, PLAN_SCOPE, _read, _write, _updated
from reticle.cognitive.chatgpt_subscription import (
    ChatGPTSubscriptionClient, model_response, read_completed, responses_payload,
)
from reticle.runtime.controller import ModelClientError


TOOL = {"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}
CALL = {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"x"}'}}
COMPLETED = {"id": "resp_1", "model": "test-model", "status": "completed", "output": [
    {"type": "function_call", "namespace": "reticle", "name": "read_file", "call_id": "call_1",
     "arguments": '{"path":"x"}'}], "usage": {"input_tokens": 40, "output_tokens": 8, "total_tokens": 48}}


def stream(data):
    return io.BytesIO(('event: response.completed\ndata: ' + json.dumps({"type": "response.completed", "response": data}) + '\n\n').encode())


class SubscriptionTests(unittest.TestCase):
    def test_full_tool_history_and_preview_constraints(self):
        messages = [{"role": "system", "content": "instruction"}, {"role": "user", "content": "read x"},
                    {"role": "assistant", "content": None, "tool_calls": [CALL]},
                    {"role": "tool", "tool_call_id": "call_1", "content": "contents"}]
        body = responses_payload("test-model", messages, [TOOL])
        self.assertEqual(body["input"][0], {"role": "developer", "content": "instruction"})
        self.assertEqual(body["input"][-2]["call_id"], body["input"][-1]["call_id"])
        self.assertEqual(body["input"][-1]["output"], "contents")
        self.assertEqual(body["tools"][0]["type"], "namespace")
        self.assertFalse(body["store"])
        self.assertTrue(body["stream"])
        self.assertFalse({"temperature", "max_output_tokens", "previous_response_id"} & body.keys())

    def test_completed_tools_usage_and_unknown_cost(self):
        response = model_response(read_completed(stream(COMPLETED)), "hash")
        self.assertEqual(response.message["tool_calls"], [CALL])
        self.assertEqual(response.usage["prompt_tokens"], 40)
        self.assertNotIn("cost", response.usage)

    def test_incomplete_stream_never_executes_partial_call(self):
        for payload in (b'data: {"type":"response.output_item.added"}\n\n',
                        b'data: {"type":"response.failed"}\n\n', b'data: [DONE]\n\n'):
            with self.assertRaises(ModelClientError):
                read_completed(io.BytesIO(payload))

    def test_plan_stream_outputs_arrive_before_empty_completed_envelope(self):
        event = {"type": "response.output_item.done", "output_index": 0, "item": COMPLETED["output"][0]}
        terminal = {"type": "response.completed", "response": {**COMPLETED, "output": []}}
        raw = ''.join('data: ' + json.dumps(item) + '\n\n' for item in (event, terminal)).encode()
        response = model_response(read_completed(io.BytesIO(raw)), "hash")
        self.assertEqual(response.message["tool_calls"], [CALL])
        self.assertEqual(response.usage["completion_tokens"], 8)

    def test_attempt_accounting_and_no_credentials_in_log(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "calls.jsonl"
            auth, budget, attempts = Mock(), Mock(), Mock()
            attempts.begin.return_value = "attempt_1"
            auth.access_token.return_value = "secret-token"
            with patch("urllib.request.urlopen", return_value=stream(COMPLETED)) as opener:
                response = ChatGPTSubscriptionClient("test-model", auth=auth, budget=budget,
                                                     calls_path=path).complete([], [TOOL], attempts=attempts)
            self.assertEqual(response.message["tool_calls"], [CALL])
            budget.check.assert_called_once()
            budget.take.assert_called_once()
            attempts.begin.assert_called_once()
            attempts.finish.assert_not_called()  # controller reconciles successful attempt
            self.assertNotIn("secret-token", path.read_text())
            self.assertEqual(opener.call_args.args[0].full_url, "https://api.openai.com/v1/responses")

    def test_failed_http_charges_one_attempt_without_retry_or_token_leak(self):
        auth, attempts = Mock(), Mock()
        auth.access_token.return_value = "secret-token"
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429, "rate limit", {}, io.BytesIO(b"secret-token"))
        with patch("urllib.request.urlopen", side_effect=error) as opener:
            with self.assertRaisesRegex(ModelClientError, "http_429"):
                ChatGPTSubscriptionClient("test-model", auth=auth).complete([], [], attempts=attempts)
        opener.assert_called_once()
        attempts.finish.assert_called_once()

    def test_credential_storage_and_serialized_rotation(self):
        # DPAPI needs a loaded Windows user profile, unavailable in the offline sandbox.
        # The live setup separately verifies DPAPI under the signed-in desktop user.
        with tempfile.TemporaryDirectory() as root, patch(
                "reticle.cognitive.chatgpt_auth._dpapi", side_effect=lambda data, decrypt=False: data):
            auth = ChatGPTAuth(root)
            record = {"access_token": "expired-secret", "refresh_token": "old-refresh", "client_id": "issued-id",
                      "scopes": [PLAN_SCOPE], "expires_at": 0}
            _write(auth.path, record)
            self.assertEqual(_read(auth.path), record)
            replacement = {"access_token": "renewed-secret", "refresh_token": "rotated-refresh", "expires_in": 3600}
            with patch("reticle.cognitive.chatgpt_auth._token_request", return_value=replacement) as exchange:
                self.assertEqual(auth.access_token(), "renewed-secret")
                self.assertEqual(auth.access_token(), "renewed-secret")
            exchange.assert_called_once()
            self.assertEqual(exchange.call_args.args[0]["client_id"], "issued-id")
            self.assertEqual(_read(auth.path)["refresh_token"], "rotated-refresh")

    def test_missing_plan_grant_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "permission"):
            _updated({}, {"scope": "openid", "access_token": "x", "expires_in": 3600})


if __name__ == "__main__":
    unittest.main()
