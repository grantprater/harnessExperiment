# Weakness-mining baseline (S6b): E3 runs 1-4 and the positive control

Date: 2026-09-27  
Tools: [`weakness_mining.py`](weakness_mining.py) (signatures, clusters, rule phases), [`label_phases.py`](label_phases.py)
(Claude labelling and agreement); schema [`labels/SCHEMA.md`](labels/SCHEMA.md); labelled set
[`labels/labels.jsonl`](labels/labels.jsonl)  
Inputs, read-only: `experiments/p6_pilot/runs/e3-sqlparse-*-{1..4}`, `pc-reticle-sonnet-{1,2}` (session journals kept
locally under `sessions/`, git-ignored), `native_runs/pc-native-sonnet-1` (Claude Code stream)

```
python experiments/session_harness/weakness_mining.py \
  runs/e3-sqlparse-gemma-deepinfra-1 runs/e3-sqlparse-gemma-cloudflare-2 runs/e3-sqlparse-qwen-parasail-3 \
  runs/e3-sqlparse-qwen-parasail-4 runs/pc-reticle-sonnet-1 runs/pc-reticle-sonnet-2 native_runs/pc-native-sonnet-1
```

## Clusters

Signature = verifier cause | causal status | mechanism (rule vocabulary), clustered on exact equality; minable
clusters first, ranked by distinct tasks, then runs. Infrastructure causes and `accepted` are not minable.

| # | Verifier cause | Causal status | Mechanism | Runs | Tasks | Minable | Runs in cluster |
|---:|---|---|---|---:|---:|---|---|
| 1 | `budget` | `rejected_calls` | `explore_only` | 1 | 1 | yes | e3-sqlparse-qwen-parasail-3 |
| 2 | `budget` | `rejected_calls+repeated_call` | `reproduce_no_edit` | 1 | 1 | yes | e3-sqlparse-qwen-parasail-4 |
| 3 | `no_edit` | `repeated_call+repeat_stop` | `reproduce_no_edit` | 1 | 1 | yes | e3-sqlparse-gemma-cloudflare-2 |
| 4 | `adapter_error` | `none` | `no_response` | 1 | 1 | no | pc-reticle-sonnet-1 |
| 5 | `provider_error` | `none` | `reproduce_no_edit` | 1 | 1 | no | e3-sqlparse-gemma-deepinfra-1 |
| 6 | `accepted` | `none` | `edit_verified` | 2 | 1 | no | pc-reticle-sonnet-2, pc-native-sonnet-1 |

| Run | Task | Source | Stop (class) | Acceptance | Rejected | Stuck responses | First edit | Edit in gold | Verified before finish | Phases (rule) | results.jsonl |
|---|---|---|---|---|---:|---|---:|---|---|---|---|
| e3-sqlparse-gemma-deepinfra-1 | sqlparse-865 | reticle-journal | `model_error` (provider_error) | rejected | 0 | - | - | False | False | explore reproducex2 explore | agrees |
| e3-sqlparse-gemma-cloudflare-2 | sqlparse-865 | reticle-journal | `model_error` (repeat_stop) | rejected | 0 | 9, 16, 17, 18 | - | False | False | explorex3 reproducex4 explore stuck explorex6 stuckx3 | agrees |
| e3-sqlparse-qwen-parasail-3 | sqlparse-865 | reticle-journal | `model_call_limit` (budget) | rejected | 4 | - | - | False | False | explorex20 | agrees |
| e3-sqlparse-qwen-parasail-4 | sqlparse-865 | reticle-journal | `model_call_limit` (budget) | rejected | 4 | 18, 19 | - | False | False | explorex15 reproducex2 stuckx2 reproduce | agrees |
| pc-reticle-sonnet-1 | sqlparse-865 | reticle-journal | `model_error` (adapter_error) | rejected | 0 | - | - | False | False | - | agrees |
| pc-reticle-sonnet-2 | sqlparse-865 | reticle-journal | `finish_requested` (finish) | accepted | 0 | - | 6 | True | True | explorex5 edit verifyx2 finish | agrees |
| pc-native-sonnet-1 | sqlparse-865 | claude-code-stream | `end_turn` (finish) | accepted | 0 | - | 8 | True | True | explorex7 edit verifyx2 finish | n/a |

Reading the table:

- **Three minable clusters, one run each, all on one task (`sqlparse-865`).** Support is 1 everywhere, so ranking
  by distinct-task support cannot separate them yet; the ranking becomes informative on card-007 trajectories.
- Cluster 1 (Qwen run 3): read tests and `grouping.py` for 20 responses after naming the fix site at response 3;
  4 rejected `search` calls, each recovered next response, none repeated. No command, no edit.
