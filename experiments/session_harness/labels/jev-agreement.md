# Jev as a phase labeller: agreement on the held-out set (S6b)

Date: 2026-09-27  
Tools: [`jev_labeller.py`](../jev_labeller.py) (questions, request, reply parsing),
[`label_phases.py`](../label_phases.py) `--labeller jev` (labelling and agreement); schema [`SCHEMA.md`](SCHEMA.md)  
Held-out set: [`labels.jsonl`](labels.jsonl), read only and unchanged: the 49 responses of E3 runs 3 and 4 and
`pc-reticle-sonnet-2`, with rule, Claude, and gold phases  
Outputs: [`labels_jev.jsonl`](labels_jev.jsonl) (first pass) and [`labels_jev_repeat.jsonl`](labels_jev_repeat.jsonl)
(a second, identical pass for determinism), one record per response keyed by (run, response)  
Model: `typesafe/jev-1.13` through OpenRouter's decisions endpoint (`POST /api/alpha/decisions`); every reply named
`typesafe/jev-1.13-20260917`

## Result in brief

- **Jev = gold on 49/49 (kappa 1.00)**, and so Jev = rules on 49/49. Jev = Claude on 43/49 (kappa 0.71); the 6
  differences are exactly Claude's 6 `diagnose` labels, which the adjudication had already put back to `explore`.
- **Jev did not over-use `diagnose`: 0 of 49** (Claude 6). Its largest diagnose probability was 0.24.
- **Gold is not independent of the rules** (the same agent wrote the schema, the rules, and the adjudication, and
  rules = gold on 49/49). Jev agreeing with gold therefore means Jev reproduces the schema's strict reading on this
  set, where the rules already did so for free. This set has no gold `diagnose` and no `other`, so it cannot show
  whether Jev finds a real `diagnose` when one occurs.
- The two yes/no questions found every rule-positive response (values 0.97) and had one false positive each, both
  on the same response: the finish response, whose text narrates the fix and its checks.
- **Deterministic in label, not in number:** the second identical pass gave the same phase on 49/49; probabilities
  moved by up to 0.08 and the yes/no values by up to 0.07.
- Cost $0.00475 per 49-response pass (about $0.0001 per call, 2,308 input tokens on average), 9-10 s wall time per
  pass, against 177 s and a $0.56 list-price estimate for the Claude pass.

## What Jev sees, and what the Claude labeller sees that Jev does not

- **The state is the Claude labeller's user message, byte for byte.** `label_phases.render_request` produces it for
  both labellers; the sha256 of each of the 49 states equals the `request_sha256` recorded for Claude in
  `labels.jsonl` (49/49). No further length limit was needed: the largest call was 2,941 input tokens (state plus
  the three questions) against Jev's 32k-token state limit. Both labellers therefore see the same cuts the renderer
  already makes: the task statement, each call's arguments, and each call's result are cut at 1,500 characters,
  and earlier responses appear only as one-line summaries (arguments cut to 60 characters per value and 160 in
  all, the first result line to 80, the text of a response without calls to 120).
- **The rules reach Jev in a different place.** Claude reads them as one system prompt
  ([`claude_phase_prompt.md`](claude_phase_prompt.md)) followed by the state; Jev reads them split across question
  instructions and one rubric line per option, with the state description repeated in each of the three questions.
  The wording is taken from `SCHEMA.md` (the phase table and the precedence rule) and the first paragraph of the
  Claude prompt.
- **Jev gives no mechanism.** Claude also writes a free-text mechanism per response; the Jev request has no
  free-text question, so `claude_mechanism` has no Jev counterpart.
- **Nothing was tuned on this set.** The questions, the 0.5 yes/no threshold, and the confidence bins were written
  before any Jev reply on a held-out response. The one development call went to `e3-sqlparse-gemma-cloudflare-2`
  response 1 (not in the held-out set) to check the reply's shape. No question text changed after the held-out
  passes.

## The questions (exact)

One request per response carries all three questions (`questions_sha256` `c199d959aeda...`):

