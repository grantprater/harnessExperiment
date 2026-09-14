"""Unit tests for General Domain Harness (doc_perception, evidence_ledger, synthetic_verifier)."""
import unittest
from pathlib import Path
import tempfile

from doc_perception import extract_doc_map, extract_section, extract_passage, parse_document_structure
from evidence_ledger import EvidenceLedger
from synthetic_verifier import SyntheticInvariantVerifier


SAMPLE_DOC = """# Vendor Agreement: Acme Corp & Globex

## 1. Scope of Work
Acme shall provide cloud operations and real-time event routing.
All work will be performed under standard SLA agreements.

## 2. SLA & Penalties
Monthly uptime guarantee is set at 99.95 percent.
If monthly uptime drops below 99.95 percent, a 10 percent credit will be issued.
Unplanned outages exceeding 4 hours result in a 25 percent penalty.

## 3. Limitation of Liability
Neither party shall be liable for indirect or consequential damages.
Maximum cumulative liability is strictly capped at 50,000 USD.
"""


class GeneralDomainHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.doc_path = self.base_path / "agreement.md"
        self.doc_path.write_text(SAMPLE_DOC, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_doc_perception_structure(self):
        sections = parse_document_structure(SAMPLE_DOC)
        titles = [s.title for s in sections]
        self.assertIn("1. Scope of Work", titles)
        self.assertIn("2. SLA & Penalties", titles)
        self.assertIn("3. Limitation of Liability", titles)

    def test_doc_perception_section_extraction(self):
        sec = extract_section(self.doc_path, "Limitation of Liability")
        self.assertIn("strictly capped at 50,000 USD", sec)
        self.assertIn("Section View", sec)

    def test_doc_perception_passage_saccade(self):
        pas = extract_passage(self.doc_path, 8, 12)
        self.assertIn("uptime drops below 99.95 percent", pas)
        self.assertIn("Passage Saccade", pas)

    def test_evidence_ledger_lifecycle(self):
        ledger = EvidenceLedger()
        atom = ledger.record_evidence(
            claim="Liability cap is 50,000 USD.",
            source_doc="agreement.md",
            section="3. Limitation of Liability",
            verbatim_quote="Maximum cumulative liability is strictly capped at 50,000 USD.",
            topic="liability"
        )
        self.assertEqual(atom.atom_id, "ev_001")
        ledger.mark_evaporated("agreement.md", "Section 3 distilled; liability cap extracted.")

        view = ledger.render_ledger_view()
        self.assertIn("ev_001", view)
        self.assertIn("50,000 USD", view)
        self.assertIn("Evaporated Source Documents", view)

    def test_synthetic_verifier_validates_grounding(self):
        ledger = EvidenceLedger()
        ledger.record_evidence(
            claim="Monthly uptime guarantee is 99.95 percent.",
            source_doc="agreement.md",
            section="2. SLA & Penalties",
            verbatim_quote="Monthly uptime guarantee is set at 99.95 percent.",
            topic="sla"
        )
        verifier = SyntheticInvariantVerifier(ledger, root_dir=self.base_path)

        # Passing draft with valid citation
        good_draft = "Under the SLA, the monthly uptime guarantee is set at 99.95 percent [ev_001]."
        report = verifier.verify_draft(good_draft)
        self.assertTrue(report.passed)
        self.assertEqual(report.citations_verified, 1)

        # Failing draft with hallucinated / fake quote
        bad_ledger = EvidenceLedger()
        bad_ledger.record_evidence(
            claim="Unlimited liability applies.",
            source_doc="agreement.md",
            section="3",
            verbatim_quote="This sentence does not exist anywhere in the document.",
            topic="liability"
        )
        bad_verifier = SyntheticInvariantVerifier(bad_ledger, root_dir=self.base_path)
        bad_report = bad_verifier.verify_draft("Unlimited liability [ev_001].")
        self.assertFalse(bad_report.passed)
        self.assertEqual(bad_report.citations_failed, 1)


if __name__ == "__main__":
    unittest.main()
