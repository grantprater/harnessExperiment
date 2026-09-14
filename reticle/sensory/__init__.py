"""Sensory transduction modules for spatial and temporal perception."""

from reticle.sensory.spatial_saccade import (
    SpatialSector,
    create_spatial_grid,
    render_spatial_map,
    foveated_crop,
    project_to_global,
    project_to_local,
    generate_overview_thumbnail
)
from reticle.sensory.temporal_transducer import (
    compute_frame_difference,
    compute_temporal_energy_profile,
    detect_motion_intervals,
    select_coarse_keyframe_anchors,
    render_temporal_summary
)
from reticle.sensory.video_stream import VideoStreamTransducer
from reticle.sensory.audio_transducer import (
    AudioTransducer,
    AcousticPeak,
    AcousticProfileResult
)
from reticle.sensory.perceptual_probe import (
    PerceptualProbeRunner,
    ProbeExecutionResult
)

__all__ = [
    "SpatialSector",
    "create_spatial_grid",
    "render_spatial_map",
    "foveated_crop",
    "project_to_global",
    "project_to_local",
    "generate_overview_thumbnail",
    "compute_frame_difference",
    "compute_temporal_energy_profile",
    "detect_motion_intervals",
    "select_coarse_keyframe_anchors",
    "render_temporal_summary",
    "VideoStreamTransducer",
    "AudioTransducer",
    "AcousticPeak",
    "AcousticProfileResult",
    "PerceptualProbeRunner",
    "ProbeExecutionResult",
]
