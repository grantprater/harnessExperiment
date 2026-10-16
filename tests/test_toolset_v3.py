"""Toolset v3 coding-tool interface contract (IMPLEMENTATION_PLAN.md, "Coding-tool interface contract")."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from reticle.context import PressureRecentContextPolicyV3
from reticle.context.baseline import RESOURCE_STATUS_PREFIX
from reticle.runtime import LocalRuntime
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
from reticle.tools import ToolSuite
from reticle.tools.primitives import LEGACY_TOOL_NAMES, TOOL_SCHEMAS, TOOLSET_VERSION


class ContractTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        files = {
            "pkg/__init__.py": "",
            "pkg/core.py": "def get_name(x):\n    return x.split('.')[1]\n\n\ndef other(x):\n    return x.split('.')[1]\n",
            "pkg/README.md": "get_name(x) returns the last dotted part.\n",
            "pkg/__pycache__/core.cpython-313.pyc": "cached get_name(",
            "tests/test_core.py": "from pkg.core import get_name\n",
            "Setup.CFG": "[metadata]\n",
            "data/blob.bin": "get_name(\x00binary",
        }
        for relative, content in files.items():
            (self.workspace / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.workspace / relative).write_bytes(content.encode("utf-8"))
        self.runtime = LocalRuntime(root / "session", self.workspace)
        self.tools = ToolSuite(self.runtime, interpreter=sys.executable)
        self.counter = 0

    def tearDown(self):
        self.temp_dir.cleanup()

    def dispatch(self, name, **arguments):
        self.counter += 1
        return self.tools.dispatch(name, arguments, f"call-{self.counter}")


class SchemaTests(ContractTestCase):
    def test_schema_has_no_duplicate_synonyms_and_no_advertised_regex(self):
        names = [s["function"]["name"] for s in TOOL_SCHEMAS]
        self.assertEqual(TOOLSET_VERSION, "reticle-tools-v3")
        self.assertIn("glob_files", names)
        self.assertIn("search_text", names)
        for legacy in LEGACY_TOOL_NAMES:
            self.assertNotIn(legacy, names)
        properties = {s["function"]["name"]: s["function"]["parameters"] for s in TOOL_SCHEMAS}
        self.assertEqual(properties["glob_files"]["required"], ["glob"])
        self.assertNotIn("regex", properties["search_text"]["properties"])
        self.assertEqual(len(names), len(set(names)))


class GlobFilesTests(ContractTestCase):
    def test_sorted_relative_paths_matching_name_or_path_skipping_caches(self):
        outcome = self.dispatch("glob_files", glob="*.py")
        self.assertEqual(outcome.status, "success")
        lines = outcome.content.splitlines()
        self.assertEqual(lines[0], "3 file(s) match glob '*.py' under '.':")
        self.assertEqual(lines[1:], ["pkg/__init__.py", "pkg/core.py", "tests/test_core.py"])
        self.assertIn("tests/test_core.py", self.dispatch("glob_files", glob="tests/*").content)

    def test_case_sensitive_and_never_matches_contents(self):
        self.assertTrue(self.dispatch("glob_files", glob="setup.cfg").content.startswith("0 file(s)"))
        self.assertIn("Setup.CFG", self.dispatch("glob_files", glob="Setup.CFG").content)
        empty = self.dispatch("glob_files", glob="get_name")
        self.assertIn("case-sensitive", empty.content)
        self.assertIn("cache/VCS directories skipped", empty.content)

    def test_missing_glob_and_wrong_argument_names_are_recoverable(self):
        missing = self.dispatch("glob_files", path="pkg")
        self.assertEqual(missing.status, "rejected")
        self.assertIn("missing required argument 'glob'", missing.content)
        self.assertIn('Example: {"glob": "*.py", "path": "src"}', missing.content)
        wrong = self.dispatch("glob_files", pattern="*.py")
        self.assertEqual(wrong.status, "rejected")
        self.assertIn("unknown argument(s) pattern; nothing was done.", wrong.content)
        self.assertIn("pass the glob as glob", wrong.content)


class SearchTextTests(ContractTestCase):
    def test_literal_punctuation_line_numbers_and_scope(self):
        outcome = self.dispatch("search_text", query="split('.')[1]", file_glob="*.py")
        self.assertEqual(outcome.status, "success")
        self.assertIn("2 match(es) for \"split('.')[1]\" (exact text, case-sensitive; path '.', file_glob '*.py'; "
                      "3 file(s) searched)", outcome.content)
        self.assertIn("pkg/core.py:2:     return x.split('.')[1]", outcome.content)
        self.assertIn("pkg/core.py:6:     return x.split('.')[1]", outcome.content)

    def test_file_selection_is_separate_from_content_and_empty_results_state_scope(self):
        everywhere = self.dispatch("search_text", query="get_name(")
        self.assertIn("pkg/README.md:1:", everywhere.content)
        self.assertIn("binary file(s) skipped", everywhere.content)
        self.assertNotIn("__pycache__", everywhere.content)
        python_only = self.dispatch("search_text", query="get_name(", file_glob="*.py")
        self.assertNotIn("README", python_only.content)
        empty = self.dispatch("search_text", query="x.split(.)", path="pkg", file_glob="*.py")
        self.assertEqual(empty.content, "0 match(es) for 'x.split(.)' (exact text, case-sensitive; path 'pkg', "
                                        "file_glob '*.py'; 2 file(s) searched).")

    def test_missing_query_with_file_selection_explains_and_gives_an_example(self):
        outcome = self.dispatch("search_text", file_glob="*.py")
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("missing required argument 'query': search_text finds exact text inside files; "
                      "'file_glob' only selects which files are searched", outcome.content)
        self.assertIn('Example: {"query": "def get_name(", "file_glob": "*.py"}'.replace("get_name", "get_real_name"),
                      outcome.content)

    def test_pattern_and_regex_are_rejected_not_silently_reinterpreted(self):
        pattern = self.dispatch("search_text", pattern="get_name|other")
        self.assertEqual(pattern.status, "rejected")
        self.assertIn("'pattern' is not a search_text argument: put the text to find in query", pattern.content)
        regex = self.dispatch("search_text", query="get_.*", regex=True)
        self.assertEqual(regex.status, "rejected")
        self.assertIn("Regex matching is not available in this toolset", regex.content)


class ReadEditWriteTests(ContractTestCase):
    def test_read_file_inclusive_ranges_with_actual_range_reported(self):
        self.assertTrue(self.dispatch("read_file", path="pkg/core.py").content.startswith("pkg/core.py (lines 1-6 of 6)"))
        region = self.dispatch("read_file", path="pkg/core.py", start_line=2, end_line=2).content
        self.assertEqual(region, "pkg/core.py (lines 2-2 of 6)\n    2|     return x.split('.')[1]")
        clamped = self.dispatch("read_file", path="pkg/core.py", start_line=5, end_line=99).content
        self.assertTrue(clamped.startswith("pkg/core.py (lines 5-6 of 6)"))
        invalid = self.dispatch("read_file", path="pkg/core.py", start_line=5, end_line=2)
        self.assertEqual(invalid.status, "rejected")

    def test_replace_text_ambiguity_fails_without_mutation_and_counts_are_reported(self):
        before = (self.workspace / "pkg/core.py").read_bytes()
        ambiguous = self.dispatch("replace_text", path="pkg/core.py", old_text="[1]", new_text="[-1]")
        self.assertEqual(ambiguous.status, "error")
        self.assertIn("occurs 2 times", ambiguous.content)
        self.assertEqual((self.workspace / "pkg/core.py").read_bytes(), before)
        replaced = self.dispatch("replace_text", path="pkg/core.py", old_text="[1]", new_text="[-1]", replace_all=True)
        self.assertTrue(replaced.content.startswith("Replaced 2 occurrence(s) in pkg/core.py."))

    def test_write_file_creates_parents_and_reports_overwrite(self):
        created = self.dispatch("write_file", path="new/dir/notes.txt", content="a\nb\n")
        self.assertEqual(created.content, "Created new/dir/notes.txt (4 bytes, 2 lines).")
        overwritten = self.dispatch("write_file", path="new/dir/notes.txt", content="c\n")
        self.assertTrue(overwritten.content.startswith("Overwrote new/dir/notes.txt"))
        self.assertEqual((self.workspace / "new/dir/notes.txt").read_text(encoding="utf-8"), "c\n")

    def test_unknown_arguments_to_schema_tools_are_rejected_with_guidance(self):
        outcome = self.dispatch("read_file", path="pkg/core.py", offset=10)
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("unknown argument(s) offset; nothing was done.", outcome.content)
        self.assertIn("read_file accepts: path (required), start_line, end_line.", outcome.content)


class RunTests(ContractTestCase):
    def test_cd_chaining_rejection_shows_the_command_to_run_instead(self):
        outcome = self.dispatch("run", command="cd /testbed && python test_issue.py")
        self.assertEqual(outcome.status, "rejected")
        self.assertIn("shell operator(s) && are not supported", outcome.content)
        self.assertIn("commands already run in the workspace root, so 'cd /testbed &&' is not needed", outcome.content)
        self.assertIn('Run instead: {"command": "python test_issue.py"}', outcome.content)
        self.assertEqual(outcome.content.count("Example:"), 0)

    def test_bare_cd_pipes_and_unknown_arguments_are_explained(self):
        cd = self.dispatch("run", command="cd pkg")
        self.assertIn("cd is not available: commands already run in the workspace root", cd.content)
        piped = self.dispatch("run", command="python -c pass | cat")
        self.assertIn("shell operator(s) | are not supported", piped.content)
        self.assertIn('Example: {"command": "pytest tests/test_example.py -q"}', piped.content)
        unknown = self.dispatch("run", command="python -c pass", cwd="pkg")
        self.assertEqual(unknown.status, "rejected")
        self.assertIn("unknown argument(s) cwd; nothing was run.", unknown.content)

    def test_output_shows_command_status_and_exit_code(self):
        outcome = self.dispatch("run", command='python -c "print(7)"')
        self.assertEqual(outcome.status, "success")
        self.assertIn('$ python -c "print(7)"', outcome.content)
        self.assertIn("status: success; exit code: 0", outcome.content)
        self.assertIn("--- stdout ---\n7", outcome.content)
        timeout = self.dispatch("run", command='python -c "import time; time.sleep(5)"', timeout_seconds=1)
        self.assertIn("status: timeout", timeout.content)


class ResourceStatusV3Tests(ContractTestCase):
    def test_limits_are_labeled_and_unknown_billing_is_stated(self):
        class Recorder:
            def __init__(self):
                self.requests = []
                self.replies = [
                    ModelResponse({"role": "assistant", "content": None, "tool_calls": [
                        {"id": "g", "type": "function", "function": {"name": "glob_files", "arguments": json.dumps({"glob": "*.py"})}}]}),
                    ModelResponse({"role": "assistant", "content": None, "tool_calls": [
                        {"id": "f", "type": "function", "function": {"name": "finish", "arguments": json.dumps({"summary": "done"})}}]}),
                ]

            def complete(self, messages, tools):
                self.requests.append(messages)
                return self.replies.pop(0)

        model = Recorder()
        task = TaskEnvelope("v3-status", "Status.", budgets={
            "model_responses": 5, "cost_usd": 0.05, "model_attempt_cost_reservation": 0.002})
        AgentController(self.runtime, task, self.tools, model, AgentLimits(5, 100_000),
                        policy=PressureRecentContextPolicyV3()).run()
        status = [next(m["content"] for m in request if str(m.get("content", "")).startswith(RESOURCE_STATUS_PREFIX))
                  for request in model.requests]
        self.assertIn("model responses, including this one: 5 remaining (limit 5)", status[0])
        self.assertIn("cost USD: 0.0500 remaining (limit 0.0500)", status[0])
        self.assertNotIn("billing unknown", status[0])
        self.assertIn("model responses, including this one: 4 remaining (limit 5)", status[1])
        self.assertIn("cost USD: 0.0480 remaining (limit 0.0500), after charging 1 attempt(s) with no reported cost "
                      "at their reservation (actual billing unknown)", status[1])


if __name__ == "__main__":
    unittest.main()
