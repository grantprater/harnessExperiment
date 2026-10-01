"""S6d executable run cards: validation, expansion, lock, execution, resume (a stub runner; no model, no container)."""

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "session_harness"))

import run_card  # noqa: E402

STUB = Path(__file__).resolve().parent / "card_runner_stub.py"
CARDS = ROOT / "experiments" / "session_harness" / "cards"
STUB_CLI = "9.9.9 (stub)"


def arm(name, policy, **extra):
    value = {"name": name, "client": "claude-cli", "model": "claude-m1", "policy": policy, "toolset": "stub-tools-v1",
             "backend": {"kind": "trusted-local"},
             "guards": {"stop_on_repeats": False, "resume_after_provider_stop": 0, "resume_wait_seconds": None}}
    value.update(extra)
    return value


class Fixture:
    """A temporary runner directory: the stub runner, a task file, a behaviour file, and the lock path."""

    def __init__(self, test: unittest.TestCase, tasks=None):
        scratch = tempfile.TemporaryDirectory()
        test.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)
        self.script = self.dir / "run_stub.py"
        shutil.copy(STUB, self.script)
        self.tasks = tasks or [{"task_id": f"t{i}", "kind": "k"} for i in range(1, 3)]
        (self.dir / "tasks.json").write_text(json.dumps({"tasks": self.tasks}), encoding="utf-8")
        self.log = self.dir / "invocations.log"
        self.behaviour_path = self.dir / "behaviour.json"
        self.behave({})
        self.lock = self.dir / "locks" / "live-run.lock"
        self.sleeps = []
        self.output = []
        patcher = mock.patch.dict(os.environ, {"CARD_STUB_BEHAVIOUR": str(self.behaviour_path)})
        patcher.start()
        test.addCleanup(patcher.stop)

    def behave(self, runs, attempts=2):
        self.behaviour_path.write_text(json.dumps({"log": str(self.log), "attempts": attempts, "runs": runs}),
                                       encoding="utf-8")

    def card(self, **overrides):
        card = {
            "schema_version": 1, "id": "test-card", "status": "approved", "markdown": "test-card.md",
            "hypothesis": "h", "run_prefix": "tc",
            "runner": {"script": str(self.script), "runner_version": 1},
            "environment": {"claude_cli_version": STUB_CLI},
            "arms": [arm("a", "stub-policy-a"), arm("b", "stub-policy-b")],
            "controls": [],
            "tasks": {"file": str(self.dir / "tasks.json"),
                      "sets": {"all": {"ids": [t["task_id"] for t in self.tasks]}}},
            "blocks": [{"name": "main", "task_set": "all", "arms": ["a", "b"], "rollouts": 2,
                        "arm_order": {"rule": "seeded", "seed": 7}}],
            "budgets": {
                "per_run": {"responses": 5, "model_attempts": 6, "active_seconds": 60, "context_bytes": 1000,
                            "max_tokens": 100, "pytest_timeout_seconds": 60,
                            "command_timeout_seconds": {"default": 120, "max": 600}},
                "campaign": {"max_runs": 100, "max_model_attempts": 1000},
            },
            "stop_rules": {"max_retries_per_invocation": 2, "retry_backoff_seconds": [1, 2],
                           "consecutive_failures_to_stop": 3},
            "measurements": {"per_run": ["accepted", "responses_used", "first_edit_response"],
                             "campaign": ["acceptance_rate_ci", "paired_table", "delta:b:a"]},
            "decision_rule": "d",
            "report": {"path": str(self.dir / "report.md"), "sets_path": str(self.dir / "sets.json")},
        }
        for key, value in overrides.items():
            card[key] = value
        return card

    def plan(self, card):
        errors = run_card.validate_card(card)
        if errors:
            raise AssertionError(errors)
        path = self.dir / "card.json"
        path.write_text(json.dumps(card), encoding="utf-8")
        return run_card.build_plan(card, path)

    def execute(self, plan, resume=False):
        return run_card.execute(plan, resume=resume, python=sys.executable, lock_path=self.lock,
                                sleep=self.sleeps.append, out=self.output.append)

    def invoked(self):
        return self.log.read_text(encoding="utf-8").split() if self.log.exists() else []

    def events(self, plan):
        return run_card.read_jsonl(run_card.Campaign(plan).log_path)


