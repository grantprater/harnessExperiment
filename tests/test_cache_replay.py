"""Prefix and message-boundary arithmetic of experiments/session_harness/cache_replay.py."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import cache_replay  # noqa: E402
from cache_replay import (  # noqa: E402
    AppendOnlyReplayPolicy,
    analyse,
    cacheable_prefix,
    common_prefix,
    omission_changes,
    parse_resource_status,
    prefix_breaks,
    render_order,
)
from reticle.context import (  # noqa: E402
    PressureRecentContextPolicyV2,
    PressureRecentContextPolicyV4,
    TranscriptStore,
    render_resource_status,
)
from reticle.context.baseline import _encoded  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
OPENING = [
    {"role": "system", "content": "Reticle runtime contract. Synthetic."},
    {"role": "user", "content": "Fix the synthetic bug."},
]


def status(left: int) -> dict:
    return {"role": "system", "content": render_resource_status(
        {"model_responses": {"remaining": left, "limit": 3}})}


def unit(index: int) -> list:
    call_id = f"call-{index}"
    return [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{index}.py"})}}]},
        {"role": "tool", "tool_call_id": call_id, "content": f"line {index}\n" * 40},
    ]


def transcript_before(turn: int) -> list:
    return [message for index in range(1, turn) for message in unit(index)]


def status_first(turn: int) -> list:  # the pressure-recent-v2 layout
    return [*OPENING, status(4 - turn), *transcript_before(turn)]


def status_last(turn: int) -> list:  # the append-only layout
    return [*OPENING, *transcript_before(turn), status(4 - turn)]


def prefix_bytes(messages: list) -> int:
    """Render-order bytes of the tool block plus these whole messages, counted independently."""
    return len(b'{"tools":' + _encoded(TOOLS) + b',"messages":[' + b",".join(_encoded(m) for m in messages))


class PrefixArithmeticTests(unittest.TestCase):
    def test_render_order_has_the_canonical_length_and_message_boundaries(self):
        messages = status_last(3)
        raw, boundaries = render_order(messages, TOOLS)
        self.assertEqual(len(raw), len(_encoded({"messages": messages, "tools": TOOLS})))
        self.assertEqual(len(boundaries), len(messages) + 2)
        for count in range(1, len(messages) + 1):
            self.assertEqual(boundaries[count + 1], prefix_bytes(messages[:count]))

    def test_rounding_down_to_a_unit_boundary(self):
        boundaries = [0, 10, 20, 30]
        self.assertEqual(cacheable_prefix(25, boundaries), (20, 2))
        self.assertEqual(cacheable_prefix(20, boundaries), (20, 2))
        self.assertEqual(cacheable_prefix(9, boundaries), (0, 0))
        self.assertEqual(common_prefix(b"x" * 9000 + b"a", b"x" * 9000 + b"b"), 9000)
        self.assertEqual(common_prefix(b"abc", b"abcdef"), 3)

    def test_status_first_caches_only_the_opening(self):
        turns = analyse([{"messages": status_first(turn), "tools": TOOLS} for turn in (1, 2, 3)])
        self.assertEqual(turns[0].cacheable_bytes, 0)
        self.assertAlmostEqual(turns[0].cached_cost, 1.25 * turns[0].request_bytes / 4)
        for number, turn in zip((2, 3), turns[1:]):
            old_status, new_status = _encoded(status(5 - number)), _encoded(status(4 - number))
            opening = prefix_bytes(OPENING)
            self.assertEqual(turn.cacheable_bytes, opening)
            self.assertEqual(turn.leading_messages, 2)
            # The prefix runs into the status message up to its first changed byte (the count).
            self.assertEqual(turn.lcp_bytes, opening + 1 + len(os.path.commonprefix([old_status, new_status])))
            self.assertTrue(turn.break_at.startswith("m2 status +"))
            self.assertEqual(turn.not_reused, ["m2 status"])
            self.assertAlmostEqual(turn.cached_cost, 0.10 * opening / 4 + 1.25 * (turn.request_bytes - opening) / 4)

    def test_status_last_caches_the_whole_previous_transcript(self):
        turns = analyse([{"messages": status_last(turn), "tools": TOOLS} for turn in (1, 2, 3)])
        self.assertEqual([t.leading_messages for t in turns[1:]], [2, 4])
        self.assertEqual(turns[1].cacheable_bytes, prefix_bytes(OPENING))
        self.assertEqual(turns[2].cacheable_bytes, prefix_bytes([*OPENING, *unit(1)]))
        self.assertTrue(turns[2].break_at.startswith("m4 status->assistant(read_file)"))
        self.assertEqual(turns[2].not_reused, ["m4 status"])
        first = analyse([{"messages": status_first(turn), "tools": TOOLS} for turn in (1, 2, 3)])
        self.assertEqual(sum(t.uncached_cost for t in turns), sum(t.uncached_cost for t in first))
        self.assertLess(sum(t.cached_cost for t in turns), sum(t.cached_cost for t in first))

    def test_prefix_breaks_count_turns_that_rewrite_more_than_the_trailing_status(self):
        first = analyse([{"messages": status_first(turn), "tools": TOOLS} for turn in (1, 2, 3)])
        last = analyse([{"messages": status_last(turn), "tools": TOOLS} for turn in (1, 2, 3)])
        self.assertEqual(prefix_breaks(first), [3])  # turn 2 rewrites only turn 1's final message, its status
        self.assertEqual(prefix_breaks(last), [])
        requests = [{"omitted_units": units} for units in ([], [], [0, 1], [0, 1], [0, 1, 2])]
        self.assertEqual(omission_changes(requests), [3, 5])
        self.assertIsNone(omission_changes([{"messages": []}]))

    def test_a_changed_tool_schema_breaks_before_every_message(self):
        changed = [{**TOOLS[0], "function": {**TOOLS[0]["function"], "description": "new"}}]
        turns = analyse([{"messages": status_last(2), "tools": TOOLS}, {"messages": status_last(3), "tools": changed}])
        self.assertEqual((turns[1].cacheable_bytes, turns[1].leading_messages), (0, 0))
        self.assertTrue(turns[1].break_at.startswith("tools"))
        self.assertEqual(turns[1].not_reused[0], "tools")


class PackagePolicyReplayTests(unittest.TestCase):
    """The same three turns built by the package's v2 policy and by the append-only replay policy."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / "workspace").mkdir()
        self.runtime = LocalRuntime(root / "session", root / "workspace")
        self.task = TaskEnvelope("synthetic", "Fix the synthetic bug.", budgets={"model_responses": 3})

    def tearDown(self):
        self.temp_dir.cleanup()

    def replay(self, policy) -> list:
        store, requests = TranscriptStore(self.runtime), []
        for turn in (1, 2, 3):
            if turn > 1:
                for message in unit(turn - 1):
                    if message["role"] == "tool":
                        message["_reticle_output"] = {"handle": f"out_{turn - 1}", "tool": "read_file", "status": "success"}
                    store.append(message)
            built = policy.build(self.runtime, self.task, store.load(), TOOLS, 80_000,
                                 resource_status={"model_responses": {"remaining": 4 - turn, "limit": 3}})
            requests.append({"messages": built.messages, "tools": built.tools})
        return requests

    def test_v2_breaks_at_the_status_and_append_only_after_the_previous_transcript(self):
        v2 = self.replay(PressureRecentContextPolicyV2())
        self.temp_dir.cleanup()
        self.setUp()
        append_only = self.replay(AppendOnlyReplayPolicy())
        v2_turns, append_turns = analyse(v2), analyse(append_only)
        self.assertEqual([t.leading_messages for t in v2_turns[1:]], [2, 2])
        self.assertTrue(all(t.break_at.startswith("m2 status +") for t in v2_turns[1:]))
        self.assertEqual([t.leading_messages for t in append_turns[1:]], [2, 4])
        self.assertEqual(cache_replay.label(append_only[2]["messages"][-1]), "status")
        # Same bytes each turn: only the status moved.
        self.assertEqual([t.request_bytes for t in v2_turns], [t.request_bytes for t in append_turns])
        self.assertLess(sum(t.cached_cost for t in append_turns), sum(t.cached_cost for t in v2_turns))

    def test_v4_puts_the_status_last_and_matches_v2_moved_to_the_end_without_pressure(self):
        v2 = self.replay(PressureRecentContextPolicyV2())
        self.temp_dir.cleanup()
        self.setUp()
        v4 = self.replay(PressureRecentContextPolicyV4())
        turns = analyse(v4)
        self.assertEqual([t.leading_messages for t in turns[1:]], [2, 4])
        self.assertEqual(prefix_breaks(turns), [])
        self.assertEqual(cache_replay.label(v4[2]["messages"][-1]), "status")
        # Without pressure v4 differs from v2 only in the status position and v3's status wording.
        for old, new in zip(v2, v4):
            self.assertEqual(cache_replay.move_status_last(old["messages"])[:-1], new["messages"][:-1])

    def test_status_lines_parse_back_to_the_same_text(self):
        state = {"model_responses": {"remaining": 2, "limit": 3}, "cost_usd": {"remaining": 0.0934, "limit": 0.1},
                 "attempt_cost_reservation_usd": 0.006477, "cost_unknown_billing_attempts": 1}
        for labeled in (False, True):
            text = render_resource_status(state, labeled_limits=labeled)
            parsed, parsed_labeled = parse_resource_status(text)
            self.assertEqual(parsed_labeled, labeled)
            self.assertEqual(render_resource_status(parsed, labeled_limits=labeled), text)


if __name__ == "__main__":
    unittest.main()
