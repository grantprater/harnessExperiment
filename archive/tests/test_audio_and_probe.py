"""Tests for Audio Transducer and Dynamic Perceptual Probing Engine."""

from __future__ import annotations

import unittest
from pathlib import Path
import numpy as np
import cv2

from reticle.sensory.audio_transducer import AudioTransducer, HAS_SCIPY
from reticle.sensory.perceptual_probe import PerceptualProbeRunner


class TestAudioAndPerceptualProbe(unittest.TestCase):

    def test_audio_transducer_analysis(self):
        if not HAS_SCIPY:
            self.skipTest("scipy not available")

        wav_path = Path(__file__).resolve().parents[1] / "experiments" / "reticle_audio.wav"
        if not wav_path.exists():
            self.skipTest(f"Audio file not found at {wav_path}")

        transducer = AudioTransducer(wav_path)
        self.assertEqual(transducer.sample_rate, 16000)
        self.assertGreater(transducer.duration_s, 40.0)

        times, env = transducer.compute_rms_envelope(window_size_s=0.05)
        self.assertEqual(len(times), len(env))
        self.assertGreater(len(env), 800)

        peaks = transducer.detect_transient_peaks(std_multiplier=2.5)
        self.assertGreater(len(peaks), 0)

        # Check frequency band decomposition
        bands = transducer.get_frequency_band_energies(40.0, 41.0)
        self.assertIn("low", bands)
        self.assertIn("mid", bands)
        self.assertIn("high", bands)
        band_sum = sum(bands.values())
        self.assertAlmostEqual(band_sum, 1.0, places=1)

    def test_probe_runner_custom_code(self):
        runner = PerceptualProbeRunner()
        script = """
arr = np.array([10, 20, 30, 40])
probe_result["mean_val"] = float(np.mean(arr))
probe_result["max_val"] = int(np.max(arr))
"""
        res = runner.execute_probe(script)
        self.assertTrue(res.success)
        self.assertEqual(res.data["mean_val"], 25.0)
        self.assertEqual(res.data["max_val"], 40)

    def test_probe_runner_error_handling(self):
        runner = PerceptualProbeRunner()
        bad_script = "x = 1 / 0"
        res = runner.execute_probe(bad_script)
        self.assertFalse(res.success)
        self.assertIsNotNone(res.error)
        self.assertIn("ZeroDivisionError", res.error)

    def test_probe_color_centroid(self):
        # Create a blank black image with a bright cyan square
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        # BGR cyan: [255, 255, 0]
        img[50:100, 50:100] = [255, 255, 0]

        # HSV for cyan roughly: H in [80, 100], S in [150, 255], V in [150, 255]
        res = PerceptualProbeRunner.probe_color_centroid(
            img,
            lower_hsv=(80, 150, 150),
            upper_hsv=(105, 255, 255)
        )
        self.assertTrue(res["found"])
        self.assertGreater(res["pixel_count"], 2000)
        cx, cy = res["centroid"]
        self.assertAlmostEqual(cx, 74, delta=3)
        self.assertAlmostEqual(cy, 74, delta=3)

    def test_probe_optical_flow(self):
        # Create two frames with shifted white square
        frame1 = np.zeros((180, 320, 3), dtype=np.uint8)
        frame2 = np.zeros((180, 320, 3), dtype=np.uint8)

        frame1[60:120, 100:160] = 255
        frame2[60:120, 120:180] = 255  # shifted right by 20px

        flow_res = PerceptualProbeRunner.probe_optical_flow(frame1, frame2)
        self.assertGreater(flow_res["mean_magnitude"], 0.1)
        # Shift was purely horizontal to the right (dx > 0)
        self.assertGreater(flow_res["mean_dx"], 0.0)


if __name__ == "__main__":
    unittest.main()
