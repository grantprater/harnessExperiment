"""Unit tests for Foveated Technical Document Generator & Verifier."""

from __future__ import annotations

import unittest
from pathlib import Path

from doc_generator import (
    DocumentBlueprint,
    FoveatedDocumentGenerator,
    SectionSpec,
    TechnicalSpecVerifier,
)
from evidence_ledger import EvidenceLedger


class DocumentGeneratorTests(unittest.TestCase):

    def setUp(self):
        self.ledger = EvidenceLedger()
        self.ledger.record_evidence(
            claim="PEP 695 introduces type parameter syntax using square brackets.",
            source_doc="pep-0695.rst",
            section="Specification",
            verbatim_quote="The syntax adds support for type parameters following the class name.",
            topic="syntax"
        )
        self.ledger.record_evidence(
            claim="Generic classes automatically inherit from Generic without explicit declaration.",
            source_doc="pep-0695.rst",
            section="Specification",
            verbatim_quote="It is no longer necessary to inherit from Generic.",
            topic="inheritance"
        )

        self.blueprint = DocumentBlueprint(
            title="Specification for Modern Generic Classes in Python",
            abstract="Formal specification of PEP 695 type parameter syntax and generic class semantics.",
            doc_type="PEP",
            sections=[
                SectionSpec(
                    title="Introduction & Motivation",
                    level=2,
                    intent="Explain the need for clean type parameter syntax.",
                    required_invariants=["PEP 695", "square brackets"],
                    evidence_topics=["syntax"],
                    target_words=50
                ),
                SectionSpec(
                    title="Syntax Specification",
                    level=2,
                    intent="Detail the class Stack[T] syntax and Generic inheritance rules.",
                    required_invariants=["Stack[T]", "Generic"],
                    evidence_topics=["inheritance"],
                    target_words=80,
                    must_contain_code=True
                )
            ]
        )
        self.verifier = TechnicalSpecVerifier(self.blueprint, self.ledger)

    def test_spec_verifier_passes_valid_document(self):
        valid_doc = (
            "# Specification for Modern Generic Classes in Python\n\n"
            "## Introduction & Motivation\n"
            "This specification covers PEP 695 type parameter declarations using square brackets [ev_001].\n\n"
            "## Syntax Specification\n"
            "Modern syntax uses `class Stack[T]:`. It eliminates the need to explicitly inherit from Generic [ev_002].\n\n"
            "```python\n"
            "class Stack[T]:\n"
            "    def __init__(self) -> None:\n"
            "        self.items: list[T] = []\n"
            "```\n"
        )
        res = self.verifier.verify_document(valid_doc)
        self.assertTrue(res.passed, f"Failed verification: {res.summary()}")
        self.assertEqual(len(res.missing_sections), 0)
        self.assertEqual(len(res.code_syntax_errors), 0)
        self.assertEqual(len(res.citation_errors), 0)

    def test_spec_verifier_catches_invalid_python_syntax(self):
        bad_code_doc = (
            "# Specification for Modern Generic Classes in Python\n\n"
            "## Introduction & Motivation\n"
            "This specification covers PEP 695 with square brackets [ev_001].\n\n"
            "## Syntax Specification\n"
            "Modern syntax uses Stack[T] without Generic.\n\n"
            "```python\n"
            "class Stack[T]\n"  # Missing colon -> SyntaxError!
            "    invalid python code syntax = @@@\n"
            "```\n"
        )
        res = self.verifier.verify_document(bad_code_doc)
        self.assertFalse(res.passed)
        self.assertTrue(any("syntax error" in err.lower() for err in res.code_syntax_errors))

    def test_spec_verifier_catches_phantom_citation(self):
        phantom_doc = (
            "# Specification for Modern Generic Classes in Python\n\n"
            "## Introduction & Motivation\n"
            "This specification covers PEP 695 with square brackets [ev_999].\n\n"  # ev_999 is hallucinated!
            "## Syntax Specification\n"
            "Modern syntax uses Stack[T] without Generic [ev_002].\n\n"
            "```python\n"
            "class Stack[T]:\n"
            "    pass\n"
            "```\n"
        )
        res = self.verifier.verify_document(phantom_doc)
        self.assertFalse(res.passed)
        self.assertTrue(any("ev_999" in err for err in res.citation_errors))

    def test_spec_verifier_catches_missing_invariant(self):
        missing_inv_doc = (
            "# Specification for Modern Generic Classes in Python\n\n"
            "## Introduction & Motivation\n"
            "This introduction mentions some concepts but forgets the required keyword.\n\n"
            "## Syntax Specification\n"
            "Here is Stack[T] without Generic.\n\n"
            "```python\n"
            "class Stack[T]:\n"
            "    pass\n"
            "```\n"
        )
        res = self.verifier.verify_document(missing_inv_doc)
        self.assertFalse(res.passed)
        self.assertTrue(any("PEP 695" in inv for inv in res.unfulfilled_invariants))

    def test_foveated_generator_with_mock_llm(self):
        def mock_llm(prompt: str) -> str:
            if "Introduction & Motivation" in prompt:
                return "## Introduction & Motivation\nThis covers PEP 695 and square brackets for generics [ev_001]."
            elif "Syntax Specification" in prompt:
                return (
                    "## Syntax Specification\n"
                    "We declare `class Stack[T]:` without subclassing Generic [ev_002].\n\n"
                    "```python\n"
                    "class Stack[T]:\n"
                    "    def push(self, item: T) -> None:\n"
                    "        pass\n"
                    "```"
                )
            return "Unknown section"

        generator = FoveatedDocumentGenerator(self.blueprint, self.ledger, mock_llm)
        full_doc, res = generator.generate_document()
        self.assertTrue(res.passed, f"Generator failed: {res.summary()}")
        self.assertIn("class Stack[T]:", full_doc)
        self.assertIn("[ev_001]", full_doc)
        self.assertIn("[ev_002]", full_doc)


if __name__ == "__main__":
    unittest.main()
