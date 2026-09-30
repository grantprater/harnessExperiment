"""Evidence provenance, advisory rules, restart and opt-in runner boundaries."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from reticle.runtime.session import LocalRuntime
from reticle.runtime.reasoning import EvidenceOntology
from reticle.tools.primitives import ToolSuite, TOOL_SCHEMAS
from reticle.tools.reasoning import ReasoningTools

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "p6_pilot"))
import run_pilot
from experiments.neurosymbolic.run_fixtures import exercise

AVAILABLE = all(importlib.util.find_spec(name) for name in ("rdflib", "pyshacl"))


class Suite(ReasoningTools, ToolSuite):
    pass


@unittest.skipUnless(AVAILABLE, "install reticle[reasoning] for ontology tests")
class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "mod.py").write_text("x = 1\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", workspace)
        self.ontology = EvidenceOntology(self.runtime, "symbolic")
        self.tools = Suite(self.runtime, interpreter=sys.executable, reasoning=self.ontology)
        self.tools.dispatch("read_file", {"path": "mod.py"}, "read")
        self.observation = self.ontology.state()["entities"][0]

    def entity(self, entity_id="h", kind="hypothesis", **fields):
        return {"id": entity_id, "kind": kind, "text": "A testable assertion",
                "evidence": self.observation["evidence"], **fields}

    def test_runtime_observations_cannot_be_forged(self):
        with self.assertRaises(ValueError):
            self.ontology.update([self.entity(kind="observation")])
        self.assertEqual(self.ontology.record()["updates"], 0)

    def test_private_and_unknown_evidence_rejected(self):
        hidden = self.runtime.journal.append("acceptance_decision", {"secret": "hidden answer"})
        for evidence in ([hidden.event_id], ["evt_missing"], []):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.ontology.update([self.entity(evidence=evidence)])
        self.assertNotIn("hidden answer", json.dumps(self.ontology.state()))

    def test_task_grounded_requirements_without_hidden_criteria(self):
        from reticle.runtime.contracts import TaskEnvelope
        self.runtime.persist_task_contract(TaskEnvelope("task", "Zero must be positive",
                                                       criteria=[{"visibility": "hidden", "answer": "do not expose"}]))
        requirement = next(item for item in self.ontology.state()["entities"] if item["origin"] == "runtime_contract")
        self.assertEqual(requirement["text"], "Zero must be positive")
        self.assertNotIn("do not expose", json.dumps(self.ontology.state()))
        self.ontology.update([self.entity("scoped", "requirement", evidence=requirement["evidence"], cases=["zero"])])
        with self.assertRaises(ValueError):
            self.ontology.update(relations=[{"source": "scoped", "relation": "supersedes", "target": requirement["id"]}])

    def test_evaluator_labeled_observations_are_not_projected(self):
        artifact = self.runtime.record_observation(b"hidden answer", "text/plain", labels=["evaluator"])
        self.assertNotIn(artifact.artifact_id, json.dumps(self.ontology.state()))
        self.assertNotIn("hidden answer", json.dumps(self.ontology.state()))

    def test_invalid_batch_is_atomic(self):
        with self.assertRaises(ValueError):
            self.ontology.update([self.entity()], [{"source": "h", "relation": "tests", "target": "missing"}])
        self.assertEqual(self.ontology.record()["updates"], 0)
        self.assertFalse(any(item["id"] == "h" for item in self.ontology.state()["entities"]))

    def test_immutable_ids_and_duplicate_batch_ids(self):
        with self.assertRaises(ValueError):
            self.ontology.update([self.entity(), self.entity()])
        self.ontology.update([self.entity()])
        with self.assertRaises(ValueError):
            self.ontology.update([self.entity(text="changed")])

    def test_superseding_hypothesis_removes_old_warning(self):
        link = {"source": self.observation["id"], "relation": "contradicts", "target": "h"}
        self.ontology.update([self.entity()], [link])
        self.assertEqual(self.ontology.state()["findings"][0]["rule"], "contradicted_hypothesis")
        self.ontology.update([self.entity("h2")], [{"source": "h2", "relation": "supersedes", "target": "h"}])
        self.assertEqual(self.ontology.state()["findings"], [])
        with self.assertRaises(ValueError):
            self.ontology.update(relations=[{"source": "h", "relation": "supersedes", "target": "h2"}])

    def test_missing_prediction_or_scope_stays_unknown(self):
        self.ontology.update([self.entity("c", "check"), self.entity("r", "requirement")],
                             [{"source": "c", "relation": "addresses", "target": "r"}])
        self.assertEqual(self.ontology.state()["findings"], [])

    def test_bad_types_and_fields_rejected(self):
        for entity in (self.entity(evidence="oops"), self.entity(cases=["zero"]),
                       self.entity("c", "check", predictions={"missing": "pass"}),
                       self.entity("c", "check", observation=self.observation["id"]),
                       self.entity(origin="runtime_observation"), self.entity("unsafe id")):
            with self.subTest(entity=entity), self.assertRaises((TypeError, ValueError)):
                self.ontology.update([entity])

    def test_shacl_requires_provenance(self):
        entity = {**self.entity(), "origin": "model_assertion", "evidence": []}
        with self.assertRaisesRegex(ValueError, "SHACL"):
            EvidenceOntology.validate_graph({"h": entity})

    def test_memory_arm_has_identical_entities_without_inference(self):
        self.ontology.update([self.entity()],
                             [{"source": self.observation["id"], "relation": "contradicts", "target": "h"}])
        memory = EvidenceOntology(self.runtime, "memory").state()
        symbolic = self.ontology.state()
        self.assertEqual(memory["entities"], symbolic["entities"])
        self.assertEqual(memory["relations"], symbolic["relations"])
        self.assertEqual(memory["findings"], [])
        self.assertEqual(len(symbolic["findings"]), 1)

    def test_restart_and_paging(self):
        self.ontology.update([self.entity()])
        restarted = EvidenceOntology(LocalRuntime(self.root / "session"), "symbolic")
        self.assertEqual(restarted.state(), self.ontology.state())
        first, second = restarted.state(limit=1), restarted.state(offset=1, limit=1)
        self.assertEqual(first["next_offset"], 1)
        self.assertNotEqual(first["entities"], second["entities"])
        self.ontology.update([self.entity("new")])
        snapshot = restarted.state(as_of_sequence=first["high_water_sequence"], offset=1, limit=1)
        self.assertEqual(snapshot, second)
        with self.assertRaises(ValueError):
            restarted.state(limit=True)

    def test_model_tool_update_and_assessment(self):
        result = self.tools.dispatch("reasoning_update", json.dumps({"entities": [self.entity("c", "check")]}), "update")
        self.assertEqual(result.status, "success", result.content)
        assessment = self.tools.dispatch("assess_check", {"id": "c"}, "assess")
        self.assertEqual(assessment.status, "success", assessment.content)
        self.assertTrue(json.loads(assessment.content)["advisory"])
        for name, args in (("assess_check", {}), ("reasoning_state", {"extra": True}),
                           ("reasoning_update", {"entities": "bad"})):
            with self.subTest(name=name):
                self.assertEqual(self.tools.dispatch(name, args, "bad").status, "rejected")

    def test_finish_stays_advisory(self):
        self.ontology.update([self.entity()],
                             [{"source": self.observation["id"], "relation": "contradicts", "target": "h"}])
        result = self.tools.dispatch("finish", {"summary": "done"}, "finish")
        self.assertTrue(result.finished)

    def test_controller_recovers_reasoning_through_model_tool_protocol(self):
        from reticle.runtime.contracts import TaskEnvelope
        from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
        from reticle.context import PressureRecentContextPolicyV3
        self.ontology.update([self.entity()])
        runtime = LocalRuntime(self.root / "session")
        tools = Suite(runtime, interpreter=sys.executable, reasoning=EvidenceOntology(runtime, "symbolic"))

        class Client:
            def __init__(self):
                self.requests = []

            def complete(self, messages, tools):
                self.requests.append(messages)
                name = "reasoning_state" if len(self.requests) == 1 else "finish"
                args = {} if name == "reasoning_state" else {"summary": "Recovered hypothesis"}
                return ModelResponse({"role": "assistant", "content": None, "tool_calls": [
                    {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})

        client = Client()
        result = AgentController(runtime, TaskEnvelope("reasoning-fixture", "Recover the earlier hypothesis"),
                                 tools, client, AgentLimits(3, 100_000), policy=PressureRecentContextPolicyV3()).run()
        self.assertEqual(result.stop_reason, "finish_requested")
        response = next(message for message in client.requests[1] if message.get("tool_call_id") == "reasoning_state")
        payload = response["content"].split("\n", 1)[1]  # pressure policy prefixes the result status
        self.assertTrue(any(entity["id"] == "h" for entity in json.loads(payload)["entities"]))

    def test_opt_in_hash_and_schema_composition(self):
        off = run_pilot.treatments_from_args([])
        self.assertEqual(off, {})
        self.assertEqual(run_pilot.model_tool_schemas(off), TOOL_SCHEMAS)
        hashes = {run_pilot.protocol_hash("pressure-recent-v3", {}, {}, {}, treatments=off)}
        for mode in ("memory", "symbolic"):
            treatment = run_pilot.treatments_from_args(["--reasoning", mode])
            hashes.add(run_pilot.protocol_hash("pressure-recent-v3", {}, {}, {}, treatments=treatment))
            tools, state = run_pilot.build_tools(self.runtime, treatment, ToolSuite, interpreter=sys.executable)
            self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(treatment))
            self.assertEqual(state["reasoning"].mode, mode)
        self.assertEqual(len(hashes), 3)
        combined = run_pilot.treatments_from_args(["--reasoning", "symbolic", "--completion", "finish-guard"])
        tools, state = run_pilot.build_tools(self.runtime, combined, run_pilot.RepeatGuardTools, interpreter=sys.executable)
        self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(combined))
        self.assertEqual(set(state), {"reasoning", "completion"})

    def test_four_executable_fixtures_in_both_modes(self):
        for name in ("stale_evidence", "misleading_reproduction", "competing_diagnoses", "interrupted_investigation"):
            for mode in ("memory", "symbolic"):
                with self.subTest(name=name, mode=mode):
                    result = exercise(name, mode, self.root / f"{name}-{mode}")
                    self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
