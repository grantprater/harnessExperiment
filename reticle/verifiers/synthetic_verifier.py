"""Synthetic Invariant Verifier for Unstructured and Technical Text Domains."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from reticle.core.evidence_ledger import EvidenceLedger, EvidenceAtom
from reticle.core.verifier_base import BaseVerifier, VerificationResult


@dataclass
class VerificationReport:
    passed: bool
    grounding_score: float  # 0.0 - 1.0
    citations_verified: int
    citations_failed: int
    unsupported_claims: List[str]
    detected_contradictions: List[Dict[str, Any]]
    feedback_notes: str


class SyntheticInvariantVerifier(BaseVerifier):
    """Verifies textual drafts against evidence ledgers and source documents."""

    def __init__(self, ledger: EvidenceLedger, root_dir: Union[str, Path] = "."):
        self.ledger = ledger
        self.root_dir = Path(root_dir)

    def verify_citations(self) -> Tuple[int, int, List[str]]:
        """Verify that verbatim quotes in the ledger exist in actual source documents."""
        verified = 0
        failed = 0
        errors = []

        for atom in self.ledger.atoms:
            doc_path = self.root_dir / atom.source_doc
            if not doc_path.exists():
                failed += 1
                errors.append(f"Atom {atom.atom_id}: Source doc '{atom.source_doc}' does not exist.")
                continue

            content = doc_path.read_text(encoding="utf-8")
            norm_content = re.sub(r"\s+", " ", content)
            norm_quote = re.sub(r"\s+", " ", atom.verbatim_quote)

            if norm_quote in norm_content:
                verified += 1
            else:
                failed += 1
                errors.append(f"Atom {atom.atom_id}: Quote \"{atom.verbatim_quote[:40]}...\" not found in {atom.source_doc}.")

        return verified, failed, errors

    def verify_draft(self, draft_text: str) -> VerificationReport:
        """Evaluate a draft artifact against the evidence ledger."""
        ver_count, fail_count, cit_errors = self.verify_citations()

        cited_atom_ids = set(re.findall(r"\[(ev_\d{3})\]", draft_text))
        all_atom_ids = {a.atom_id for a in self.ledger.atoms}

        sentences = [s.strip() for s in re.split(r"[.!?]\s+", draft_text) if len(s.strip()) > 25]
        unsupported = [s for s in sentences if not re.search(r"\[ev_\d{3}\]", s) and not s.startswith("#")]

        grounding_score = len(cited_atom_ids) / max(1, len(all_atom_ids))
        contradictions = self.ledger.find_potential_conflicts()

        passed = (fail_count == 0) and (len(cited_atom_ids) >= 1) and (len(contradictions) == 0)

        notes = []
        if fail_count > 0:
            notes.append(f"Citation verification failed on {fail_count} atoms.")
        if contradictions:
            notes.append(f"Potential cross-document contradictions detected on topics: {[c['topic'] for c in contradictions]}.")
        if not passed:
            notes.append("Draft requires revision to meet grounding and non-contradiction invariants.")
        else:
            notes.append("All citations verified against source documents. Non-contradiction invariant holds.")

        return VerificationReport(
            passed=passed,
            grounding_score=min(1.0, grounding_score),
            citations_verified=ver_count,
            citations_failed=fail_count,
            unsupported_claims=unsupported[:5],
            detected_contradictions=contradictions,
            feedback_notes=" ".join(notes)
        )

    def verify(self, draft_text: str) -> VerificationResult:
        rep = self.verify_draft(draft_text)
        passed = ["All citations verified against source documents"] if rep.citations_failed == 0 else []
        violations = [f"{rep.citations_failed} citations failed verification"] if rep.citations_failed > 0 else []
        return VerificationResult(
            passed=rep.passed,
            score=rep.grounding_score,
            passed_invariants=passed,
            detected_violations=violations,
            details={"report": rep}
        )