```json
{
  "phase": {
    "type": "choice",
    "instructions": "The state is one response from a coding agent's recorded trajectory. The agent was asked to repair a bug in a Python repository through a tool interface. The state holds the task statement, a one-line summary of each earlier response in the same run, and the response to label: its text, its tool calls, and the result of each call. Which phase is the response to label in? Apply the first rule that fits. 1. stuck: every tool call in the response repeats an earlier call of the same run exactly (same tool, same arguments) and that earlier call was rejected, or has run with no workspace change since. 2. Otherwise take the most advanced phase among the response's non-repeated calls, in this order: finish > edit > verify > reproduce > diagnose > explore > other. A rejected call keeps the phase of what it tried to do.",
    "criteria": {
      "explore": "it lists, searches, or reads files, or runs a look-only command (ls, cat, grep, git), to find or understand relevant code, tests, or behaviour",
      "reproduce": "before any edit of a pre-existing file, it writes a new scratch script or test, or runs a command that exercises the code, to observe the reported behaviour; later edits of that scratch file stay reproduce",
      "diagnose": "it reads, searches, or prints code the agent has already located as the suspected cause, to test or narrow a stated hypothesis about the fault",
      "edit": "it changes a file that existed before the run (source, tests, configuration), or creates a new non-scratch source file",
      "verify": "it runs a command that exercises the code (tests, a script, python -c) after the run's first edit of a pre-existing file",
      "finish": "it calls finish; or, in a run without a finish tool, it is the run's last response, text only, and the run ended normally",
      "stuck": "every tool call in the response repeats an earlier call of the same run exactly (same tool, same arguments) and that earlier call was rejected, or has run with no workspace change since",
      "other": "anything else: history, notes, output paging with no clear purpose; a text-only response that does not end the run"
    }
  },
  "edited_existing_source": {
    "type": "noul",
    "instructions": "The state is one response from a coding agent's recorded trajectory. The agent was asked to repair a bug in a Python repository through a tool interface. The state holds the task statement, a one-line summary of each earlier response in the same run, and the response to label: its text, its tool calls, and the result of each call. Does the response to label successfully change a file that existed in the repository before the run started (source, tests, or configuration)?",
    "criteria": {
      "true": "at least one tool call in the response to label writes to or replaces text in a pre-existing repository file, and its result reports success",
      "false": "no call in the response to label changes a pre-existing file: its calls only list, read, search, or run commands, create a new scratch file, edit a file the run itself created, or were rejected"
    }
  },
  "verified_after_edit": {
    "type": "noul",
    "instructions": "The state is one response from a coding agent's recorded trajectory. The agent was asked to repair a bug in a Python repository through a tool interface. The state holds the task statement, a one-line summary of each earlier response in the same run, and the response to label: its text, its tool calls, and the result of each call. Does the response to label run a command that exercises the code (tests, a script, python -c) after the run has already edited a pre-existing repository file, in this response or an earlier one?",
    "criteria": {
      "true": "a pre-existing repository file was successfully edited earlier in the run or earlier in this response, and this response then runs tests, a script, or python -c, and that call was not rejected",
      "false": "no pre-existing file had been edited before this response's commands, or the response runs no command that exercises the code (it only reads, searches, runs look-only commands, or edits), or its command was rejected"
    }
  }
}
```

The rule-derived facts the yes/no questions are scored against come from `weakness_mining.label_trajectory`:
`edited_existing_source` is true for a response holding a successful edit of a file the run did not create
(`base_edits`), and `verified_after_edit` for a response holding a non-rejected verify-phase call
(`verify_responses`). Each Jev record carries both facts next to Jev's values.

## Tables

Output of `label_phases.py agreement --labeller jev --repeat labels/labels_jev_repeat.jsonl`. "95% lower bound" is
the Wilson interval's lower end for Jev = gold within the gold phase.

Responses: 49. Jev = gold 49/49 (100.0%), kappa 1.00; Jev = rules 49/49 (100.0%), kappa 1.00; Jev = Claude 43/49 (87.8%), kappa 0.71. For reference: rules = gold 49/49, Claude = gold 43/49.

| Phase | Gold | Rule | Claude | Jev | Jev = gold, of gold | 95% lower bound | Specific: Jev-gold | Jev-rule | Jev-Claude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| explore | 40 | 40 | 34 | 40 | 40/40 | 0.91 | 1.00 | 1.00 | 0.92 |
| reproduce | 3 | 3 | 3 | 3 | 3/3 | 0.44 | 1.00 | 1.00 | 1.00 |
| diagnose | 0 | 0 | 6 | 0 | 0/0 | - | - | - | 0.00 |
| edit | 1 | 1 | 1 | 1 | 1/1 | 0.21 | 1.00 | 1.00 | 1.00 |
| verify | 2 | 2 | 2 | 2 | 2/2 | 0.34 | 1.00 | 1.00 | 1.00 |
| finish | 1 | 1 | 1 | 1 | 1/1 | 0.21 | 1.00 | 1.00 | 1.00 |
| stuck | 2 | 2 | 2 | 2 | 2/2 | 0.34 | 1.00 | 1.00 | 1.00 |

Jev differs from gold on no response.

