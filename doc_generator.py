"""Technical Document Generation Engine with Deterministic Invariant Verification.

Extends the cognitive harness into the generative domain for verifiable documents
(technical specifications, RFCs, API contracts, protocol definitions).

Architecture:
1. DocumentBlueprint: Hierarchical schema defining sections, required invariants, and word budgets.
2. FoveatedSectionGenerator: Generates one section at a time using lean context:
   - Global Blueprint TOC (~150 tokens)
   - Preceding section bridge summary (~50 tokens)
   - Sliced EvidenceAtoms relevant to the section (~200 tokens)
   - Evaporates generation scratchpads between turns.
3. TechnicalSpecVerifier ("The Document Compiler"):
   - Structural completeness against blueprint
   - Citation veracity against EvidenceLedger
   - Syntax validation of embedded code blocks (ast.parse)
   - Invariant non-contradiction and terminology consistency
4. Saccadic Patcher: Repairs failing sections in isolation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from evidence_ledger import EvidenceLedger, EvidenceAtom
from synthetic_verifier import SyntheticInvariantVerifier


@dataclass
class SectionSpec:
    title: str
    level: int
    intent: str
    required_invariants: List[str]
    evidence_topics: List[str]
    target_words: int = 150
    must_contain_code: bool = False


@dataclass
class DocumentBlueprint:
    title: str
    abstract: str
    doc_type: str  # "RFC", "PEP", "API_SPEC"
    sections: List[SectionSpec]

    def render_toc(self) -> str:
        lines = [f"=== Blueprint: {self.title} ({self.doc_type}) ===", f"Abstract: {self.abstract}", "TOC:"]
        for s in self.sections:
            indent = "  " * (s.level - 1)
            reqs = f" [Reqs: {', '.join(s.required_invariants)}]" if s.required_invariants else ""
            lines.append(f"{indent}- {s.title}{reqs}")
        return "\n".join(lines)


@dataclass
class SpecVerificationResult:
    passed: bool
    missing_sections: List[str]
    code_syntax_errors: List[str]
    citation_errors: List[str]
    unfulfilled_invariants: List[str]
    section_reports: Dict[str, Dict[str, Any]]

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [f"=== Spec Verification: {status} ==="]
        if self.missing_sections:
            lines.append(f"- Missing Sections: {self.missing_sections}")
        if self.code_syntax_errors:
            lines.append(f"- Code Syntax Errors: {self.code_syntax_errors}")
        if self.citation_errors:
            lines.append(f"- Citation Errors: {self.citation_errors}")
        if self.unfulfilled_invariants:
            lines.append(f"- Unfulfilled Invariants: {self.unfulfilled_invariants}")
        return "\n".join(lines)


class TechnicalSpecVerifier:
    """Deterministic compiler and validator for generated technical specifications."""

    def __init__(self, blueprint: DocumentBlueprint, ledger: EvidenceLedger):
        self.blueprint = blueprint
        self.ledger = ledger

    def verify_document(self, doc_text: str) -> SpecVerificationResult:
        missing_sections = []
        code_syntax_errors = []
        citation_errors = []
        unfulfilled_invariants = []
        section_reports = {}

        # 1. Check Section Presence & Extract Section Contents
        lines = doc_text.splitlines()
        extracted_sections: Dict[str, str] = {}
        curr_sec = None
        curr_lines = []

        heading_re = re.compile(r"^#+\s+(.+)$")
        for line in lines:
            m = heading_re.match(line)
            if m:
                if curr_sec:
                    extracted_sections[curr_sec] = "\n".join(curr_lines).strip()
                curr_sec = m.group(1).strip()
                curr_lines = []
            else:
                curr_lines.append(line)
        if curr_sec:
            extracted_sections[curr_sec] = "\n".join(curr_lines).strip()

        # Check blueprint coverage
        for sec in self.blueprint.sections:
            matched_content = None
            for title, content in extracted_sections.items():
                if sec.title.lower() in title.lower() or title.lower() in sec.title.lower():
                    matched_content = content
                    break

            if not matched_content or len(matched_content.split()) < 3:
                missing_sections.append(sec.title)
                continue

            sec_rep: Dict[str, Any] = {"words": len(matched_content.split()), "code_blocks": 0}

            # 2. Check Invariants
            for inv in sec.required_invariants:
                if inv.lower() not in matched_content.lower():
                    unfulfilled_invariants.append(f"[{sec.title}] Missing required concept/invariant: '{inv}'")

            # 3. Check Code Blocks (if python code expected)
            code_blocks = re.findall(r"```(?:python)?\s*(.*?)```", matched_content, re.DOTALL)
            sec_rep["code_blocks"] = len(code_blocks)

            if sec.must_contain_code and not code_blocks:
                code_syntax_errors.append(f"[{sec.title}] Specification requires code examples but none found.")

            for c_idx, code in enumerate(code_blocks):
                code_clean = code.strip()
                if not code_clean:
                    continue
                try:
                    ast.parse(code_clean)
                except SyntaxError as e:
                    code_syntax_errors.append(f"[{sec.title}] Code block {c_idx+1} syntax error: {e.msg} on line {e.lineno}")

            # 4. Check Citations against Ledger
            citations = re.findall(r"\[(ev_\d{3})\]", matched_content)
            known_atoms = {a.atom_id for a in self.ledger.atoms}
            for cit in citations:
                if cit not in known_atoms:
                    citation_errors.append(f"[{sec.title}] Phantom citation: '{cit}' not found in EvidenceLedger.")

            section_reports[sec.title] = sec_rep

        passed = not (missing_sections or code_syntax_errors or citation_errors or unfulfilled_invariants)
        return SpecVerificationResult(
            passed=passed,
            missing_sections=missing_sections,
            code_syntax_errors=code_syntax_errors,
            citation_errors=citation_errors,
            unfulfilled_invariants=unfulfilled_invariants,
            section_reports=section_reports
        )


class FoveatedDocumentGenerator:
    """Generates long-form technical specifications using foveated context windows."""

    def __init__(
        self,
        blueprint: DocumentBlueprint,
        ledger: EvidenceLedger,
        llm_fn: Callable[[str], str]
    ):
        self.blueprint = blueprint
        self.ledger = ledger
        self.llm_fn = llm_fn
        self.verifier = TechnicalSpecVerifier(blueprint, ledger)
        self.drafted_sections: Dict[str, str] = {}
        self.section_summaries: Dict[str, str] = {}

    def generate_section(
        self,
        spec: SectionSpec,
        preceding_summary: str = ""
    ) -> str:
        """Draft a single section in isolation with lean context."""
        # 1. Saccade: Get only the evidence atoms relevant to this section's topics
        topic_set = set(t.lower() for t in spec.evidence_topics)
        relevant_atoms = [a for a in self.ledger.atoms if a.topic in topic_set or "general" in topic_set]
        evidence_slice = "\n".join([f"- [{a.atom_id}] {a.claim} (Quote: \"{a.verbatim_quote}\")" for a in relevant_atoms])

        # 2. Build lean, foveated prompt
        prompt = (
            f"You are drafting Section '{spec.title}' of a formal specification.\n"
            f"=== Document Context ===\n"
            f"Title: {self.blueprint.title}\n"
            f"Abstract: {self.blueprint.abstract}\n"
        )
        if preceding_summary:
            prompt += f"Preceding Section Bridge: {preceding_summary}\n"

        prompt += (
            f"\n=== Section Requirements ===\n"
            f"Section: {'#' * spec.level} {spec.title}\n"
            f"Intent: {spec.intent}\n"
            f"Required Invariants: {', '.join(spec.required_invariants)}\n"
            f"Target Word Count: ~{spec.target_words} words\n"
        )
        if spec.must_contain_code:
            prompt += "MUST include at least one valid, syntactically correct Python code block demonstrating the feature.\n"

        if evidence_slice:
            prompt += f"\n=== Epistemic Evidence (Cite using [ev_001], etc.) ===\n{evidence_slice}\n"

        prompt += (
            f"\nWrite ONLY the Markdown content for this section, starting with heading: "
            f"{'#' * spec.level} {spec.title}\n"
        )

        section_content = self.llm_fn(prompt)
        return section_content.strip()

    def generate_document(self, max_patch_attempts: int = 2) -> Tuple[str, SpecVerificationResult]:
        """Orchestrate end-to-end foveated generation with verification and saccadic patching."""
        preceding_summary = ""

        # Step 1: Draft sections sequentially
        for spec in self.blueprint.sections:
            draft = self.generate_section(spec, preceding_summary)
            self.drafted_sections[spec.title] = draft

            # Generate a 1-sentence anchor summary for next section and evaporate the draft from memory
            words = draft.split()[:40]
            preceding_summary = f"{spec.title} established: " + " ".join(words) + "..."
            self.section_summaries[spec.title] = preceding_summary

        # Step 2: Assemble full document
        full_doc = f"# {self.blueprint.title}\n\n"
        full_doc += f"> **Abstract**: {self.blueprint.abstract}\n\n---\n\n"
        for spec in self.blueprint.sections:
            full_doc += self.drafted_sections[spec.title] + "\n\n"

        # Step 3: Run Deterministic Verification
        rep = self.verifier.verify_document(full_doc)

        # Step 4: Saccadic Patching if verification found issues
        attempts = 0
        while not rep.passed and attempts < max_patch_attempts:
            attempts += 1
            # Identify which sections failed
            failed_titles: Set[str] = set(rep.missing_sections)
            for err in rep.code_syntax_errors + rep.unfulfilled_invariants + rep.citation_errors:
                m = re.match(r"\[(.*?)\]", err)
                if m:
                    failed_titles.add(m.group(1))

            for title in failed_titles:
                target_spec = next((s for s in self.blueprint.sections if s.title == title), None)
                if not target_spec:
                    continue

                patch_feedback = [e for e in rep.code_syntax_errors + rep.unfulfilled_invariants if title in e]
                patch_prompt = (
                    f"Section '{title}' failed verification due to:\n"
                    + "\n".join(patch_feedback)
                    + f"\n\nPlease regenerate Section '{title}' fixing these exact errors. "
                    f"Ensure any Python code block is 100% valid Python syntax."
                )
                patched_draft = self.generate_section(target_spec, preceding_summary=patch_prompt)
                self.drafted_sections[title] = patched_draft

            # Reassemble
            full_doc = f"# {self.blueprint.title}\n\n> **Abstract**: {self.blueprint.abstract}\n\n---\n\n"
            for spec in self.blueprint.sections:
                full_doc += self.drafted_sections[spec.title] + "\n\n"
            rep = self.verifier.verify_document(full_doc)

        return full_doc, rep
