"""Geometry predicates tested without requiring Blender in the test interpreter."""
import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[1] / 'examples/extensions/blender_mesh_audit/mesh_audit.py'
spec = importlib.util.spec_from_file_location('mesh_quality', path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class MeshGeometryTests(unittest.TestCase):
    def test_triangle_overlap_is_independent_of_winding(self):
        first = [(0, 0), (1, 0), (0, 1)]
        self.assertAlmostEqual(audit.triangle_overlap_area(first, first), 0.5)
        self.assertAlmostEqual(audit.triangle_overlap_area(first[::-1], first), 0.5)
        self.assertAlmostEqual(audit.triangle_overlap_area(first, first[::-1]), 0.5)

    def test_touching_edges_and_vertices_have_no_positive_area(self):
        first = [(0, 0), (1, 0), (0, 1)]
        self.assertAlmostEqual(audit.triangle_overlap_area(first, [(1, 0), (1, 1), (0, 1)]), 0)
        self.assertAlmostEqual(audit.triangle_overlap_area(first, [(1, 0), (2, 0), (1, 1)]), 0)

    def test_partial_and_disjoint_overlap(self):
        first = [(0, 0), (1, 0), (0, 1)]
        self.assertAlmostEqual(audit.triangle_overlap_area(first, [(0.5, 0), (1.5, 0), (0.5, 1)]), 0.125)
        self.assertAlmostEqual(audit.triangle_overlap_area(first, [(2, 0), (3, 0), (2, 1)]), 0)


if __name__ == '__main__':
    unittest.main()