- Cluster 2 (Qwen run 4): the same exploration for 15 responses, a reproduction script at 16, then the identical
  rejected `cd /testbed && python test_issue.py` twice (responses 18-19, `stuck`); the budget ended at 20.
- Cluster 3 (gemma run 2): reproduced early (responses 4-7), then re-read `sql.py` ranges it already had in full
  until the runner's repeat guard stopped it; the 4 `stuck` responses are exactly the repeats the
  [run-2 report](E3-sqlparse-gemma-cloudflare-2.md) lists.
- Clusters 4-5 are infrastructure (the adapter v1 failure, DeepInfra HTTP 429) and are excluded from mining.
- Cluster 6 holds both accepted arms: explore, one gold-file edit, two checks, finish. The two harnesses give the
  same signature and the same phase shape (Reticle 5 explore responses with batched calls, Claude Code 7).
- `results.jsonl` agrees with the journal-derived stop reason and acceptance for every Reticle run.

Sanity check on the no-API controls (`pc-v8-control-{gold,noop}-sqlparse`): the gold client comes out
`accepted | no_verification_before_finish | edit_unverified` (it writes the fix and finishes without a check) and
the noop client `no_edit | no_verification_before_finish | no_action`, as they should.

| # | Verifier cause | Causal status | Mechanism | Runs | Tasks | Minable | Runs in cluster |
|---:|---|---|---|---:|---:|---|---|
| 1 | `no_edit` | `no_verification_before_finish` | `no_action` | 1 | 1 | yes | pc-v8-control-noop-sqlparse |
| 2 | `accepted` | `no_verification_before_finish` | `edit_unverified` | 1 | 1 | no | pc-v8-control-gold-sqlparse |

## What the signature needs besides the journal

- **Reticle runs: the journal alone, except the gold files.** Verifier cause, stop class, rejected calls, repeats,
  phases, first edit, and verification all come from `events.jsonl` and the artifact store it references
  (transcript messages, `action_outcome` workspace revisions, `provider_attempt_finished` outcomes,
  `agent_run_result`, `evaluation_measurement`, `acceptance_decision`). `calls.jsonl` is never read.
  `results.jsonl` is read only for the cross-check column. **`edit_outside_gold` and `edit_in_gold_files` need the
  task file's `gold_source_files`**: the journal's task contract does not carry them (they are hidden from the
  model), nor does the evaluator bundle's `task.json`. Without a task file the run is flagged `gold_unknown`.
- **Claude Code runs have no journal.** `pc-native-sonnet-1` is read from `stream.jsonl` and `result.json`
  (acceptance, timeout, CLI result subtype). There is no workspace revision per call, so the repeat rule uses the
  count of earlier edits and commands as a stand-in.
- The verifier cause separates `budget` from `no_edit` by the stop reason, and `fail_to_pass_failed` from both by
  whether a pre-existing file was edited. It does not read the evaluator's failing-test list.
- No field needs prose (reports, narration, or Claude labels). The free-text run mechanism is not part of the
  clustered signature.

## Labelled set: rules versus Claude

Every assistant response of E3 runs 3 and 4 and `pc-reticle-sonnet-2` (20 + 20 + 9 = 49), labelled by the rules and
by Claude: Sonnet (`claude-sonnet-5`) through the local CLI in headless mode (`claude -p --model sonnet
--output-format json --max-turns 1`, no tools, no settings, no session persistence, subscription login), one call
per response, serialised under `.runtime/locks/live-run.lock`, with the fixed system prompt
[`labels/claude_phase_prompt.md`](labels/claude_phase_prompt.md) (sha256 `0e65f36a2a9a...` of its LF bytes as
committed). 49 calls, each succeeding on its first attempt; 177 s in total; CLI list-price estimate $0.56, not
billed. One further smoke call was not recorded. The per-call request hash is in each record.

**Gold labels:** where the rules and Claude agree, the label was reviewed and kept. Where they disagree, **the
orchestrating agent (Claude Opus 5.5) adjudicated as a stand-in for a human reviewer. No human labelled this set.**
Gold is therefore not independent of the rules: the same agent wrote the schema, the rules, and the adjudication.
Read "rules = gold" as consistency with the schema's strict wording, not as the rules' accuracy.

Responses: 49; rule = Claude on 43 (87.8%); Cohen's kappa 0.71.

