"""Unit tests for automated falsification extraction (reticle.cognitive.falsification).

Fixtures follow the exact formats Python 3.14's `python -m unittest` produced for the
Exercism tasks: FAIL/ERROR blocks, a test-module import failure, and a solution SyntaxError.
"""

from __future__ import annotations

import unittest

from reticle.cognitive.falsification import (
    DeadEndLedger,
    code_fingerprint,
    parse_approach,
    parse_unittest_output,
)

SEP = "=" * 70
DASH = "-" * 70


def failure_output(blocks, ran, summary):
    parts = [".F" * 2]
    for kind, test, message in blocks:
        parts += [SEP, f"{kind}: {test} (bst_test.BstTest.{test})", DASH,
                  "Traceback (most recent call last):",
                  f'  File "C:/tmp/bst_test.py", line 16, in {test}',
                  "    self.assertEqual(tree.data, '4')",
                  message, ""]
    parts += [DASH, f"Ran {ran} tests in 0.002s", "", summary, ""]
    return "\n".join(parts)


FAILS = failure_output(
    [("ERROR", "test_data_is_retained", "AttributeError: 'NoneType' object has no attribute 'data'"),
     ("FAIL", "test_sort_single", "AssertionError: None != ['2']")],
    ran=4, summary="FAILED (failures=1, errors=1)")

IMPORT_FAILURE = "\n".join([
    "E", SEP, "ERROR: paasio_test (unittest.loader._FailedTest.paasio_test)", DASH,
    "ImportError: Failed to import test module: paasio_test",
    "Traceback (most recent call last):",
    '  File "C:/tmp/paasio_test.py", line 6, in <module>',
    "    from test_utils import MockSock",
    "ModuleNotFoundError: No module named 'test_utils'", "", "",
    DASH, "Ran 1 test in 0.000s", "", "FAILED (errors=1)", ""])

SYNTAX_ERROR = "\n".join([
    "Traceback (most recent call last):",
    '  File "<frozen runpy>", line 198, in _run_module_as_main',
    '  File "C:/tmp/bowling.py", line 2',
    "    def __init__(self)",
    "                      ^",
    "SyntaxError: expected ':'", ""])

OK_OUTPUT = "\n".join(["....", DASH, "Ran 4 tests in 0.001s", "", "OK", ""])
OK_SKIPPED = "\n".join(["..s.", DASH, "Ran 4 tests in 0.001s", "", "OK (skipped=1)", ""])


class ParseUnittestOutputTests(unittest.TestCase):
    def test_fail_and_error_blocks(self):
        report = parse_unittest_output(FAILS)
        self.assertEqual(report.ran, 4)
        self.assertFalse(report.passed)
        self.assertIsNone(report.collection_error)
        self.assertEqual([(f.kind, f.test) for f in report.failures],
                         [("ERROR", "test_data_is_retained"), ("FAIL", "test_sort_single")])
        self.assertEqual(report.failures[1].message, "AssertionError: None != ['2']")

    def test_ok_and_skipped_pass(self):
        self.assertTrue(parse_unittest_output(OK_OUTPUT).passed)
        self.assertTrue(parse_unittest_output(OK_SKIPPED).passed)

    def test_import_failure_is_a_collection_error(self):
        report = parse_unittest_output(IMPORT_FAILURE)
        self.assertFalse(report.passed)
        self.assertEqual(report.failures, ())
        self.assertEqual(report.collection_error, "ModuleNotFoundError: No module named 'test_utils'")

    def test_syntax_error_without_summary(self):
        report = parse_unittest_output(SYNTAX_ERROR)
        self.assertEqual(report.ran, 0)
        self.assertEqual(report.collection_error, "SyntaxError: expected ':'")

    def test_timeout(self):
        report = parse_unittest_output("", timed_out=True)
        self.assertFalse(report.passed)
        self.assertTrue(report.collection_error.startswith("Timeout"))

    def test_signature_ignores_messages_but_not_exception_types(self):
        other_values = FAILS.replace("None != ['2']", "['9'] != ['2']")
        self.assertEqual(parse_unittest_output(FAILS).signature, parse_unittest_output(other_values).signature)
        other_type = FAILS.replace("AssertionError: None", "TypeError: None")
        self.assertNotEqual(parse_unittest_output(FAILS).signature, parse_unittest_output(other_type).signature)


class FingerprintAndApproachTests(unittest.TestCase):
    def test_fingerprint_ignores_comments_formatting_and_docstrings(self):
        a = "def add(a, b):\n    return a + b\n"
        b = 'def add( a,b ):\n    """Add."""\n    # sum\n    return (a + b)\n'
        self.assertEqual(code_fingerprint(a), code_fingerprint(b))
        self.assertNotEqual(code_fingerprint(a), code_fingerprint("def add(a, b):\n    return a - b\n"))

    def test_fingerprint_of_unparsable_code_ignores_trailing_whitespace(self):
        self.assertEqual(code_fingerprint("def broken(:\n  pass"), code_fingerprint("def broken(:   \n\n  pass\n"))

    def test_parse_approach(self):
        self.assertEqual(parse_approach("APPROACH: use a stack\n```python\n```"), ("use a stack", True))
        self.assertEqual(parse_approach("**APPROACH:** recursive descent parser"), ("recursive descent parser", True))
        self.assertEqual(parse_approach("```python\npass\n```"), ("", False))


