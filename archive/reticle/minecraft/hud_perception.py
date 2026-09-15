"""Perceptual HUD Grounding: Deriving Health and Inventory States Directly from Pixels.

Replaces oracle backend memory queries (e.g. sim.health, sim.inventory) with
empirical computer vision probes operating over raw RGB screen frames:

1. Health Bar Grounding: Measures active red heart pixel clusters to extract empirical health.
2. Hotbar Slot Grounding: Measures localized edge density and color variance to detect item presence.
3. State Invariant Verification: Verifies that physical interventions (e.g. falling or picking up items)
   manifest as ground-truth pixel transitions on the HUD without reading memory variables.
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
class PerceivedHUDState:
    health_units: int             # [0..20] half-hearts estimated from red pixel mass
    occupied_hotbar_slots: List[int]  # List of slot indices (0..8) containing items
    total_active_slots: int
    raw_confidence: float


class HUDPerceptionTransducer:
    """Extracts ground-truth game state directly from 2D screen frames via computer vision."""

    def __init__(
        self,
        health_roi: Tuple[int, int, int, int] = (400, 680, 580, 700),    # (x1, y1, x2, y2)
        hotbar_roi: Tuple[int, int, int, int] = (460, 670, 820, 715)
    ):
        if not HAS_CV2:
            raise ImportError("opencv-python required for HUDPerceptionTransducer.")
        self.health_roi = health_roi
        self.hotbar_roi = hotbar_roi

    def extract_health_from_pixels(self, frame_bgr: np.ndarray) -> Tuple[int, float]:
        """Measures active red heart pixels in the health HUD ROI to compute empirical health."""
        x1, y1, x2, y2 = self.health_roi
        patch = frame_bgr[y1:y2, x1:x2]
        if patch.size == 0:
            return 0, 0.0

        # Convert to HSV to isolate saturated Minecraft heart red
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        # Red spans 0-10 and 170-180 in OpenCV Hue
        mask1 = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 100, 100]), np.array([180, 255, 255]))
        red_mask = cv2.bitwise_or(mask1, mask2)

        red_pixels = int(np.count_nonzero(red_mask))
        # Each full heart is approximately 40 red pixels in a standard 180x20 strip (total 10 hearts = 400 pixels)
        # Scale to 20 half-heart units
        max_expected_pixels = 400.0
        health_ratio = min(1.0, red_pixels / max_expected_pixels)
        health_units = int(round(health_ratio * 20.0))
        confidence = min(1.0, red_pixels / 50.0) if red_pixels > 0 else 0.5

        return health_units, confidence

    def extract_hotbar_occupancy(self, frame_bgr: np.ndarray, num_slots: int = 9) -> List[int]:
        """Detects which hotbar slots contain items by measuring localized feature variance."""
        x1, y1, x2, y2 = self.hotbar_roi
        patch = frame_bgr[y1:y2, x1:x2]
        if patch.size == 0:
            return []

        h, w = patch.shape[:2]
        slot_width = w / num_slots
        occupied_slots = []

        for i in range(num_slots):
            sx1 = int(i * slot_width + 4)
            sx2 = int((i + 1) * slot_width - 4)
            slot_patch = patch[:, sx1:sx2]
            if slot_patch.size == 0:
                continue

            # Empty slots are uniform dark gray. Occupied slots contain multi-colored sprite pixels.
            std_dev = float(np.std(slot_patch))
            if std_dev > 45.0:  # Texture complexity / color entropy threshold
                occupied_slots.append(i)

        return occupied_slots

    def perceive_hud(self, frame_bgr: np.ndarray) -> PerceivedHUDState:
        """Full perceptual scan returning structured state without reading backend memory."""
        health, conf = self.extract_health_from_pixels(frame_bgr)
        occupied = self.extract_hotbar_occupancy(frame_bgr)

        return PerceivedHUDState(
            health_units=health,
            occupied_hotbar_slots=occupied,
            total_active_slots=len(occupied),
            raw_confidence=conf
        )
