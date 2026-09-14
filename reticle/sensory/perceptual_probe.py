"""Dynamic Perceptual Probe Engine (Code-as-Sensor).

Allows the cognitive harness and agent to formulate, execute, and verify
custom computer vision, signal processing, and sensory queries dynamically.
"""

from __future__ import annotations

import io
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


@dataclass
class ProbeExecutionResult:
    success: bool
    data: Dict[str, Any]
    duration_s: float
    stdout: str
    error: Optional[str] = None


class PerceptualProbeRunner:
    """Executes sandboxed perceptual probes against video, image, or audio buffers."""

    def __init__(self, default_timeout_s: float = 10.0):
        self.default_timeout_s = default_timeout_s

    def execute_probe(
        self,
        probe_code: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ProbeExecutionResult:
        """Execute a Python perceptual probe snippet with sensory context injected.
        
        The probe script should store its findings in a dictionary named `probe_result`.
        """
        t0 = time.time()
        ctx = dict(context or {})

        # Standard scientific imports available by default
        ctx.setdefault("np", np)
        if HAS_CV2:
            ctx.setdefault("cv2", cv2)

        probe_result: Dict[str, Any] = {}
        ctx["probe_result"] = probe_result

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = stdout_capture
            exec(probe_code, ctx)
            elapsed = time.time() - t0
            output_data = ctx.get("probe_result", {})
            return ProbeExecutionResult(
                success=True,
                data=output_data,
                duration_s=round(elapsed, 4),
                stdout=stdout_capture.getvalue()
            )
        except Exception as e:
            elapsed = time.time() - t0
            err_msg = traceback.format_exc()
            return ProbeExecutionResult(
                success=False,
                data={},
                duration_s=round(elapsed, 4),
                stdout=stdout_capture.getvalue(),
                error=err_msg
            )
        finally:
            sys.stdout = old_stdout

    # --- Pre-Built Perceptual Probe Recipes ---

    @staticmethod
    def probe_color_centroid(
        image_bgr: np.ndarray,
        lower_hsv: Tuple[int, int, int],
        upper_hsv: Tuple[int, int, int]
    ) -> Dict[str, Any]:
        """Detect and track the centroid of pixels matching a specified HSV range."""
        if not HAS_CV2:
            return {"error": "cv2 not available"}

        hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower_hsv), np.array(upper_hsv))
        pixel_count = int(np.sum(mask > 0))

        if pixel_count == 0:
            return {"found": False, "pixel_count": 0, "centroid": None, "bbox": None}

        moments = cv2.moments(mask)
        cx = int(moments["m10"] / (moments["m00"] + 1e-6))
        cy = int(moments["m01"] / (moments["m00"] + 1e-6))
        x, y, w, h = cv2.boundingRect(mask)

        return {
            "found": True,
            "pixel_count": pixel_count,
            "centroid": (cx, cy),
            "bbox": (x, y, x + w, y + h)
        }

    @staticmethod
    def probe_optical_flow(
        frame_prev_bgr: np.ndarray,
        frame_curr_bgr: np.ndarray,
        downscale: Tuple[int, int] = (320, 180)
    ) -> Dict[str, Any]:
        """Compute average dense optical flow motion vector between two frames."""
        if not HAS_CV2:
            return {"error": "cv2 not available"}

        p_prev = cv2.resize(frame_prev_bgr, downscale)
        p_curr = cv2.resize(frame_curr_bgr, downscale)
        g_prev = cv2.cvtColor(p_prev, cv2.COLOR_BGR2GRAY)
        g_curr = cv2.cvtColor(p_curr, cv2.COLOR_BGR2GRAY)

        flow = cv2.calcOpticalFlowFarneback(
            g_prev, g_curr, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        flow_x = flow[:, :, 0]
        flow_y = flow[:, :, 1]

        mag, ang = cv2.cartToPolar(flow_x, flow_y)
        avg_mag = float(np.mean(mag))
        mean_dx = float(np.mean(flow_x))
        mean_dy = float(np.mean(flow_y))

        return {
            "mean_magnitude": round(avg_mag, 3),
            "mean_dx": round(mean_dx, 3),
            "mean_dy": round(mean_dy, 3),
            "dominant_direction_deg": round(float(np.degrees(np.arctan2(mean_dy, mean_dx))) % 360, 1)
        }
