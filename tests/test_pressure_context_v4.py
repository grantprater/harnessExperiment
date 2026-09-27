"""E1 cache layout 008: pressure-recent-v4 (status last, page-wise omission); v1-v3 unchanged."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))

import cache_replay  # noqa: E402
import run_pilot  # noqa: E402
from reticle.context import (  # noqa: E402
    PressureRecentContextPolicy,
    PressureRecentContextPolicyV2,
    PressureRecentContextPolicyV3,
    PressureRecentContextPolicyV4,
    TranscriptStore,
    render_resource_status,
)
from reticle.context.baseline import _encoded  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.runtime.contracts import TaskEnvelope  # noqa: E402
from reticle.runtime.controller import NO_TOOL_CALL_PROMPT, AgentController, AgentLimits, ModelResponse  # noqa: E402
from reticle.tools import ToolSuite  # noqa: E402

STATUS = {
    "model_responses": {"remaining": 7, "limit": 20},
    "tool_actions": {"remaining": 31, "limit": 60},
    "cost_usd": {"remaining": 0.0934, "limit": 0.1},
    "attempt_cost_reservation_usd": 0.006477,
    "cost_unknown_billing_attempts": 1,
}


def exchange(store, index, content, *, status="success", tool="read_file"):
    call_id = f"call-{index}"
    store.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": tool, "arguments": json.dumps({"path": f"f{index}.txt"})},
        }],
    })
    store.append({
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
        "_reticle_output": {"handle": f"out_{index}", "tool": tool, "status": status},
    })


# The fixtures of tests/test_pressure_context.py, each with the budget that test uses.
def ample(store, runtime):
    exchange(store, 1, "OLDER-BEGIN\n" + ("a" * 3_000) + "\nOLDER-END")
    exchange(store, 2, "NEWEST-BEGIN\n" + ("b" * 3_000) + "\nNEWEST-END")


def pressure(store, runtime):
    exchange(store, 1, "OLDER-ONLY\n" + ("a" * 3_000))
    exchange(store, 2, "LATEST-REQUIRED\n" + ("b" * 3_000), status="error")


def oversized(store, runtime):
    exchange(store, 1, "LATEST-BEGIN\n" + ("line of evidence\n" * 2_000) + "LATEST-END")


def no_tool_call_prompt(store, runtime):
    exchange(store, 1, "line\n" * 4_000)
    store.append({"role": "assistant", "content": "I believe the task is complete."})
    store.append({"role": "user", "content": NO_TOOL_CALL_PROMPT})


def correction(store, runtime):
    exchange(store, 1, "line\n" * 4_000)
    store.append({"role": "user", "content": "CORRECTION: target the v2 API, not v1."})


def contiguous(store, runtime):
    exchange(store, 1, "OLD-SMALL")
    store.append({"role": "assistant", "content": "PLAN " + ("p" * 3_000)})
    exchange(store, 2, "LATEST")


def multi_tool(store, runtime):
    calls = [{"id": f"multi-{i}", "type": "function",
              "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{i}.txt"})}} for i in (1, 2)]
    store.append({"role": "assistant", "content": None, "tool_calls": calls})
    for i in (1, 2):
        store.append({"role": "tool", "tool_call_id": f"multi-{i}", "content": f"RESULT-{i}\n" + ("evidence\n" * 500),
                      "_reticle_output": {"handle": f"out_{i}", "tool": "read_file", "status": "success"}})


def utf8(store, runtime):
    exchange(store, 1, "é" * 10_000)


def huge_arguments(store, runtime):
    store.append({"role": "assistant", "content": None, "tool_calls": [{
        "id": "huge-args", "type": "function",
        "function": {"name": "write_file", "arguments": json.dumps({"path": "x.txt", "content": "x" * 10_000})}}]})
    store.append({"role": "tool", "tool_call_id": "huge-args", "content": "success",
                  "_reticle_output": {"handle": "out_1", "tool": "write_file", "status": "success"}})


def large_pin(store, runtime):
    runtime.scratch.write("large-pin", "P" * 10_000)
    runtime.scratch.pin("large-pin", priority=100)
    exchange(store, 1, "LATEST-MUST-STAY\n" + ("z" * 1_000))


FIXTURES = {
    "ample": (ample, 20_000),
    "pressure": (pressure, 4_300),
    "oversized": (oversized, 3_000),
    "no_tool_call_prompt": (no_tool_call_prompt, 5_000),
    "correction": (correction, 5_000),
    "contiguous": (contiguous, 2_500),
    "multi_tool": (multi_tool, 2_500),
    "utf8": (utf8, 2_500),
    "huge_arguments": (huge_arguments, 2_000),
    "large_pin": (large_pin, 2_000),
}


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "workspace").mkdir()
        self.runtime = LocalRuntime(self.root / "session", self.root / "workspace")
        self.store = TranscriptStore(self.runtime)
        self.task = TaskEnvelope("pressure", "Keep the newest tool outcome visible.")

    def tearDown(self):
        self.temp_dir.cleanup()

    def build(self, policy, budget, status=STATUS):
        options = {"resource_status": status} if getattr(policy, "renders_resource_status", False) else {}
        return policy.build(self.runtime, self.task, self.store.load(), [], budget, **options)


def digest(result) -> str:
    """The request bytes, message order, omissions and budget flag; artifact IDs (random) are excluded."""
    value = {"request": {"messages": result.messages, "tools": result.tools},
             "message_order": result.manifest.message_order, "omitted": result.manifest.omitted_items,
             "over_budget": result.over_budget, "policy_version": result.manifest.policy_version}
    return hashlib.sha256(_encoded(value)).hexdigest()[:16]


LEGACY = {"v1": PressureRecentContextPolicy, "v2": PressureRecentContextPolicyV2, "v3": PressureRecentContextPolicyV3}

# Generated from the pre-v4 code (commit ef524a2) with legacy_digests(); v1-v3 must keep producing them.
GOLDEN = {
    "ample@20000/v1": "819e23918de4476a",
    "ample@20000/v2": "02964603ade0b4dc",
    "ample@20000/v3": "860d1cd5776365ea",
    "ample@21000/v1": "819e23918de4476a",
    "ample@21000/v2": "02964603ade0b4dc",
    "ample@21000/v3": "860d1cd5776365ea",
    "pressure@4300/v1": "e400a92600be4da4",
    "pressure@4300/v2": "5c7244d5c5aec05d",
    "pressure@4300/v3": "b361e9b3ae46b27e",
    "pressure@5300/v1": "e400a92600be4da4",
    "pressure@5300/v2": "5c7244d5c5aec05d",
    "pressure@5300/v3": "6288f0829c129dea",
    "oversized@3000/v1": "a714820ad82d967d",
    "oversized@3000/v2": "1bf4238dd03b42be",
    "oversized@3000/v3": "f8a94243dfe0392e",
    "oversized@4000/v1": "22dbdcf0a75ea2d1",
    "oversized@4000/v2": "07d8a91152e2ca7c",
    "oversized@4000/v3": "066f8f4f4a82efb6",
    "no_tool_call_prompt@5000/v1": "c8e9cea584196c33",
    "no_tool_call_prompt@5000/v2": "99633d36866cdec3",
    "no_tool_call_prompt@5000/v3": "2566a8286e6225ef",
    "no_tool_call_prompt@6000/v1": "96510ba766ca9c2e",
    "no_tool_call_prompt@6000/v2": "02b3f4bb27f0633a",
    "no_tool_call_prompt@6000/v3": "22113957bc87a353",
    "correction@5000/v1": "3ed625ee9505d6a5",
    "correction@5000/v2": "171902d4049e4415",
    "correction@5000/v3": "2abdb6dc61794852",
    "correction@6000/v1": "37ef25be6eb1d24b",
    "correction@6000/v2": "12359b0064349522",
    "correction@6000/v3": "38116ff05a57142a",
    "contiguous@2500/v1": "2696fb444bfb2ca8",
    "contiguous@2500/v2": "16d9bc9d55d733eb",
    "contiguous@2500/v3": "7df3a709dc93b280",
    "contiguous@3500/v1": "2696fb444bfb2ca8",
    "contiguous@3500/v2": "16d9bc9d55d733eb",
    "contiguous@3500/v3": "7df3a709dc93b280",
    "multi_tool@2500/v1": "9fd1a2d63f21839d",
    "multi_tool@2500/v2": "f540c47a7bc8c1f4",
    "multi_tool@2500/v3": "eb0ed400b17d1106",
    "multi_tool@3500/v1": "2129d416f156024e",
    "multi_tool@3500/v2": "988bb95b74f51cfc",
    "multi_tool@3500/v3": "0a37127f214ef247",
    "utf8@2500/v1": "e9bbc52d3a6df344",
    "utf8@2500/v2": "7c6aeac84bd440a0",
    "utf8@2500/v3": "1ccc49b099312897",
    "utf8@3500/v1": "ad44d35f236fbdb6",
    "utf8@3500/v2": "a7823d217a951c51",
    "utf8@3500/v3": "0793c957c7ed88fc",
    "huge_arguments@2000/v1": "a1e099919252c4a5",
    "huge_arguments@2000/v2": "79139240346e2451",
    "huge_arguments@2000/v3": "fcff900ffb5deab2",
    "huge_arguments@3000/v1": "a1e099919252c4a5",
    "huge_arguments@3000/v2": "79139240346e2451",
    "huge_arguments@3000/v3": "fcff900ffb5deab2",
    "large_pin@2000/v1": "520d7922e592e828",
    "large_pin@2000/v2": "9a7887a9b6410126",
    "large_pin@2000/v3": "d08e54cc65e24afc",
    "large_pin@3000/v1": "520d7922e592e828",
    "large_pin@3000/v2": "354c1ed245a9718c",
    "large_pin@3000/v3": "f7a67f06124b2f47",
}


def legacy_digests():
    values = {}
    for name, (fixture, budget) in FIXTURES.items():
        case = FixtureCase()
        case.setUp()
        try:
            fixture(case.store, case.runtime)
            for extra in (0, 1_000):
                for version, policy in LEGACY.items():
                    values[f"{name}@{budget + extra}/{version}"] = digest(case.build(policy(), budget + extra))
        finally:
            case.tearDown()
    return values


class LegacyPoliciesUnchangedTests(unittest.TestCase):
    def test_v1_v2_v3_render_the_existing_fixtures_byte_for_byte_as_before(self):
        self.assertEqual(legacy_digests(), GOLDEN)


STATUS_BYTES = len(_encoded({"content": render_resource_status(STATUS, labeled_limits=True), "role": "system"})) + 1


def is_status(message) -> bool:
    return cache_replay.label(message) == "status"


def is_marker(message) -> bool:
    return cache_replay.label(message) == "omission-marker"


def required_messages_present(transcript, result) -> bool:
    """The latest exchange and every unit after it, as v1-v4 define them, are all in the request."""
    policy = PressureRecentContextPolicyV4()
    units = policy._paired_units(transcript)
    start = policy._required_start(units)
    if start is None:
        return True
    shown_calls = {call["id"] for m in result.messages for call in (m.get("tool_calls") or [])}
    shown_results = {m.get("tool_call_id") for m in result.messages if m.get("role") == "tool"}
    shown_text = {m.get("content") for m in result.messages}
    for message in (m for unit in units[start:] for m in unit):
        if message.get("tool_calls"):
            ok = all(call["id"] in shown_calls for call in message["tool_calls"])
        elif message.get("role") == "tool":
            ok = message["tool_call_id"] in shown_results
        else:
            ok = message.get("content") in shown_text
        if not ok:
            return False
    return True


class V4FixtureTests(FixtureCase):
    """Gate 1: the E1 fixtures (ample budget, forced pressure, oversized latest exchange) under v4."""

    def test_ample_budget_moves_only_the_status(self):
        for name, (fixture, _) in FIXTURES.items():
            with self.subTest(fixture=name):
                self.tearDown()
                self.setUp()
                fixture(self.store, self.runtime)
                v3 = self.build(PressureRecentContextPolicyV3(), 200_000)
                v4 = self.build(PressureRecentContextPolicyV4(), 200_000)
                self.assertEqual(v4.manifest.policy_version, "pressure-recent-v4")
                self.assertEqual(v4.manifest.omitted_items, [])
                self.assertFalse(v4.over_budget)
                self.assertTrue(is_status(v4.messages[-1]))
                self.assertEqual(v4.manifest.message_order[-1], "resource-status")
                self.assertEqual(v4.manifest.selected_items[-1], {"kind": "resource_status", "rendering": "full"})
                self.assertEqual(v4.messages, cache_replay.move_status_last(v3.messages))
                self.assertEqual(v4.manifest.request_bytes, v3.manifest.request_bytes)

    def test_forced_pressure_omits_older_history_behind_the_marker(self):
        pressure(self.store, self.runtime)
        budget = 4_300 + STATUS_BYTES
        v3 = self.build(PressureRecentContextPolicyV3(), budget)
        v4 = self.build(PressureRecentContextPolicyV4(), budget)

        self.assertFalse(v4.over_budget)
        self.assertLessEqual(v4.manifest.request_bytes, budget)
        shown = "\n".join(str(message.get("content")) for message in v4.messages)
        self.assertNotIn("OLDER-ONLY", shown)
        self.assertIn("LATEST-REQUIRED", shown)
        self.assertIn("status=error; output=out_2", shown)
        self.assertEqual(v4.manifest.omitted_items,
                         [{"kind": "transcript_unit", "unit_index": 0, "reason": "context_pressure_page"}])
        # Discoverable: the same marker as v3, directly after the opening, and the contract's retrieval tools.
        marker = v4.messages[2]
        self.assertTrue(is_marker(marker))
        self.assertEqual(marker, next(m for m in v3.messages if is_marker(m)))
        self.assertIn("search_history", marker["content"])
        self.assertIn("read_output/search_output or read_artifact", marker["content"])
        self.assertIn("Use search_history to discover omitted actions", v4.messages[0]["content"])
        self.assertTrue(is_status(v4.messages[-1]))

    def test_oversized_latest_exchange_gets_a_retrievable_view(self):
        oversized(self.store, self.runtime)
        budget = 3_000 + STATUS_BYTES
        v3 = self.build(PressureRecentContextPolicyV3(), budget)
        v4 = self.build(PressureRecentContextPolicyV4(), budget)

        self.assertFalse(v4.over_budget)
        self.assertLessEqual(v4.manifest.request_bytes, budget)
        tool = next(message for message in v4.messages if message.get("role") == "tool")
        self.assertIn("status=success; output=out_1", tool["content"])
        self.assertIn('read_output(id="out_1"', tool["content"])
        self.assertNotEqual(next(i for i in v4.manifest.selected_items if i.get("role") == "tool")["rendering"], "full")
        self.assertEqual(v4.messages, cache_replay.move_status_last(v3.messages))

    def test_every_budget_keeps_the_latest_exchange_and_flags_overflow_where_v3_does(self):
        for name, (fixture, _) in FIXTURES.items():
            self.tearDown()
            self.setUp()
            fixture(self.store, self.runtime)
            transcript = self.store.load()
            for budget in (*range(1_000, 10_001, 750), 15_000, 25_000, 40_000):
                with self.subTest(fixture=name, budget=budget):
                    v3 = PressureRecentContextPolicyV3().build(
                        self.runtime, self.task, transcript, [], budget, resource_status=STATUS)
                    v4 = PressureRecentContextPolicyV4().build(
                        self.runtime, self.task, transcript, [], budget, resource_status=STATUS)
                    self.assertEqual(v4.over_budget, v3.over_budget)
                    self.assertEqual(v4.over_budget, v4.manifest.request_bytes > budget)
                    self.assertTrue(required_messages_present(transcript, v4))
                    self.assertTrue(is_status(v4.messages[-1]))
                    omitted = {item["unit_index"] for item in v4.manifest.omitted_items}
                    # v4 never keeps a unit that v3 omits; it may omit more (the page).
                    self.assertLessEqual({item["unit_index"] for item in v3.manifest.omitted_items}, omitted)
                    if omitted and not v4.over_budget and any(is_marker(m) for m in v3.messages):
                        self.assertTrue(any(is_marker(m) for m in v4.messages))

    def test_context_budget_exhausted_is_raised_at_the_same_budget_as_v3(self):
        huge_arguments(self.store, self.runtime)
        status = {"model_responses": {"remaining": 2, "limit": 2}}  # what the controller passes for this task

        def over(policy, budget):
            return policy.build(self.runtime, self.task, self.store.load(), [], budget,
                                resource_status=status).over_budget

        low, high = 100, 20_000  # the smallest budget at which v3 fits
        while low < high:
            middle = (low + high) // 2
            low, high = (low, middle) if not over(PressureRecentContextPolicyV3(), middle) else (middle + 1, high)
        threshold = low
        self.assertTrue(over(PressureRecentContextPolicyV4(), threshold - 1))
        self.assertFalse(over(PressureRecentContextPolicyV4(), threshold))

        class Finisher:
            calls = 0

            def complete(self, messages, tools):
                Finisher.calls += 1
                return ModelResponse({"role": "assistant", "content": None, "tool_calls": [{
                    "id": "f", "type": "function",
                    "function": {"name": "finish", "arguments": json.dumps({"summary": "done"})}}]})

        stops = {}
        for policy in (PressureRecentContextPolicyV3, PressureRecentContextPolicyV4):
            for budget in (100, threshold - 1, threshold):
                self.tearDown()
                self.setUp()
                huge_arguments(self.store, self.runtime)
                # The fixture budgets assume no tool schemas; the controller sends what the suite declares.
                tools = ToolSuite(self.runtime, interpreter=sys.executable)
                tools.schemas = lambda: []
                Finisher.calls = 0
                result = AgentController(self.runtime, self.task, tools, Finisher(),
                                         AgentLimits(max_model_calls=2, max_context_bytes=budget),
                                         policy=policy()).run()
                stops[(policy.policy_version, budget)] = (result.stop_reason, Finisher.calls)
        for budget in (100, threshold - 1):
            for version in ("pressure-recent-v3", "pressure-recent-v4"):
                self.assertEqual(stops[(version, budget)], ("context_budget_exhausted", 0))
        self.assertEqual(stops[("pressure-recent-v4", threshold)], stops[("pressure-recent-v3", threshold)])
        self.assertNotEqual(stops[("pressure-recent-v4", threshold)][0], "context_budget_exhausted")

    def test_omitted_history_is_recoverable_with_the_marker_instructions(self):
        (self.root / "workspace" / "state.txt").write_text(
            "OLD-NEEDLE original evidence\n" + ("historical filler\n" * 300), encoding="utf-8")
        tools = ToolSuite(self.runtime, interpreter=sys.executable)

        def run(call_id, name, arguments):
            self.store.append({"role": "assistant", "content": None, "tool_calls": [{
                "id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]})
            outcome = tools.dispatch(name, arguments, call_id)
            self.store.append({"role": "tool", "tool_call_id": call_id, "content": outcome.content,
                               "_reticle_output": {"handle": outcome.handle, "tool": name, "status": outcome.status}})
            return outcome

        old = run("read-old", "read_file", {"path": "state.txt"})
        run("change", "write_file", {"path": "state.txt", "content": "NEW live state\n"})
        run("large", "read_file", {"path": "state.txt"})
        result = self.build(PressureRecentContextPolicyV4(), 2_000 + STATUS_BYTES)

        self.assertFalse(result.over_budget)
        self.assertNotIn("OLD-NEEDLE", "\n".join(str(message.get("content", "")) for message in result.messages))
        self.assertIn(0, {item["unit_index"] for item in result.manifest.omitted_items})
        self.assertTrue(any(is_marker(message) for message in result.messages))
        found = json.loads(tools.dispatch("search_history", {"query": "OLD-NEEDLE", "limit": 10}, "find").content)
        hit = next(record for record in found["records"] if record.get("output_handle") == old.handle)
        recovered = tools.dispatch("read_artifact", {"id": hit["artifact_ids"][0]}, "recover")
        self.assertIn("OLD-NEEDLE", json.loads(recovered.content)["content"])

    def test_pressure_recent_v4_is_a_named_arm_with_its_own_protocol_hash(self):
        self.assertIs(run_pilot.ARMS["pressure-recent-v4"], PressureRecentContextPolicyV4)
        execution = {"backend": "trusted-local"}
        self.assertNotEqual(run_pilot.protocol_hash("pressure-recent-v3", {}, execution, {}),
                            run_pilot.protocol_hash("pressure-recent-v4", {}, execution, {}))


class V4PageTests(FixtureCase):
    """The page rule over a growing transcript: the boundary moves once per page, not once per turn."""

    TURNS = 18
    BUDGET = 7_000

    def grow(self, policy):
        results, sequences = [], []
        for turn in range(1, self.TURNS + 1):
            if turn > 1:
                exchange(self.store, turn - 1, f"OBSERVATION-{turn - 1}\n" + ("x" * (700 + 37 * (turn % 5))))
            status = {"model_responses": {"remaining": self.TURNS + 1 - turn, "limit": self.TURNS}}
            events = self.runtime.journal.read_all()
            sequences.append((events[-1].sequence if events else 0, status))
            results.append(self.build(policy, self.BUDGET, status=status))
        return results, sequences

    @staticmethod
    def page_starts(results):
        """The number of leading omitted units per request (omission is always a contiguous oldest run)."""
        starts = []
        for result in results:
            omitted = sorted(item["unit_index"] for item in result.manifest.omitted_items)
            assert omitted == list(range(len(omitted))), omitted
            starts.append(len(omitted))
        return starts

    @staticmethod
    def breaks(results):
        """Turns whose cacheable prefix ends before the previous request's final message."""
        turns = cache_replay.analyse([{"messages": r.messages, "tools": r.tools} for r in results])
        return [turn.turn for previous, turn in zip(results, turns[1:])
                if turn.leading_messages < len(previous.messages) - 1]

    def test_the_boundary_moves_only_when_the_budget_is_exceeded_and_then_to_half(self):
        results, _ = self.grow(PressureRecentContextPolicyV4())
        starts = self.page_starts(results)
        pages = [turn for turn, (before, after) in enumerate(zip(starts, starts[1:]), 2) if after != before]
        self.assertGreaterEqual(len(pages), 2)
        for turn, result in enumerate(results, 1):
            self.assertFalse(result.over_budget)
            self.assertLessEqual(result.manifest.request_bytes, self.BUDGET)
            self.assertTrue(is_status(result.messages[-1]))
            if turn in pages:
                self.assertLessEqual(result.manifest.request_bytes, self.BUDGET // 2)
                self.assertTrue(is_marker(result.messages[2]))
        # Every prefix break is a page; every other turn reuses the whole previous request but its status.
        self.assertEqual(self.breaks(results), pages)

    def test_v3_moves_the_boundary_on_more_turns_and_breaks_at_the_status_every_turn(self):
        v4, _ = self.grow(PressureRecentContextPolicyV4())
        self.tearDown()
        self.setUp()
        v3, _ = self.grow(PressureRecentContextPolicyV3())
        v3_starts, v4_starts = self.page_starts(v3), self.page_starts(v4)
        v3_moves = sum(after != before for before, after in zip(v3_starts, v3_starts[1:]))
        v4_moves = sum(after != before for before, after in zip(v4_starts, v4_starts[1:]))
        self.assertLess(v4_moves, v3_moves)
        # From turn 3 on (turn 1 has no transcript, so its status is also its last message).
        self.assertEqual(self.breaks(v3), list(range(3, self.TURNS + 1)))
        self.assertLess(len(self.breaks(v4)), len(self.breaks(v3)))

    def test_a_fresh_policy_rebuilds_every_request_identically(self):
        results, sequences = self.grow(PressureRecentContextPolicyV4())
        for result, (sequence, status) in zip(results, sequences):
            rebuilt = PressureRecentContextPolicyV4().build(
                self.runtime, self.task, self.store.load(as_of_sequence=sequence), [], self.BUDGET,
                resource_status=status)
            self.assertEqual(rebuilt.messages, result.messages)


if __name__ == "__main__":
    unittest.main()
