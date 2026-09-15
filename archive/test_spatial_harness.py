"""Unit tests for Spatial Perception Engine and Verifier."""

from __future__ import annotations

import unittest
from pathlib import Path
from PIL import Image

import spatial_loader as sl
import spatial_perception as sp
import spatial_verifier as sv


class SpatialHarnessTests(unittest.TestCase):

    def test_create_spatial_grid_partitions_canvas(self):
        grid = sp.create_spatial_grid(3840, 2160, rows=3, cols=3)
        self.assertEqual(len(grid), 9)
        top_left = grid[0]
        self.assertEqual(top_left.sector_id, "S_0_0")
        self.assertEqual(top_left.name, "Top-Left (Toolbar / Menu)")
        # Check center contains center point
        center = next(s for s in grid if s.sector_id == "S_1_1")
        self.assertTrue(center.contains_point(1920, 1080))

    def test_foveated_crop_and_coordinate_projection(self):
        # Create a test synthetic 1000x1000 image
        img = Image.new("RGB", (1000, 1000), color="white")
        crop_box = (200, 300, 600, 700)  # width 400, height 400
        cropped = sp.foveated_crop(img, crop_box)
        self.assertEqual(cropped.size, (400, 400))

        # Local point (50, 50) inside the crop corresponds to global (250, 350)
        local_pt = (50, 50)
        global_pt = sp.project_to_global(local_pt, crop_box)
        self.assertEqual(global_pt, (250.0, 350.0))

        # Reverse projection
        self.assertEqual(sp.project_to_local(global_pt, crop_box), (50.0, 50.0))

    def test_spatial_verifier_containment_oracle(self):
        bbox = (100, 200, 300, 400)
        # Inside
        self.assertTrue(sv.is_point_inside_bbox((150, 250), bbox))
        self.assertTrue(sv.is_point_inside_bbox((100, 200), bbox))  # boundary
        # Outside
        self.assertFalse(sv.is_point_inside_bbox((50, 250), bbox))
        self.assertFalse(sv.is_point_inside_bbox((150, 450), bbox))

    def test_spatial_verifier_iou(self):
        box1 = (0, 0, 100, 100)  # area 10,000
        box2 = (50, 0, 150, 100)  # area 10,000, overlap 50x100 = 5,000
        # union = 15,000, iou = 5000/15000 = 0.3333
        iou = sv.compute_iou(box1, box2)
        self.assertAlmostEqual(iou, 0.3333, places=3)

    def test_real_screenspot_sample_grounding_verification(self):
        # Load real cached sample from ScreenSpot-Pro
        sample = sl.load_spatial_sample("android_studio_macos", 0)
        bbox = tuple(sample["ground_truth_bbox"])  # [1774, 1586, 2113, 1618]
        canvas = sample["canvas_size"]  # (3840, 2160)

        # Target center point
        center = sample["target_center"]

        # Exact hit evaluation
        eval_hit = sv.evaluate_grounding(center, bbox, canvas)
        self.assertTrue(eval_hit.hit)
        self.assertEqual(eval_hit.euclidean_distance_px, 0.0)
        self.assertGreater(eval_hit.token_savings_pct, 60.0)

        # Near miss point (10 px below bottom)
        miss_pt = (center[0], bbox[3] + 10)
        eval_miss = sv.evaluate_grounding(miss_pt, bbox, canvas)
        self.assertFalse(eval_miss.hit)


if __name__ == "__main__":
    unittest.main()
