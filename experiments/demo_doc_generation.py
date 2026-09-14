"""End-to-End Demonstration: Technical Document Generation on Least Capable Model.

Demonstrates generating a multi-section formal architecture specification using:
- Model: gemini-3.6-flash-low (effort=low)
- Blueprint: 4 formal RFC-style sections
- Epistemic Evidence Ledger: Ingested architectural atoms
- Foveated generation with zero context bloat
- TechnicalSpecVerifier (AST Python parse + citation verification + invariant check)
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from doc_generator import (
    DocumentBlueprint,
    FoveatedDocumentGenerator,
    SectionSpec,
    TechnicalSpecVerifier,
)
from evidence_ledger import EvidenceLedger


def call_llm(prompt: str) -> str:
    cmd = [
        "agy",
        "--model", "gemini-3.6-flash-low",
        "--effort", "low",
        "--dangerously-skip-permissions",
        f"--print={prompt}"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    return (proc.stdout or "").strip()


def run_demo():
    print("=================================================================")
    print("DEMO: FORMAL TECHNICAL DOCUMENT GENERATION ON LEAST CAPABLE MODEL")
    print("Model: gemini-3.6-flash-low (effort=low)")
    print("=================================================================\n")

    # 1. Epistemic Evidence Ledger Setup
    ledger = EvidenceLedger()
    ledger.record_evidence(
        claim="Monolithic prompt accumulation causes severe attention dilution and quadratic token costs.",
        source_doc="ARCHITECTURE.md",
        section="Pillar I",
        verbatim_quote="Standard agent architectures accumulate full file contents into an append-only transcript.",
        topic="problem"
    )
    ledger.record_evidence(
        claim="EvidenceLedger stores discrete atomic facts and evaporates raw text from active context.",
        source_doc="ARCHITECTURE.md",
        section="Pillar III",
        verbatim_quote="If reality matches prediction, the interaction is wiped from the active context.",
        topic="architecture"
    )
    ledger.record_evidence(
        claim="The Synthetic Invariant Verifier validates code blocks via ast.parse and citations against the ledger.",
        source_doc="ARCHITECTURE.md",
        section="Pillar IV",
        verbatim_quote="Acts as the compiler for text synthesis and analysis.",
        topic="verification"
    )

    # 2. Define Document Blueprint
    blueprint = DocumentBlueprint(
        title="RFC-9020: Cognitive Harness Specification for Foveated Agentic Architecture",
        abstract="Specifies a deterministic multi-scale sensory harness that prevents context bloat in autonomous AI agents.",
        doc_type="RFC",
        sections=[
            SectionSpec(
                title="1. Introduction and Problem Statement",
                level=2,
                intent="Outline why standard monolithic context windows degrade agent performance.",
                required_invariants=["monolithic", "attention", "token"],
                evidence_topics=["problem"],
                target_words=100
            ),
            SectionSpec(
                title="2. Cognitive Scaffolding Architecture",
                level=2,
                intent="Detail the core pillars: Epistemic Evidence Ledger, Saccadic Perception, and Context Evaporation.",
                required_invariants=["EvidenceLedger", "Evaporation", "atoms"],
                evidence_topics=["architecture"],
                target_words=120
            ),
            SectionSpec(
                title="3. Formal Reference Implementation",
                level=2,
                intent="Provide valid Python code defining the core EvidenceLedger interface.",
                required_invariants=["class EvidenceLedger", "record_evidence"],
                evidence_topics=["architecture"],
                target_words=120,
                must_contain_code=True
            ),
            SectionSpec(
                title="4. Deterministic Verification and Invariant Enforcement",
                level=2,
                intent="Specify how generated documents and code are verified via ast.parse and citation grounding.",
                required_invariants=["ast.parse", "compiler", "verifier"],
                evidence_topics=["verification"],
                target_words=100
            )
        ]
    )

    # 3. Execute Foveated Document Generation
    generator = FoveatedDocumentGenerator(blueprint, ledger, call_llm)
    t0 = time.time()
    generated_doc, rep = generator.generate_document(max_patch_attempts=2)
    elapsed = time.time() - t0

    print(f"\nGeneration completed in {elapsed:.2f} seconds.")
    print(rep.summary())

    out_file = ROOT / "experiments" / "GENERATED_SPECIFICATION.md"
    out_file.write_text(generated_doc, encoding="utf-8")
    print(f"\n[SUCCESS] Generated Specification saved to: {out_file}")


if __name__ == "__main__":
    run_demo()