`diagnose`: Jev chose it 0 times (Claude 6, gold 0); Jev's diagnose probability: mean 0.037, max 0.240.

| Run | # (Claude said diagnose) | Gold | Jev | Jev's diagnose probability |
|---|---:|---|---|---:|
| e3-sqlparse-qwen-parasail-3 | 2 | explore | explore | 0.030 |
| e3-sqlparse-qwen-parasail-3 | 13 | explore | explore | 0.230 |
| e3-sqlparse-qwen-parasail-4 | 2 | explore | explore | 0.040 |
| e3-sqlparse-qwen-parasail-4 | 12 | explore | explore | 0.240 |
| e3-sqlparse-qwen-parasail-4 | 14 | explore | explore | 0.020 |
| pc-reticle-sonnet-2 | 2 | explore | explore | 0.140 |

Calibration of `jev_confidence` against gold (bins fixed in advance):

| Confidence | Responses | Mean confidence | Jev = gold | Accuracy |
|---|---:|---:|---:|---:|
| [0.0, 0.5] | 0 | - | - | - |
| (0.5, 0.7] | 3 | 0.630 | 3 | 1.00 |
| (0.7, 0.9] | 13 | 0.806 | 13 | 1.00 |
| (0.9, 0.99] | 21 | 0.956 | 21 | 1.00 |
| (0.99, 1.0] | 12 | 1.000 | 12 | 1.00 |

Multi-class Brier score against gold: 0.0284 (0 is perfect, 2 is the worst). `jev_confidence` equals the top option's probability on 16/49 responses.

Yes/no questions against the rule-derived facts (yes = Jev's value >= 0.5, fixed in advance):

| Question | Rule yes | Jev yes when rule yes | Lowest Jev value when rule yes | Rule no | Jev yes when rule no | Highest Jev value when rule no |
|---|---:|---:|---:|---:|---:|---:|
| edited_existing_source | 1 | 1 | 0.970 | 48 | 1 | 0.550 |
| verified_after_edit | 2 | 2 | 0.970 | 47 | 1 | 0.790 |

| Run | # | Rule phase | Jev phase | Jev edited | Rule edited | Jev verified | Rule verified |
|---|---:|---|---|---:|---|---:|---|
| pc-reticle-sonnet-2 | 9 | finish | finish | 0.550 | False | 0.790 | False |

Run labels derived from Jev's per-response answers (first edit = first response with edited >= threshold; verified = verified >= threshold at or after Jev's last edit response):

| Run | First edit: rule / adjudicated / Jev | Verified before finish: rule / adjudicated / Jev | Jev edit responses | Jev verify responses |
|---|---|---|---|---|
| e3-sqlparse-qwen-parasail-3 | None / None / None | False / False / False | - | - |
| e3-sqlparse-qwen-parasail-4 | None / None / None | False / False / False | - | - |
| pc-reticle-sonnet-2 | 6 / 6 / 6 | True / True / True | 6, 9 | 7, 8, 9 |

Determinism, second identical pass (49/49 with identical request and question hashes): identical phase 49/49 (100.0%); identical confidence 20/49; largest phase-probability change 0.0800; largest yes/no change 0.0700; second pass = gold 49/49.

| Pass | Responses (attempts) | Cost (USD) | Input tokens | Sum of latencies (s) | Wall time (s) | Model |
|---|---:|---:|---:|---:|---:|---|
| first | 49 (49) | 0.004750 | 113103 | 8.9 | 9.0 | typesafe/jev-1.13-20260917 |
| second | 49 (49) | 0.004750 | 113103 | 9.7 | 9.8 | typesafe/jev-1.13-20260917 |

## Reading

**Which phases Jev can be trusted on, given the counts.** Only `explore` has enough cases to say anything: 40/40,
with a 95% lower bound of 0.91, and these are reads, searches, and listings through the Reticle tools. `reproduce`
(3/3), `verify` (2/2), `stuck` (2/2), `edit` (1/1), and `finish` (1/1) agree perfectly but their lower bounds are
0.21 to 0.44, so they are not validated; they were also the easy cases for the rules. `other` never occurs in this
set. On every phase here Jev only reproduces what the rules already compute from the journal at no cost. Jev's value
over the rules is on what the rules cannot see (`diagnose`, and tools or shell commands the rule tables do not list),
and this set does not measure that.

