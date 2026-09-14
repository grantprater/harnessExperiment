# RFC-9020: Cognitive Harness Specification for Foveated Agentic Architecture

> **Abstract**: Specifies a deterministic multi-scale sensory harness that prevents context bloat in autonomous AI agents.

---

## 1. Introduction and Problem Statement

Standard agent architectures accumulate full file contents into an append-only transcript, creating a **monolithic** context window that severely degrades execution quality over extended tasks [ev_001]. As input sequences grow, transformer **attention** mechanism efficiency suffers from severe context dilution, dispersing key task directives across irrelevant details [ev_001]. Furthermore, unconstrained history scaling results in quadratic **token** growth and elevated operational latency [ev_001]. To sustain high operational precision and efficiency, autonomous systems require a structured sensory mechanism that bounds context bloat while dynamically focusing processing power on active state transitions.

## 2. Cognitive Scaffolding Architecture

To address context degradation, the foveated agentic architecture introduces a deterministic cognitive harness structured around three core operational pillars:

1. **Epistemic Evidence Ledger**: The `EvidenceLedger` serves as a persistent store for discrete atomic facts (`atoms`) derived from execution steps. Rather than retaining complete transcripts, raw execution outputs undergo structured distillation into immutable evidence entries.
2. **Saccadic Perception**: The agent executes targeted sampling operations across the codebase, focusing attention strictly on localized context boundaries required for the immediate subtask.
3. **Context Evaporation**: Through `Evaporation`, transient operational data and redundant details are purged from the working memory. As established in experimental evaluations, "If reality matches prediction, the interaction is wiped from the active context" [ev_002], guaranteeing bounded prompt growth.

## 3. Formal Reference Implementation

To realize the deterministic sensory harness defined in the cognitive scaffolding, the reference implementation formalizes the active context management interface. As established, raw sensory inputs and intermediate dialogue must not persist unconditionally within the context window. The `EvidenceLedger` class acts as the single source of truth for discrete atomic facts (`atoms`), guaranteeing that if reality matches prediction, the raw interaction is evaporated from active context to prevent context bloat [ev_002].

```python
from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class EvidenceAtom:
    atom_id: str
    predicate: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class EvidenceLedger:
    """Stores discrete atomic facts while evaporating raw interaction context."""
    
    def __init__(self) -> None:
        self.atoms: Dict[str, EvidenceAtom] = {}

    def record_evidence(self, atom_id: str, predicate: str, confidence: float, **metadata: Any) -> EvidenceAtom:
        """Records an atomic fact to the ledger, allowing raw text to be safely purged."""
        atom = EvidenceAtom(atom_id=atom_id, predicate=predicate, confidence=confidence, metadata=metadata)
        self.atoms[atom_id] = atom
        return atom
```

## 4. Deterministic Verification and Invariant Enforcement

To ensure mathematical precision and structural integrity, text synthesis and code generation are governed by the Synthetic Invariant Verifier, which acts as the compiler for text synthesis and analysis [ev_003]. The verifier enforces non-negotiable correctness invariants across all generated outputs through a two-stage pipeline:

1. **Syntactic Verification**: Executable code blocks are parsed using `ast.parse` to catch syntax anomalies and illegal AST structures prior to execution.
2. **Grounding Verification**: Non-code claims and citations are verified against the immutable ledger to prevent hallucination and guarantee provenance.

Outputs failing either `ast.parse` validation or citation grounding are rejected before context ingestion.

