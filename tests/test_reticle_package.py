"""Unit Tests for the Unified Reticle Cognitive Harness Package."""

from __future__ import annotations

import unittest
from pathlib import Path
from PIL import Image

import reticle
from reticle.core.evidence_ledger import EvidenceLedger
from reticle.core.world_line_ledger import WorldLineLedger
from reticle.core.verifier_base import VerificationResult
from reticle.sensory.spatial_saccade import (
    create_spatial_grid,
    foveated_crop,
    project_to_global,
    project_to_local
)
from reticle.sensory.temporal_transducer import (
    compute_frame_difference,
    detect_motion_intervals
)
from reticle.adapters.code_ast import parse_and_inspect_code, validate_python_syntax
from reticle.adapters.blender_engine import verify_blender_installed, get_blender_path
from reticle.verifiers.spatial_verifier import is_point_inside_bbox, compute_iou, evaluate_grounding
from reticle.verifiers.temporal_verifier import TemporalInvariantVerifier
from reticle.verifiers.synthetic_verifier import SyntheticInvariantVerifier


class TestReticlePackage(unittest.TestCase):

    def test_package_version(self):
        self.assertEqual(reticle.__version__, "0.2.0")

    def test_evidence_ledger_lifecycle(self):
        ledger = EvidenceLedger()
        atom = ledger.record_evidence(
            claim="Zero-surprise silence drops matching frames.",
            source_doc="ARCHITECTURE.md",
            section="Section 3",
            verbatim_quote="If reality matches prediction, the interaction is wiped.",
            topic="memory"
        )
        self.assertEqual(atom.atom_id, "ev_001")
        self.assertEqual(len(ledger.atoms), 1)

        ledger.mark_evaporated("ARCHITECTURE.md", "Distilled 1 atom from doc.")
        view = ledger.render_ledger_view()
        self.assertIn("ev_001", view)
        self.assertIn("memory", view)

    def test_world_line_ledger_lifecycle(self):
        ledger = WorldLineLedger()
        item = ledger.record_interval(
            entity_id="drone_01",
            label="Recon Drone",
            t_start=0.0,
            t_end=5.0,
            state_predicate="in_motion",
            start_coords=(0.0, 0.0),
            end_coords=(10.0, 10.0),
            provenance_frames=[0, 150]
        )
        self.assertEqual(item.interval_id, "wl_001")
        self.assertEqual(len(ledger.intervals), 1)
        view = ledger.render_ledger_view()
        self.assertIn("drone_01", view)
        self.assertIn("in_motion", view)

    def test_spatial_saccade_and_projections(self):
        grid = create_spatial_grid(1920, 1080, rows=3, cols=3)
        self.assertEqual(len(grid), 9)

        # Center sector S_1_1
        center_sec = next(s for s in grid if s.sector_id == "S_1_1")
        self.assertTrue(center_sec.contains_point(960, 540))

        # Test coordinate projection
        local_pt = project_to_local((960, 540), center_sec.bbox)
        global_pt = project_to_global(local_pt, center_sec.bbox)
        self.assertEqual(global_pt, (960.0, 540.0))

    def test_spatial_verifier_grounding(self):
        bbox = (100, 100, 200, 200)
        self.assertTrue(is_point_inside_bbox((150, 150), bbox))
        self.assertFalse(is_point_inside_bbox((50, 50), bbox))

        res = evaluate_grounding((150, 150), bbox, (1920, 1080))
        self.assertTrue(res.hit)
        self.assertEqual(res.euclidean_distance_px, 0.0)
        self.assertGreater(res.token_savings_pct, 50.0)

    def test_temporal_ltl_verifier(self):
        ledger = WorldLineLedger()
        ledger.record_interval(
            entity_id="bot",
            label="Patrol Bot",
            t_start=0.0,
            t_end=2.0,
            state_predicate="at_rest",
            start_coords=(10.0, 10.0),
            end_coords=(10.0, 10.0)
        )
        ledger.record_interval(
            entity_id="bot",
            label="Patrol Bot",
            t_start=2.0,
            t_end=4.0,
            state_predicate="in_motion",
            start_coords=(10.0, 10.0),
            end_coords=(20.0, 10.0)
        )

        verifier = TemporalInvariantVerifier(ledger, fps=10.0, max_velocity_px_per_s=50.0)
        res = verifier.verify_temporal_invariants()
        self.assertTrue(res.passed)
        self.assertEqual(res.score, 1.0)
        self.assertEqual(len(res.detected_violations), 0)

    def test_code_ast_adapter(self):
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        ok, err = validate_python_syntax(valid_code)
        self.assertTrue(ok)
        self.assertIsNone(err)

        res = parse_and_inspect_code(valid_code)
        self.assertTrue(res.valid)
        self.assertIn("add", res.functions)

        invalid_code = "def broken(:\n    pass\n"
        ok_bad, err_bad = validate_python_syntax(invalid_code)
        self.assertFalse(ok_bad)
        self.assertIsNotNone(err_bad)

    def test_blender_engine_discovery(self):
        installed = verify_blender_installed()
        path = get_blender_path()
        # On this machine, Blender 5.0 is installed
        self.assertTrue(installed)
        self.assertIsNotNone(path)


if __name__ == "__main__":
    unittest.main()
