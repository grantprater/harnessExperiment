"""Unit Tests for the Unified Reticle Cognitive Harness Package."""

from __future__ import annotations

import os
import unittest

import reticle
from reticle.core.evidence_ledger import EvidenceLedger
from reticle.core.verifier_base import VerificationResult
from reticle.adapters.code_ast import parse_and_inspect_code, validate_python_syntax
from reticle.adapters.blender_engine import verify_blender_installed, get_blender_path
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

    @unittest.skipUnless(os.name == "nt", "asserts the Windows host's Blender install")
    def test_blender_engine_discovery(self):
        installed = verify_blender_installed()
        path = get_blender_path()
        # On this machine, Blender 5.0 is installed
        self.assertTrue(installed)
        self.assertIsNotNone(path)


if __name__ == "__main__":
    unittest.main()
