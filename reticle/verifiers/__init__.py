"""Domain verifiers for spatial, temporal, 3D blender, and synthetic document domains."""

from reticle.verifiers.spatial_verifier import (
    GroundingEvaluation,
    SpatialVerifier,
    evaluate_grounding,
    is_point_inside_bbox,
    compute_iou,
    estimate_vision_tokens
)
from reticle.verifiers.temporal_verifier import (
    TemporalInvariantVerifier,
    TemporalVerificationResult
)
from reticle.verifiers.blender_verifier import (
    BlenderVerifier,
    BlenderVerificationResult,
    verify_prop_studio_scene
)
from reticle.verifiers.synthetic_verifier import (
    SyntheticInvariantVerifier,
    VerificationReport
)

__all__ = [
    "GroundingEvaluation",
    "SpatialVerifier",
    "evaluate_grounding",
    "is_point_inside_bbox",
    "compute_iou",
    "estimate_vision_tokens",
    "TemporalInvariantVerifier",
    "TemporalVerificationResult",
    "BlenderVerifier",
    "BlenderVerificationResult",
    "verify_prop_studio_scene",
    "SyntheticInvariantVerifier",
    "VerificationReport",
]
