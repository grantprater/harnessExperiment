# Trajectory label schema (S6b)

Labels for recorded repair runs, used by weakness mining ([`weakness_mining.py`](../weakness_mining.py)) and by
any future trajectory classifier. The unit is one **assistant response** (one model reply, which may carry several
tool calls); a run also gets four run labels. Everything here is decidable from the session journal and the task
file, except `diagnose` and the free-text mechanism, which need judgement.

## Phase label, one per response

Apply the first rule that fits.

1. **stuck**: every tool call in the response repeats an earlier call of the same run exactly (same tool, same
   arguments) and that earlier call was rejected, or has run with no workspace change since; in either case the
   earlier call's result was still in the model's context when it made this response. Re-issuing a call whose
   earlier result the context policy had omitted is a refetch, not a repeat (added 2026-09-28 from card 007; see
   below).
2. Otherwise take the most advanced phase among the response's non-repeated calls, in this order:
   **finish > edit > verify > reproduce > diagnose > explore > other**.

| Phase | A call has this phase when |
|---|---|
| finish | it is `finish`; or, in a run without a finish tool, the run's last response is text only and the run ended normally |
| edit | it changes a file that existed before the run (source, tests, configuration), or creates a new non-scratch source file |
| verify | it runs a command that exercises the code (tests, a script, `python -c`) after the run's first edit of a pre-existing file |
| reproduce | before any edit of a pre-existing file, it writes a new scratch script or test, or runs a command that exercises the code, to observe the reported behaviour; later edits of that scratch file stay `reproduce` |
| diagnose | it reads, searches, or prints code the agent has already located as the suspected cause, to test or narrow a stated hypothesis about the fault |
| explore | it lists, searches, or reads files, or runs a look-only command (`ls`, `cat`, `grep`, `git`, test discovery such as `pytest --collect-only`, `pip`), to find or understand relevant code, tests, or behaviour |
| other | anything else: history, notes, output paging with no clear purpose; a text-only response that does not end the run |

A rejected call keeps the phase of what it tried to do (a rejected `run` before any edit is `reproduce`).

## Run labels

| Label | Type | Definition |
|---|---|---|
| `first_edit_response` | int or null | number of the first response with a successful edit of a pre-existing file |
| `verified_before_finish` | bool | the run edited a pre-existing file and ran a verify command (not rejected) after its last such edit, before the run ended; false when there was no such edit |
| `edit_in_gold_files` | bool | a successful edit touched a file in the task's `gold_source_files` |
| `mechanism` | short free text | at most six words saying why the run ended as it did, e.g. `explored_until_budget`; human or Claude |

## Failure signature (computed by `weakness_mining.py`)

`signature = verifier cause | causal status | mechanism`, clustered on exact equality.

**Verifier cause**, first match wins: `accepted`; `evaluator_error` (an evaluation measurement reported an
infrastructure error, or no accept/reject decision); `adapter_error`, `provider_error`, `timeout` (the run stopped on
the client or runtime, on provider HTTP/network failures after retries, or on active time or the deadline);
`pass_to_pass_regression`; `fail_to_pass_failed` (a pre-existing file was edited and the target tests still fail);
`budget` (no such edit, stopped by the response, attempt, tool, cost, or context budget); `no_edit` (no such edit,
the model stopped itself: `finish` or the repeat stop). Infrastructure causes and `accepted` are not mined.

