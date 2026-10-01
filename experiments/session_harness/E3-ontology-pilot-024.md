# E3 ontology pilot 024: four arms on card 010's eval split (screen)

Date: 2026-10-01  
Status: **approved (2026-10-01; launch approval below).** Phase 1 (verifier generation, `--spend-cap-usd 30`) runs
first; `run_card.py --execute` still refuses until the verifier manifest is generated, verified, committed and re-planned.
The verifier-commit code is ported (see "Verifier-commit: ported verifier-only, generation confined in podman").  
Owner launch approval (2026-10-01, verbatim):
- Q: "Card 024 is ready to launch. Phase 1: generate reproduction tests for verifier-commit (at most 93 model calls,
  about 43 expected, about $19 list; tests run in podman). Phase 2: 248 pilot runs + 2 scripted controls on
  claude-sonnet-5 via the private CLI 2.1.286, at most 7,037 model calls in total, about $338-395 list, about 29 h
  sequential on this machine at idle priority. It bills the subscription; if Anthropic's paused Agent SDK credit change
  resumes mid-campaign, `claude -p` usage could start drawing on a monthly credit ($20-200) instead. What do you
  approve?" A: "Both phases (Recommended)". The option read: "Run generation, then I verify the manifest (one test per
  task, each fails on the mutated tree and passes on gold), commit it, re-plan, and launch the 248 runs without asking
  again. I stop and come back if anything in that check fails or costs exceed the estimate."
- Q: "Spend cap for phase 1 generation (each call is already capped at $0.60, so 93 calls can never exceed $55.80)?"
  A: "$30". The option read: "About 1.6x the expected spend. If hit, some tasks get no verifier, and I'd come back
  before the pilot."  
Machine card: [`cards/024.json`](cards/024.json). Task file:
[`tasks.pilot024-eval.json`](../mutation_tasks/tasks.pilot024-eval.json), built by
[`build_pilot_eval_tasks.py`](../mutation_tasks/build_pilot_eval_tasks.py) (`--check` rebuilds it).  
Owner decisions this card rests on (2026-10-01, verbatim; also in
[card 010 A1.7](E3-difficulty-calibration-010.md#a17-owner-decisions-for-the-ontology-pilot-2026-10-01) and
`IMPLEMENTATION_PLAN.md`):
- Question: "31 eval tasks share a mutated function (38 pairs) or an exact failing-test set (26 pairs) with dev tasks.
  None of those dev tasks has ever been run. The card says eval must be 'disjoint from every dev task'. How should the
  overlap be handled?" Answer: "Quarantine dev twins (Recommended)" (option text: "Tag the overlapping dev tasks so no
  arm, lesson or evolution step ever uses them. Eval stays at 31, it costs nothing, and the pilot can't learn on a
  near-copy of an eval bug.")
- Question: "How many rollouts per task should the 4-arm pilot use (incumbent, memory, symbolic, verifier-commit on 31
  tasks)? Costs are list price at about $1.20/run on these harder tasks; it is billed to the subscription for now. The
  earlier plan was an r=2 screen." Answer: "r=2 screen (Recommended)" (option text: "248 runs, about $300 list, about 29
  hours sequential. A screen only: it detects roughly 23-point effects. A powered follow-up runs only if an arm looks
  promising. Matches the earlier pilot plan.")
- Earlier: verifier-commit stays the 4th arm; its 1-3 generation calls per task are confirmed with the owner at
  launch; card 021 is invalidated, but the arm is kept. Pilot protocol:
  [`experiments/neurosymbolic/README.md`](../neurosymbolic/README.md).

Owner decisions on the draft (2026-10-01, verbatim; also in `IMPLEMENTATION_PLAN.md`):
1. Q: "Merging the verifier-commit code from integration/2026-10 changes the protocol hash of every
   incumbent/memory/symbolic run (its CLI wrapper adds a model_pin block), so the pilot would no longer run the same
   code as card 010's calibration. How should the arm's code come in?" A: "Port verifier only (Recommended)". The
   option read: "Bring over only the verifier-commit runner and repro-test code, not the CLI wrapper change. Must keep
   all 186 other hashes equal to calibration. The 'same code as calibration' rule holds."
