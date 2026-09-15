"""Outcome parsing for the P6 fixed evaluator (synthetic pytest JUnit XML; no pytest needed)."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p6_evaluate_task_under_test", ROOT / "experiments" / "p6_pilot" / "evaluate_task.py")
evaluator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluator
spec.loader.exec_module(evaluator)

# Shapes observed from pytest 9: a module that fails to import is a nameless-class error case.
JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="" name="tests.test_broken" time="0.0"><error message="collection failure">ImportError</error></testcase>
  <testcase classname="tests.test_ok" name="test_a" time="0.0"/>
  <testcase classname="tests.test_more.OneTests" name="test_x" time="0.0"><failure message="assert">AssertionError</failure></testcase>
  <testcase classname="tests.test_ok" name="test_skip" time="0.0"><skipped message="skip"/></testcase>
</testsuite></testsuites>
"""


class EvaluatorOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.xml = Path(self.temp_dir.name) / "junit.xml"
        self.xml.write_text(JUNIT, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collection_error_fails_its_module_only(self):
        outcomes, errors = evaluator.load_outcomes(self.xml)
        self.assertEqual(errors, ["tests.test_broken"])
        statuses = evaluator.classify(
            [
                "tests.test_broken::test_y",
                "tests.test_ok::test_a",
                "tests.test_more.OneTests::test_x",
                "tests.test_other::test_z",
                "tests.test_broken_extra::test_q",
                "tests.test_ok::test_skip",
            ],
            outcomes,
            errors,
        )
        self.assertEqual(statuses, {
            "tests.test_broken::test_y": "fail",
            "tests.test_ok::test_a": "pass",
            "tests.test_more.OneTests::test_x": "fail",
            "tests.test_other::test_z": "missing",
            "tests.test_broken_extra::test_q": "missing",
            "tests.test_ok::test_skip": "skip",
        })

    def test_unittest_class_tests_fail_when_their_module_does_not_import(self):
        statuses = evaluator.classify(["tests.test_broken.Cases::test_y"], {}, ["tests.test_broken"])
        self.assertEqual(statuses, {"tests.test_broken.Cases::test_y": "fail"})

    def test_conftest_import_failure_fails_every_expected_test(self):
        output = "ImportError while loading conftest 'C:/x/tests/conftest.py'.\nSyntaxError: invalid syntax"
        errors = evaluator.conftest_collection_errors({}, output)
        self.assertEqual(errors, [evaluator.CONFTEST_ERROR])
        statuses = evaluator.classify(["tests.test_a::test_x", "tests.test_b.Cases::test_y"], {}, errors)
        self.assertEqual(set(statuses.values()), {"fail"})
        # With observed test cases, the conftest rule does not apply.
        self.assertEqual(evaluator.conftest_collection_errors({"tests.test_a::test_x": "pass"}, output), [])

    def test_candidate_test_trees_and_root_config_are_replaced(self):
        root = Path(self.temp_dir.name)
        bundle, candidate = root / "bundle", root / "candidate"
        (bundle / "files" / "tests").mkdir(parents=True)
        (bundle / "files" / "tests" / "test_fixed.py").write_text("fixed", encoding="utf-8")
        (bundle / "files" / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        (candidate / "tests").mkdir(parents=True)
        (candidate / "tests" / "conftest.py").write_text("gaming hooks", encoding="utf-8")
        (candidate / "tests" / "test_fixed.py").write_text("edited", encoding="utf-8")
        (candidate / "conftest.py").write_text("root hooks", encoding="utf-8")
        (candidate / "pyproject.toml").write_text("edited", encoding="utf-8")
        (candidate / "pkg.py").write_text("source", encoding="utf-8")
        evaluator.install_fixed_test_inputs(bundle, candidate, {
            "test_roots": ["tests"], "managed_root_files": ["conftest.py", "pyproject.toml", "pytest.ini"],
        })
        self.assertFalse((candidate / "tests" / "conftest.py").exists())
        self.assertFalse((candidate / "conftest.py").exists())
        self.assertEqual((candidate / "tests" / "test_fixed.py").read_text(encoding="utf-8"), "fixed")
        self.assertEqual((candidate / "pyproject.toml").read_text(encoding="utf-8"), "[tool.pytest.ini_options]\n")
        self.assertEqual((candidate / "pkg.py").read_text(encoding="utf-8"), "source")

    def test_criterion_never_passes_with_missing_or_skipped_tests(self):
        version = "v1"
        self.assertEqual(evaluator.criterion({"a": "pass", "b": "pass"}, version)["outcome"], "pass")
        self.assertEqual(evaluator.criterion({"a": "pass", "b": "fail"}, version)["outcome"], "fail")
        partial = evaluator.criterion({"a": "pass", "b": "missing"}, version)
        self.assertEqual(partial["outcome"], "unknown")
        self.assertEqual(partial["coverage_ids"], ["a"])
        self.assertEqual(evaluator.criterion({"a": "skip"}, version)["outcome"], "unknown")
        self.assertEqual(evaluator.criterion({}, version)["outcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
