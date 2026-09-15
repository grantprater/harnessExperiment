"""Reticle: The Cognitive Harness Framework.

Provides epistemic ledgers and formal invariant verifiers across:
1. Code AST and Syntax
2. Technical Document Synthesis
3. 3D Program Use (Blender 5.0 Scene Graphs)

Spatial, temporal, audio/video, and Minecraft modules were moved to archive/ on 2026-09-14.
"""

__version__ = "0.2.0"

from reticle.core.evidence_ledger import EvidenceAtom, EvidenceLedger
from reticle.core.verifier_base import BaseVerifier, VerificationResult
from reticle.adapters.code_ast import parse_and_inspect_code, validate_python_syntax
from reticle.adapters.blender_engine import run_blender_script, verify_blender_installed
from reticle.verifiers.blender_verifier import BlenderVerifier
from reticle.verifiers.synthetic_verifier import SyntheticInvariantVerifier

__all__ = [
    "__version__",
    "EvidenceAtom",
    "EvidenceLedger",
    "BaseVerifier",
    "VerificationResult",
    "parse_and_inspect_code",
    "validate_python_syntax",
    "run_blender_script",
    "verify_blender_installed",
    "BlenderVerifier",
    "SyntheticInvariantVerifier",
]
