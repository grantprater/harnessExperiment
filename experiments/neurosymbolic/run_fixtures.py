"""No-model mechanism checks for the evidence ontology. Run from the repository root.

python experiments/neurosymbolic/run_fixtures.py [--output REPORT.json]
These are engineered controls, not evidence of improved agent repair performance.
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.runtime.session import LocalRuntime
from reticle.runtime.reasoning import EvidenceOntology, INFERENCE_MODES, INJECTION_HEADER, MODES
from reticle.tools.primitives import ToolSuite
from reticle.tools.reasoning import ReasoningTools


class FixtureTools(ReasoningTools, ToolSuite):
    pass


def exercise(name, mode, root):
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    # The defect affects zero only; a negative-only check provides misleading reassurance.
    (workspace / "mod.py").write_text("def sign(x):\n    return -1 if x <= 0 else 1\n", encoding="utf-8")
    runtime = LocalRuntime(root / "session", workspace)
    ontology = EvidenceOntology(runtime, mode)
    tools = FixtureTools(runtime, interpreter=sys.executable, reasoning=ontology)
    sequence = 0

    def call(tool, **args):
        nonlocal sequence
        sequence += 1
        result = tools.dispatch(tool, args, f"fixture-{sequence}")
        if result.status != "success":
            raise AssertionError(f"{tool}: {result.content}")
        return result

    call("run", command='python -c "from mod import sign; assert sign(-1) == -1"')
    observation = next(entity for entity in ontology.state()["entities"] if entity["tool"] == "run")
    evidence = observation["evidence"]

    def entity(key, kind, text, **fields):
        return {"id": key, "kind": kind, "text": text, "evidence": evidence, **fields}

    check = entity("check-negative", "check", "Negative input returns negative", cases=["negative"],
                   observation=observation["id"])
    expected = []
    delivered = None  # injected mode: (action result, finding rule the appended advisory block must show)
    if name == "stale_evidence":
        call("reasoning_update", entities=[check])
        edit = call("replace_text", path="mod.py", old_text="x <= 0", new_text="x < 0")
        expected = ["stale_observation"]
        delivered = (edit, "stale_observation")
    elif name == "misleading_reproduction":
        requirement = entity("requirement", "requirement", "Zero and positives return positive; negatives negative",
                             cases=["negative", "zero", "positive"])
        call("reasoning_update", entities=[requirement, check], relations=[
            {"source": check["id"], "relation": "addresses", "target": "requirement"}])
        # Establish the false reassurance with an actual command on the missing edge case.
        failing = tools.dispatch("run", {"command": 'python -c "from mod import sign; assert sign(0) == 1"'}, "zero")
        if failing.status != "error":
            raise AssertionError("the omitted zero case should fail")
        expected = ["narrow_coverage"]
        delivered = (failing, "narrow_coverage")
    elif name == "competing_diagnoses":
        hypotheses = [entity("boundary", "hypothesis", "Zero boundary is wrong"),
                      entity("always-negative", "hypothesis", "All inputs return negative")]
        check["predictions"] = {"boundary": "passes", "always-negative": "passes"}
        call("reasoning_update", entities=[*hypotheses, check])
        expected = ["non_discriminating_check"]
    elif name == "interrupted_investigation":
        hypothesis = entity("boundary", "hypothesis", "Zero boundary is wrong")
        check["predictions"] = {"boundary": "passes"}
        call("reasoning_update", entities=[hypothesis, check], relations=[
            {"source": check["id"], "relation": "tests", "target": "boundary"}])
        before = ontology.state()
        # Fresh runtime and tools; no transcript or process-local reasoning objects retained.
        runtime = LocalRuntime(root / "session")
        ontology = EvidenceOntology(runtime, mode)
        tools = FixtureTools(runtime, interpreter=sys.executable, reasoning=ontology)
        if ontology.state() != before:
            raise AssertionError("reasoning state changed across restart")
        recovered = json.loads(call("reasoning_state").content)
        if not any(item["id"] == "boundary" for item in recovered["entities"]):
            raise AssertionError("carried hypothesis not recovered")
    else:
        raise ValueError(name)
    state = ontology.state()
    actual = sorted(set(item["rule"] for item in state["findings"]))
    if actual != (expected if mode in INFERENCE_MODES else []):
        raise AssertionError(f"{name}/{mode}: expected {expected}, got {actual}")
    record = ontology.record()
    injected_rules = []
    if mode == "injected":
        if record["injections"] < 1:
            raise AssertionError(f"{name}/{mode}: no advisory block was injected")
        if delivered is not None:
            result, rule = delivered
            block = result.content.split(INJECTION_HEADER, 1)
            if len(block) != 2 or f"\n- {rule} [" not in block[1]:
                raise AssertionError(f"{name}/{mode}: {rule} was not delivered in the action result")
            injected_rules = [rule]
        # Injected text is shown to the model only; recorded observations (citable evidence) never contain it.
        if any(INJECTION_HEADER in item["text"] for item in state["entities"] if item["kind"] == "observation"):
            raise AssertionError(f"{name}/{mode}: injected text leaked into a citable observation")
    elif delivered is not None and INJECTION_HEADER in delivered[0].content:
        raise AssertionError(f"{name}/{mode}: advisory block injected outside injected mode")
    return {"fixture": name, "mode": mode, "passed": True, "rules": actual,
            "delivered_in_action_result": injected_rules, "state": record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        for name in ("stale_evidence", "misleading_reproduction", "competing_diagnoses", "interrupted_investigation"):
            for mode in MODES:
                results.append(exercise(name, mode, Path(temporary) / f"{name}-{mode}"))
    report = {"model_calls": 0, "interpretation": "mechanism controls only", "results": results}
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