class CardValidationTests(unittest.TestCase):
    def test_repository_cards_validate(self):
        for name in ("006-replay", "007", "008", "009", "010", "011", "012", "013", "014", "015", "017"):
            card = run_card.load_card(CARDS / f"{name}.json")
            self.assertEqual(run_card.validate_card(card), [], name)

    def test_executable_claude_cli_cards_pin_the_full_model_id(self):
        """An alias resolves to whatever the installed CLI maps it to (2026-09-30: `sonnet` moved from
        claude-sonnet-5 to claude-sonnet-5-5), so a card --execute can launch must name the full model ID."""
        base = Fixture(self).card()
        for alias in ("sonnet", "opus", "haiku", "default", "opusplan", "claude-sonnet-latest", "sonnet[1m]"):
            for status in ("approved", "running"):
                card = copy.deepcopy(base)
                card["status"] = status
                card["arms"][0]["model"] = alias
                self.assertIn(f"arms.a: model {alias!r} is a CLI alias", "\n".join(run_card.validate_card(card)),
                              (alias, status))
        for model in ("claude-sonnet-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"):
            card = copy.deepcopy(base)
            card["arms"][0]["model"] = model
            self.assertEqual(run_card.validate_card(card), [], model)
        # Cards --execute cannot launch keep their recorded alias: they validate and replay as before.
        for status in ("proposed", "completed", "inconclusive", "invalidated"):
            card = copy.deepcopy(base)
            card["status"] = status
            card["arms"][0]["model"] = "sonnet"
            self.assertEqual(run_card.validate_card(card), [], status)
        for name in ("006-replay", "013"):  # completed claude-cli cards recorded with the alias
            card = run_card.load_card(CARDS / f"{name}.json")
            self.assertEqual({a["model"] for a in card["arms"]}, {"sonnet"})
            self.assertEqual(run_card.validate_card(card), [], name)
        for name in ("010", "014", "015"):  # pinned after the alias drift
            card = run_card.load_card(CARDS / f"{name}.json")
            self.assertEqual({a["model"] for a in card["arms"]}, {"claude-sonnet-5"}, name)

    def test_minimal_card_is_valid(self):
        self.assertEqual(run_card.validate_card(Fixture(self).card()), [])

    def test_structural_errors_name_the_field(self):
        base = Fixture(self).card()
        cases = {
            "$: missing 'hypothesis'": lambda c: c.pop("hypothesis"),
            "$: unknown field 'arm_count'": lambda c: c.update(arm_count=2),
            "$.blocks[0].rollouts: expected integer": lambda c: c["blocks"][0].update(rollouts="2"),
            "$.stop_rules.max_retries_per_invocation: must be <= 2":
                lambda c: c["stop_rules"].update(max_retries_per_invocation=3),
            "$.arms[0].client: must be one of": lambda c: c["arms"][0].update(client="gpt"),
            "$.arms[0].backend: matches no allowed form":
                lambda c: c["arms"][0].update(backend={"kind": "oci", "image": "x"}),
        }
        for expected, mutate in cases.items():
            card = copy.deepcopy(base)
            mutate(card)
            errors = run_card.validate_card(card)
            self.assertTrue(any(error.startswith(expected) for error in errors), (expected, errors))

    def test_semantic_errors(self):
        base = Fixture(self).card()
        cases = {
            "blocks.main: unknown arm 'c'": lambda c: c["blocks"][0].update(arms=["a", "c"]),
            "blocks.main.arm_order: a seeded order needs an integer seed":
                lambda c: c["blocks"][0].update(arm_order={"rule": "seeded"}),
            "arms.a.extra_args: --max-calls-per-run is set from structured card fields":
                lambda c: c["arms"][0].update(extra_args=["--max-calls-per-run", "9"]),
            "tasks.sets.all: needs exactly one of":
                lambda c: c["tasks"]["sets"]["all"].update(from_sets=["all"]),
            "stop_rules: retry_backoff_seconds needs one entry per allowed retry":
                lambda c: c["stop_rules"].update(retry_backoff_seconds=[1]),
            "measurements.per_run: unknown measurement 'vibes'":
                lambda c: c["measurements"]["per_run"].append("vibes"),
            "measurements.campaign: 'delta:b:z' names an unknown arm":
                lambda c: c["measurements"]["campaign"].append("delta:b:z"),
            "arms.a: a claude-cli arm needs a model": lambda c: c["arms"][0].update(model=None),
            "arms.a.guards: resume_wait_seconds is required when resuming":
                lambda c: c["arms"][0]["guards"].update(resume_after_provider_stop=1),
        }
        for expected, mutate in cases.items():
            card = copy.deepcopy(base)
            mutate(card)
            self.assertIn(expected, "\n".join(run_card.validate_card(card)), expected)

    def test_unresolved_inputs_block_execution(self):
        fixture = Fixture(self)
        card = fixture.card(status="proposed", prerequisites=[{"text": "wire the runner", "done": False}])
        card["environment"]["claude_cli_version"] = {"unresolved": "pin after the CLI update"}
        card["tasks"]["sets"]["later"] = {"ref": {"path": str(fixture.dir / "missing.json"), "key": "ids"}}
        plan = fixture.plan(card)
        joined = "\n".join(plan.blockers)
        self.assertIn("card status is 'proposed'", joined)
        self.assertIn("prerequisite not done: wire the runner", joined)
        self.assertIn("unresolved $.environment.claude_cli_version: pin after the CLI update", joined)
        self.assertIn("missing.json does not exist yet", joined)
        self.assertEqual(plan.arm_hashes["a"], [])  # no hash without the pinned CLI version
        self.assertEqual(fixture.execute(plan), run_card.EXIT_REFUSED)
        self.assertFalse(fixture.lock.exists())
        self.assertEqual(fixture.invoked(), [])


