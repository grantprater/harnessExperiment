"""Reticle: The Cognitive Harness Framework for Multimodal AI Agents.

Provides deterministic sensory transduction, epistemic ledgers, and formal
invariant verifiers across:
1. Code AST and Syntax
2. Technical Document Synthesis
3. Spatial GUI Perception (Multi-Scale Saccades)
4. 3D Program Use (Blender 5.0 Scene Graphs)
5. Temporal Video Event Reasoning (LTL Invariants)
"""

__version__ = "0.2.0"

from reticle.core.evidence_ledger import EvidenceAtom, EvidenceLedger
from reticle.core.world_line_ledger import EntityInterval, WorldLineLedger
from reticle.core.verifier_base import BaseVerifier, VerificationResult
from reticle.sensory.spatial_saccade import (
    SpatialSector,
    create_spatial_grid,
    foveated_crop,
    project_to_global,
    project_to_local
)
from reticle.sensory.temporal_transducer import (
    compute_frame_difference,
    compute_temporal_energy_profile,
    detect_motion_intervals,
    select_coarse_keyframe_anchors
)
from reticle.sensory.video_stream import VideoStreamTransducer
from reticle.sensory.audio_transducer import AudioTransducer, AcousticPeak
from reticle.sensory.perceptual_probe import PerceptualProbeRunner
from reticle.adapters.code_ast import parse_and_inspect_code, validate_python_syntax
from reticle.adapters.blender_engine import run_blender_script, verify_blender_installed
from reticle.verifiers.spatial_verifier import SpatialVerifier, evaluate_grounding
from reticle.verifiers.temporal_verifier import TemporalInvariantVerifier
from reticle.verifiers.blender_verifier import BlenderVerifier
from reticle.verifiers.synthetic_verifier import SyntheticInvariantVerifier

__all__ = [
    "__version__",
    "EvidenceAtom",
    "EvidenceLedger",
    "EntityInterval",
    "WorldLineLedger",
    "BaseVerifier",
    "VerificationResult",
    "SpatialSector",
    "create_spatial_grid",
    "foveated_crop",
    "project_to_global",
    "project_to_local",
    "compute_frame_difference",
    "compute_temporal_energy_profile",
    "detect_motion_intervals",
    "select_coarse_keyframe_anchors",
    "VideoStreamTransducer",
    "AudioTransducer",
    "AcousticPeak",
    "PerceptualProbeRunner",
    "parse_and_inspect_code",
    "validate_python_syntax",
    "run_blender_script",
    "verify_blender_installed",
    "SpatialVerifier",
    "evaluate_grounding",
    "TemporalInvariantVerifier",
    "BlenderVerifier",
    "SyntheticInvariantVerifier",
]
