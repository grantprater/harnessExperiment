"""Spatial Invariant Verifier for GUI Grounding and Visual Perception.

Provides deterministic mathematical evaluation for spatial predictions:
1. Point-in-Bbox Containment Oracle:
   Verifies whether an agent's predicted click point (x, y) falls inside
   the target UI widget's ground truth bounding box [x1, y1, x2, y2].
2. Spatial Error Metrics:
   Euclidean distance to center, margin-to-edge, normalized error.
3. Vision Token Economy Calculation:
   Compares the token footprint of full-canvas ingestion vs foveated localized saccades.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple


@dataclass
class GroundingEvaluation:
    hit: bool
    predicted_point: Tuple[float, float]
    ground_truth_bbox: Tuple[int, int, int, int]
    target_center: Tuple[float, float]
    euclidean_distance_px: float
    normalized_distance: float  # Fraction of canvas diagonal
    full_screen_tokens: int
    foveated_tokens: int
    token_savings_pct: float

    def summary(self) -> str:
        status = "HIT (SUCCESS)" if self.hit else "MISS (FAILED)"
        lines = [
            f"=== Spatial Grounding Evaluation: {status} ===",
            f"- Predicted Point: ({self.predicted_point[0]:.1f}, {self.predicted_point[1]:.1f})",
            f"- Ground Truth BBox: {list(self.ground_truth_bbox)}",
            f"- Target Center: ({self.target_center[0]:.1f}, {self.target_center[1]:.1f})",
            f"- Distance to Center: {self.euclidean_distance_px:.1f} px ({self.normalized_distance*100:.2f}% of diagonal)",
            f"- Vision Tokens: {self.foveated_tokens} foveated vs {self.full_screen_tokens} full screen "
            f"({self.token_savings_pct:.1f}% savings)"
        ]
        return "\n".join(lines)


def is_point_inside_bbox(
    point: Tuple[float, float],
    bbox: Tuple[int, int, int, int]
) -> bool:
    """Deterministic oracle checking whether point (x, y) is inside [x1, y1, x2, y2]."""
    x, y = point
    x1, y1, x2, y2 = bbox
    return (x1 <= x <= x2) and (y1 <= y <= y2)


def compute_iou(
    bbox_a: Tuple[int, int, int, int],
    bbox_b: Tuple[int, int, int, int]
) -> float:
    """Compute Intersection over Union (IoU) between two bounding boxes."""
    x1 = max(bbox_a[0], bbox_b[0])
    y1 = max(bbox_a[1], bbox_b[1])
    x2 = min(bbox_a[2], bbox_b[2])
    y2 = min(bbox_a[3], bbox_b[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
    area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0
    return round(intersection / union, 4)


def estimate_vision_tokens(width: int, height: int, patch_size: int = 28) -> int:
    """Estimate vision transformer token footprint based on resolution and standard patch size."""
    # Standard ViT models process images in 28x28 or 14x14 pixel patches, capped by tiling limits
    patches_w = math.ceil(width / patch_size)
    patches_h = math.ceil(height / patch_size)
    raw_patches = patches_w * patches_h
    # Most vision APIs tile up to ~1,600 - 3,200 tokens for 4K
    return min(3200, max(256, raw_patches))


def evaluate_grounding(
    predicted_point: Tuple[float, float],
    ground_truth_bbox: Tuple[int, int, int, int],
    canvas_size: Tuple[int, int],
    foveated_patch_size: Optional[Tuple[int, int]] = None
) -> GroundingEvaluation:
    """Evaluate grounding prediction against deterministic mathematical truth."""
    hit = is_point_inside_bbox(predicted_point, ground_truth_bbox)
    cx = (ground_truth_bbox[0] + ground_truth_bbox[2]) / 2.0
    cy = (ground_truth_bbox[1] + ground_truth_bbox[3]) / 2.0

    px, py = predicted_point
    dist_px = math.hypot(px - cx, py - cy)

    w, h = canvas_size
    diag = math.hypot(w, h)
    norm_dist = dist_px / max(1.0, diag)

    full_tokens = estimate_vision_tokens(w, h)
    pw, ph = foveated_patch_size if foveated_patch_size else (w // 3, h // 3)
    fov_tokens = estimate_vision_tokens(pw, ph)

    savings = (1.0 - (fov_tokens / max(1, full_tokens))) * 100.0

    return GroundingEvaluation(
        hit=hit,
        predicted_point=predicted_point,
        ground_truth_bbox=ground_truth_bbox,
        target_center=(cx, cy),
        euclidean_distance_px=round(dist_px, 2),
        normalized_distance=round(norm_dist, 4),
        full_screen_tokens=full_tokens,
        foveated_tokens=fov_tokens,
        token_savings_pct=round(savings, 2)
    )
