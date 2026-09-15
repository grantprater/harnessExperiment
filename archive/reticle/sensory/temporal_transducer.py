"""Temporal Perception and Kinetic Motion Energy Transducer."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image, ImageChops, ImageStat


def compute_frame_difference(img_path_a: Union[str, Path], img_path_b: Union[str, Path]) -> float:
    """Compute normalized RMS difference between two image frames in [0.0, 1.0]."""
    with Image.open(img_path_a) as im_a, Image.open(img_path_b) as im_b:
        diff = ImageChops.difference(im_a.convert("RGB"), im_b.convert("RGB"))
        stat = ImageStat.Stat(diff)
        rms = math.sqrt(sum(stat.rms) / (3.0 * (255.0 ** 2)))
        return round(rms, 4)


def compute_temporal_energy_profile(frame_paths: List[Union[str, Path]]) -> List[Dict[str, Any]]:
    """Generate motion energy profile across the entire frame sequence."""
    profile = []
    if len(frame_paths) < 2:
        return profile

    for idx in range(1, len(frame_paths)):
        prev_f = frame_paths[idx - 1]
        curr_f = frame_paths[idx]
        diff_val = compute_frame_difference(prev_f, curr_f)
        profile.append({
            "frame_index": idx,
            "prev_frame": Path(prev_f).name,
            "curr_frame": Path(curr_f).name,
            "motion_energy": diff_val
        })
    return profile


def detect_motion_intervals(
    energy_profile: List[Dict[str, Any]],
    energy_threshold: float = 0.015,
    min_duration_frames: int = 2
) -> List[Tuple[int, int]]:
    """Isolate continuous intervals [start_frame, end_frame] where motion occurs."""
    active_intervals = []
    in_interval = False
    start_idx = 0

    for item in energy_profile:
        idx = item["frame_index"]
        val = item["motion_energy"]

        if val >= energy_threshold:
            if not in_interval:
                in_interval = True
                start_idx = idx - 1  # include baseline frame
        else:
            if in_interval:
                in_interval = False
                end_idx = idx
                if (end_idx - start_idx) >= min_duration_frames:
                    active_intervals.append((start_idx, end_idx))

    if in_interval:
        active_intervals.append((start_idx, len(energy_profile)))

    return active_intervals


def select_coarse_keyframe_anchors(
    frame_paths: List[Union[str, Path]],
    energy_profile: List[Dict[str, Any]],
    max_anchors: int = 6
) -> List[Union[str, Path]]:
    """Select high-leverage keyframes representing major states and energy peaks."""
    if len(frame_paths) <= max_anchors:
        return frame_paths

    selected_indices = {0, len(frame_paths) - 1}
    sorted_by_energy = sorted(energy_profile, key=lambda x: x["motion_energy"], reverse=True)
    for item in sorted_by_energy:
        if len(selected_indices) >= max_anchors:
            break
        selected_indices.add(item["frame_index"])

    return [frame_paths[i] for i in sorted(selected_indices)]


def render_temporal_summary(
    total_frames: int,
    fps: float,
    energy_profile: List[Dict[str, Any]],
    intervals: List[Tuple[int, int]]
) -> str:
    """Format motion profile and active intervals into a high-density, low-token summary."""
    total_duration_s = round(total_frames / fps, 2)
    lines = [
        f"=== Video Temporal Dynamics Summary ===",
        f"Total Frames: {total_frames} | Frame Rate: {fps} fps | Duration: {total_duration_s}s",
        "\nActive Motion & State-Transition Intervals:"
    ]

    if not intervals:
        lines.append("- No significant motion detected (Static Scene).")
    else:
        for idx, (s, e) in enumerate(intervals, 1):
            t_start = round(s / fps, 2)
            t_end = round(e / fps, 2)
            sub_energies = [p["motion_energy"] for p in energy_profile if s <= p["frame_index"] <= e]
            peak_e = max(sub_energies) if sub_energies else 0.0
            lines.append(
                f"- Interval {idx}: Frames [{s} -> {e}] ({t_start}s - {t_end}s) | Peak Motion: {peak_e:.3f}"
            )

    lines.append("=== End Temporal Summary ===")
    return "\n".join(lines)
