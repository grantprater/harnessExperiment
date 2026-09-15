"""P2 acceptance tests for contracts, artifacts, revisions, and recovery."""

from pathlib import Path
import tempfile
import unittest

from reticle.runtime import LocalRuntime, StaleWorkspaceError, ToolResultEnvelope
from reticle.runtime.contracts import FinalResultEnvelope, TaskEnvelope
from reticle.runtime.events import EventJournal
from reticle.storage import ArtifactStore, StaleReferenceError


class ContractTests(unittest.TestCase):
    def test_versioned_contracts_validate_statuses(self):
        task = TaskEnvelope(task_id="task-1", description="Preserve output")
        self.assertEqual(task.to_dict()["schema_version"], 1)
        result = FinalResultEnvelope(
            task_id="task-1",
            status="needs_review",
            workspace_revision="sha256:abc",
            criterion_outcomes={"human": "unknown"},
        )
        self.assertEqual(result.to_dict()["status"], "needs_review")
        with self.assertRaises(ValueError):
            ToolResultEnvelope(
                call_id="call-1",
                status="maybe",
                workspace_revision_before="a",
                workspace_revision_after="a",
            )


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ArtifactStore(Path(self.temp_dir.name) / "store")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_blob_is_exact_and_stale_reference_write_is_rejected(self):
        first = self.store.put(b"first\x00output", "application/octet-stream", "evt-1")
        second = self.store.put(b"second output", "text/plain", "evt-2")
        self.assertEqual(self.store.read(first.artifact_id), b"first\x00output")

        reference = self.store.update_reference("scratch/current", first.artifact_id, expected_version=0)
        self.assertEqual(reference.version, 1)
        self.store.update_reference("scratch/current", second.artifact_id, expected_version=1)
        with self.assertRaises(StaleReferenceError):
            self.store.update_reference("scratch/current", first.artifact_id, expected_version=1)
        self.assertEqual(self.store.read_reference("scratch/current"), b"second output")


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.session = self.root / "session"
        self.workspace.mkdir()
        (self.workspace / "note.txt").write_bytes(b"version one")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scripted_session_recovers_exact_output_and_incomplete_action(self):
        runtime = LocalRuntime(self.session, self.workspace)
        revision = runtime.workspace.revision()
        runtime.begin_action("op-complete", "run", {"cmd": "probe"})
        tool_result = runtime.record_tool_result(
            operation_id="op-complete",
            call_id="call-complete",
            status="success",
            workspace_revision_before=revision,
            workspace_revision_after=revision,
            stdout=b"exact stdout\x00with bytes",
            stderr=b"exact stderr",
            exit_code=0,
            preview_limit=8,
        )
        runtime.artifacts.update_reference(
            "observations/latest", tool_result.stdout_ref, expected_version=0
        )
        runtime.begin_action("op-interrupted", "write", {"path": "note.txt"})
        checkpoint = runtime.checkpoint()
        self.assertIn("op-interrupted", checkpoint["incomplete_operation_ids"])

        resumed = LocalRuntime(self.session)
        self.assertEqual(resumed.recovery.incomplete_operation_ids, ["op-interrupted"])
        self.assertEqual(
            resumed.artifacts.read_reference("observations/latest"),
            b"exact stdout\x00with bytes",
        )
        self.assertTrue(tool_result.preview_truncated)
        self.assertEqual(resumed.load_checkpoint()["last_event_sequence"], 4)
        self.assertNotIn("op-complete", resumed.recovery.incomplete_operation_ids)
        with self.assertRaises(ValueError):
            resumed.begin_action("op-complete", "run", {"cmd": "probe"})

    def test_workspace_write_rejects_stale_revision(self):
        runtime = LocalRuntime(self.session, self.workspace)
        observation = runtime.workspace.read("note.txt")
        (self.workspace / "other.txt").write_bytes(b"external change")

        with self.assertRaises(StaleWorkspaceError):
            runtime.workspace.write(
                "note.txt",
                b"version two",
                expected_workspace_revision=observation.workspace_revision,
                expected_content_hash=observation.content_hash,
            )
        self.assertEqual((self.workspace / "note.txt").read_bytes(), b"version one")

    def test_incomplete_journal_tail_is_reported_and_blocks_append(self):
        journal_path = self.session / "events.jsonl"
        journal = EventJournal(journal_path)
        journal.append("observation", {"value": 1})
        with journal_path.open("ab") as stream:
            stream.write(b'{"partial":')

        resumed = EventJournal(journal_path)
        self.assertTrue(resumed.truncated_tail_detected)
        with self.assertRaises(RuntimeError):
            resumed.append("observation", {"value": 2})


if __name__ == "__main__":
    unittest.main()