**Causal status**, a `+`-joined set of flags (or `none`): `rejected_calls` (at least one rejected call; the count
is kept per run), `repeated_call` (at least one `stuck` response), `refetch_after_omission` (at least one call
re-issued an identical earlier call, with no workspace change since, whose result the context policy had omitted
from the request; the count is kept per run), `repeat_stop` (the runner's repeat guard ended the run), `edit_outside_gold` (an edited pre-existing file is not a gold file), `no_verification_before_finish`
(`finish` was called and no verify call followed the last edit, or there was no edit), `gold_unknown` (the task file
has no gold files for this task).

**Mechanism (rule)**, a fixed vocabulary derived from the rule phases so that it clusters: `no_response`,
`no_action` (no explore, reproduce, or edit), `explore_only`, `reproduce_no_edit`, `edit_unverified`,
`edit_verified`. The free-text run mechanism above is for people and for a future classifier; it is not clustered.

## How the rules implement the phases

`weakness_mining.label_trajectory` maps tools to phases: `list_files`, `glob_files`, `read_file`, `outline`,
`search`, `search_text`, `read_output`, `search_output` (and Claude Code's `Read`, `Grep`, `Glob`) are explore;
`replace_text`, and `write_file` that overwrote a file (`Edit`, `Write`), are edit, unless the file was created in
the run as a scratch file; `write_file` that created a file named like a scratch or test script (`test_*`,
`repro*`, `debug*`, `check*`, ..., at the workspace root or under `tests/`) is reproduce; `run` (`Bash`,
`PowerShell`) is explore for look-only commands, otherwise reproduce before the first edit and verify after it;
`finish` is finish; history and note tools are other. Look-only commands are the first word in a fixed list (`ls`,
`cat`, `grep`, `git`, ...) plus `pytest --collect-only`/`--co` and `pip`/`python -m pip` (`LOOK_ONLY_RUN`). "No
workspace change" uses the journal's workspace revision at each call, the same key as the runner's repeat guard;
Claude Code streams have no revision, so the count of earlier successful edits and commands stands in for it. "Still
in the model's context" uses the journal's `context_manifest` for each request: its `omitted_items` name the
transcript units (unit k is response k + 1) the context policy left out. The runner's repeat guard does not look at
omissions, so it can count a refetch as a repeat; Claude Code streams have no manifest, so every earlier result
counts as in context. **The rules never emit `diagnose`**: they label every read `explore`.

The two card-007 fixes (2026-09-28, [weakness-mining-c007.md](../weakness-mining-c007.md)): all three `stuck`
responses in the 40 runs were re-reads of results `pressure-recent-v3` had omitted (a context symptom, not a loop),
and `pytest --collect-only` (which runs no test) and a `pip download` were labelled reproduce or verify. Neither fix
changes a label of the held-out set below or a signature of the baseline runs. The Jev questions
(`jev_labeller.QUESTIONS`, sha256 `c199d959aeda...`) keep the earlier stuck and explore wording; Jev's state does
not show omissions, so it cannot apply the context clause. Rule-versus-Claude agreement is measured per phase in
[weakness-mining-baseline.md](../weakness-mining-baseline.md).

## The labelled set is held out

[`labels.jsonl`](labels.jsonl) holds every response of E3 runs 3 and 4 and `pc-reticle-sonnet-2` (49 responses)
labelled by the rules, by Claude (Sonnet via the CLI, fixed prompt [`claude_phase_prompt.md`](claude_phase_prompt.md)),
and a gold label (agreement reviewed, or adjudicated by the orchestrating agent standing in for a human), plus one
run record per run. **This set is the held-out evaluation set for any future classifier or labelling prompt.** Do
not train on it, tune a prompt against it, or choose a threshold from it; measuring on it is fine. Label new
trajectories (card 007 and later) in a separate file, and use those for development.

Card 007 (development, not held out): [`labels_c007_rules.jsonl`](labels_c007_rules.jsonl) (rule phases and facts
for all 533 responses of the 40 runs, plus run labels and signatures), [`labels_c007_jev.jsonl`](labels_c007_jev.jsonl)
(Jev, same questions), and [`diagnose-devset.jsonl`](diagnose-devset.jsonl) (a diagnose adjudication by the mining
agent standing in for a human; its header record states the conventions). Tune diagnose questions or thresholds on
these, never on `labels.jsonl`.

Record fields: `kind` (`response` or `run`), `run`, `task_id`, `response`, `rule_phase`, `claude_phase`,
`claude_mechanism`, `gold_phase`, `gold_source`, `note`; run records carry the rule and human values of the run labels.