2. Q: "Before the pilot, verifier-commit generates a reproduction test per task (at most 93 calls, about 43 expected,
   about $19). The model-written test file is then executed with plain host Python on this machine, outside any
   sandbox. How should that run?" A: "Confine it in podman (Recommended)". The option read: "Run each generated test
   in the same OCI image the runs use (network none, scratch copy only) before freezing it. A small code change;
   nothing model-written runs on the host."
3. Q: "The card's decision rule, written before any data: an arm earns a powered follow-up if it beats the incumbent
   by at least +0.10 in acceptance AND wins more tasks than it loses; an arm at -0.10 or worse is recorded as harmful.
   The draft agent chose the 0.10 threshold. Keep it?" A: "Keep +0.10 (Recommended)".

Card number: 024, the next number after the highest card anywhere in the repository (023, card 023 on
`integration/2026-10`; checked over every local and remote branch). 016 is an unused gap below cards already run and
is left unused so numbers stay in drafting order.

## Hypothesis

On card 010's 31 combined-eval sqlparse tasks (calibrated incumbent acceptance 32/62), at least one treatment arm
(`--reasoning memory`, `--reasoning symbolic`, or verifier-commit) shows a per-task acceptance difference over the
unchanged incumbent large enough to justify a powered follow-up. This is a screen at r = 2, not a test: with 31 tasks
it detects effects of roughly 23 points.

## Arms

All four arms: runner v8, `--client claude-cli --models claude-sonnet-5` (full ID), Claude CLI `2.1.286 (Claude Code)`
from the private copy `.runtime/claude-cli-2.1.286/node_modules/@anthropic-ai/claude-code/bin/claude.exe` (first on
PATH, `DISABLE_AUTOUPDATER=1`, A1.6), `pressure-recent-v3`, `reticle-tools-v3`, local OCI backend (podman, image
`localhost/reticle-p6-task:py313-v1`, ID `8b74015e5079`; network none, workspace-only mount, unprivileged user), repeat
guard off; 20 responses, 24 attempts, 1,200 active seconds, `max_tokens` 4096, 80,000 context bytes, pytest timeout
600 s. Card 010's budgets and backend, unchanged.

| Arm | Runner flags beyond the incumbent | What changes |
|---|---|---|
| `incumbent` | none | Card 010's incumbent arm, field for field |
| `memory` | `--reasoning memory` | Evidence-ontology tools (`reasoning_state`, `reasoning_update`, `assess_check`) over this run's own journal |
| `symbolic` | `--reasoning symbolic` | The memory tools plus advisory inference rules, returned when the model asks |
| `verifier-commit` | `--verifier repro-test:3 --verifier-manifest experiments/session_harness/verifiers/024/manifest.json --nudge commit` | check() over the task's frozen reproduction test (counts only, at most 3 calls), plus the commitment nudge at half the response budget with `commit_hypothesis` / `record_observation` |

