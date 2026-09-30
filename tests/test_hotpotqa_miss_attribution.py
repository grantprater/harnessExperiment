"""Data-free tests for the HotpotQA miss-attribution helpers."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "hotpotqa_eval" / "miss_attribution"))

from miss_attribution import classify, link_candidates, link_key, pair_linked, parse_docs  # noqa: E402

PROMPT = """Answer the question using the documents below.

=== Ed Wood (film) ===
Ed Wood is a 1994 film directed by Tim Burton.

=== Tim Burton ===
Tim Burton is an American filmmaker.

=== Scott Derrickson ===
Scott Derrickson is an American director.

=== Wood ===
Wood is a material.

Question: Who directed Ed Wood?
Give the shortest possible answer."""


class MissAttributionTests(unittest.TestCase):
    def test_parse_docs_splits_blocks_and_drops_question(self):
        docs = parse_docs(PROMPT)
        self.assertEqual(list(docs), ["Ed Wood (film)", "Tim Burton", "Scott Derrickson", "Wood"])
        self.assertEqual(docs["Wood"], "Wood is a material.")

    def test_link_key_strips_disambiguator_and_short_titles(self):
        self.assertEqual(link_key("Ed Wood (film)"), "ed wood")
        self.assertIsNone(link_key("Abc"))

    def test_forward_links_come_first_and_whole_words_only(self):
        docs = parse_docs(PROMPT)
        # "Ed Wood (film)" mentions "Wood" (whole word, at position 3) before "Tim Burton": both are
        # forward links, ordered by first mention. "Scott Derrickson" links to nothing.
        cands = link_candidates(["Ed Wood (film)", "Scott Derrickson"], docs)
        self.assertEqual(cands, ["Wood", "Tim Burton"])
        self.assertEqual(link_candidates(["Tim Burton"], docs, "forward"), [])
        self.assertEqual(link_candidates(["Tim Burton"], docs, "both"), ["Ed Wood (film)"])  # back link

    def test_pair_linked_and_classify(self):
        docs = parse_docs(PROMPT)
        self.assertTrue(pair_linked(["Ed Wood (film)", "Tim Burton"], docs))
        self.assertFalse(pair_linked(["Scott Derrickson", "Wood"], docs))
        self.assertEqual(classify(2, 2, 1.0), "a")
        self.assertEqual(classify(2, 2, 0.0), "b")
        self.assertEqual(classify(1, 2, 1.0), "c")
        self.assertEqual(classify(0, 2, 1.0), "d")


if __name__ == "__main__":
    unittest.main()