| Phase | Rule | Claude | Both | Specific agreement | Gold | Rule = gold | Claude = gold |
|---|---:|---:|---:|---:|---:|---:|---:|
| explore | 40 | 34 | 34 | 0.92 | 40 | 40 | 34 |
| reproduce | 3 | 3 | 3 | 1.00 | 3 | 3 | 3 |
| diagnose | 0 | 6 | 0 | 0.00 | 0 | 0 | 0 |
| edit | 1 | 1 | 1 | 1.00 | 1 | 1 | 1 |
| verify | 2 | 2 | 2 | 1.00 | 2 | 2 | 2 |
| finish | 1 | 1 | 1 | 1.00 | 1 | 1 | 1 |
| stuck | 2 | 2 | 2 | 1.00 | 2 | 2 | 2 |

Against gold (49 responses): rules 49/49, Claude 43/49.

Every disagreement, with the adjudication:

| Run | # | Rule | Claude | Gold | Claude's mechanism | Adjudication note |
|---|---:|---|---|---|---|---|
| e3-sqlparse-qwen-parasail-3 | 2 | explore | diagnose | explore | Reads sql.py's NameAliasMixin.get_real_name to locate the dot-splitting logic causing the bug. | First read of sql.py, 'where get_real_name() is likely defined': locating code, no suspected cause stated yet. |
| e3-sqlparse-qwen-parasail-3 | 13 | explore | diagnose | explore | Reads group_period/group_as grouping logic to locate root cause of dotted-name bug. | Reads group_identifier/group_period 'to understand how identifiers with dots are parsed'; no fault hypothesis stated, and the fault is in sql.py. |
| e3-sqlparse-qwen-parasail-4 | 2 | explore | diagnose | explore | Reads sql.py to locate and inspect get_real_name/token_next_by logic causing bug. | Same as run 3 #2: first whole-file read of sql.py to find get_real_name; locating, not testing a hypothesis. |
| e3-sqlparse-qwen-parasail-4 | 12 | explore | diagnose | explore | Reads group_period function to test hypothesis about dotted-name grouping logic. | Borderline: 'group_period ... seems to handle dots' guesses where dot handling lives, not a suspected cause of the fault; strict reading gives explore. |
| e3-sqlparse-qwen-parasail-4 | 14 | explore | diagnose | explore | Searches grouping.py for _group function definition to trace identifier grouping logic. | Searches for the definition of _group after a 0-match regex query; finding a definition is explore by the schema. |
| pc-reticle-sonnet-2 | 2 | explore | diagnose | explore | Reads get_real_name/get_parent_name/_get_first_name implementations to locate the dot-splitting bug. | Borderline: first read of the three methods its searches located; no text, so no stated hypothesis; strict reading gives explore. |

Run labels (3 runs): the rules and the adjudicated values agree on `first_edit_response` (none, none, 6),
`verified_before_finish` (false, false, true) and `edit_in_gold_files` (false, false, true). The free-text
mechanisms are `explored_until_budget`, `late_repro_then_rejected_command_loop`, `located_edited_verified_finished`.

## Which rules are unreliable

- **`diagnose` is out of reach of the rules and unreliable from Claude.** The rules never emit it. Claude used it 6
  times, each for a read of code near the fault with no hypothesis stated, and all 6 were adjudicated `explore`
  under the schema's requirement of a stated hypothesis. Two of the six (run 4 #12, pc-2 #2) are borderline. All
  disagreement in this set is on this one boundary. A classifier or a revised prompt needs its own diagnose
  examples and must not tune on this set.
- **Small counts outside explore.** 40 of 49 responses are `explore`. reproduce (3), stuck (2), verify (2),
  edit (1) and finish (1) agree perfectly, but on too few cases to call those rules validated. They were exercised
  more broadly only by the synthetic tests and the 7-run table above.
- **Rules not exercised by any recorded response:** `other` (no history or note tool was used); scratch-file
  naming (a new file at the workspace root always counts as scratch, so a new top-level module would be labelled
  `reproduce`); look-only shell commands (`cat`, `grep`, ...) as `explore`; `pass_to_pass_regression`; `timeout`;
  `edit_outside_gold`. The repeat rule on Claude Code streams uses a mutation count, so a read-only `Bash` between
  two identical calls hides the repeat.
- **Verify versus reproduce depends only on order.** Running the reproduction script after the first source edit
  counts as `verify`, whether or not the agent meant it as a check.

## Not done

- No run from card 007: the S6a trajectories do not exist yet. This baseline is 7 runs on one task.
- No cheap classifier was trained, and none was measured in this baseline. The labelled set is reserved as the
  held-out set for one.
- No human labels. The adjudication is by the orchestrating agent.
- Runs 1 and 2 and the native arm were not labelled by Claude. They have rule phases only, in the table above.

Follow-up: Jev (`typesafe/jev-1.13`, untrained, three decomposed questions) was measured on this set in [labels/jev-agreement.md](labels/jev-agreement.md): Jev = gold 49/49, 0 `diagnose`; gold has no `diagnose`, so its diagnose recall is unmeasured.