def report_failing(*tests, ran=4, exc="AssertionError"):
    blocks = [("FAIL", t, f"{exc}: wrong") for t in tests]
    return parse_unittest_output(failure_output(blocks, ran=ran, summary=f"FAILED (failures={len(tests)})"))


class DeadEndLedgerTests(unittest.TestCase):
    def test_same_signature_merges_approaches(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "constant result", "x = 1", report_failing("test_a"))
        ledger.record_attempt(2, "lookup table", "x = 2", report_failing("test_a"))
        self.assertEqual(len(ledger.dead_ends), 1)
        d = ledger.dead_ends[0]
        self.assertEqual((d.attempts, d.first_turn, d.last_turn), (2, 1, 2))
        self.assertEqual(d.approaches, ["constant result", "lookup table"])

    def test_resolved_when_cited_tests_pass_and_reopened_on_recurrence(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "first idea", "x = 1", report_failing("test_a"))
        ledger.record_attempt(2, "second idea", "x = 2", report_failing("test_b"))
        f1, f2 = ledger.dead_ends
        self.assertEqual(f1.resolved_turn, 2)
        self.assertFalse(f2.resolved)
        rendered = ledger.render()
        self.assertIn("f_02", rendered)
        self.assertNotIn("first idea", rendered)
        self.assertIn("1 earlier dead end(s) resolved", rendered)

        ledger.record_attempt(3, "first idea again", "x = 3", report_failing("test_a"))
        self.assertFalse(f1.resolved)
        self.assertEqual(f2.resolved_turn, 3)

    def test_collection_errors_resolve_only_when_tests_run_again(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "broken syntax", "def f(:", parse_unittest_output(SYNTAX_ERROR))
        ledger.record_attempt(2, "still broken", "def g(:", parse_unittest_output("", timed_out=True))
        self.assertFalse(ledger.dead_ends[0].resolved)
        ledger.record_attempt(3, "compiles now", "x = 1", report_failing("test_a"))
        self.assertTrue(ledger.dead_ends[0].resolved)
        self.assertTrue(ledger.dead_ends[1].resolved)

    def test_collection_error_does_not_resolve_test_failures(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "idea", "x = 1", report_failing("test_a"))
        ledger.record_attempt(2, "typo", "def f(:", parse_unittest_output(SYNTAX_ERROR))
        self.assertFalse(ledger.dead_ends[0].resolved)

    def test_passing_attempt_resolves_everything(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "idea", "x = 1", report_failing("test_a"))
        self.assertIsNone(ledger.record_attempt(2, "fix", "x = 2", parse_unittest_output(OK_OUTPUT)))
        self.assertTrue(all(d.resolved for d in ledger.dead_ends))
        self.assertTrue(ledger.render().startswith("No unresolved dead ends."))

    def test_find_repeat_ignores_formatting(self):
        ledger = DeadEndLedger()
        ledger.record_attempt(1, "idea", "def f(a):\n    return a\n", report_failing("test_a"))
        match = ledger.find_repeat("def f( a ):\n    # same\n    return (a)\n")
        self.assertIsNotNone(match)
        self.assertEqual(match.dead_end_id, "f_01")
        self.assertIsNone(ledger.find_repeat("def f(a):\n    return -a\n"))

    def test_render_caps_open_dead_ends_most_recent_first(self):
        ledger = DeadEndLedger(max_rendered=5)
        for turn in range(1, 8):
            ledger.record_attempt(turn, f"idea {turn}", f"x = {turn}", report_failing(*[f"test_{i}" for i in range(turn)]))
        rendered = ledger.render()
        self.assertIn("Do not retry them", rendered)
        self.assertLess(rendered.index("f_07"), rendered.index("f_03"))
        self.assertNotIn("f_02", rendered)
        self.assertIn("2 older unresolved dead end(s) not shown", rendered)

    def test_approaches_capped_keeping_latest(self):
        ledger = DeadEndLedger(max_approaches=3)
        for turn in range(1, 6):
            ledger.record_attempt(turn, f"idea {turn}", f"x = {turn}", report_failing("test_a"))
        self.assertEqual(ledger.dead_ends[0].approaches, ["idea 3", "idea 4", "idea 5"])

    def test_evidence_lists_first_failures_and_counts_the_rest(self):
        ledger = DeadEndLedger(max_evidence=2)
        d = ledger.record_attempt(1, "idea", "x = 1", report_failing("test_a", "test_b", "test_c", ran=5))
        self.assertEqual(d.evidence, ["test_a: AssertionError: wrong", "test_b: AssertionError: wrong",
                                      "...and 1 more failing test(s)"])


if __name__ == "__main__":
    unittest.main()