**Confidence.** Every bin is 100% correct, so the set shows no over-confidence but cannot show whether low confidence
predicts errors: there are no errors. `jev_confidence` sits at or up to 0.07 below the top option's probability.
The low-confidence responses are where the schema needs judgement: the second choice is `diagnose` (late reads of
the suspected code, for example run 4 #12, run 3 #13 and #20), `stuck` (run 3 #14 and #16, rejected searches that
do not repeat an earlier call), or `reproduce` (run 4 #18, the first repeat of the rejected
`cd /testbed && python test_issue.py`, 0.59 against 0.40, the closest call in the set). Apart from run 4 #18, the
responses at or below 0.7 changed between the two passes (run 3 #14 and #16 in the first, run 3 #13 and #20 in the
second), so the bins are not stable at this size.

**The yes/no questions.** Both separate the rule facts on this set (rule-positive responses 0.97; rule-negative
responses at most 0.55 and 0.79). But the positives are 1 and 2 responses, and both false positives are
`pc-reticle-sonnet-2` #9, a `finish` call whose text says "Fixed get_real_name() ..." and "Verified: ...". Jev scored
the narration as if it were an action. The run labels derived from Jev still match (first edit 6; verified before
finish true), but for `verified_before_finish` only because the two errors cancel: the false edit at #9 moves Jev's
last edit to 9, and the false verify at #9 then satisfies it. A threshold between 0.79 and 0.97 would separate this
set perfectly; choosing it here would tune on the held-out set, so 0.5 stands.

**Determinism.** The phase answer was stable (49/49), but the numbers are not repeatable to the digit: 20/49
confidences were identical, and probabilities changed by up to 0.08. Store the probabilities with each label and
do not expect a rerun to reproduce them exactly.

**What to do about `diagnose`.** Claude over-used it (6 of 49, all adjudicated `explore`); Jev did not (0 of 49,
diagnose probability at most 0.24). Of Claude's six, Jev gave three a diagnose probability of 0.14 to 0.24 (run 3
#13, run 4 #12, `pc-reticle-sonnet-2` #2; the adjudication called the last two borderline) and three 0.02 to 0.04.
It also gave 0.15 to 0.20 to four late reads that Claude called `explore` (run 3 #17 and #20, run 4 #11 and #15).
But with no gold `diagnose` in the set, Jev's diagnose recall is unmeasured: "never says diagnose" and "says
diagnose correctly" look the same here. Next:

1. Label a development set from card-007 trajectories in a separate file, with deliberate `diagnose` positives
   (the response text states a hypothesis about the fault and the calls read or print the code it names), and
   measure Jev's diagnose recall and precision there.
2. If recall is low, decompose further rather than rewording the choice question: add yes/no questions such as
   "does the text state a hypothesis about the cause of the fault?" and "do the calls read or print code the agent
   already named as the suspected cause?", and derive `diagnose` from both. Test them on the development set only.
3. Consider the same treatment for the narration error: tell the yes/no questions to judge the tool calls and their
   results, not the response's text, and check it on the development set.
4. Until then: rules for every phase but `diagnose`; treat `diagnose` as unmeasured; use Jev's diagnose probability
   only to flag responses for a human look.

## Reproduce

The Jev labeller reads the OpenRouter key from the environment variable `OPENROUTER_API_KEY`; it is never printed,
logged, or written to a record. Calls are serialised, one per response, and are not taken under the live-run lock
(they do not use the Claude subscription).

```
python experiments/session_harness/label_phases.py label \
  experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-3 experiments/p6_pilot/runs/e3-sqlparse-qwen-parasail-4 \
  experiments/p6_pilot/runs/pc-reticle-sonnet-2 --labeller jev
python experiments/session_harness/label_phases.py label <same run directories> --labeller jev \
  --labels experiments/session_harness/labels/labels_jev_repeat.jsonl
python experiments/session_harness/label_phases.py agreement --labeller jev \
  --repeat experiments/session_harness/labels/labels_jev_repeat.jsonl
```

The run directories need their session journals (`sessions/`, git-ignored); in this pass runs 3 and 4 were read from
the main checkout and `pc-reticle-sonnet-2` from the positive-control worktree. `label` resumes, skipping responses
already in the output file. The yes/no threshold is the `threshold` argument of `jev_agreement_tables` (0.5).

Calls made: 99 (1 development call, 49 per pass, every call succeeding on its first attempt); total cost $0.0096.

## Not done

- No development set: card-007 trajectories do not exist yet, so nothing measures Jev's `diagnose` recall or the
  phases absent here (`other`, look-only shell commands, Claude Code tool names).
- No human labels; gold is still the orchestrating agent's adjudication.
- No question was revised, no threshold was chosen, and no second question design was tried; the held-out rule
  forbids doing that against this set.
- Runs 1 and 2 and the native arm were not labelled by Jev.
- No free-text mechanism from Jev.
