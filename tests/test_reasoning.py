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
        for mode in ("memory", "symbolic", "injected"):
            treatment = run_pilot.treatments_from_args(["--reasoning", mode])
            hashes.add(run_pilot.protocol_hash("pressure-recent-v3", {}, {}, {}, treatments=treatment))
            tools, state = run_pilot.build_tools(self.runtime, treatment, ToolSuite, interpreter=sys.executable)
            self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(treatment))
            self.assertEqual(state["reasoning"].mode, mode)
        self.assertEqual(len(hashes), 4)
        combined = run_pilot.treatments_from_args(["--reasoning", "symbolic", "--completion", "finish-guard"])
        tools, state = run_pilot.build_tools(self.runtime, combined, run_pilot.RepeatGuardTools, interpreter=sys.executable)
        self.assertEqual(tools.schemas(), run_pilot.model_tool_schemas(combined))
        self.assertEqual(set(state), {"reasoning", "completion"})

    def test_four_executable_fixtures_in_all_modes(self):
        for name in ("stale_evidence", "misleading_reproduction", "competing_diagnoses", "interrupted_investigation"):
            for mode in ("memory", "symbolic", "injected"):
                with self.subTest(name=name, mode=mode):
                    result = exercise(name, mode, self.root / f"{name}-{mode}")
                    self.assertTrue(result["passed"])