Verifier-commit here differs from card 021's arm in two ways, both chosen so the treatment is the arm's only
difference from the incumbent: it runs on local OCI, not the cloud trusted-local backend, and it does not add
`--cli-reply-recovery` (card 010's incumbent did not use it).

**Reasoning-arm interpreter.** The reasoning arms' hashes include the installed `rdflib` and `pyshacl` versions. Of
the repository's interpreters only `.runtime/test-venv` (Python 3.13) has them: rdflib 7.6.0, pyshacl 0.40.1. The
hashes below were planned with those versions. Launch `run_card.py` with an interpreter that has exactly those
versions (`--python`), or the memory and symbolic hashes change; the system Python 3.14 has neither, and `--plan`
under it stops with "Install the optional reticle[reasoning] dependencies".

## Incumbent equals card 010 (hash check)

Method: card 010's control-hash check. `run_card.py cards/024.json --plan --json` computes each invocation's protocol
hash with the runner's own `protocol_hash` and `task_contract`;
[`check_pilot_hashes_024.py`](check_pilot_hashes_024.py) compares, per eval task, the incumbent's planned hash with
the `protocol_hash` in `config.json` and every `results.jsonl` row of that task's two valid calibration runs
(`c010-<task>-r<k>` or `c010b-<task>-r<k>`; `*.void-*` folders skipped). The protocol hash covers task contracts, not
the task file's path, so copying the 31 tasks unchanged into one file keeps each task's hash.

Result (2026-10-01, commit of this card): **31/31 match**; each task has one recorded hash across both runs, equal to
the planned one. No mismatch. Rollouts share a task's hash. Rechecked after the verifier port and confinement: still
31/31, and the full `--plan` (text and `--json`) is unchanged for every incumbent, memory and symbolic invocation and
both controls (188 of 188); only the 62 verifier-commit invocations changed, from no runner to provisional hashes.

| Task | Stage | Hash (planned = recorded) | Task | Stage | Hash (planned = recorded) |
|---|---|---|---|---|---|
| sqlparse-mut-064-nm | 1 | 52293a88b6c7 | sqlparse-mut-143-nm | 2a | 9f5169f70472 |
| sqlparse-mut-015 | 1 | 8ad5bfad9053 | sqlparse-mut-151 | 2a | 43e3b7818550 |
| sqlparse-mut-016-nm | 1 | ad3bea334b14 | sqlparse-mut-125-nm | 2a | 013a1b1dfa82 |
| sqlparse-mut-050 | 1 | 1133844d240d | sqlparse-mut-232-nm | 2a | 5c84a0a79f28 |
| sqlparse-mut-012 | 1 | 5a6f4417de81 | sqlparse-mut-266 | 2a | 3d6380d0f2aa |
| sqlparse-mut-052-nm | 1 | addd59754660 | sqlparse-mut-084-nm | 2a | b8f131b9d679 |
| sqlparse-mut-041 | 1 | e04a89d101f4 | sqlparse-mut-164-nm | 2a | ce76480985b3 |
| sqlparse-mut-045-nm | 1 | c3593472b419 | sqlparse-mut-323-nm | 2a | e25c7bf1a603 |
| sqlparse-mut-059 | 1 | 24205ccdf809 | sqlparse-mut-089-nm | 2a | bcbb7dcdff50 |
| sqlparse-mut-020 | 1 | a16b33141c1b | sqlparse-mut-152 | 2a | 76db3c9e2560 |
| sqlparse-mut-062-nm | 1 | 5206d38dc05d | sqlparse-mut-226 | 2a | 3decec5a15db |
| sqlparse-mut-005 | 1 | 25bd643b8f47 | sqlparse-mut-102 | 2a | 2375b02efd5c |
| sqlparse-mut-154 | 2a | 6fb88b89265c | sqlparse-mut-085 | 2a | 160bb0c782a8 |
| sqlparse-mut-310-nm | 2a | 4d6ea4772079 | sqlparse-mut-181 | 2a | 1db3f049e6c2 |
| sqlparse-mut-172-nm | 2a | 56f036fbfe75 | | | |
| sqlparse-mut-186-nm | 2a | 5328183f07ab | | | |
| sqlparse-mut-111 | 2a | 3deec5bd259b | | | |

The hash includes `evaluate_task.py`'s bytes as checked out (CRLF on this Windows checkout), as for card 010.

## Verifier-commit: ported verifier-only, generation confined in podman

**History.** The arm's code (card 021) is on `integration/2026-10` (merge `dbcca70`, which brings `wt/card021` with
`wt/cloud-port` and `wt/cli-retry`, plus the guard fix `4ae5dea`). Merging `dbcca70` into this branch was tried on
2026-10-01 and aborted before any commit: the merged `claude_cli.cli_contract` adds a `model_pin` block to the routing
contract for every full model id, which changes the planned hash of all 31 tasks in the incumbent, memory and symbolic
arms (186 of 186 invocations; e.g. `sqlparse-mut-015` incumbent `8ad5bfad9053` would become `3f1a67374a22`). The owner
chose option 2 of the three then listed: port only the verifier (decision 1 below).

**Port (commit `07f70df`).** Only what the arm needs, from `52deea7`, `a41fcff` and `4ae5dea`:
- taken whole: `experiments/p6_pilot/run_repro_test.py`, `reticle/tools/repro_verifier.py`,
  `reticle/tools/commitment.py`, `reticle/runtime/nudges.py`, `reticle/tools/check_oracle.py`,
  `experiments/session_harness/score_commitments.py`, `tests/test_card021_verifier_commit.py` (adapted, below);
