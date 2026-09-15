"""S1b tests for authorized, discoverable, stable session history."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

from reticle.context import BaselineContextPolicy, PressureRecentContextPolicy, TranscriptStore
from reticle.runtime import LocalRuntime, SessionQueryService
from reticle.runtime.contracts import TaskEnvelope
from reticle.tools import ToolSuite


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "state.txt").write_text(
            "OLD-NEEDLE original evidence\n" + ("historical filler\n" * 300),
            encoding="utf-8",
        )
        self.session = self.root / "session"
        self.runtime = LocalRuntime(self.session, self.workspace)
        self.tools = ToolSuite(self.runtime, interpreter=sys.executable)
        self.transcript = TranscriptStore(self.runtime)
        self.task = TaskEnvelope("history", "Recover earlier evidence after it leaves context.")

    def tearDown(self):
        self.temp_dir.cleanup()

    def exchange(self, call_id, name, arguments):
        self.transcript.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }],
        })
        outcome = self.tools.dispatch(name, arguments, call_id)
        self.transcript.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": outcome.content,
            "_reticle_output": {
                "handle": outcome.handle,
                "tool": name,
                "status": outcome.status,
            },
        })
        return outcome

    def test_discovers_evicted_observation_after_file_change_and_restart(self):
        old = self.exchange("read-old", "read_file", {"path": "state.txt"})
        self.exchange("change", "write_file", {"path": "state.txt", "content": "NEW live state\n"})
        self.exchange("large", "read_file", {"path": "state.txt"})
        result = PressureRecentContextPolicy().build(
            self.runtime,
            self.task,
            self.transcript.load(),
            [],
            2_000,
        )
        self.assertFalse(result.over_budget)
        self.assertNotIn("OLD-NEEDLE", "\n".join(str(message.get("content", "")) for message in result.messages))

        resumed = LocalRuntime(self.session)
        resumed_tools = ToolSuite(resumed, interpreter=sys.executable)
        searched = resumed_tools.dispatch(
            "search_history", {"query": "OLD-NEEDLE", "limit": 10}, "find-old"
        )
        self.assertEqual(searched.status, "success")
        payload = json.loads(searched.content)
        output_hit = next(record for record in payload["records"] if record.get("output_handle") == old.handle)
        self.assertEqual(output_hit["path"], "state.txt")
        self.assertEqual(output_hit["status"], "success")
        self.assertIn("OLD-NEEDLE", output_hit["snippet"])
        artifact_id = output_hit["artifact_ids"][0]

        recovered = resumed_tools.dispatch("read_artifact", {"id": artifact_id}, "read-old-artifact")
        self.assertEqual(recovered.status, "success")
        self.assertIn("OLD-NEEDLE", json.loads(recovered.content)["content"])
        self.assertEqual((self.workspace / "state.txt").read_text(encoding="utf-8"), "NEW live state\n")

    def test_paged_history_keeps_call_metadata(self):
        self.exchange("read-1", "read_file", {"path": "state.txt"})
        self.exchange("run-1", "run", {"command": 'python -c "print(1)"'})
        service = SessionQueryService(self.runtime)

        def summary(record):
            return (record["kind"], record["source"], record.get("path"), record.get("status"),
                    tuple(record.get("artifact_ids", [])))

        single = {record["sequence"]: summary(record) for record in service.history(limit=100).records}
        paged, cursor = {}, None
        while True:
            page = service.history(limit=1, cursor=cursor)
            paged.update({record["sequence"]: summary(record) for record in page.records})
            cursor = page.next_cursor
            if not cursor:
                break

        self.assertEqual(paged, single)
        read_record = next(value for value in single.values() if value[1] == "read_file")
        self.assertEqual(read_record[2:4], ("state.txt", "success"))

    def test_explicit_window_never_returns_retrieval_records(self):
        self.exchange("read-1", "read_file", {"path": "state.txt"})
        self.exchange("find-1", "search_history", {"query": "OLD-NEEDLE"})
        intent = next(
            event.sequence for event in self.runtime.journal.read_all()
            if event.kind == "action_intent" and event.payload.get("action") == "search_history"
        )

        records = SessionQueryService(self.runtime).history(after_sequence=intent, limit=100).records

        self.assertEqual(records, [])

    def test_search_returns_one_record_per_call_with_linked_artifacts(self):
        self.exchange("read-1", "read_file", {"path": "state.txt"})
        service = SessionQueryService(self.runtime)

        records = service.search("OLD-NEEDLE").records

        self.assertEqual([(record["kind"], record["source"]) for record in records], [("tool_output", "read_file")])
        self.assertGreater(len(records[0]["artifact_ids"]), 1)
        for artifact_id in records[0]["artifact_ids"]:
            self.assertEqual(service.read_artifact(artifact_id)["artifact_id"], artifact_id)
        # Asking for a derived kind explicitly still returns it.
        self.assertTrue(service.search("OLD-NEEDLE", kinds=["observation"]).records)

    def test_credentials_inside_tool_call_arguments_are_redacted(self):
        self.exchange("secret-args", "unknown_tool", {"path": "state.txt", "api_key": "ARG-SECRET"})
        service = SessionQueryService(self.runtime)

        self.assertEqual(service.search("ARG-SECRET").records, [])
        assistant = next(
            record for record in service.history(kinds=["transcript_message"]).records
            if record["source"] == "assistant"
        )
        self.assertIn("[redacted]", assistant["snippet"])

    def test_history_tool_output_is_line_pageable(self):
        self.exchange("read-1", "read_file", {"path": "state.txt"})

        outcome = self.tools.dispatch("search_history", {"query": "OLD-NEEDLE"}, "find")

        self.assertGreater(len(outcome.content.splitlines()), 5)
        self.assertEqual(json.loads(outcome.content)["records"][0]["source"], "read_file")

    def test_search_cursor_keeps_first_page_high_water(self):
        for index in range(3):
            self.runtime.record_observation(
                f"CURSOR-NEEDLE {index}".encode(), labels=["fixture", str(index)]
            )
        service = SessionQueryService(self.runtime)
        first = service.search("CURSOR-NEEDLE", limit=1)
        self.assertTrue(first.truncated)
        self.runtime.record_observation(b"CURSOR-NEEDLE late", labels=["fixture", "late"])

        sequences = [first.records[0]["sequence"]]
        cursor = first.next_cursor
        while cursor:
            page = service.search("CURSOR-NEEDLE", limit=1, cursor=cursor)
            self.assertEqual(page.high_water_sequence, first.high_water_sequence)
            sequences.extend(record["sequence"] for record in page.records)
            cursor = page.next_cursor

        self.assertEqual(len(sequences), 3)
        self.assertTrue(all(sequence <= first.high_water_sequence for sequence in sequences))

    def test_controller_history_and_artifacts_are_denied(self):
        built = BaselineContextPolicy().build(self.runtime, self.task, [], [], 2_000)
        service = SessionQueryService(self.runtime)
        with self.assertRaises(PermissionError):
            service.history(kinds=["context_manifest"])
        with self.assertRaises(PermissionError):
            service.read_artifact(built.manifest.materialized_request_artifact_id)

        denied = self.tools.dispatch(
            "read_artifact", {"id": built.manifest.materialized_request_artifact_id}, "denied"
        )
        self.assertEqual(denied.status, "rejected")
        self.assertIn("unavailable or not authorized", denied.content)

    def test_structured_credentials_are_redacted_from_history(self):
        self.tools.dispatch(
            "unknown_tool", {"path": "state.txt", "api_key": "DO-NOT-EXPOSE"}, "secret-call"
        )
        service = SessionQueryService(self.runtime)

        self.assertEqual(service.search("DO-NOT-EXPOSE").records, [])
        page = service.history(kinds=["action_intent"])
        record = next(item for item in page.records if item["source"] == "unknown_tool")
        self.assertIn("[redacted]", record["snippet"])
        self.assertNotIn("DO-NOT-EXPOSE", record["snippet"])

        transcript = self.transcript.append({
            "role": "user", "content": "constraint", "api_key": "TRANSCRIPT-SECRET"
        })
        with self.assertRaises(PermissionError):
            service.read_artifact(transcript)
        self.assertEqual(service.search("TRANSCRIPT-SECRET").records, [])

    def test_revised_user_constraint_is_searchable_after_restart(self):
        self.transcript.append({
            "role": "user",
            "content": "REVISED-CONSTRAINT: preserve the public function name",
        })
        resumed = SessionQueryService(LocalRuntime(self.session))

        page = resumed.search("REVISED-CONSTRAINT")

        self.assertTrue(page.records)
        self.assertEqual(page.records[0]["source"], "user")
        self.assertIn("preserve the public function name", page.records[0]["snippet"])

    def test_history_pages_bound_large_record_text_and_report_scope(self):
        self.runtime.record_observation(b"x" * 10_000, labels=["large-fixture"])

        page = SessionQueryService(self.runtime).history(kinds=["observation"])

        self.assertEqual(page.scope["kinds"], ["observation"])
        self.assertLessEqual(len(page.records[0]["snippet"]), 320)
        self.assertTrue(page.records[0]["text_truncated"])

    def test_missing_authorized_artifact_reports_unavailable(self):
        artifact = self.runtime.record_observation(b"temporary", labels=["fixture"])
        envelope = self.runtime.artifacts.get_envelope(artifact.artifact_id)
        blob = self.runtime.artifacts.blob_dir / envelope.content_hash[:2] / envelope.content_hash[2:]
        blob.unlink()

        result = self.tools.dispatch("read_artifact", {"id": artifact.artifact_id}, "missing")
        self.assertEqual(result.status, "error")
        self.assertIn("Artifact blob unavailable", result.content)


if __name__ == "__main__":
    unittest.main()