@unittest.skipUnless(AVAILABLE, "install reticle[reasoning] for ontology tests")
class InjectedReasoningTests(unittest.TestCase):
    """The injected arm: a bounded advisory block appended to edit and run results, never at finish."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "mod.py").write_text("x = 1\n", encoding="utf-8")
        self.runtime = LocalRuntime(self.root / "session", workspace)
        self.ontology = EvidenceOntology(self.runtime, "injected")
        self.tools = Suite(self.runtime, interpreter=sys.executable, reasoning=self.ontology)
        self.tools.dispatch("read_file", {"path": "mod.py"}, "read")
        self.observation = self.ontology.state()["entities"][0]
        self.calls = 0

    def call(self, name, **args):
        self.calls += 1
        return self.tools.dispatch(name, args, f"call-{self.calls}")

    def edit(self, new):
        text = (self.runtime.workspace.root / "mod.py").read_text(encoding="utf-8")
        return self.call("write_file", path="mod.py", content=text + new)

    def hypothesis(self, entity_id):
        """A hypothesis and a model-declared contradiction link, which yields a contradicted_hypothesis finding."""
        entity = {"id": entity_id, "kind": "hypothesis", "text": "A testable assertion",
                  "evidence": self.observation["evidence"]}
        link = {"source": self.observation["id"], "relation": "contradicts", "target": entity_id}
        return entity, link

    def injections(self):
        return [event for event in self.runtime.journal.read_all() if event.kind == "reasoning_injection"]

    def test_injection_after_edit_and_after_run(self):
        from reticle.runtime.reasoning import INJECTION_HEADER
        edit = self.call("replace_text", path="mod.py", old_text="x = 1", new_text="x = 2")
        self.assertEqual(edit.status, "success")  # the action executed
        self.assertIn("x = 2", (self.runtime.workspace.root / "mod.py").read_text(encoding="utf-8"))
        raw, block = edit.content.split("\n\n" + INJECTION_HEADER, 1)
        self.assertIn("active hypotheses=0; active checks=0; findings=0", block)
        self.ontology.update(*[[item] for item in self.hypothesis("h")])
        run = self.call("run", command='python -c "print(1)"')
        self.assertEqual(run.status, "success", run.content)
        self.assertIn(INJECTION_HEADER, run.content)
        self.assertIn("- contradicted_hypothesis [" + self.observation["id"] + ", h]:", run.content)
        self.assertEqual([event.payload["tool"] for event in self.injections()], ["replace_text", "run"])
        record = self.ontology.record()
        self.assertEqual(record["injections"], 2)
        self.assertEqual(record["injected_chars"], sum(event.payload["chars"] for event in self.injections()))
        self.assertGreater(record["injected_tokens_estimate"], 0)

    def test_no_injection_at_finish_or_other_tools(self):
        from reticle.runtime.reasoning import INJECTION_HEADER
        self.ontology.update(*[[item] for item in self.hypothesis("h")])  # findings exist, so a hook would fire
        for name, args in (("read_file", {"path": "mod.py"}), ("reasoning_state", {}),
                           ("finish", {"summary": "done"})):
            with self.subTest(name=name):
                result = self.call(name, **args)
                self.assertNotIn(INJECTION_HEADER, result.content)
        self.assertTrue(result.finished)
        self.assertEqual(self.injections(), [])
        symbolic = Suite(self.runtime, interpreter=sys.executable, reasoning=EvidenceOntology(self.runtime, "symbolic"))
        self.assertNotIn(INJECTION_HEADER, symbolic.dispatch("write_file", {"path": "b.py", "content": "y = 1\n"},
                                                              "symbolic-edit").content)

    def test_cap_is_respected_and_truncation_is_marked(self):
        from reticle.runtime.reasoning import INJECTION_MAX_CHARS, INJECTION_MAX_LINE_CHARS
        for batch in range(2):
            pairs = [self.hypothesis(f"h{batch}-{index}-" + "x" * 80) for index in range(10)]
            self.ontology.update([pair[0] for pair in pairs], [pair[1] for pair in pairs])
        result = self.edit("y = 1\n")
        block = self.injections()[-1].payload["text"]
        self.assertTrue(result.content.endswith(block))
        self.assertLessEqual(len(block), INJECTION_MAX_CHARS)
        self.assertRegex(block, r"\[truncated: \d+ of 20 findings omitted; reasoning_state lists all\]$")
        self.assertTrue(all(len(line) <= INJECTION_MAX_LINE_CHARS for line in block.splitlines()))
        self.assertTrue(self.injections()[-1].payload["truncated"])
        summary = self.ontology.summary()
        self.assertEqual(EvidenceOntology.render_injection(summary), EvidenceOntology.render_injection(summary))
        text, shown = EvidenceOntology.render_injection(summary, max_chars=400)
        self.assertLessEqual(len(text), 400)
        self.assertEqual(self.ontology.record()["injections_truncated"], 1)

    def test_no_change_since_last_injection_injects_nothing(self):
        from reticle.runtime.reasoning import INJECTION_HEADER
        self.assertIn(INJECTION_HEADER, self.edit("a = 1\n").content)
        quiet = self.edit("b = 1\n")
        self.assertTrue(quiet.content)
        self.assertNotIn(INJECTION_HEADER, quiet.content)  # no findings, same state: nothing appended
        self.assertEqual(quiet.content, self.runtime.artifacts.read(next(
            event.payload["artifact_id"] for event in reversed(self.runtime.journal.read_all())
            if event.kind == "tool_output")).decode("utf-8"))
        self.ontology.update([{"id": "c", "kind": "check", "text": "A check", "evidence": self.observation["evidence"]}])
        self.assertIn("active checks=1", self.edit("c = 1\n").content)  # state changed
        self.ontology.update(*[[item] for item in self.hypothesis("h")])
        self.assertIn(INJECTION_HEADER, self.edit("d = 1\n").content)
        self.assertIn(INJECTION_HEADER, self.edit("e = 1\n").content)  # active findings repeat even if unchanged
        record = self.ontology.record()
        self.assertEqual((record["injections"], record["injections_skipped_no_change"]), (4, 1))

    def test_block_has_no_authority_wording(self):
        import re
        pairs = [self.hypothesis("h1"), self.hypothesis("h2")]
        check = {"id": "c", "kind": "check", "text": "A check", "evidence": self.observation["evidence"],
                 "predictions": {"h1": "passes", "h2": "passes"}}
        self.ontology.update([pairs[0][0], pairs[1][0], check], [pairs[0][1], pairs[1][1]])
        block = self.edit("y = 1\n").content
        self.assertIn("advisory", block)
        self.assertIn("non_discriminating_check", block)
        forbidden = r"\b(must|accept\w*|approv\w*|mandatory|instruct\w*|authori\w*|verified|required|complete)\b"
        self.assertIsNone(re.search(forbidden, block, re.IGNORECASE))
        payload = self.injections()[-1].payload
        self.assertFalse({"acceptance", "accepted", "authority", "instruction"} & set(payload))

    def test_injected_content_is_not_citable(self):
        from reticle.runtime.queries import MODEL_VISIBLE_KINDS
        from reticle.runtime.reasoning import INJECTION_HEADER
        self.edit("y = 1\n")
        injection = self.injections()[-1]
        self.assertNotIn("reasoning_injection", MODEL_VISIBLE_KINDS)  # controller-only, like evaluator events
        with self.assertRaises(ValueError):
            self.ontology.update([{"id": "h", "kind": "hypothesis", "text": "From the summary",
                                   "evidence": [injection.event_id]}])
        observations = [item for item in self.ontology.state()["entities"] if item["kind"] == "observation"]
        self.assertEqual(len(observations), 2)  # read_file and write_file tool outputs only
        self.assertFalse(any(INJECTION_HEADER in item["text"] for item in observations))

    def drive(self, policy, max_context_bytes, root):
        """Run the controller in injected mode: two ~25 KB failing-test runs, then finish. Returns the
        requests exactly as the model client received them."""
        from reticle.runtime.contracts import TaskEnvelope
        from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
        workspace = root / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "mod.py").write_text("x = 1\n", encoding="utf-8")
        runtime = LocalRuntime(root / "session", workspace)
        ontology = EvidenceOntology(runtime, "injected")
        tools = Suite(runtime, interpreter=sys.executable, reasoning=ontology)
        tools.dispatch("read_file", {"path": "mod.py"}, "read")
        observation = ontology.state()["entities"][0]
        ontology.update([{"id": "h", "kind": "hypothesis", "text": "t", "evidence": observation["evidence"]}],
                        [{"source": observation["id"], "relation": "contradicts", "target": "h"}])
        command = ('python -c "import sys; [print(\'FAILED tests/test_mod.py::test_case_%d - AssertionError: '
                   'expected 1\' % i) for i in range(350)]; sys.exit(1)"')
        script = [("run1", "run", {"command": command}), ("run2", "run", {"command": command}),
                  ("fin", "finish", {"summary": "done"})]

        class Client:
            def __init__(self):
                self.requests = []

            def complete(self, messages, tools):
                self.requests.append((messages, tools))
                call_id, name, args = script[len(self.requests) - 1]
                return ModelResponse({"role": "assistant", "content": None, "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})

        client = Client()
        AgentController(runtime, TaskEnvelope("t", "Fix the failing tests"), tools, client,
                        AgentLimits(5, max_context_bytes), policy=policy).run()
        raw = [runtime.artifacts.read(event.payload["artifact_id"]).decode("utf-8")
               for event in runtime.journal.read_all() if event.kind == "tool_output" and event.payload["tool"] == "run"]
        return client.requests, raw

    def test_newest_long_run_result_always_shows_the_whole_block(self):
        """A failing suite's long output is the typical last observation before finish. Whatever view the
        context policy renders, the newest result carries the whole labelled block; older reduced results
        drop it rather than show an unlabelled fragment."""
        from reticle.context import BaselineContextPolicy, PressureRecentContextPolicyV3
        from reticle.runtime.reasoning import INJECTION_HEADER

        def result(messages, call_id):
            return next((m["content"] for m in messages if m.get("tool_call_id") == call_id), None)

        def assert_whole_block(content, raw, label):
            self.assertIsNotNone(content, label)
            self.assertIn(INJECTION_HEADER, content, label)
            block = content.split(INJECTION_HEADER, 1)[1]
            self.assertIn("\n- contradicted_hypothesis [", block, label)
            self.assertTrue(block.rstrip().endswith("reassess it before proceeding."), label)
            note = re.search(r"of (\d+) \(", content)
            if note:  # a reduced view counts the recorded output's lines, as read_output pages them
                self.assertEqual(int(note.group(1)), len(raw.splitlines()), label)

        import re
        requests, raw = self.drive(BaselineContextPolicy(), 80_000, self.root / "baseline")
        self.assertTrue(all(INJECTION_HEADER not in text for text in raw))  # tool_output stays raw
        self.assertGreater(len(raw[0]), 20_000)
        for index, call_id in ((1, "run1"), (2, "run2")):
            content = result(requests[index][0], call_id)
            self.assertIn("[output out_", content)  # the view really was cut
            assert_whole_block(content, raw[0], f"baseline newest {call_id}")
        older = result(requests[2][0], "run1")
        self.assertNotIn("contradicted_hypothesis", older)  # dropped whole, not a fragment

        # pressure-recent-v3 (the pilot campaigns' arm), from ample context down to the tightest budgets
        base = len(json.dumps({"messages": requests[0][0], "tools": requests[0][1]}))
        reduced = 0
        for margin in (70_000, 3_000, 1_500, 1_000, 800, 600, 400):
            with self.subTest(margin=margin):
                requests, raw = self.drive(PressureRecentContextPolicyV3(), base + margin,
                                           self.root / f"pressure-{margin}")
                for index, call_id in ((1, "run1"), (2, "run2")):
                    if index < len(requests):  # otherwise the controller stopped over budget without a request
                        content = result(requests[index][0], call_id)
                        reduced += "[output out_" in content
                        assert_whole_block(content, raw[0], f"pressure +{margin} {call_id}")
        self.assertGreater(reduced, 4)

    def test_contract_records_mode_template_and_cap(self):
        from reticle.runtime.reasoning import INJECTION_MAX_CHARS, INJECTION_VERSION, reasoning_contract
        contract = reasoning_contract("injected")
        self.assertEqual(contract["mode"], "injected")
        self.assertEqual(contract["injection"]["template_version"], INJECTION_VERSION)
        self.assertEqual(contract["injection"]["max_chars"], INJECTION_MAX_CHARS)
        self.assertNotIn("injection", reasoning_contract("symbolic"))
        hashes = {mode: run_pilot.protocol_hash("pressure-recent-v3", {}, {}, {},
                                                treatments=run_pilot.treatments_from_args(["--reasoning", mode]))
                  for mode in ("symbolic", "injected")}
        self.assertNotEqual(hashes["symbolic"], hashes["injected"])
        with self.assertRaises(ValueError):
            reasoning_contract("notes")


if __name__ == "__main__":
    unittest.main()
