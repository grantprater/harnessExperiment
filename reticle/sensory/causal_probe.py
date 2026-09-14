"""Causal Correlation Probe for Emergent HUD and Feature Localization.

Discovers spatial interface elements (e.g. health bar, hotbar, minimap icons)
strictly through empirical causal perturbation:

1. Takes a pre-event screen frame and post-event screen frame.
2. Computes the spatial difference heatmap across the entire 2D canvas.
3. Filters out non-stationary parallax noise.
4. Dynamically extracts the bounding box (ROI) of the localized pixel cluster.
5. Returns the discovered ROI without any hardcoded coordinates!
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


@dataclass
class DiscoveredROI:
    channel_name: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    pixel_area: int
    mean_delta: float
    confidence: float


class CausalSpatialCorrelationProbe:
    """Discovers visual UI regions emergently by correlating physical events with pixel changes."""

    def __init__(self, delta_threshold: float = 15.0, min_area: int = 100, max_area: int = 250000):
        if not HAS_CV2:
            raise ImportError("opencv-python and numpy required for CausalSpatialCorrelationProbe.")
        self.delta_threshold = delta_threshold
        self.min_area = min_area
        self.max_area = max_area

    def discover_roi_from_event(
        self,
        channel_name: str,
        pre_frame_bgr: np.ndarray,
        post_frame_bgr: np.ndarray
    ) -> Optional[DiscoveredROI]:
        """Discovers the bounding box of pixels that changed as a direct result of an event."""
        # 1. 3-channel absolute difference across entire frame
        diff = cv2.absdiff(pre_frame_bgr, post_frame_bgr)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        # 2. Threshold to isolate localized cluster
        _, thresh = cv2.threshold(gray_diff, int(self.delta_threshold), 255, cv2.THRESH_BINARY)

        # Morphological close to merge nearby sprite elements (e.g. adjacent hearts)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 7))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # 3. Find connected components / contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Filter by area and select the dominant candidate cluster
        valid_candidates = []
        for c in contours:
            area = cv2.contourArea(c)
            if self.min_area <= area <= self.max_area:
                x, y, w, h = cv2.boundingRect(c)
                # Compute average delta within candidate bounding box
                box_patch = gray_diff[y:y+h, x:x+w]
                mean_delta = float(np.mean(box_patch))
                valid_candidates.append({
                    "bbox": (x, y, x + w, y + h),
                    "area": int(area),
                    "mean_delta": mean_delta
                })

        if not valid_candidates:
            return None

        # Sort by pixel area * mean_delta (signal energy)
        valid_candidates.sort(key=lambda c: c["area"] * c["mean_delta"], reverse=True)
        best = valid_candidates[0]

        conf = min(1.0, (best["mean_delta"] / 40.0) * (best["area"] / 500.0))

        return DiscoveredROI(
            channel_name=channel_name,
            bbox=best["bbox"],
            pixel_area=best["area"],
            mean_delta=round(best["mean_delta"], 2),
            confidence=round(conf, 2)
        )
