"""Unit tests for the HotpotQA evaluation's parsing and scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "hotpotqa_eval"))

from hotpotqa_scoring import bootstrap_ci, exact_match, f1, normalize_answer, parse_answer, parse_titles


class TestNormalizeAndScore(unittest.TestCase):
    def test_normalize_strips_case_punctuation_and_articles(self):
        self.assertEqual(normalize_answer("The  Chief of Protocol."), "chief of protocol")

    def test_exact_match_after_normalization(self):
        self.assertEqual(exact_match("the Chief of Protocol", "Chief of Protocol"), 1.0)
        self.assertEqual(exact_match("Chief", "Chief of Protocol"), 0.0)

    def test_f1_partial_overlap(self):
        # pred tokens {chief}, gold {chief, of, protocol}: precision 1, recall 1/3
        self.assertAlmostEqual(f1("Chief", "Chief of Protocol"), 0.5)

    def test_yes_no_needs_exact_agreement(self):
        self.assertEqual(f1("no", "not known"), 0.0)
        self.assertEqual(f1("yes", "yes"), 1.0)
        self.assertEqual(f1("yes they are", "yes"), 0.0)

    def test_substring_is_not_a_match(self):
        # The old benchmark counted gold "no" as found inside "not" or "known".
        self.assertEqual(exact_match("It is not known", "no"), 0.0)
        self.assertEqual(f1("It is not known", "no"), 0.0)


class TestParseAnswer(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_answer("Answer: YG Entertainment"), ("YG Entertainment", True))

    def test_markdown_and_trailing_period(self):
        self.assertEqual(parse_answer("Reasoning...\n**Answer:** Chief of Protocol."), ("Chief of Protocol", True))

    def test_last_answer_line_wins(self):
        self.assertEqual(parse_answer("Answer: maybe\nActually,\nAnswer: yes"), ("yes", True))

    def test_missing_answer_line_flags_format(self):
        self.assertEqual(parse_answer("  YG Entertainment "), ("YG Entertainment", False))


class TestParseTitles(unittest.TestCase):
    TITLES = ["Ed Wood", "Ed Wood (film)", "Scott Derrickson", "Doctor Strange"]

    def test_json_list(self):
        self.assertEqual(parse_titles('Documents: ["Scott Derrickson", "Ed Wood"]', self.TITLES),
                         ["Scott Derrickson", "Ed Wood"])

    def test_quoted_titles_case_insensitive(self):
        self.assertEqual(parse_titles('I need "ed wood (film)" and "Doctor Strange".', self.TITLES),
                         ["Ed Wood (film)", "Doctor Strange"])

    def test_bare_comma_separated_titles(self):
        # Real reply from the first run: both gold titles, exact, but unquoted.
        titles = ["2009 Colorado Buffaloes football team", "2009 Big 12 Conference football season", "Other"]
        self.assertEqual(parse_titles("2009 Big 12 Conference football season, 2009 Colorado Buffaloes football team",
                                      titles),
                         ["2009 Big 12 Conference football season", "2009 Colorado Buffaloes football team"])

    def test_unquoted_titles_in_brackets(self):
        # Real reply from the long-context run.
        self.assertEqual(parse_titles("[Charmed, Rose McGowan]", ["Charmed", "Rose McGowan", "Other"]),
                         ["Charmed", "Rose McGowan"])

    def test_bare_title_containing_comma(self):
        self.assertEqual(parse_titles("Documents: Washington, D.C., Paris", ["Washington, D.C.", "Paris", "D.C."]),
                         ["Washington, D.C.", "Paris"])

    def test_no_substring_matching(self):
        self.assertEqual(parse_titles("Documents: Ed Wood and Scott Derrickson", self.TITLES), [])

    def test_unknown_titles_ignored_and_limit(self):
        self.assertEqual(parse_titles('["Nope", "Ed Wood", "Ed Wood", "Scott Derrickson", "Doctor Strange"]',
                                      self.TITLES), ["Ed Wood", "Scott Derrickson"])


class TestDistractorPadding(unittest.TestCase):
    @staticmethod
    def make_row(qid, titles):
        return {"id": qid, "question": "?", "answer": "a", "type": "bridge",
                "supporting_facts": {"title": titles[:2], "sent_id": [0, 0]},
                "documents": [{"title": t, "text": t, "sentences": [t]} for t in titles]}

    def setUp(self):
        import run_eval
        self.pad = run_eval.pad_with_distractors
        self.rows = [self.make_row(f"q{i}", [f"T{i}_{j}" for j in range(10)]) for i in range(5)]

    def test_adds_k_unique_foreign_documents_and_keeps_originals(self):
        out = self.pad(self.rows[:1], self.rows, 20, seed=0)[0]
        titles = [d["title"] for d in out["documents"]]
        self.assertEqual(len(titles), 30)
        self.assertEqual(len(set(titles)), 30)
        self.assertEqual(sum(t.startswith("T0_") for t in titles), 10)

    def test_deterministic_and_seed_dependent(self):
        a = self.pad(self.rows[:1], self.rows, 20, seed=0)[0]["documents"]
        self.assertEqual(a, self.pad(self.rows[:1], self.rows, 20, seed=0)[0]["documents"])
        self.assertNotEqual(a, self.pad(self.rows[:1], self.rows, 20, seed=1)[0]["documents"])

    def test_zero_distractors_is_unchanged_and_input_not_mutated(self):
        original = [d["title"] for d in self.rows[0]["documents"]]
        self.assertIs(self.pad(self.rows[:1], self.rows, 0, seed=0)[0], self.rows[0])
        self.pad(self.rows[:1], self.rows, 20, seed=0)
        self.assertEqual([d["title"] for d in self.rows[0]["documents"]], original)


class TestBootstrap(unittest.TestCase):
    def test_constant_differences_give_degenerate_interval(self):
        self.assertEqual(bootstrap_ci([0.5] * 10), (0.5, 0.5, 0.5))

    def test_interval_contains_mean_and_is_deterministic(self):
        diffs = [1.0, 0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 1.0]
        mean, lo, hi = bootstrap_ci(diffs)
        self.assertLessEqual(lo, mean)
        self.assertLessEqual(mean, hi)
        self.assertEqual(bootstrap_ci(diffs), (mean, lo, hi))

    def test_too_few_values(self):
        self.assertIsNone(bootstrap_ci([1.0]))


if __name__ == "__main__":
    unittest.main()
