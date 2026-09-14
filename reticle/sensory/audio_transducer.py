"""Acoustic Sensory Transducer for Temporal Video & Audio Understanding.

Extracts sub-second acoustic features from video soundtracks and audio files:
1. Fast Demuxing: Extracts 16kHz mono WAV streams from MP4/MOV via FFmpeg.
2. RMS Envelope: Computes frame-level acoustic energy across time windows.
3. Transient Peak Detection: Isolates sharp impulse events (gunshots, impacts, ability sound effects).
4. Spectral Band Decomposition: Separates low-frequency footsteps from high-frequency actions.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    import imageio_ffmpeg
    HAS_FFMPEG = True
except ImportError:
    HAS_FFMPEG = False

try:
    from scipy.io import wavfile
    from scipy import signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


@dataclass
class AcousticPeak:
    timestamp_s: float
    amplitude_rms: float
    relative_prominence: float
    channel_energy: Dict[str, float]


@dataclass
class AcousticProfileResult:
    sample_rate: int
    duration_s: float
    max_rms: float
    mean_rms: float
    peaks: List[AcousticPeak]
    envelope_times: List[float]
    envelope_rms: List[float]

    def summary(self) -> str:
        lines = [
            f"=== Acoustic Profile Summary ===",
            f"Sample Rate: {self.sample_rate} Hz | Duration: {self.duration_s:.2f}s",
            f"Peak RMS: {self.max_rms:.4f} | Mean RMS: {self.mean_rms:.4f}",
            f"Detected Transient Peaks ({len(self.peaks)}):"
        ]
        for p in self.peaks[:10]:
            lines.append(f"  - t = {p.timestamp_s:.3f}s (RMS: {p.amplitude_rms:.3f}, prominence: {p.relative_prominence:.2f})")
        lines.append("=== End Acoustic Summary ===")
        return "\n".join(lines)


class AudioTransducer:
    """Deterministic transducer for audio waveforms and soundtrack analysis."""

    def __init__(self, audio_source: Union[str, Path]):
        self.source_path = Path(audio_source)
        self.wav_path = self._prepare_wav_source(self.source_path)
        if not HAS_SCIPY:
            raise ImportError("scipy is required for AudioTransducer.")
        
        self.sample_rate, self.raw_data = wavfile.read(str(self.wav_path))
        # Convert stereo to mono if needed
        if len(self.raw_data.shape) > 1:
            self.data = np.mean(self.raw_data, axis=1).astype(np.float32)
        else:
            self.data = self.raw_data.astype(np.float32)

        # Normalize to [-1.0, 1.0]
        max_val = np.max(np.abs(self.data)) + 1e-6
        self.norm_data = self.data / max_val
        self.duration_s = len(self.norm_data) / self.sample_rate

    def _prepare_wav_source(self, source_path: Path) -> Path:
        """Ensure the source is a valid 16kHz WAV file, demuxing if it is a video."""
        if source_path.suffix.lower() == ".wav":
            return source_path

        # If it's a video, demux to a sibling WAV file
        if not HAS_FFMPEG:
            raise ImportError("imageio-ffmpeg is required to demux audio from video files.")

        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        out_wav = source_path.with_name(f"{source_path.stem}_transduced.wav")
        if not out_wav.exists() or out_wav.stat().st_size == 0:
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(source_path),
                "-vn", "-ac", "1", "-ar", "16000",
                str(out_wav)
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        return out_wav

    def compute_rms_envelope(self, window_size_s: float = 0.05) -> Tuple[np.ndarray, np.ndarray]:
        """Compute rolling RMS amplitude envelope with fixed temporal resolution."""
        win_samples = max(1, int(self.sample_rate * window_size_s))
        n_windows = len(self.norm_data) // win_samples
        
        envelope = np.zeros(n_windows, dtype=np.float32)
        for i in range(n_windows):
            chunk = self.norm_data[i * win_samples : (i + 1) * win_samples]
            envelope[i] = np.sqrt(np.mean(chunk ** 2))

        times = np.arange(n_windows) * window_size_s
        return times, envelope

    def detect_transient_peaks(
        self,
        window_size_s: float = 0.025,
        std_multiplier: float = 2.0,
        min_distance_s: float = 0.08
    ) -> List[AcousticPeak]:
        """Detect sharp transient impulse peaks (e.g. gunshots, explosions, ability casts)."""
        times, env = self.compute_rms_envelope(window_size_s=window_size_s)
        mean_rms = float(np.mean(env))
        std_rms = float(np.std(env))
        threshold = mean_rms + std_multiplier * std_rms
        min_dist_idx = max(1, int(min_distance_s / window_size_s))

        peaks: List[AcousticPeak] = []
        last_peak_idx = -min_dist_idx

        for idx in range(1, len(env) - 1):
            if env[idx] > threshold and env[idx] > env[idx - 1] and env[idx] >= env[idx + 1]:
                if (idx - last_peak_idx) >= min_dist_idx:
                    prominence = (env[idx] - mean_rms) / (std_rms + 1e-6)
                    t_val = round(float(times[idx]), 3)
                    
                    # Compute frequency band energies for this transient
                    bands = self.get_frequency_band_energies(t_val - 0.05, t_val + 0.05)
                    peaks.append(AcousticPeak(
                        timestamp_s=t_val,
                        amplitude_rms=round(float(env[idx]), 4),
                        relative_prominence=round(float(prominence), 2),
                        channel_energy=bands
                    ))
                    last_peak_idx = idx

        return peaks

    def get_frequency_band_energies(self, start_s: float, end_s: float) -> Dict[str, float]:
        """Measure relative energy in Low (<500Hz), Mid (500Hz-3kHz), and High (>3kHz) bands."""
        s_idx = max(0, int(start_s * self.sample_rate))
        e_idx = min(len(self.norm_data), int(end_s * self.sample_rate))
        if e_idx <= s_idx:
            return {"low": 0.0, "mid": 0.0, "high": 0.0}

        slice_data = self.norm_data[s_idx:e_idx]
        if len(slice_data) < 32:
            return {"low": 0.0, "mid": 0.0, "high": 0.0}

        fft_vals = np.abs(np.fft.rfft(slice_data))
        freqs = np.fft.rfftfreq(len(slice_data), 1.0 / self.sample_rate)

        low_mask = freqs < 500.0
        mid_mask = (freqs >= 500.0) & (freqs < 3000.0)
        high_mask = freqs >= 3000.0

        total = np.sum(fft_vals) + 1e-6
        return {
            "low": round(float(np.sum(fft_vals[low_mask]) / total), 3),
            "mid": round(float(np.sum(fft_vals[mid_mask]) / total), 3),
            "high": round(float(np.sum(fft_vals[high_mask]) / total), 3)
        }

    def analyze_profile(self) -> AcousticProfileResult:
        """Full deterministic pass returning peaks and RMS profile."""
        times, env = self.compute_rms_envelope(window_size_s=0.05)
        peaks = self.detect_transient_peaks()
        return AcousticProfileResult(
            sample_rate=self.sample_rate,
            duration_s=self.duration_s,
            max_rms=round(float(np.max(env)), 4) if len(env) > 0 else 0.0,
            mean_rms=round(float(np.mean(env)), 4) if len(env) > 0 else 0.0,
            peaks=peaks,
            envelope_times=[round(float(t), 3) for t in times],
            envelope_rms=[round(float(e), 4) for e in env]
        )
