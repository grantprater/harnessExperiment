"""Rebuildable evidence ontology over authorized session history.

Tool observations are runtime facts. All semantic links, scopes and predictions are
model assertions. Rules report consequences conditional on those assertions; they
never promote a passing command to task acceptance. No model calls are made here.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List

from reticle.runtime.queries import SessionQueryService, _index_calls


REASONING_VERSION = "evidence-ontology-v2"
MAX_ENTITIES = 200
MAX_BATCH = 20
KINDS = ("requirement", "hypothesis", "check", "change", "code_entity", "procedure")
RELATIONS = {
    "supports": ({"observation"}, {"hypothesis"}),
    "contradicts": ({"observation"}, {"hypothesis"}),
    "tests": ({"check"}, {"hypothesis"}),
    "depends_on": ({"check", "hypothesis", "requirement", "change", "procedure"},
                   {"code_entity", "hypothesis", "check", "procedure"}),
    "addresses": ({"change", "check"}, {"requirement"}),
    "supersedes": (set(KINDS), set(KINDS)),
}
SHAPES = '''
@prefix e: <urn:reticle:evidence:> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
e:EntityShape a sh:NodeShape ; sh:targetClass e:Entity ;
  sh:property [ sh:path e:kind ; sh:minCount 1 ; sh:maxCount 1 ;
    sh:in ("requirement" "hypothesis" "check" "change" "code_entity" "procedure" "observation") ] ;
  sh:property [ sh:path e:text ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path e:origin ; sh:minCount 1 ; sh:maxCount 1 ;
    sh:in ("model_assertion" "runtime_observation" "runtime_contract") ] ;
  sh:property [ sh:path e:evidence ; sh:minCount 1 ; sh:nodeKind sh:IRI ] .
'''


def reasoning_contract(mode: str) -> Dict[str, Any]:
    if mode not in {"memory", "symbolic"}:
        raise ValueError("reasoning mode must be memory or symbolic")
    from importlib.metadata import PackageNotFoundError, version
    try:
        dependencies = {name: version(name) for name in ("rdflib", "pyshacl")}
    except PackageNotFoundError as exc:
        raise RuntimeError("Install the optional reticle[reasoning] dependencies to enable --reasoning") from exc
    return {"name": "evidence-ontology", "version": REASONING_VERSION, "mode": mode,
            "schema_hash": hashlib.sha256(SHAPES.encode()).hexdigest(),
            "source_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "dependencies": dependencies,
            "max_entities": MAX_ENTITIES, "max_batch": MAX_BATCH,
            "rules": ["stale_observation", "narrow_coverage", "non_discriminating_check", "contradicted_hypothesis"],
            "advisory": True, "extraction": "explicit model tool calls"}


def _string(value: Any, name: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def _strings(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f"{name} must be an array of at most 100 strings")
    return list(dict.fromkeys(_string(item, name, 200) for item in value))


class EvidenceOntology:
    def __init__(self, runtime, mode: str):
        self.runtime = runtime
        self.contract = reasoning_contract(mode)
        self.mode = mode

    def _projection(self, as_of_sequence=None):
        events = self.runtime.journal.read_all()
        if as_of_sequence is not None:
            events = [event for event in events if event.sequence <= as_of_sequence]
        entities, relations = {}, []
        for event in events:
            if event.kind == "task_contract":
                description = event.payload.get("task", {}).get("description")
                if isinstance(description, str):
                    entity_id = "task:" + event.event_id
                    entities[entity_id] = {"id": entity_id, "kind": "requirement", "origin": "runtime_contract",
                                           "text": description[:2000], "evidence": [event.event_id],
                                           "text_truncated": len(description) > 2000}
                # Description is already model-visible. Never project hidden criteria or authority internals.
            if event.kind != "reasoning_update":
                continue
            if event.payload.get("version") not in {"evidence-ontology-v1", REASONING_VERSION}:
                raise ValueError("Unsupported reasoning event version")
            for entity in event.payload["entities"]:
                entities[entity["id"]] = {**entity, "assertion_event_id": event.event_id}
            relations.extend(event.payload["relations"])

        # Use the same authorization/redaction projection as the history tools.
        queries = SessionQueryService(self.runtime)
        records = queries._visible_records(events, events, kinds=["tool_output"])
        calls = _index_calls(events)
        output_calls = {value.event_id: key for key, value in calls.outputs.items()}
        outcomes = {}
        for event in events:
            if event.kind == "action_outcome":
                result = event.payload.get("result", {})
                if isinstance(result.get("call_id"), str):
                    outcomes[result["call_id"]] = result
        for record in records:
            if record["source"] in {"reasoning_update", "reasoning_state", "assess_check"}:
                continue
            call_id = output_calls.get(record["event_id"])
            result = outcomes.get(call_id, {})
            entity_id = "obs:" + record["event_id"]
            entities[entity_id] = {
                "id": entity_id, "kind": "observation", "origin": "runtime_observation",
                "text": record["text"][:2000], "evidence": [record["event_id"]],
                "tool": record["source"], "call_id": call_id, "status": record["status"],
                "exit_code": result.get("exit_code"),
                "revision_before": result.get("workspace_revision_before"),
                "revision_after": result.get("workspace_revision_after"),
                "output_handle": record.get("output_handle"),
                "text_truncated": len(record["text"]) > 2000,
            }
        return entities, relations, events

    @staticmethod
    def _rdf(entities, relations=()):
        from rdflib import Graph, Literal, Namespace, RDF, URIRef
        graph, ns = Graph(), Namespace("urn:reticle:evidence:")
        for entity in entities.values():
            subject = URIRef("urn:reticle:entity:" + entity["id"])
            graph.add((subject, RDF.type, ns.Entity))
            for key in ("kind", "text", "origin"):
                graph.add((subject, ns[key], Literal(entity[key])))
            for event_id in entity["evidence"]:
                graph.add((subject, ns.evidence, URIRef("urn:reticle:event:" + event_id)))
            for key in ("cases",):
                for value in entity.get(key, []):
                    graph.add((subject, ns[key], Literal(value)))
            if entity.get("observation"):
                graph.add((subject, ns.observation, URIRef("urn:reticle:entity:" + entity["observation"])))
        for link in relations:
            graph.add((URIRef("urn:reticle:entity:" + link["source"]), ns[link["relation"]],
                       URIRef("urn:reticle:entity:" + link["target"])))
        return graph

    @classmethod
    def validate_graph(cls, entities, relations=()):
        from pyshacl import validate
        conforms, _, report = validate(cls._rdf(entities, relations), shacl_graph=SHAPES,
                                       shacl_graph_format="turtle", inference="none")
        if not conforms:
            raise ValueError("Evidence graph does not conform to SHACL: " + report)

    def update(self, entities=None, relations=None):
        entities = [] if entities is None else entities
        relations = [] if relations is None else relations
        if not isinstance(entities, list) or not isinstance(relations, list):
            raise ValueError("entities and relations must be arrays")
        if not entities and not relations:
            raise ValueError("provide at least one entity or relation")
        if len(entities) + len(relations) > MAX_BATCH:
            raise ValueError(f"at most {MAX_BATCH} records per update")
        current, links, events = self._projection()
        # Only authorized tool evidence and task descriptions may be cited.
        visible = {ref for entity in current.values() if entity["origin"] in {"runtime_observation", "runtime_contract"}
                   for ref in entity["evidence"]}
        prepared = []
        allowed = {"id", "kind", "text", "evidence", "cases", "predictions", "observation", "path", "conditions"}
        for raw in entities:
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise ValueError("entity contains unsupported fields")
            entity = deepcopy(raw)
            entity_id = _string(entity.get("id"), "id", 100)
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", entity_id):
                raise ValueError("IDs may contain only letters, digits, underscores, dots, colons and hyphens")
            if entity_id.startswith(("obs:", "task:")) or entity_id in current:
                raise ValueError("entity IDs are immutable; use a new ID and supersedes")
            if entity.get("kind") not in KINDS:
                raise ValueError(f"kind must be one of {KINDS}; observations are recorded by the runtime")
            _string(entity.get("text"), "text")
            evidence = _strings(entity.get("evidence"), "evidence")
            if not evidence or not set(evidence).issubset(visible):
                raise ValueError("evidence must cite existing authorized tool-output or task-description event IDs")
            entity["evidence"] = evidence
            entity["origin"] = "model_assertion"
            if "conditions" in entity:
                entity["conditions"] = _strings(entity["conditions"], "conditions")
            if "cases" in entity:
                if entity["kind"] not in {"check", "requirement"}:
                    raise ValueError("cases only apply to checks and requirements")
                entity["cases"] = _strings(entity["cases"], "cases")
            if "path" in entity:
                if entity["kind"] != "code_entity":
                    raise ValueError("path only applies to code entities")
                path = _string(entity["path"], "path", 200)
                resolved = self.runtime.workspace._resolve(path)
                if not resolved.is_file():
                    raise ValueError("code entity path must name an existing file")
                entity["content_hash"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
                entity["fingerprint_origin"] = "runtime_at_assertion"
            if "observation" in entity:
                observation = current.get(entity["observation"], {})
                if entity["kind"] != "check" or observation.get("kind") != "observation" or observation.get("tool") != "run":
                    raise ValueError("check observation must reference a runtime run observation")
                if not set(observation["evidence"]).issubset(evidence):
                    raise ValueError("check evidence must include its run observation's source event")
            if "predictions" in entity:
                predictions = entity["predictions"]
                if entity["kind"] != "check" or not isinstance(predictions, dict) or len(predictions) > 20:
                    raise ValueError("predictions must map at most 20 hypothesis IDs to expected outcomes")
                for key, value in predictions.items():
                    _string(key, "hypothesis ID", 100)
                    _string(value, "prediction", 200)
            current[entity_id] = entity
            prepared.append(entity)
        if sum(entity["origin"] == "model_assertion" for entity in current.values()) > MAX_ENTITIES:
            raise ValueError(f"at most {MAX_ENTITIES} model entities per session")
        for entity in prepared:
            for hypothesis in entity.get("predictions", {}):
                if current.get(hypothesis, {}).get("kind") != "hypothesis":
                    raise ValueError("prediction references an unknown hypothesis")
        prepared_links = []
        for raw in relations:
            if not isinstance(raw, dict) or set(raw) != {"source", "relation", "target"}:
                raise ValueError("relations require exactly source, relation and target")
            source, relation, target = (raw[key] for key in ("source", "relation", "target"))
            for value in (source, relation, target):
                _string(value, "relation field", 200)
            if relation not in RELATIONS or source not in current or target not in current:
                raise ValueError("unknown relation or endpoint")
            kinds = (current[source]["kind"], current[target]["kind"])
            permitted = RELATIONS[relation]
            if kinds[0] not in permitted[0] or kinds[1] not in permitted[1] or source == target:
                raise ValueError("relation has invalid endpoint types")
            if relation == "supersedes" and kinds[0] != kinds[1]:
                raise ValueError("supersedes requires entities of the same kind")
            if relation == "supersedes" and current[target]["origin"] == "runtime_contract":
                raise ValueError("model assertions cannot supersede the authorized task contract")
            if raw not in links and raw not in prepared_links:
                prepared_links.append(deepcopy(raw))
        if len(links) + len(prepared_links) > 500:
            raise ValueError("at most 500 relations per session")
        successors = {}
        for link in [*links, *prepared_links]:
            if link["relation"] == "supersedes":
                successors.setdefault(link["source"], []).append(link["target"])
        visited = set()
        def visit(key, ancestors):
            if key in ancestors:
                raise ValueError("supersedes must not form a cycle")
            if key in visited:
                return
            for target in successors.get(key, []):
                visit(target, ancestors | {key})
            visited.add(key)
        for key in successors:
            visit(key, set())
        self.validate_graph(current, [*links, *prepared_links])
        event = self.runtime.journal.append("reasoning_update", {
            "version": REASONING_VERSION, "entities": prepared, "relations": prepared_links})
        return {"event_id": event.event_id, "entities_added": len(prepared), "relations_added": len(prepared_links)}

    def _findings(self, entities, relations):
        findings = []
        superseded = {link["target"] for link in relations if link["relation"] == "supersedes"}
        active = {key: value for key, value in entities.items() if key not in superseded}
        revision = self.runtime.workspace.revision()

        def add(rule, ids, message):
            findings.append({"rule": rule, "entities": ids, "message": message,
                             "origin": "rule_derived", "conditional_on_model_assertions": True,
                             "evidence": sorted({ref for key in ids for ref in entities[key]["evidence"]})})

        for check in active.values():
            if check["kind"] != "check":
                continue
            observation = active.get(check.get("observation"), {})
            if (observation.get("status") == "success" and observation.get("exit_code") == 0
                    and observation.get("revision_after") and observation["revision_after"] != revision):
                add("stale_observation", [check["id"], observation["id"]],
                    "The successful command was recorded on a different workspace revision; rerun before relying on it.")
            predictions = {key: value for key, value in check.get("predictions", {}).items() if key in active}
            ids = sorted(predictions)
            for i, left in enumerate(ids):
                for right in ids[i + 1:]:
                    if predictions[left] == predictions[right]:
                        add("non_discriminating_check", [check["id"], left, right],
                            "These hypotheses predict the same outcome; this check cannot distinguish them.")
        for link in relations:
            if link["source"] not in active or link["target"] not in active:
                continue
            source, target = active[link["source"]], active[link["target"]]
            if link["relation"] == "addresses" and source["kind"] == "check":
                required, covered = set(target.get("cases", [])), set(source.get("cases", []))
                if required and required - covered:
                    add("narrow_coverage", [source["id"], target["id"]],
                        "Declared requirement cases remain untested: " + ", ".join(sorted(required - covered)))
            if link["relation"] == "contradicts":
                add("contradicted_hypothesis", [source["id"], target["id"]],
                    "An observation is asserted to contradict this hypothesis; reassess it before proceeding.")
        return findings

    def state(self, *, offset=0, limit=50, focus=None, as_of_sequence=None):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative; limit must be between 1 and 100")
        if as_of_sequence is not None and (type(as_of_sequence) is not int or as_of_sequence < 0):
            raise ValueError("as_of_sequence must be a nonnegative integer")
        entities, relations, events = self._projection(as_of_sequence)
        if focus is not None and focus not in entities:
            raise ValueError("unknown focus entity")
        findings = self._findings(entities, relations) if self.mode == "symbolic" else []
        selected = entities
        if focus is not None:
            ids = {focus}
            for link in relations:
                if focus in (link["source"], link["target"]):
                    ids.update((link["source"], link["target"]))
            selected = {focus: entities[focus], **{key: entities[key] for key in entities if key in ids and key != focus}}
            findings = [item for item in findings if focus in item["entities"]]
        values = list(selected.values())
        page = values[offset:offset + limit]
        selected_links = [link for link in relations if link["source"] in selected and link["target"] in selected]
        return {"version": REASONING_VERSION, "mode": self.mode, "advisory": True,
                "high_water_sequence": events[-1].sequence if events else 0,
                "entities": page, "total_entities": len(values),
                "relations": selected_links[offset:offset + limit], "total_relations": len(selected_links),
                "findings": findings[offset:offset + limit], "total_findings": len(findings),
                "next_offset": offset + limit if offset + limit < max(len(values), len(selected_links), len(findings)) else None,
                "unknown": "Missing evidence is unknown; command success is not acceptance."}

    def record(self):
        entities, relations, events = self._projection()
        return {"version": REASONING_VERSION, "mode": self.mode,
                "entities": len(entities), "relations": len(relations),
                "updates": sum(event.kind == "reasoning_update" for event in events),
                "findings": len(self._findings(entities, relations)) if self.mode == "symbolic" else 0}
