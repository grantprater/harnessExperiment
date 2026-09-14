"""Online Real-Time Streaming Perceptual Transducer.

Implements O(1) per-frame ingestion for live video streams and GUI feeds:
1. Zero-copy ROI cropping before compute.
2. Exponential Moving Average (EMA) and Welford running variance accumulators.
3. Streaming Change-Point & Transient Spike Detection (Z-Score on temporal residuals).
4. Non-blocking Asynchronous Perceptual Event Bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import queue
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


@dataclass
class SensoryEvent:
    event_type: str        # e.g., "TRANSIENT_SPIKE", "STEP_TRANSITION", "HUD_FLASH"
    channel: str           # e.g., "minimap", "health_bar", "reticle"
    timestamp_ms: float
    frame_index: int
    magnitude: float
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class StreamingROIFilter:
    """O(1) online streaming filter for a localized visual region of interest (ROI)."""

    def __init__(
        self,
        name: str,
        roi_bbox: Tuple[int, int, int, int],  # (x1, y1, x2, y2)
        alpha: float = 0.08,
        z_threshold: float = 3.2,
        min_delta_floor: float = 2.0
    ):
        self.name = name
        self.roi_bbox = roi_bbox
        self.alpha = alpha
        self.z_threshold = z_threshold
        self.min_delta_floor = min_delta_floor

        self.prev_patch: Optional[np.ndarray] = None
        self.running_mean: float = 0.0
        self.running_var: float = 1.0
        self.frame_count: int = 0

    def push_frame(
        self,
        frame_bgr: np.ndarray,
        frame_idx: int,
        timestamp_ms: float
    ) -> Optional[SensoryEvent]:
        """Ingest a single frame in O(1) time and return an event if a transient occurs."""
        x1, y1, x2, y2 = self.roi_bbox
        h, w = frame_bgr.shape[:2]
        # Bounded slice
        x1_c, x2_c = max(0, min(w, x1)), max(0, min(w, x2))
        y1_c, y2_c = max(0, min(h, y1)), max(0, min(h, y2))

        patch = frame_bgr[y1_c:y2_c, x1_c:x2_c]
        if patch.size == 0:
            return None

        self.frame_count += 1

        if self.prev_patch is None or self.prev_patch.shape != patch.shape:
            self.prev_patch = patch.copy()
            self.running_mean = 0.0
            self.running_var = 1.0
            return None

        # 1. Instantaneous 3-channel delta inside isolated ROI (captures color & luminance transients)
        diff = cv2.absdiff(patch, self.prev_patch)
        delta = float(np.mean(diff))
        self.prev_patch = patch.copy()

        # 2. Update streaming statistics (Exponential Moving Average & Variance)
        if self.frame_count <= 5:
            self.running_mean = delta
            self.running_var = 1.0
            return None

        # Welford-style streaming EMA
        self.running_mean = (1.0 - self.alpha) * self.running_mean + self.alpha * delta
        diff_sq = (delta - self.running_mean) ** 2
        self.running_var = (1.0 - self.alpha) * self.running_var + self.alpha * diff_sq
        std = max(1e-4, math.sqrt(self.running_var))

        # 3. Streaming Z-Score & Floor check
        z_score = (delta - self.running_mean) / std

        if z_score >= self.z_threshold and delta >= self.min_delta_floor:
            confidence = min(1.0, z_score / (self.z_threshold * 2.0))
            return SensoryEvent(
                event_type="TRANSIENT_SPIKE",
                channel=self.name,
                timestamp_ms=timestamp_ms,
                frame_index=frame_idx,
                magnitude=round(delta, 2),
                confidence=round(confidence, 2),
                metadata={"z_score": round(z_score, 2), "std": round(std, 2)}
            )

        return None


class StreamingVideoTransducer:
    """Real-time streaming perception engine that monitors multiple ROIs concurrently."""

    def __init__(self):
        if not HAS_CV2:
            raise ImportError("opencv-python and numpy required for StreamingVideoTransducer.")

        self.filters: Dict[str, StreamingROIFilter] = {}
        self.event_queue: queue.Queue[SensoryEvent] = queue.Queue(maxsize=1000)
        self.event_history: List[SensoryEvent] = []
        self.total_frames_processed: int = 0

    def register_roi(
        self,
        name: str,
        roi_bbox: Tuple[int, int, int, int],
        alpha: float = 0.08,
        z_threshold: float = 3.2
    ):
        """Register a monitored spatial channel (e.g. minimap, health bar, ammo)."""
        self.filters[name] = StreamingROIFilter(
            name=name,
            roi_bbox=roi_bbox,
            alpha=alpha,
            z_threshold=z_threshold
        )

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        timestamp_ms: Optional[float] = None
    ) -> List[SensoryEvent]:
        """Process a single incoming frame across all registered ROIs in < 1ms."""
        self.total_frames_processed += 1
        t_ms = timestamp_ms if timestamp_ms is not None else time.time() * 1000.0

        detected_events = []
        for name, roi_filter in self.filters.items():
            evt = roi_filter.push_frame(frame_bgr, self.total_frames_processed, t_ms)
            if evt:
                detected_events.append(evt)
                try:
                    self.event_queue.put_nowait(evt)
                except queue.Full:
                    pass
                self.event_history.append(evt)

        return detected_events

    def poll_events(self, max_count: int = 10) -> List[SensoryEvent]:
        """Non-blocking drain of recent sensory events for the behavioral autopilot."""
        events = []
        while not self.event_queue.empty() and len(events) < max_count:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events