class ExpansionTests(unittest.TestCase):
    def test_counts_units_and_rollout_major_schedule(self):
        fixture = Fixture(self, tasks=[{"task_id": f"t{i}", "kind": "k"} for i in range(1, 4)])
        card = fixture.card(controls=[{"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a",
                                       "expect": "accepted"}])
        plan = fixture.plan(card)
        self.assertEqual(plan.blockers, [])
        self.assertEqual((len(plan.invocations), len(plan.controls), len(plan.runs)), (13, 1, 12))
        self.assertEqual(plan.invocations[0].kind, "control")
        self.assertEqual(plan.controls[0].task_ids, ["t1", "t2", "t3"])
        units = {}
        for inv in plan.runs:
            units.setdefault(inv.unit, []).append(inv.name)
        self.assertEqual(len(units), 6)
        self.assertTrue(all(sorted(names) == ["a", "b"] for names in units.values()))
        self.assertEqual([inv.rollout for inv in plan.runs], [1] * 6 + [2] * 6)
        self.assertEqual(len({inv.run_name for inv in plan.invocations}), 13)

    def test_seeded_order_is_reproducible_mixed_and_unit_local(self):
        tasks = [{"task_id": f"t{i:02d}", "kind": "k"} for i in range(1, 11)]
        fixture = Fixture(self, tasks=tasks)
        card = fixture.card()
        card["blocks"][0]["rollouts"] = 1
        first = [inv.name for inv in fixture.plan(card).runs]
        self.assertEqual(first, [inv.name for inv in fixture.plan(copy.deepcopy(card)).runs])
        pairs = [tuple(first[i:i + 2]) for i in range(0, len(first), 2)]
        self.assertEqual(set(pairs), {("a", "b"), ("b", "a")})
        # A unit's order depends only on (seed, block, task, rollout): dropping tasks reorders nothing else.
        smaller = copy.deepcopy(card)
        smaller["tasks"]["sets"]["all"]["ids"] = ["t03", "t07"]
        order = {inv.task_ids[0]: [] for inv in fixture.plan(smaller).runs}
        for inv in fixture.plan(smaller).runs:
            order[inv.task_ids[0]].append(inv.name)
        self.assertEqual(order["t03"], list(pairs[2]))
        self.assertEqual(order["t07"], list(pairs[6]))
        other_seed = copy.deepcopy(card)
        other_seed["blocks"][0]["arm_order"]["seed"] = 8
        self.assertNotEqual(first, [inv.name for inv in fixture.plan(other_seed).runs])

    def test_fixed_order_keeps_the_listed_order(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["blocks"][0].update(arms=["b", "a"], arm_order={"rule": "fixed"})
        self.assertEqual([inv.name for inv in fixture.plan(card).runs], ["b", "a"] * 4)

    def test_stratified_distinct_selection(self):
        tasks = []
        for index in range(24):
            tasks.append({"task_id": f"m{index:02d}", "kind": ["x", "y", "z"][index % 3],
                          "f2p": [f"test_{index % 12}"], "named": index == 5})
        fixture = Fixture(self, tasks=tasks)
        universe = run_card.TaskUniverse.load(fixture.dir / "tasks.json")
        rule = {"kind": "stratified-distinct", "count": 6, "seed": 3, "distinct_by": "f2p", "stratify_by": "kind",
                "exclude_if_true": ["named"]}
        chosen = run_card.select_stratified_distinct(universe, rule)
        self.assertEqual(chosen, run_card.select_stratified_distinct(universe, dict(rule)))
        self.assertEqual(len(chosen), 6)
        self.assertNotIn("m05", chosen)
        self.assertEqual(len({universe.tasks[t]["f2p"][0] for t in chosen}), 6)
        kinds = [universe.tasks[t]["kind"] for t in chosen]
        self.assertEqual(sorted(kinds.count(k) for k in "xyz"), [2, 2, 2])
        with self.assertRaises(ValueError):
            run_card.select_stratified_distinct(universe, dict(rule, count=13))

    def test_planned_hash_equals_the_runner_dry_run(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        inv = plan.runs[0]
        import subprocess
        printed = subprocess.run([sys.executable, str(inv.script), *inv.args, "--dry-run"], capture_output=True,
                                 text=True, check=True).stdout
        self.assertEqual(run_card.HASH_LINE.search(printed).group(1), inv.expected_hash)

    def test_oci_hash_uses_pinned_image_without_probing(self):
        fixture = Fixture(self)
        card = fixture.card()
        image_id = "ab" * 32
        card["arms"][0]["backend"] = {"kind": "oci", "image": "localhost/stub:1", "image_id": image_id,
                                      "engine": "docker"}
        with mock.patch("subprocess.run", side_effect=AssertionError("probed the machine")):
            plan = fixture.plan(card)
        module = plan.runner.module
        execution = {"backend": "isolated-oci", "image": "localhost/stub:1", "image_id": image_id,
                     "container_user_arguments": ["--user", "65534:65534"]}
        routing = {"claude-m1": module.cli_contract("claude-m1", max_turns=1, timeout=300, version=STUB_CLI)}
        guards = {"stop_on_repeats": False, "resume_after_provider_stop": 0, "resume_wait_seconds": None}
        self.assertEqual(plan.arm_hashes["a"], [module.protocol_hash("stub-policy-a", routing, execution, guards)])
        self.assertIn("--oci-image", plan.runs[0].args)

    def test_task_file_goes_first_in_tasks_and_unknown_flags_block(self):
        fixture = Fixture(self)
        other = fixture.dir / "other_tasks.json"
        shutil.copy(fixture.dir / "tasks.json", other)
        card = fixture.card()
        plan = fixture.plan(card)
        tasks_at = plan.runs[0].args.index("--tasks")
        self.assertEqual(plan.runs[0].args[tasks_at + 1:tasks_at + 3], [plan.runs[0].task_ids[0], "--run-name"])
        card["tasks"]["file"] = str(other)
        plan = fixture.plan(card)
        self.assertEqual(plan.blockers, [])
        tasks_at = plan.runs[0].args.index("--tasks")
        self.assertEqual(plan.runs[0].args[tasks_at + 1:tasks_at + 3], [str(other), plan.runs[0].task_ids[0]])
        card["arms"][0]["extra_args"] = ["--bogus-flag"]
        self.assertIn("does not accept --bogus-flag", "\n".join(fixture.plan(card).blockers))

    def test_runner_without_task_file_selection_blocks_another_file(self):
        fixture = Fixture(self)
        source = fixture.script.read_text(encoding="utf-8").replace("def load_tasks(", "def _load_tasks(")
        fixture.script.write_text(source.replace("= load_tasks(", "= _load_tasks("), encoding="utf-8")
        card = fixture.card()
        self.assertEqual(fixture.plan(card).blockers, [])  # the default task file needs no selection
        other = fixture.dir / "other_tasks.json"
        shutil.copy(fixture.dir / "tasks.json", other)
        card["tasks"]["file"] = str(other)
        self.assertIn("it cannot select", "\n".join(fixture.plan(card).blockers))

    def test_task_contracts_give_one_hash_per_task_and_the_runner_agrees(self):
        tasks = [{"task_id": "m1", "mutation_patch": "one"}, {"task_id": "m2", "mutation_patch": "two"},
                 {"task_id": "p3"}]
        fixture = Fixture(self, tasks=tasks)
        card = fixture.card(controls=[{"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a",
                                       "expect": "accepted"}])
        card["blocks"][0].update(arms=["a"], arm_order={"rule": "fixed"})
        plan = fixture.plan(card)
        by_task = {}
        for inv in plan.runs:
            by_task.setdefault(inv.task_ids[0], set()).add(inv.expected_hash)
        self.assertTrue(all(len(hashes) == 1 for hashes in by_task.values()))  # rollouts share a hash
        self.assertEqual(len({next(iter(h)) for h in by_task.values()}), 3)
        self.assertEqual(len(plan.arm_hashes["a"]), 3)
        self.assertEqual([c["task_id"] for c in plan.controls[0].expected_config["task_contracts"]], ["m1", "m2"])
        import subprocess
        for inv in [plan.controls[0], *plan.runs[:3]]:
            printed = subprocess.run([sys.executable, str(inv.script), *inv.args, "--dry-run"], capture_output=True,
                                     text=True, check=True).stdout
            self.assertEqual(run_card.HASH_LINE.search(printed).group(1), inv.expected_hash, inv.run_name)
        self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)  # recorded task_file and contracts match the plan

    def test_run_name_template_and_control_names_are_recognised_on_resume(self):
        fixture = Fixture(self)
        card = fixture.card(run_name_template="{prefix}-{task}-r{rollout}",
                            controls=[{"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a",
                                       "expect": "accepted", "run_name": "earlier-gold-control"}])
        card["blocks"][0]["arms"] = ["a"]
        plan = fixture.plan(card)
        self.assertEqual([inv.run_name for inv in plan.invocations],
                         ["earlier-gold-control", "tc-t1-r1", "tc-t2-r1", "tc-t1-r2", "tc-t2-r2"])
        self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)
        self.assertEqual(fixture.execute(plan, resume=True), run_card.EXIT_OK)
        self.assertEqual(len(fixture.invoked()), 5)  # the resume ran nothing
        skipped = [e["run"] for e in fixture.events(plan) if e["event"] == "skip"]
        self.assertEqual(skipped, [inv.run_name for inv in plan.invocations])
        bad = copy.deepcopy(card)
        bad["run_name_template"] = "{prefix}-{task}"
        self.assertIn("run_name_template: must contain {task} and {rollout}", run_card.validate_card(bad))
        bad["run_name_template"] = "{prefix}-{task}-r{rollout}-{model}"
        self.assertTrue(any(e.startswith("run_name_template:") for e in run_card.validate_card(bad)))

    def test_card_007_plan(self):
        card = run_card.load_card(CARDS / "007.json")
        plan = run_card.build_plan(card, CARDS / "007.json")
        self.assertEqual((len(plan.invocations), len(plan.controls), len(plan.runs)), (42, 2, 40))
        selected = json.loads((ROOT / "experiments" / "session_harness" / "E3-calibration-007-tasks.json")
                              .read_text(encoding="utf-8"))["task_ids"]
        self.assertEqual(plan.sets["calibration"], selected)
        self.assertEqual([inv.run_name for inv in plan.controls],
                         ["s6a-control-gold-mut-v2", "s6a-control-noop-mut-v2"])
        self.assertEqual([inv.run_name for inv in plan.runs],
                         [f"c007-{task}-r{rollout}" for rollout in (1, 2) for task in selected])
        self.assertEqual(len(plan.arm_hashes["incumbent"]), 20)  # one per task contract, shared by both rollouts
        self.assertTrue(all("--max-total-calls" in inv.args and inv.args[inv.args.index("--max-total-calls") + 1]
                            == "24" for inv in plan.runs))
        self.assertEqual(plan.blockers, ["card status is 'proposed'; --execute needs approved or running",
                                         "prerequisite not done: owner approval recorded in the markdown card "
                                         "(then set status to running)"])

    def test_card_007_replays_the_recorded_v2_controls(self):
        evaluator = ROOT / "experiments" / "p6_pilot" / "evaluate_task.py"
        if b"\r\n" not in evaluator.read_bytes():
            self.skipTest("the v2 controls were recorded on a CRLF checkout; see the positive-control test")
        plan = run_card.build_plan(run_card.load_card(CARDS / "007.json"), CARDS / "007.json")
        for name, recorded in (("s6a-control-gold-mut-v2", "f825e41bc259"), ("s6a-control-noop-mut-v2", "58dfdf928e0b")):
            lines = []
            self.assertTrue(run_card.replay_check(plan, ROOT / "experiments" / "p6_pilot" / "runs" / name,
                                                  out=lines.append), lines)
            self.assertIn(f"planned {recorded}, recorded {recorded}", lines[-1])

    def test_positive_control_replays_to_the_recorded_hash(self):
        card = run_card.load_card(CARDS / "006-replay.json")
        plan = run_card.build_plan(card, CARDS / "006-replay.json")
        evaluator = ROOT / "experiments" / "p6_pilot" / "evaluate_task.py"
        if b"\r\n" in evaluator.read_bytes():  # the recorded run hashed a CRLF checkout
            lines = []
            self.assertTrue(run_card.replay_check(plan, ROOT / "experiments" / "p6_pilot" / "runs" /
                                                  "pc-reticle-sonnet-2", out=lines.append), lines)
            self.assertEqual(plan.arm_hashes["reticle"], ["6f1061c028c8"])
        else:  # an LF checkout: the same card, with CRLF evaluator bytes, gives the recorded hash
            self.assertEqual(plan.line_ending_hashes["reticle"], ("CRLF", "6f1061c028c8"))

    def test_treatment_cards_plan_the_runner_hashes_and_keep_the_incumbent(self):
        """Cards 013-015: the treatment flag in extra_args is hashed as the runner hashes it; the incumbent arm
        plans card 007's hash for every shared task (013, which ran on the alias) or card 007's routing with only
        the model pinned to its full ID and the CLI re-pinned to 2.1.286 (014, 015, pinned 2026-09-30 after the
        alias drift)."""
        runner = run_card.RunnerAdapter.load(ROOT / "experiments" / "p6_pilot" / "run_pilot.py").module
        card_007 = run_card.build_plan(run_card.load_card(CARDS / "007.json"), CARDS / "007.json")
        hash_007 = {inv.task_ids[0]: inv.expected_hash for inv in card_007.runs}
        routing_007 = {inv.task_ids[0]: inv.expected_config["provider_routing"] for inv in card_007.runs}

        def pinned(routing, model, cli_version):
            (contract,) = routing.values()
            arguments = list(contract["arguments"])
            arguments[arguments.index("--model") + 1] = model
            # integration/2026-10: the merged model guard (cloud port) adds "model_pin" to a full ID's contract
            model_pin = runner.cli_contract(model, max_turns=1, timeout=300, version=cli_version)["model_pin"]
            return {model: {**contract, "model": model, "arguments": arguments, "cli_version": cli_version,
                            "model_pin": model_pin}}

        for name, arm_name in (("013", "finish-guard"), ("014", "midpoint-nudge"), ("015", "check-oracle")):
            with self.subTest(card=name):
                card = run_card.load_card(CARDS / f"{name}.json")
                self.assertEqual(run_card.validate_card(card), [])
                plan = run_card.build_plan(card, CARDS / f"{name}.json")
                # cards 014-015 were approved by the owner on 2026-09-28; card 013 has run and is completed
                self.assertEqual(plan.blockers, [] if card["status"] != "completed" else
                                 ["card status is 'completed'; --execute needs approved or running"])
                self.assertEqual((len(plan.runs), len(plan.controls)), (32, 2))
                treatment = next(a for a in card["arms"] if a["name"] == arm_name)
                treatments = runner.treatments_from_args(treatment["extra_args"])
                self.assertTrue(treatments)
                model = treatment["model"]
                for inv in plan.runs:
                    task_id = inv.task_ids[0]
                    if model == "sonnet":
                        self.assertEqual(inv.expected_config["provider_routing"], routing_007[task_id])
                    else:
                        self.assertEqual(model, "claude-sonnet-5")
                        self.assertEqual(inv.expected_config["provider_routing"], pinned(routing_007[task_id], model,
                                                                                        card["environment"]["claude_cli_version"]))
                    if inv.name == "incumbent":
                        if model == "sonnet":
                            self.assertEqual(inv.expected_hash, hash_007[task_id])
                        else:  # the full model ID is a hash input: the pinned incumbent is not card 007's
                            self.assertNotEqual(inv.expected_hash, hash_007[task_id])
                            contracts = [runner.task_contract(t) for t in plan.universe.tasks.values()
                                         if t["task_id"] == task_id]
                            self.assertEqual(inv.expected_hash, runner.protocol_hash(
                                "pressure-recent-v3", inv.expected_config["provider_routing"],
                                inv.expected_config["execution"], inv.expected_config["guards"], contracts, {}))
                        self.assertNotIn("treatments", inv.expected_config)
                    else:
                        self.assertNotEqual(inv.expected_hash, hash_007[inv.task_ids[0]])
                        self.assertEqual(inv.expected_config["treatments"], treatments)
                        self.assertEqual(inv.args[-len(treatment["extra_args"]):], treatment["extra_args"])
                        contracts = [runner.task_contract(t) for t in plan.universe.tasks.values()
                                     if t["task_id"] == inv.task_ids[0]]
                        routing = inv.expected_config["provider_routing"]
                        self.assertEqual(inv.expected_hash, runner.protocol_hash(
                            "pressure-recent-v3", routing, inv.expected_config["execution"],
                            inv.expected_config["guards"], contracts, treatments))
                orders = {tuple(inv.name for inv in plan.runs if (inv.task_ids, inv.rollout) == (u.task_ids, u.rollout))
                          for u in plan.runs}
                self.assertEqual(len(orders), 2)  # seeded per unit: both arm orders occur


