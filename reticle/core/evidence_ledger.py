"""Epistemic Evidence Ledger for General and Technical Text Reasoning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceAtom:
    atom_id: str
    claim: str
    source_doc: str
    section: str
    line_range: str
    verbatim_quote: str
    topic: str
    confidence: float = 1.0


class EvidenceLedger:
    """Manages verified evidence atoms and source document evaporation."""

    def __init__(self):
        self.atoms: List[EvidenceAtom] = []
        self.evaporated_sources: Dict[str, str] = {}  # {source_doc: summary}

    def record_evidence(
        self,
        claim: str,
        source_doc: str,
        section: str,
        verbatim_quote: str,
        line_range: str = "",
        topic: str = "general",
        confidence: float = 1.0
    ) -> EvidenceAtom:
        atom_id = f"ev_{len(self.atoms) + 1:03d}"
        atom = EvidenceAtom(
            atom_id=atom_id,
            claim=claim.strip(),
            source_doc=source_doc.strip(),
            section=section.strip(),
            line_range=line_range.strip(),
            verbatim_quote=verbatim_quote.strip(),
            topic=topic.strip().lower(),
            confidence=confidence
        )
        self.atoms.append(atom)
        return atom

    def mark_evaporated(self, source_doc: str, summary: str):
        """Record that raw text from source_doc has been distilled into the ledger."""
        self.evaporated_sources[source_doc] = summary

    def find_potential_conflicts(self) -> List[Dict[str, Any]]:
        """Identify atoms on the same topic that may contain contradictory claims."""
        by_topic: Dict[str, List[EvidenceAtom]] = {}
        for a in self.atoms:
            by_topic.setdefault(a.topic, []).append(a)

        conflicts = []
        for topic, group in by_topic.items():
            if len(group) > 1 and topic != "general":
                conflicts.append({
                    "topic": topic,
                    "atoms": [asdict(g) for g in group],
                    "claim_count": len(group)
                })
        return conflicts

    def render_ledger_view(self) -> str:
        """Render working-memory table of verified evidence atoms."""
        if not self.atoms:
            return "=== EVIDENCE LEDGER: (No evidence atoms recorded yet) ==="

        lines = [
            f"=== EVIDENCE LEDGER ({len(self.atoms)} verified atoms, {len(self.evaporated_sources)} docs distilled) ===",
            "| ID | Topic | Verified Claim | Source & Section | Citation Quote |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ]

        for a in self.atoms:
            lines.append(
                f"| `{a.atom_id}` | **{a.topic}** | {a.claim} | "
                f"`{a.source_doc}` ({a.section}) | \"{a.verbatim_quote[:50]}...\" |"
            )

        if self.evaporated_sources:
            lines.append("\nEvaporated Source Documents (Raw text discarded from memory):")
            for doc, summ in self.evaporated_sources.items():
                lines.append(f"  - `{doc}`: {summ}")

        lines.append("=== END LEDGER ===")
        return "\n".join(lines)

    export_context_view = render_ledger_view

    def to_json(self) -> str:
        return json.dumps({
            "atoms": [asdict(a) for a in self.atoms],
            "evaporated_sources": self.evaporated_sources
        }, indent=2)
