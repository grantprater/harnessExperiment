"""Video Stream Transducer for High-Speed Temporal Ingestion."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class VideoStreamTransducer:
    """Ingests full-length video files and extracts deterministic temporal signals."""

    def __init__(self, video_path: Union[str, Path]):
        if not HAS_CV2:
            raise ImportError("opencv-python and numpy are required for VideoStreamTransducer.")

        self.video_path = str(video_path)
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Could not open video at {video_path}")

        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_s = round(self.total_frames / self.fps, 2) if self.fps > 0 else 0.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def scan_dynamics(self, stride: int = 5) -> Dict[str, Any]:
        """Scan entire video stream at high frame rates with zero LLM tokens."""
        t0 = time.time()
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        motion_profile: List[Dict[str, Any]] = []
        brightness_curve: List[Tuple[int, float]] = []
        color_ratios: List[Tuple[int, float]] = []

        prev_small = None
        frame_idx = 0

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            if frame_idx % stride == 0:
                t = round(frame_idx / self.fps, 3)
                small = cv2.resize(frame, (320, 180))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                motion = 0.0
                if prev_small is not None:
                    diff = cv2.absdiff(gray, prev_small)
                    motion = float(np.sqrt(np.mean((diff.astype(np.float32) / 255.0) ** 2)))
                prev_small = gray

                mean_b = float(np.mean(small))
                brightness_curve.append((frame_idx, mean_b))

                center = small[50:130, 100:220]
                b_val = float(np.mean(center[:, :, 0]))
                r_val = float(np.mean(center[:, :, 2]))
                ratio = b_val / (r_val + 1e-5)
                color_ratios.append((frame_idx, ratio))

                motion_profile.append({
                    "frame_index": frame_idx,
                    "time_s": t,
                    "motion_energy": round(motion, 4),
                    "mean_brightness": round(mean_b, 2),
                    "blue_ratio": round(ratio, 3)
                })

            frame_idx += 1

        scan_duration = round(time.time() - t0, 3)

        # Detect Blackout / Cut
        blackout_frame = None
        for f, b in brightness_curve:
            if b < 12.0:
                blackout_frame = f
                break

        blackout_time = round(blackout_frame / self.fps, 2) if blackout_frame else None

        return {
            "fps": self.fps,
            "total_frames": self.total_frames,
            "duration_s": self.duration_s,
            "scan_duration_s": scan_duration,
            "fps_processed": round(self.total_frames / (scan_duration + 1e-6), 1),
            "blackout_timestamp_s": blackout_time,
            "motion_profile": motion_profile
        }

    def extract_anchor_frames(
        self,
        timestamps_s: List[float],
        output_dir: Union[str, Path]
    ) -> List[str]:
        """Extract full-resolution keyframe stills at specified timestamps."""
        out_paths = []
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for idx, ts in enumerate(timestamps_s):
            frame_num = int(min(ts * self.fps, self.total_frames - 1))
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = self.cap.read()
            if ret:
                p = out_dir / f"anchor_{idx+1:02d}_{ts:05.2f}s.jpg"
                cv2.imwrite(str(p), frame)
                out_paths.append(str(p))

        return out_paths

    def close(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