- `experiments/p6_pilot/repro_verifiers.py`: from integration; the generator's auth, model-pin and reported-model
  checks (b083d70's, with 4ae5dea's stop prefixes) are defined in the generator instead of `claude_cli.py`, so
  `cli_contract` is unchanged; generation also gets the runner's CLI pin (`DISABLE_AUTOUPDATER=1`; every attempt's
  `claude_code_version` must equal the version `claude --version` reported when generation started);
- `experiments/p6_pilot/run_pilot.py`: `52deea7`'s hunks by hand (`--verifier`, `--verifier-manifest`,
  `--nudge commit`, the per-task bundle, tool order with `--reasoning`).
- Not brought: `claude_cli.py` (the `model_pin` contract), the cloud port, CLI reply recovery, the unshare-confined
  cloud backend (`eb74ac7`, card 021's integrity-audit fix: it confines the cloud trusted-local `run` tool and is not
  on the OCI path), card 021's records.
- Card 021 was contaminated because its trusted-local `run` tool had no path guard. Nothing in this arm can fall back to
  trusted-local now: `run_pilot.py` refuses `--verifier` without `--backend oci`, `build_tools` refuses a verifier
  without an isolated backend, and `ReproTestVerifier` itself refuses a backend that is not host-isolated (it used to
  inherit `AcceptanceRunner`'s `TrustedLocalBackend` default).

**Confinement (commit `c47deb8`).** Every step that executes a model-written test runs it in this card's image, through
the same `IsolatedOCIBackend` the runs use, resolved exactly as `run_pilot.py --backend oci` resolves it:
- generation's pre-edit run (`run_on_tree`, the run that decides what is frozen) and offline `score` / `agree`
  (`check_tree`, which used `ReproTestVerifier` with no backend, i.e. trusted-local);
- `podman run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128
  --memory 512m --userns keep-id --tmpfs /tmp:rw,noexec,nosuid,size=64m`, one bind mount at `/workspace` holding only
  a scratch copy of the pre-edit tree (`candidate/`) and the bundle (`bundle/`), the guest `python`, the same 300 s
  pytest timeout (+60 s outer);
- `--oci-image` (default `localhost/reticle-p6-task:py313-v1`); the image id is recorded in the manifest's generator
  record (`pre_edit_execution`) and in `validity.json` / `agreement.json`;
- fail closed: no engine or no image stops `generate`, `score` and `agree` before any model call or test run; there is
  no host fallback.

Evidence, 2026-10-01, no model call (image ID `8b74015e5079d613...`):
- A hand-written reproduction test for `sqlparse-mut-154` (`repr(sqlparse.parse("select 1")[0].tokens[0])` starts with
  `<DML 'select'`) through `run_on_tree` in podman: **mutated tree 1 collected, 1 failed; gold tree 1 collected,
  1 passed**. Neither tree was touched.
- A probe test in the same container: a TCP connect to `1.1.1.1:53` failed with `OSError`, an https fetch of pypi.org
  failed with `URLError [Errno -3]`, and `/workspace` held only `bundle` and `candidate`.
- `tests/test_card021_verifier_commit.py::RealPodmanTests` (2 tests; skipped unless `RETICLE_OCI_TEST_IMAGE` is set,
  like the repository's other OCI tests) passed with this image: fail on mutated, pass on gold, no network, and the
  check() path in the container.
- Scripted controls under this arm's flags, one task, with a hand-written one-task manifest outside the repository
  (generation needs model calls; `run_pilot.py` directly, since `run_card.py` runs controls only with `--execute`):
  gold **accepted**, noop **rejected**, backend `isolated-oci`, verifier bundle available (1 case), commit nudge
  `commit-nudge-v1`. Run folders kept outside the repository.

**Generation calls, and when** (`repro_verifiers.py generate`):
- After the owner's launch approval and before the campaign, once per task, never during a run: a headless
  `claude -p` (the private 2.1.286 first on PATH) with the pinned model, a fresh context, only the CLI's Read, Glob and
  Grep tools on a temporary copy of the pre-edit workspace, `--permission-mode dontAsk`, `--max-budget-usd 0.60` per
  call, at most 30 turns.
- 1 call per task if the first file compiles, collects at least one case and has at least one failing case on the
  pre-edit tree (now run in podman); otherwise up to `MAX_ATTEMPTS` = 3 calls (each retry sees the previous file, its
  counts and the pytest tail). **At most 3 calls per task, 93 for 31 tasks**; expected about 43 (card 021 averaged
  1.375 calls per task, 11 for 8 tasks; 1.6 on its 5 hard tasks). Confinement adds no call.
- Spend cap: the default `--spend-cap-usd` is $8, too low for 31 tasks. **Approved: $30** (owner, 2026-10-01; $56 had been
  proposed, the hard maximum 93 x $0.60 = $55.80). A task that can get no call
  under the cap is recorded unavailable; check() then returns an error.
- Command: `python experiments/p6_pilot/repro_verifiers.py generate --out
  experiments/session_harness/verifiers/024 --tasks experiments/mutation_tasks/tasks.pilot024-eval.json --model
  claude-sonnet-5 --spend-cap-usd 30 --oci-image localhost/reticle-p6-task:py313-v1`.
- The frozen tests go to `experiments/session_harness/verifiers/024/` with `manifest.json`, whose sha256 is a hash
  input. **The verifier-commit hashes `--plan` prints today are provisional** (planned with `manifest_sha256_lf` null);
  they change once the manifest exists, and the runner refuses a verifier run without it. Hence the card's
  prerequisite "Verifier manifest generated".

**Backend during the campaign.** check() runs the frozen test through the run's OCI backend: a separate `--rm`
container whose only mount is a scratch copy, and the verifier bundle lives in the run directory outside the
workspace the model's commands mount.

## Tasks and cross-task state

- Tasks: the 31 ids under `eval` in
  [`E3-difficulty-calibration-010.eval-combined.json`](E3-difficulty-calibration-010.eval-combined.json) (pinned by
  sha256), every one role `eval-010-combined` in the [pooled registry](TASK_REGISTRY.md). The task file holds only those
  31 (the builder refuses any other role). No quarantined-eval-twin, dev, evolution or boltons task is planned: the
  plan's 248 runs and 2 controls name only the 31.
- Cross-task state, by arm:
  - incumbent, memory, symbolic: none. The runner reads only the task's own definition; `--reasoning` builds its graph
    from the current run's session journal ("rebuildable over authorized session history"); no lesson store, memory
    store or evolution set is read. The nested CLI runs with `--setting-sources ""`, `--safe-mode` and
    `--no-session-persistence`, so no CLAUDE.md, auto-memory or earlier session reaches it.
  - verifier-commit: reads `verifiers/024/manifest.json`, which holds all 31 tasks' frozen tests, but the runner copies
    only the current task's entry (sha256-checked) into that run's verifier bundle. Each entry is written before the
    campaign from that task's statement and pre-edit tree only (no gold, no hidden tests, no other task).
- Evolution tags: 21 of the 31 eval tasks carry `evolution-contrastive` (12) or `evolution-negative` (9) as registry
  tags (card 010's stage evolution lists). No arm here iterates on anything: there is no lesson, memory-store or
  evolution step. **Flag:** any later evolution or lesson step that selects tasks by those tags would select eval tasks;
  it must not.

## Decision rule (written before data)

A screen. For each treatment arm T, over the 31 tasks:
- d(T) = mean over tasks of (T's accepted runs / 2 - incumbent's accepted runs / 2);
- wins(T) / losses(T) = tasks where T's per-task rate is higher / lower than the incumbent's.

Readings:
- **Follow-up justified** for T when d(T) >= +0.10 (about +6 accepted runs of 62) and wins(T) > losses(T).
- **Possible harm** when d(T) <= -0.10; recorded, no follow-up.
- Otherwise: no follow-up for T on this evidence; reported as uncertain, not negative.
- If several arms qualify, the powered follow-up takes the one with the largest d(T); a tie goes to the cheaper arm
  (fewer model calls per run, generation included).
- Reported alongside, not deciding: tool use per run for memory and symbolic (`reasoning_state` / `assess_check` reads
  and `reasoning_update` writes; unused tools are a usability failure, not evidence against inference), check() calls
  and commitments for verifier-commit, tokens and list cost per arm. The interpretation table in
  [`experiments/neurosymbolic/README.md`](../neurosymbolic/README.md) reads the pattern.

Nothing here is a significance claim; a +0.10 threshold is below the roughly 23-point effect the screen can detect,
on purpose, so that a screen errs toward a follow-up. The owner kept the threshold on 2026-10-01 ("Keep +0.10
(Recommended)", decision 3 above).

## Runs, caps and calls

| | Count |
|---|--:|
| Runs | 31 tasks x 2 rollouts x 4 arms = **248** (62 per arm), plus 2 scripted controls (gold, noop; no model) |
| Attempts per run | 24 (`--max-attempts-per-run`, `--max-total-calls 24`) |
| Campaign attempt cap | 248 x 28 = **6,944** (card 010's 28 per run: 248 x 24 = 5,952 planned, room for retries) |
| Repro generation | 1-3 calls per task: expected about 43 (31 x 1.375), at most **93** |
| Maximum possible model calls | 6,944 + 93 = **7,037** |

Schedule: rollout-major; arm order seeded per (block, task, rollout) with seed 24; one runner invocation per task,
rollout and arm, named `c024-<task>-r<k>-<arm>`.

## Cost and time estimate

Basis: card 010's own calibration runs of these 31 tasks (the incumbent protocol, same model and CLI): sum of
`cli_result.total_cost_usd` over `calls.jsonl` of the 62 valid runs = **$79.71**, i.e. **$1.286 per run** (min $0.17,
max $2.44), **$2.571 per eval task** for 2 runs. 32 of the 62 runs were accepted.

- Campaign, at the incumbent rate: 248 x $1.2857 = **$318.85** (= 4 arms x 31 tasks x $2.571).
- If the treatment arms cost 20% more per run (card 013's finish-guard arm cost 21% more): 62 x $1.286 + 186 x $1.543
  = $79.7 + $287.0 = **$366.7**.
- Worst case, every run at card 010's maximum: 248 x $2.442 = $605.6.
- Repro generation: card 021 spent $4.83 for 8 tasks ($0.604 per task; $0.893 on its hard tasks): expected
  31 x $0.604 = **$18.7** (31 x $0.893 = $27.7 at the hard-task rate); at most 93 x $0.60 = $55.80; approved
  `--spend-cap-usd 30` (owner, 2026-10-01). Running the pre-edit check in podman changes no call or cost.
- Total expected about **$338-395 list**. The CLI subscription bills nothing today; billing is recorded as unknown.
- Wall time: card 010's mean on these 62 runs was 7.07 min (max 21.7). 248 x 7 min = 1,736 min = **about 29 h**
  sequential (248 x 7.07 = 29.2 h), plus the controls (minutes) and generation (not measured here).

## Risks

- **Agent SDK subscription-credit change.** The paused change to how subscription credit covers headless / Agent SDK
  use could resume during a 29-hour campaign. Then `claude -p` calls would draw on metered credit or hit a different
  limit, and the list-price figures above become real spend (about $340-400, up to about $660 worst case). This
  branch's `run_card.py` has no list-price cap (`list_price_cap_usd` exists only on `integration/2026-10`); the
  campaign attempt cap is the only hard limit. Check the billing status at launch and checkpoint daily.
- Usage limits: card 018 lost runs to them; such runs are voided and rerun (stop rules).
- CLI version: the private 2.1.286 copy must be first on PATH; a different version stops the campaign.
- Verifier generation: model-written test files now run only in podman (network none, scratch mount); podman or
  the image missing stops generation before any call.

## Stopping rule

As card 010: a checkpoint after 3 consecutive failures; void and rerun runs ended by a usage limit, an adapter failure
or a machine sleep; stop on evaluator leakage, evidence loss, authority escape, a model or CLI pin violation; no change
to a treatment's text or parameters, and no regeneration of a frozen test, during the card. The campaign ends at 248
valid runs or the attempt cap; an extension needs a new approval.

## Not done

- No model call, no campaign run, no generation. The card is not launched; the owner approves the launch (runs, cost,
  generation calls and spend cap) separately.
- The verifier-commit hashes are provisional until the manifest is generated.
- The card's own gold/noop controls (31 tasks each) were not run: `run_card.py` runs them only with `--execute`,
  which a proposed card refuses. Only the one-task sample above (gold/noop under the verifier arm's flags) was run.
- No report skeleton was written; `run_card.py --execute` writes it.
