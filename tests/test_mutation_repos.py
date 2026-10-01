"""Repository-parametrised mutation banks: repos.json against the P6 source tasks, the cloud setup's clone pins and the
task-interpreter pins, each bank against its repo entry, and the prefilter_unexecuted rule. No suite runs, no network."""

import ast
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "mutation_tasks"))

import generate  # noqa: E402

REPOS = json.loads((ROOT / "experiments" / "mutation_tasks" / "repos.json").read_text(encoding="utf-8"))["repos"]
SETUP = (ROOT / "experiments" / "cloud" / "setup_cloud.sh").read_text(encoding="utf-8")


def pins(path: Path) -> dict:
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)", line.strip())
        if match:
            found[match.group(1).lower().replace("_", "-")] = match.group(2)
    return found


class RepoConfigTests(unittest.TestCase):
    def test_every_entry_matches_its_p6_source_task(self):
        for name in REPOS:
            config = generate.load_repo_config(name)  # raises SystemExit on a mismatch
            self.assertEqual(config["name"], name)
            self.assertIn(config["pythonpath"], (".", "src"))

    def test_sqlparse_entry_is_the_historical_generator(self):
        # The sqlparse bank (tasks.mutations.json) was generated with these constants before repos.json existed.
        sqlparse = REPOS["sqlparse"]
        self.assertEqual((sqlparse["source_task"], sqlparse["seed"], sqlparse["library_root"], sqlparse["test_root"],
                          sqlparse["test_glob"], sqlparse["pythonpath"], sqlparse["task_prefix"], sqlparse["package"]),
                         ("sqlparse-865", 865, "sqlparse", "tests", "**/test_*.py", ".", "sqlparse-mut", "sqlparse"))
        self.assertFalse(sqlparse["prefilter_unexecuted"])
        self.assertEqual(sqlparse["excluded_tests"], {})
        self.assertEqual((sqlparse["tasks_file"], sqlparse["log_file"]), ("tasks.mutations.json", "generation_log.json"))

    def test_setup_cloud_clones_every_repo_at_its_pinned_commit(self):
        block = re.search(r"TASK_REPOS=\((.*?)\n\)", SETUP, re.S).group(1)
        entries = {}
        for line in block.strip().splitlines():
            name, url, commit = line.strip().strip('"').split()
            entries[name] = (url, commit)
        self.assertEqual(entries, {name: (c["repo_url"], c["commit"]) for name, c in REPOS.items()})

    def test_test_requirements_are_pinned_for_both_backends(self):
        cloud = pins(ROOT / "experiments" / "cloud" / "bugs-venv.requirements.txt")
        oci = pins(ROOT / "experiments" / "p6_pilot" / "oci" / "requirements.lock")
        for name, config in REPOS.items():
            for requirement in ["pytest", *config["test_requirements"]]:
                key = requirement.lower().replace("_", "-")
                self.assertIn(key, cloud, f"{name}: {requirement} not in bugs-venv.requirements.txt")
                self.assertIn(key, oci, f"{name}: {requirement} not in oci/requirements.lock")
                self.assertEqual(cloud[key], oci[key], f"{name}: {requirement} pinned differently")
            # the task interpreter must not hold a healthy copy of the task package
            self.assertNotIn(config["package"].lower(), cloud)
            self.assertNotIn(config["package"].lower(), oci)


class BankTests(unittest.TestCase):
    def test_each_bank_matches_its_repo_entry(self):
        for name, config in REPOS.items():
            path = ROOT / "experiments" / "mutation_tasks" / config["tasks_file"]
            if not path.exists():
                continue
            with self.subTest(repo=name):
                tasks = json.loads(path.read_text(encoding="utf-8"))["tasks"]
                self.assertTrue(tasks)
                excluded = set(config["excluded_tests"])
                for number, task in enumerate(tasks, 1):
                    self.assertEqual(task["task_id"], f"{config['task_prefix']}-{number:03d}")
                    self.assertEqual((task["repo"], task["repo_url"], task["base_commit"], task["fix_commit"]),
                                     (config["repo"], config["repo_url"], config["commit"], config["commit"]))
                    self.assertEqual((task["source_task"], task["hidden_paths"], task["hidden_tests"]),
                                     (config["source_task"], [config["test_root"]], True))
                    self.assertTrue(task["mutation_file"].startswith(config["library_root"].rstrip("/") + "/"))
                    self.assertTrue(task["statement"].startswith(f"{config['package']} has a regression: "))
                    self.assertNotIn(task["mutation_file"], task["statement"])
                    self.assertFalse(excluded & (set(task["fail_to_pass"]) | set(task["pass_to_pass"])))
                    self.assertTrue(task["fail_to_pass"])
                    self.assertFalse(set(task["fail_to_pass"]) & set(task["pass_to_pass"]))


class PrefilterTests(unittest.TestCase):
    SOURCE = (
        "def used(x):\n"
        "    if x > 1:\n"
        "        return 1\n"
        "    return 0\n"
        "\n"
        "\n"
        "def unused(x):\n"
        "    if x > 1:\n"
        "        return 1\n"
        "    return 0\n"
    )

    def test_statement_span_is_the_smallest_enclosing_statement(self):
        tree = ast.parse(self.SOURCE)
        self.assertEqual(generate.statement_span(tree, 2, 2), (2, 3))  # the if statement, not the function
        self.assertEqual(generate.statement_span(tree, 3, 3), (3, 3))
        self.assertEqual(generate.statement_span(tree, 2, 3), (2, 3))

    def test_drops_only_candidates_in_statements_that_never_ran(self):
        with tempfile.TemporaryDirectory() as scratch:
            tree = Path(scratch)
            (tree / "lib").mkdir()
            (tree / "lib" / "mod.py").write_text(self.SOURCE, encoding="utf-8", newline="\n")
            candidates, _ = generate.find_candidates(tree, "lib")
            self.assertEqual(len(candidates), 6)  # per function: compare_flip, negate_condition, remove_guard
            executed = {"lib/mod.py": {1, 2, 4, 7}}  # used() ran with x <= 1; unused() was only defined
            kept, dropped = generate.prefilter_unexecuted(candidates, tree, executed)
            self.assertEqual({c.function for c in kept}, {"used"})
            self.assertEqual({c.function for c in dropped}, {"unused"})
            self.assertEqual(len(kept) + len(dropped), len(candidates))

    def test_statement_template_defaults_to_sqlparse(self):
        failing = ["tests.test_x::test_one"]
        text = generate.build_statement(failing, {failing[0]: "AssertionError: assert 1 == 2"})
        self.assertTrue(text.startswith("sqlparse has a regression: 1 previously passing check"))
        self.assertTrue(generate.build_statement(failing, {failing[0]: "x"}, name="boltons").startswith(
            "boltons has a regression: "))


if __name__ == "__main__":
    unittest.main()
