"""Base Verifier Interface and Verification Result Abstraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    """Unified result container for deterministic invariant verification."""
    passed: bool
    score: float  # 0.0 to 1.0 (or percentage 0.0 - 100.0)
    passed_invariants: List[str] = field(default_factory=list)
    detected_violations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        score_fmt = f"{self.score * 100:.1f}%" if self.score <= 1.0 else f"{self.score:.1f}%"
        lines = [
            f"=== Invariant Verification: {status} (Score: {score_fmt}) ===",
            f"- Passed Invariants ({len(self.passed_invariants)}): {self.passed_invariants}"
        ]
        if self.detected_violations:
            lines.append(f"- Detected Violations ({len(self.detected_violations)}): {self.detected_violations}")
        return "\n".join(lines)


class BaseVerifier:
    """Abstract base class for domain-specific verifiers."""
    def verify(self, *args, **kwargs) -> VerificationResult:
        raise NotImplementedError("Subclasses must implement verify()")
