"""Tests for the shared OpenRouter chat client in experiments/hotpotqa_eval/run_eval.py (no network)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hotpotqa_run_eval_under_test", ROOT / "experiments" / "hotpotqa_eval" / "run_eval.py")
hotpotqa = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hotpotqa
spec.loader.exec_module(hotpotqa)


def response(content, completion_tokens=5, **message_extra):
    message = {"role": "assistant", "content": content, **message_extra}
    return {"choices": [{"message": message, "finish_reason": "stop"}], "provider": "FakeProvider",
            "usage": {"prompt_tokens": 10, "completion_tokens": completion_tokens}}


class FakeUrlopen:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.bodies = []

    def __call__(self, req, timeout=None):
        self.bodies.append(json.loads(req.data))
        return io.BytesIO(json.dumps(self.payloads[len(self.bodies) - 1]).encode("utf-8"))


class ChatClientTests(unittest.TestCase):
    def call(self, payloads, prompt="hi"):
        fake = FakeUrlopen(payloads)
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            return hotpotqa.chat("key", "model", prompt), fake

    def test_string_prompt_is_sent_as_one_user_message(self):
        (content, p_tok, c_tok, attempts), fake = self.call([response("hello")])
        self.assertEqual((content, p_tok, c_tok, attempts), ("hello", 10, 5, 1))
        self.assertEqual(fake.bodies[0]["messages"], [{"role": "user", "content": "hi"}])

    def test_message_list_is_sent_unchanged(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        _, fake = self.call([response("ok")], prompt=messages)
        self.assertEqual(fake.bodies[0]["messages"], messages)

    def test_empty_content_is_retried(self):
        (content, _, _, attempts), fake = self.call([response("", completion_tokens=486), response("second try")])
        self.assertEqual((content, attempts), ("second try", 2))
        self.assertEqual(len(fake.bodies), 2)

    def test_persistent_empty_content_raises_with_diagnostics(self):
        payloads = [response(None, completion_tokens=486, reasoning="thinking...")] * 4
        with self.assertRaises(hotpotqa.ApiError) as ctx:
            self.call(payloads)
        message = str(ctx.exception)
        self.assertIn("empty content", message)
        self.assertIn('"completion_tokens": 486', message)
        self.assertIn('"reasoning_chars": 11', message)
        self.assertIn("FakeProvider", message)

    def test_content_parts_are_joined(self):
        parts = [{"type": "text", "text": "APPROACH: x\n"}, {"type": "text", "text": "code"}]
        (content, _, _, _), _ = self.call([response(parts)])
        self.assertEqual(content, "APPROACH: x\ncode")


if __name__ == "__main__":
    unittest.main()
