"""Unit tests for Temporal Perception Engine, World-Line Ledger, and LTL Verifier."""

from __future__ import annotations

import unittest
from pathlib import Path
from PIL import Image

import temporal_perception as tp
from world_line_ledger import WorldLineLedger
from temporal_verifier import TemporalInvariantVerifier


class TemporalHarnessTests(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path("temporal_cache_test")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # Generate 10 synthetic frames: 0-3 static white, 4-7 black square moves, 8-9 static
        self.frames = []
        for i in range(10):
            im = Image.new("RGB", (200, 200), color="white")
            if 4 <= i <= 7:
                # Add moving black square
                x_offset = (i - 4) * 30
                for x in range(20 + x_offset, 60 + x_offset):
                    for y in range(50, 90):
                        im.putpixel((x, y), (0, 0, 0))
            f_path = self.tmp_dir / f"frame_{i:04d}.png"
            im.save(f_path)
            self.frames.append(f_path)

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_motion_energy_profile_isolates_moving_interval(self):
        profile = tp.compute_temporal_energy_profile(self.frames)
        self.assertEqual(len(profile), 9)

        # Frames 0-3: near zero motion
        for p in profile[:3]:
            self.assertLess(p["motion_energy"], 0.005)

        # Frames 4-7: positive motion energy
        for p in profile[3:7]:
            self.assertGreater(p["motion_energy"], 0.02)

        intervals = tp.detect_motion_intervals(profile, energy_threshold=0.015)
        self.assertEqual(len(intervals), 1)
        # Interval should start at frame 3/4 and end around 7/8
        self.assertTrue(3 <= intervals[0][0] <= 4)
        self.assertTrue(7 <= intervals[0][1] <= 9)

    def test_world_line_ledger_and_monotonicity(self):
        ledger = WorldLineLedger()
        ledger.record_interval(
            entity_id="Box_A",
            label="Black Box",
            t_start=0.0,
            t_end=1.0,
            state_predicate="at_rest",
            start_coords=(20.0, 50.0),
            end_coords=(20.0, 50.0)
        )
        ledger.record_interval(
            entity_id="Box_A",
            label="Black Box",
            t_start=1.0,
            t_end=2.5,
            state_predicate="in_motion",
            start_coords=(20.0, 50.0),
            end_coords=(110.0, 50.0)
        )
        view = ledger.render_ledger_view()
        self.assertIn("Box_A", view)
        self.assertIn("in_motion", view)

    def test_ltl_verifier_catches_teleportation(self):
        ledger = WorldLineLedger()
        # Interval 1: Box at (20, 50) at t in [0.0, 1.0]
        ledger.record_interval("Box_A", "Box", 0.0, 1.0, "at_rest", (20.0, 50.0), (20.0, 50.0))
        # Interval 2: Box instantaneously jumps to (500, 500) at t=1.0s (0 seconds delta!)
        ledger.record_interval("Box_A", "Box", 1.0, 2.0, "at_rest", (500.0, 500.0), (500.0, 500.0))

        verifier = TemporalInvariantVerifier(ledger, fps=10.0, max_velocity_px_per_s=100.0)
        res = verifier.verify_temporal_invariants()
        self.assertFalse(res.passed)
        self.assertTrue(any("teleportation" in v.lower() for v in res.detected_violations))

    def test_ltl_verifier_catches_hallucinated_motion(self):
        profile = tp.compute_temporal_energy_profile(self.frames)
        ledger = WorldLineLedger()
        # Claim that Box moved during frames 0-2 (where image was completely static white!)
        ledger.record_interval("Box_A", "Box", 0.0, 0.2, "in_motion", (0.0, 0.0), (10.0, 10.0))

        verifier = TemporalInvariantVerifier(ledger, energy_profile=profile, fps=10.0)
        res = verifier.verify_temporal_invariants()
        self.assertFalse(res.passed)
        self.assertTrue(any("hallucinated motion" in v.lower() for v in res.detected_violations))


if __name__ == "__main__":
    unittest.main()