class LockTests(unittest.TestCase):
    def test_exclusive_and_released(self):
        fixture = Fixture(self)
        first, second = run_card.LiveRunLock(fixture.lock), run_card.LiveRunLock(fixture.lock)
        first.acquire({"card": "one"})
        with self.assertRaises(run_card.LockHeld) as held:
            second.acquire({"card": "two"})
        self.assertIn("one", str(held.exception))
        second.release()  # never removes a lock it does not own
        self.assertTrue(fixture.lock.exists())
        first.release()
        self.assertFalse(fixture.lock.exists())

    def test_execute_fails_while_the_lock_is_held(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        fixture.lock.parent.mkdir(parents=True)
        fixture.lock.write_text(json.dumps({"card": "someone-else", "pid": 1}), encoding="utf-8")
        self.assertEqual(fixture.execute(plan), run_card.EXIT_LOCKED)
        self.assertEqual(fixture.invoked(), [])
        self.assertIn("someone-else", json.loads(fixture.lock.read_text(encoding="utf-8"))["card"])

    def test_lock_released_after_success_and_after_a_stop(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)
        self.assertFalse(fixture.lock.exists())
        fixture2 = Fixture(self)
        plan2 = fixture2.plan(fixture2.card())
        fixture2.behave({plan2.runs[0].run_name: "wrong_hash"})
        self.assertEqual(fixture2.execute(plan2), run_card.EXIT_INTEGRITY)
        self.assertFalse(fixture2.lock.exists())


class ExecutionTests(unittest.TestCase):
    def test_runs_sequentially_in_plan_order_and_writes_the_report(self):
        fixture = Fixture(self)
        card = fixture.card(controls=[{"name": "gold", "client": "gold", "task_set": "all", "like_arm": "a",
                                       "expect": "accepted"}])
        plan = fixture.plan(card)
        self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked(), [inv.run_name for inv in plan.invocations])
        report = (fixture.dir / "report.md").read_text(encoding="utf-8")
        self.assertTrue(report.startswith(run_card.REPORT_MARKER))
        for heading in ("## Protocol", "## Controls", "## Runs", "## Summary by arm", "### Paired units",
                        "### Delta `b` - `a`", "## Decision rule"):
            self.assertIn(heading, report)
        self.assertIn(f"| a | 4 | 4 | 4 | 1.00 |", report)
        self.assertIn("first_edit_response", report)
        self.assertIn("pending: not in results.jsonl", report)
        derived = json.loads((fixture.dir / "sets.json").read_text(encoding="utf-8"))["derived"]["per_arm"]
        self.assertEqual(sorted(derived["a"]["all_accepted"]), ["t1", "t2"])

    def test_edited_report_is_never_overwritten(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        run_card.write_report(plan)
        run_card.write_report(plan)  # unedited: rewritten in place
        self.assertFalse((fixture.dir / "report.skeleton.md").exists())
        report = fixture.dir / "report.md"
        report.write_text(report.read_text(encoding="utf-8") + "\nanalysis by hand\n", encoding="utf-8")
        run_card.write_report(plan)
        self.assertIn("analysis by hand", report.read_text(encoding="utf-8"))
        self.assertTrue((fixture.dir / "report.skeleton.md").exists())

    def test_model_error_is_retried_after_recorded_backoff(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        first = plan.runs[0].run_name
        fixture.behave({first: "model_error"})
        self.assertEqual(fixture.execute(plan), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked()[:2], [first, f"{first}-a2"])
        self.assertEqual(fixture.sleeps, [1])
        self.assertIn({"event": "backoff", "seconds": 1},
                      [{"event": e["event"], "seconds": e.get("seconds")} for e in fixture.events(plan)])

    def test_three_consecutive_failures_checkpoint_then_resume_skips_done_and_exhausted(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        names = [inv.run_name for inv in plan.invocations]
        fixture.behave({names[2]: ["crash", "crash", "crash", "accept"]})
        self.assertEqual(fixture.execute(plan), run_card.EXIT_CHECKPOINT)
        self.assertEqual(fixture.invoked(), names[:2] + [names[2]] * 3)
        self.assertEqual(fixture.sleeps, [1, 2])
        self.assertIn("checkpoint", fixture.events(plan)[-1]["event"])
        self.assertFalse(fixture.lock.exists())
        # Without --resume the existing run directories are refused; with it, completed invocations are
        # skipped and the invocation that used its first attempt and two retries is not retried again.
        self.assertEqual(fixture.execute(plan), run_card.EXIT_REFUSED)
        self.assertEqual(fixture.execute(plan, resume=True), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked()[5:], names[3:])
        self.assertIn("skip_exhausted", [e["event"] for e in fixture.events(plan)])

    def test_resume_reruns_an_interrupted_invocation_in_place(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        names = [inv.run_name for inv in plan.invocations]
        fixture.behave({names[3]: ["silent", "accept"]})  # config.json written, no results.jsonl
        self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY)  # exit 0 without a record
        self.assertEqual(fixture.invoked(), names[:4])
        self.assertEqual(fixture.execute(plan, resume=True), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked()[4:], names[3:])
        runs_root = fixture.dir / "runs"
        self.assertFalse((runs_root / f"{names[3]}-a2").exists())
        self.assertTrue(all((runs_root / name / "results.jsonl").exists() for name in names))
        skipped = [e["run"] for e in fixture.events(plan) if e["event"] == "skip"]
        self.assertEqual(skipped, names[:3])

    def test_model_mismatch_is_a_void_adapter_failure_that_stops_without_retry(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        names = [inv.run_name for inv in plan.invocations]
        fixture.behave({names[1]: ["model_mismatch", "accept"]})
        # integration/2026-10: one guard with the cloud port's model pin, so a mismatch is an integrity stop
        # (corrupted_protocol, exit 4) rather than exp/ontology-pilot's checkpoint (exit 3); still void and resumable.
        self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY)
        self.assertEqual(fixture.invoked(), names[:2])  # no retry: it would meet the same model
        self.assertEqual(fixture.sleeps, [])
        end = [e for e in fixture.events(plan) if e["event"] == "invocation_end"][-1]
        self.assertEqual(end["outcome"], "integrity")
        self.assertTrue(end["detail"].startswith("corrupted_protocol: model_mismatch (model_pin_violation): "
                                                 "requested claude-m1"), end["detail"])
        self.assertIn("model_mismatch", fixture.events(plan)[-1]["reason"])
        record = run_card.read_jsonl(fixture.dir / "runs" / names[1] / "results.jsonl")[0]
        self.assertTrue(run_card.is_model_failure(record))
        # Not a task outcome: the invocation has no completed attempt, so --resume runs it again.
        self.assertIsNone(run_card.completed_attempt(run_card.Campaign(plan), plan.invocations[1]))
        self.assertEqual(fixture.execute(plan, resume=True), run_card.EXIT_OK)
        self.assertEqual(fixture.invoked()[2:3], [f"{names[1]}-a2"])  # the void attempt runs again on --resume

    def test_consecutive_failures_across_invocations(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["stop_rules"] = {"max_retries_per_invocation": 0, "retry_backoff_seconds": [],
                              "consecutive_failures_to_stop": 3}
        plan = fixture.plan(card)
        names = [inv.run_name for inv in plan.invocations]
        fixture.behave({name: "model_error" for name in names[:3]})
        self.assertEqual(fixture.execute(plan), run_card.EXIT_CHECKPOINT)
        self.assertEqual(fixture.invoked(), names[:3])
        self.assertEqual(fixture.sleeps, [])

    def test_integrity_stops(self):
        cases = {"wrong_hash": "corrupted_protocol", "over_budget": "budget_violation", "silent": "evidence_loss"}
        for behaviour, reason in cases.items():
            fixture = Fixture(self)
            plan = fixture.plan(fixture.card())
            fixture.behave({plan.runs[1].run_name: behaviour})
            self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY, behaviour)
            self.assertEqual(len(fixture.invoked()), 2, behaviour)
            self.assertIn(reason, fixture.events(plan)[-1]["reason"], behaviour)

    def test_failed_control_stops_before_any_run(self):
        fixture = Fixture(self)
        card = fixture.card(controls=[{"name": "noop", "client": "noop", "task_set": "all", "like_arm": "a",
                                       "expect": "accepted"}])
        plan = fixture.plan(card)
        self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY)
        self.assertEqual(fixture.invoked(), [plan.controls[0].run_name])

    def test_preflight_catches_machine_drift(self):
        fixture = Fixture(self)
        plan = fixture.plan(fixture.card())
        with mock.patch.dict(os.environ, {"CARD_STUB_CLI_VERSION": "10.0.0 (newer)"}):
            self.assertEqual(fixture.execute(plan), run_card.EXIT_INTEGRITY)
        self.assertEqual(fixture.invoked(), [])
        self.assertIn("would record protocol", fixture.output[-1])

    def test_campaign_cap_refuses_a_plan_that_does_not_fit(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["budgets"]["campaign"]["max_model_attempts"] = 47  # 8 runs x 6 attempts = 48 allocated
        plan = fixture.plan(card)
        self.assertIn("the plan allocates 48 model attempts; the campaign cap is 47", plan.blockers)
        self.assertEqual(fixture.execute(plan), run_card.EXIT_REFUSED)

    def test_campaign_cap_after_retries_never_splits_a_unit(self):
        fixture = Fixture(self)
        card = fixture.card()
        card["budgets"]["campaign"]["max_model_attempts"] = 48  # exactly the plan; a retry overdraws it
        plan = fixture.plan(card)
        names = [inv.run_name for inv in plan.runs]
        fixture.behave({names[0]: "model_error"}, attempts=6)  # every run spends its whole allocation
        self.assertEqual(fixture.execute(plan), run_card.EXIT_CHECKPOINT)
        self.assertEqual(fixture.invoked(), [names[0], f"{names[0]}-a2", *names[1:6]])  # units 1-3, whole
        self.assertIn("campaign cap: 42 of 48 model attempts used; the next unit needs 12",
                      fixture.events(plan)[-1]["reason"])


if __name__ == "__main__":
    unittest.main()
