# Observation audit 001: would a coarse-by-default outline ladder fix how the model observes?

Date: 2026-09-28. Offline analysis of recorded runs only: no model calls, no cloud sessions.
Tools: [`observation_audit.py`](observation_audit.py) (per-run observation measures, tables),
[`repo_outline.py`](repo_outline.py) (ast outline of the task workspace, pre-declared lexical rank).
The score in `repo_outline.py` was committed (e60ffff) before any rank was computed.

## Question

The hypothesis: observations should be coarse by default, like an aider-style repo map or an AST outline with
file:line addresses. Every omission would carry an address, so the model could zoom in on request. Before building
an outline tool, this audit asks two things of the recorded runs:

- Is the observation waste where a ladder would remove it?
- Are the persistent failures locating failures (the model never reached the gold function), or judgement failures
  (it reached the function and misjudged it)?

## Answer in brief

- **Locating is not where the bytes or the failures are.** Every accepted run saw the mutated line: 32/32 in card
  007, 31/31 in card 019 and 29/29 native. They saw it by a median of response 4 (of about 12.5), after a median
  11 KB (~2.8k tokens) of tool output.
  - The whole-repo outline is 10.3 KB (~2.6k tokens) by itself.
  - An oracle-guided ladder costs a median 11.1 KB: the outline plus exactly the gold function.
  - 36 of the 76 located Reticle incumbent runs (cards 007 + 019) spent fewer bytes than that before locating.
- **The persistent failures are mostly reached-and-misjudged, not never-located.** All 22 rejected Reticle
  incumbent runs (cards 007 + 019 + 020) are on the five persistent tasks.
  - 17 of the 22 showed the model the mutated line: 9 made no library edit, 3 edited another file, and 5 edited the
    gold function but not the mutated line.
  - Only 5 never saw it: 4 on task 057 and 1 on task 032.
  - Task 057 is the one locating failure. On 057, and on 001, the outline's lexical top hit is the wrong target the
    model chose anyway.
- **The waste an outline would not touch is context carried from response to response.**
  - Reticle re-sends the whole flattened context on every response. Tool results make up 75-81% of all prompt
    bytes. The median accepted run sent about 200 KB of prompt to see 20 KB of tool output.
  - In cards 007 and 019, 53-78% of those carried result bytes come from results that contain no line of the gold
    file.
  - Whole-file reads are 40% of shown bytes.
  - Re-reads after the context policy dropped a result take 12% of shown bytes in rejected runs, against 1% in
    accepted ones.
  - An always-present 10 KB outline would itself be re-sent on every response.
- **Recommendation: do not run the outline-tool card as a locating or acceptance treatment.** What the evidence
  supports is a verification treatment for the hard tasks (card 020's direction). A carried-context treatment
  would be a coarse re-rendering of old observations when they age out of context: a context-policy ladder, not a
  navigation ladder. If the outline card is run anyway, its primary measure should be carried or prompt bytes at
  equal acceptance, not acceptance. The measures are listed at the end.

## Data

| Card | What | Runs analysed | Source |
|---|---|---|---|
| 007 | Reticle incumbent (host OCI, CLI 2.1.283) | 40 (20 tasks x 2) | `experiments/p6_pilot/runs/c007-*` (on master and `wt/cli-retry`) |
| 019 | Reticle incumbent, cloud VM | 40 counted of 45 run directories. The 5 superseded restarts (`057-r2`, `075-r1`, `075-r1-a2`, `076-r1`, `076-r1-a2`) are skipped; the last attempt (`-a2`/`-a3`) counts, as in the card's report | `origin/cloud-results-019` @ 895b39a |
| 020 | incumbent vs check-oracle on the 5 persistent tasks | 10 finished runs (5 per arm, 1 rollout each). `001-r2-incumbent` had no result at 9f5df42 and is skipped. The campaign is unfinished | `origin/cloud-results-020` @ 9f5df42 |
| 018 | stock Claude Code (native), matched 20-turn budget | 40 (the `.void-*` reruns excluded) | `experiments/session_harness/native_runs/c018-*` |

The task bank is `experiments/mutation_tasks/tasks.mutations.json`. The workspace text is sqlparse at f66d12c
(`git archive` of `.runtime/bug-mining/repos/sqlparse`) with `tests/` removed (a hidden path), plus each task's
mutation patch. The inputs for cards 019 and 020 were extracted read-only into a scratch directory with
`git archive`. No other card's evidence is committed on this branch.

## Method

**Transcript.** A Reticle run is read from its `calls.jsonl`, which holds every model request in full.
- A tool result is taken from the first request that carries it. That request is for the response after the one
  that issued the call.
- Results issued in the last response were never shown and are excluded.
- Responses are numbered 1..N in call order; the session journal's numbering is the same (checked on 001-r1 and
  061-r1).
- "Seen at k" means the result was issued in response k-1 and was first in front of the model at response k.
  The issuing response is therefore k-1.
- Context omission comes from the same requests: a result absent from a later request was dropped by
  `pressure-recent-v3`.

A native run is read with `weakness_mining.load_native_run` (`stream.jsonl`).

**Attribution.** Each line of a shown result is stripped of any line-number prefix (`  128| `, `128→`, `path:128:`,
`path-128-`, `128:`). It is then attributed to a workspace (file, line) by one of three rules:
- a prefix or traceback frame gives the file and line, and the text matches (or matches within 200 lines in that
  file, which allows for edits);
- its text (8 characters or more) occurs exactly once in the workspace;
- it continues an attributed run of neighbouring lines.

Everything else is "unattributed": program output, listings, headers, and the model's own files.

**Definitions.**
- **Site**: the mutation's `+` lines in the workspace. For a deleted guard (tasks 025, 032, 043) the site is the
  line before and the line after the deletion.
- **Located**: a site line was shown.
- **Function read**: at least min(5, function length) distinct lines of the gold function were shown.
- **Outcome**: accepted; rejected-finish (the model called finish); rejected-budget (any other stop, all of them
  `model_call_limit` here).
- **Reading** of a rejected run: never-located, located with no library edit, located but edited another file,
  edited the gold function but not the site, or edited the site.
  - Edit targets come from `replace_text`/`Edit` old text, matched to workspace lines.
  - Library edits made through `run` commands are only flagged, not located.

**Proxies.**
- **Relevance**: shown bytes by category (gold function / rest of the gold file / other `sqlparse/` files / other
  workspace files / unattributed).
- **Used later**, two bounds:
  - generous: the share of shown bytes in results that introduced a specific identifier (in 2 or fewer workspace
    files, not in the statement, not yet written by the model) which the model later writes;
  - strict: the share of attributed bytes whose exact line text (15 characters or more) the model later writes.
- **Re-read**: an attributed line shown again. It is counted "in context" if an earlier result that showed it was
  still in the request the model answered when it asked again, and "after omission" otherwise.
- **Carried**: the sum over requests of the tool-result bytes each request contained.

**Outline and pre-declared score** (`repo_outline.py`, committed before ranking):
- The outline lists every class, def and nested def in the workspace's 20 `.py` files, with signature and line.
- The query is only the variable parts of the statement: the behaviour names and the first failure message.
- The tokenizer splits camel and snake case, strips a trailing s, and drops stop words.
- BM25 (k1 1.2, b 0.75) scores one document per symbol: qualified name, path, argument names and docstring.
- Ranks are pessimistic: ties count against the gold symbol.
- Declared thresholds: the outline points to the gold function if it, or its enclosing method, ranks 10th or
  better; it points to the gold file if the file ranks 3rd or better. A reference-count-ranked map cut at 1,024
  tokens (aider's default `--map-tokens`) "contains" the function if the function survives the cut.

To reproduce, run `repo_outline.py` and `observation_audit.py` with the arguments in their docstrings. All cards
together run in about 8 s on one core.

## Results

### 1. Volume

Medians per run. KB = 1,000 bytes; ~tokens = bytes / 4. "Prompt sent" is the runner's `prompt_bytes`, summed over
responses.

| Card / arm | Outcome | Runs | Responses | Shown KB | ~k tokens | Prompt KB sent |
|---|---|--:|--:|--:|--:|--:|
| 007 | accepted | 32 | 12.5 | 20.5 | 5.1 | 244.7 |
| 007 | rejected-finish | 4 | 16 | 49.1 | 12.3 | 507.3 |
| 007 | rejected-budget | 4 | 20 | 42.4 | 10.6 | 506.0 |
| 019 | accepted | 31 | 12 | 19.5 | 4.9 | 182.3 |
| 019 | rejected (finish / budget) | 2 / 7 | 16.5 / 20 | 35.1 / 46.5 | 8.8 / 11.6 | 368.5 / 514.7 |
| 018 native | accepted | 29 | 12 | 9.3 | 2.3 | (not recorded) |
| 018 native | rejected-budget | 10 | 20 | 17.3 | 4.3 | |

- **Bytes by tool.** `read_file` is 68-75% of Reticle's shown bytes, then `search_text` 9-12%, `run` 7-11%,
  `glob_files` 5-6%, and the existing per-file `outline` tool 1%. The native arm's `Read` is 62%, `Bash` 21% and
  `Grep` 9%.
- **Whole-file reads.** Reads without a line range are 40% of Reticle's shown bytes and 46% of native's.
- **Rejected runs** show about 2x the bytes of accepted runs and send about 2.5x the prompt.
- **Native versus Reticle.** The native arm shows about half the bytes Reticle does for the same number of turns.
- **Existing coarse rungs are barely used.**
  - The existing `outline` tool was called in 12 of 40 card-007 runs and 16 of 40 card-019 runs. It was called on
    the gold file in only 4 and 6 of them.
  - Reticle's addressed-truncation rung (a partial result plus a `read_output` handle) never fired in card 007: no
    shown result carries a truncation marker.

### 2. Locating

| Card / arm | Outcome | Located | Site seen at (median response) | KB before locating | Share of shown bytes before locating |
|---|---|--:|--:|--:|--:|
| 007 | accepted | 32/32 | 4 | 11.2 | 59% |
| 007 | rejected-finish | 3/4 | 8 | 45.6 | 79% |
| 007 | rejected-budget | 3/4 | 6 | 15.8 | 30% |
| 019 | accepted | 31/31 | 4 | 11.1 | 55% |
| 019 | rejected-budget | 5/7 | 7 | 31.3 | 33% |
| 018 native | accepted | 29/29 | 5 | 7.5 | 84% |
| 018 native | rejected-budget | 5/10 | 16 | 13.5 | 85% |

- **Before and after locating.** Accepted Reticle runs spend just over half of their shown bytes before locating.
  Rejected-budget runs spend most of theirs after it: they located, then thrashed.
- **How the site was first shown.** In cards 007 + 019 it came from a `read_file` in 72 of 76 located runs, and 35
  of those 76 were whole-file reads.
  - The gold function is a median 15% of the locating observation (native: 27%).
  - The model is shown the site incidentally more often than by a targeted read.
- **"Function read" coincides with "site seen"** in almost every run, because the site is inside the function.

### 3. Relevance

Sums over runs, as a share of shown bytes.

| Card | Outcome | Gold function | Gold file, rest | Other library | Other workspace | Unattributed | Used later (generous / strict) |
|---|---|--:|--:|--:|--:|--:|--:|
| 007 | accepted | 6% | 26% | 42% | 3% | 24% | 60% / 3% |
| 007 | rejected-budget | 4% | 13% | 66% | 2% | 15% | 21% / 1% |
| 019 | accepted | 8% | 29% | 35% | 3% | 26% | 56% / 3% |
| 019 | rejected-budget | 2% | 16% | 47% | 7% | 29% | 21% / 1% |
| 018 native | accepted | 10% | 33% | 28% | 7% | 23% | 41% / 2% |

- **Before locating**, over located runs: 41-51% of shown bytes are the gold file, 34-43% other library files and
  13-14% unattributed.
- **Budget-rejected runs** read mostly other library code (47-66%), and little of what they read turns up in their
  later messages.

### 4. Re-reads

| Card | Outcome | Re-read, earlier copy still in context | Re-read after the policy omitted it | Identical repeated calls |
|---|---|--:|--:|--:|
| 007 | accepted | 5% | 2% | 10 |
| 007 | rejected-budget | 7% | 22% | 9 |
| 019 | accepted | 5% | 0% | 14 |
| 019 | rejected-budget | 4% | 14% | 10 |
| 018 native | all | 2% | 0% | 12 |

- **In-context re-reads** are a flat ~5% of shown bytes in every Reticle group: pure redundancy.
- **Refetches after omission** concentrate in the long, failing runs, where `pressure-recent-v3` drops results that
  the model then fetches again. This matches the `refetch_after_omission` signature in
  [weakness-mining-c007](weakness-mining-c007.md).

**Carried context** is the larger cost:

| Card | Outcome | Carried KB (median) | Carried / prompt bytes | Carried bytes from results with no gold-file line |
|---|---|--:|--:|--:|
| 007 | accepted | 173 | 76% | 61% |
| 007 | rejected-budget | 380 | 80% | 78% |
| 019 | accepted | 122 | 75% | 53% |
| 019 | rejected-budget | 384 | 79% | 76% |

### 5. Counterfactual outline

The outline of the task workspace (`sqlparse/`, `examples/`, `benchmarks/`; `tests/` hidden):
- 263 symbols in 20 files;
- 10,311 bytes (~2.6k tokens) with signatures, 6,726 bytes with names only;
- the library source itself is 153 KB;
- per file, 104 bytes (`formatter.py`) to 2,959 bytes (`sql.py`).

Pre-declared lexical rank of the gold function among the 263 symbols. A rank of 263 means a score of 0: no query
term occurs in any of the function's fields.

| Task | Gold symbol | Symbol rank | Enclosing rank | File rank | Points to fn (<=10) | File (<=3) | In 1k-token ref map | Outline's top hit |
|---|---|--:|--:|--:|:-:|:-:|:-:|---|
| 001 | `StripWhitespaceFilter.process` | 28 | 28 | 6 | no | no | yes | `ReindentFilter.process` |
| 002 | `TokenList.token_first.matcher` | 263 | 263 | 2 | no | yes | no | `StatementSplitter.process` |
| 022 | `ReindentFilter._next_token` | 263 | 263 | 20 | no | no | yes | `cli._process_file` |
| 023 | `TokenList.token_not_matching` | 263 | 263 | 3 | no | yes | no | `StripCommentsFilter` |
| 024 | `Parenthesis._groupable_tokens` | 263 | 263 | 2 | no | yes | no | `group_where` |
| 025 | `_TokenType.__getattr__` | 9 | 9 | 3 | yes | yes | no | `SQLParseError` |
| 032 | `ReindentFilter._process_where` | 16 | 16 | 6 | no | no | no | `sql.Where` |
| 033 | `group_period.post` | 134 | 90 | 2 | no | yes | yes | `Identifier.is_wildcard` |
| 034 | `Statement.get_type` | 9 | 9 | 1 | yes | yes | no | `sql.Parenthesis` |
| 040 | `OutputPythonFilter._process` | 2 | 2 | 1 | yes | yes | yes | `OutputPythonFilter` |
| 042 | `ReindentFilter._process_case` | 2 | 2 | 2 | yes | yes | no | `TokenList.token_index` |
| 043 | `imt` | 263 | 263 | 8 | no | no | yes | `group_order` |
| 044 | `build_filter_stack` | 263 | 263 | 20 | no | no | no | `OutputPythonFilter` |
| 046 | `build_filter_stack` | 263 | 263 | 20 | no | no | no | `OutputPythonFilter` |
| 057 | `Function.get_window` | 9 | 9 | 2 | yes | yes | no | `grouping.group_functions` |
| 060 | `StatementSplitter._handle_closing_keyword` | 263 | 263 | 20 | no | no | no | `SQLParseError` |
| 061 | `ReindentFilter._process_identifierlist` | 25 | 25 | 1 | no | yes | no | `ReindentFilter.__init__` |
| 073 | `AlignedIndentFilter._process_case` | 1 | 1 | 1 | yes | yes | no | (itself) |
| 075 | `StatementSplitter._handle_closing_keyword` | 48 | 48 | 6 | no | no | no | `sql.Case` |
| 076 | `ReindentFilter._split_kwds` | 16 | 16 | 2 | no | yes | no | `format` |

- **The outline points to the gold function in 6 of 20 tasks** and to the gold file in 11 of 20. The 1k-token
  reference map contains it in 6 of 20. Eight of 20 gold functions share no term with the statement at all.
- **Where the outline does point** (025, 034, 040, 042, 073), the models already located by a median response of
  3 (2.5 on 073) and accepted every run. The exception is 057; see section 6.
- **Cost against actual locating.** An oracle that shows the outline and then exactly the gold function would
  cost a median 11.1 KB. The runs actually spent a median 12.0 KB (card 007) and 12.2 KB (card 019) before
  locating.
  - 18 of 38 located card-007 runs, 18 of 38 card-019 runs and 20 of 34 native runs spent less than that oracle
    ladder.
  - In Reticle's stateless protocol, an outline that stays in the prompt is re-sent every response: about 10 KB x
    12.5 responses, or roughly 130 KB of added prompt per accepted run, against a median 245 KB today.

### 6. The persistent failures (001, 022, 032, 057, 061)

These five tasks hold all 22 rejected Reticle incumbent runs across cards 007, 019 and 020 (25 runs, 3
accepted).

| Task | Accepted | Never located | Located, no library edit | Located, edited another file | Edited gold fn, not the site | Outline fn rank / top hit |
|---|--:|--:|--:|--:|--:|---|
| 001 | 1/5 | 0 | 2 | 2 (`reindent.py`) | 0 | 28 / `ReindentFilter.process` |
| 022 | 2/5 | 0 | 3 | 0 | 0 | 263 (no overlap) |
| 032 | 0/5 | 1 | 4 | 0 | 0 | 16 |
| 057 | 0/5 | 4 | 0 | 1 (`grouping.py`) | 0 | 9 / `grouping.group_functions` |
| 061 | 0/5 | 0 | 0 | 0 | 5 | 25 |

- **001: reached and misjudged.** Every run saw `if depth != 0 and ...` in `StripWhitespaceFilter.process`.
  - 001-r1 was shown it at response 11 and edited `ReindentFilter._split_statements` at response 13.
  - The behaviour name 'format reindent: stmts' pulls toward the reindent filter, and the outline's top hit is
    `ReindentFilter.process`: the outline would reinforce the wrong target.
  - 001-r2 was accepted with a compensating fix in `reindent.py`, not at the site.
- **022: reached, never diagnosed.** The rejected runs were shown the negated `if` at responses 6, 7 and 16 and
  never edited the library in 20 responses; the model never named `_next_token`. The statement shares no term with
  the function.
- **032: reached, never repaired.** The mutation deletes a guard, so there is nothing to see: the site is the gap
  between two lines. Four runs saw that gap and none added the guard back; no Reticle 032 run edited the library at
  all.
- **057: the one locating failure.** Four of five runs never saw line 646 (`tokens[-2]` in `Function.get_window`).
  - Four of the five runs edited `engine/grouping.py`. In 057-r1 (card 007) the edit was the `AS` check in
    `group_functions`, which is what 'grouping function' names and what the outline ranks first.
  - `get_window` ranks 9th, so it would sit in the top 10 of the outline, below the trap.
  - The one card-020 check-oracle run reached it at response 11 and fixed it.
- **061: reached early, wrong edit.** All five runs were shown the site at response 3 or 4 and edited
  `_process_identifierlist`, but never the condition on line 139 that lost its `not`. The edit checked (061-r1,
  card 007) went into the function's `wrap_after` block. This is judgement.
- **Late locating** (site first seen at response 15 or later of 20, leaving too little budget) applies to 4 of the
  17 located rejected runs: 001 x2, 022, 032. For those tasks the outline ranks the gold function 28th, not at all,
  and 16th, so it would not plausibly have brought the site forward.

Card 020's arms on these five tasks (n = 1 per task, campaign unfinished): the check-oracle arm accepted 3 of 5
(022, 057, 061), the incumbent 0 of 5. That is too few runs for an effect estimate. It does point the same way as
the failure reading: the failures yield to feedback about correctness, not to better navigation.

### 7. Native Claude Code (card 018) for contrast

- **Less shown, located less often in failures.** The native arm shows half the bytes (median 12.2 KB per run),
  and its located accepted runs reached the site with 7.5 KB. Its rejected runs are more often never-located: 6 of
  11 (022 x2, 001, 032, 033, 057). Reticle's are 5 of 22.
- **Where native could gain from an outline.** Native reads a narrower slice and sometimes never reaches the gold
  function, so a map could plausibly help it more than Reticle.
- **Its successes are just as early.** Native locating in accepted runs is as early as Reticle's (median response
  5 versus 4).

## Verdict

- **Is there waste an outline ladder would remove? Little.**
  - The waste is real, but most of it is not navigation:
    - carried context: three quarters of prompt bytes, about two thirds of them from results with no gold-file
      line;
    - whole-file reads: 40% of shown bytes;
    - in-context re-reads: 5% of shown bytes;
    - refetches after omission: 12% of shown bytes in rejected runs.
  - Locating itself is cheap and early in the runs that succeed. An oracle ladder would not have been cheaper than
    what the model did in about half of them.
  - A per-file outline tool already exists and is rarely used.
- **Are the hard-task failures locating failures? Mostly not.**
  - 17 of the 22 rejected Reticle runs were shown the mutated line and then misjudged, stalled or edited elsewhere.
  - Only task 057 is a locating failure, and there the lexical signal an outline would add ranks the model's own
    wrong target first.
  - On 001 the outline would reinforce the wrong target too.
  - An outline cannot fix 022, 032 or 061. A verifier or check signal is the lever (card 020's direction).

## Recommendation

- **Do not build the outline-tool treatment card as the next card, and do not frame it as an acceptance
  treatment.** The recorded failures leave it at most one task (057) to move, and on that task its lexical cue
  points to the trap.
- **If the ladder idea is pursued, aim it at carried context rather than navigation.** When a result ages out of
  context, replace it with its coarse rendering (the symbols and line ranges it covered, with a re-fetch address)
  instead of dropping it or keeping it whole. That targets the 75-81% of prompt bytes that are carried results. It
  should also cut the refetches after omission (12-22% of shown bytes in rejected runs).
- **If the outline card is run anyway**, pre-register:
  - Primary: prompt bytes and carried tool-result bytes per accepted run, at non-inferior acceptance (run on the
    20-task calibration set).
  - Secondary:
    - responses and bytes to locate (site seen at);
    - the share of whole-file reads;
    - `outline` or map use;
    - locating on 057 specifically: is `get_window` read before `group_functions` is edited?
    - the never-located rate among rejected runs.
  - Declare in advance that acceptance on 001, 022, 032 and 061 is not expected to move. A gain there would point
    to something other than locating.
  - Count the outline's own re-sent bytes against it. In the stateless protocol it costs about 10 KB per response
    unless it is omitted after first use.
  - Test the map on the native arm as well, where 6 of 11 failures were never-located.

## Limits of each proxy

- **"Seen" is not "attended".**
  - A site shown inside a whole-file read (35 of 76 Reticle locating observations) counts as located.
  - The attention proxy (the first response whose text or tool arguments name the gold function) is sparse and
    only suggestive: 061's runs edited the function without naming it.
  - The failure reading therefore under-counts locating failures of the "saw it but never looked" kind. It is
    better read as "the information was in the context window".
- **Attribution**
  - Lines the model changed, text it created and program output are unattributed; for the most part they are not
    source.
  - A short line that is not unique, outside an aligned run, stays unattributed.
  - Attribution to "other library files" is reliable. "Unattributed" mixes useful program output (tracebacks,
    repro prints) with listings and headers.
- **Deleted-guard sites** (025, 032, 043) are proxied by the two lines around the gap.
- **Edit targets** come from `replace_text`/`Edit` old text matched to workspace lines. Library edits made through
  `run` commands are flagged but not located. An edit of text the model had itself changed earlier may not
  resolve.
- **Used later**
  - The generous proxy counts a result as used if any fresh specific identifier from it appears later, so it
    over-counts.
  - The strict proxy needs an exact line quote, so it under-counts.
  - Neither measures influence on a decision.
- **Re-reads** are measured on attributed lines only. "In context" is judged against the request the model
  answered when it issued the repeat.
- **Carried bytes**
  - For Reticle, carried bytes come straight from the recorded requests.
  - For native they are hypothetical: Claude Code keeps one conversation, and prompt caching makes the re-sent
    bytes cheap. So native carried bytes are not comparable in cost.
- **Outline rank**
  - BM25 over symbol names and docstrings is a lexical floor. A model reading the outline could reason past it (or
    be misled as it was without it).
  - The rank measures whether the outline makes the gold salient, not what a model would do with it.
  - The thresholds (<=10, <=3, 1k tokens) are conventions declared in advance, not fitted.
- **Ladder counterfactual.** It assumes an oracle that zooms straight to the gold function, and counts the outline
  once. Both flatter the ladder.
- **Sample size**
  - Card 020 has 1 run per task per arm and was still running.
  - The persistent-task table pools three cards run in two environments (host OCI and cloud VM) under the same
    incumbent protocol.

## What I did not do

- I made no model calls, did not rerun any campaign, and did not build or trial an outline tool.
- I did not read the session journals except to check the response numbering on two card-007 runs. Everything
  else comes from `calls.jsonl` and `results.jsonl`, the only records that exist for cards 019 and 020.
- I did not hand-adjudicate the persistent-failure transcripts beyond the edit and locating spot checks (001-r1,
  057-r1, 061-r1, c020 057 check-oracle). The per-run "reading" is rule-based.
- I did not analyse card 020's check-oracle mechanism (what the check told the model), nor wait for its remaining
  run.
- I did not compute the outline for tasks outside the 20-task calibration set.
- I did not fit or tune the outline score after seeing ranks.
- I did not measure time or latency.

## Appendix: generated tables

Verbatim output of:
```
python experiments/session_harness/observation_audit.py --workspace SCRATCH/sqlparse-base \
  --card c007=experiments/p6_pilot/runs --card c019=SCRATCH/c019/experiments/p6_pilot/runs \
  --card c020=SCRATCH/c020/experiments/p6_pilot/runs --native c018=experiments/session_harness/native_runs
```
The per-task table pools the Reticle incumbent runs of cards 007, 019 and 020. Running one card alone reproduces
that card's rows in the other tables unchanged (the by-tool table's column set depends on which tools occur).

### Volume and locating (medians per run; KB = 1,000 bytes; ~tokens = bytes / 4)

| Card | Arm | Outcome | Runs | Responses | Shown KB | ~k tokens | Prompt KB sent | Located (site seen) | Site seen at | Fn read at | File content at | KB before locating | Share before |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| c007 | incumbent | all | 40 | 13.0 | 26.9 | 6.7 | 283.2 | 38/40 | 4.0 | 4.0 | 3.0 | 12.0 | 57% |
| c007 | incumbent | accepted | 32 | 12.5 | 20.5 | 5.1 | 244.7 | 32/32 | 4.0 | 4.0 | 2.5 | 11.2 | 59% |
| c007 | incumbent | rejected-finish | 4 | 16.0 | 49.1 | 12.3 | 507.3 | 3/4 | 8 | 8 | 7.5 | 45.6 | 79% |
| c007 | incumbent | rejected-budget | 4 | 20.0 | 42.4 | 10.6 | 506.0 | 3/4 | 6 | 6 | 4.0 | 15.8 | 30% |
| c018 | native | all | 40 | 15.5 | 12.2 | 3.0 | - | 34/40 | 5.5 | 5.0 | 4.0 | 8.9 | 84% |
| c018 | native | accepted | 29 | 12 | 9.3 | 2.3 | - | 29/29 | 5 | 5 | 3 | 7.5 | 84% |
| c018 | native | rejected-finish | 1 | 7 | 5.3 | 1.3 | - | 0/1 | - | - | - | - | -% |
| c018 | native | rejected-budget | 10 | 20.0 | 17.3 | 4.3 | - | 5/10 | 16 | 16 | 8 | 13.5 | 85% |
| c019 | incumbent | all | 40 | 12.5 | 22.0 | 5.5 | 226.7 | 38/40 | 4.0 | 4.0 | 3.0 | 12.2 | 55% |
| c019 | incumbent | accepted | 31 | 12 | 19.5 | 4.9 | 182.3 | 31/31 | 4 | 4 | 3 | 11.1 | 55% |
| c019 | incumbent | rejected-finish | 2 | 16.5 | 35.1 | 8.8 | 368.5 | 2/2 | 6.5 | 6.5 | 5.5 | 19.4 | 48% |
| c019 | incumbent | rejected-budget | 7 | 20 | 46.5 | 11.6 | 514.7 | 5/7 | 7 | 7 | 4 | 31.3 | 33% |
| c020 | check-oracle | all | 5 | 20 | 49.6 | 12.4 | 573.5 | 4/5 | 12.5 | 12.5 | 6 | 37.8 | 68% |
| c020 | check-oracle | accepted | 3 | 16 | 49.6 | 12.4 | 573.5 | 3/3 | 11 | 11 | 4 | 24.0 | 48% |
| c020 | check-oracle | rejected-budget | 2 | 20.0 | 48.1 | 12.0 | 589.9 | 1/2 | 15 | 15 | 11.5 | 51.6 | 88% |
| c020 | incumbent | all | 5 | 20 | 40.8 | 10.2 | 495.9 | 4/5 | 15.0 | 15.0 | 4 | 46.8 | 64% |
| c020 | incumbent | rejected-finish | 2 | 16.5 | 31.7 | 7.9 | 359.1 | 1/2 | 3 | 3 | 5.0 | 11.9 | 40% |
| c020 | incumbent | rejected-budget | 3 | 20 | 97.5 | 24.4 | 680.3 | 3/3 | 16 | 16 | 4 | 70.8 | 73% |

### Shown bytes by tool (sum over runs, % of card/arm total)

| Card | Arm | Total KB | read_file | Read | run | search_text | glob_files | Bash | Grep | replace_text | search_history | outline | PowerShell | Write | Glob | Edit | write_file | read_output | check |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| c007 | incumbent | 1,209.8 | 75% | - | 7% | 9% | 5% | - | - | 2% | 1% | 1% | - | - | - | - | 0% | - | - |
| c018 | native | 511.3 | - | 62% | - | - | - | 21% | 9% | - | - | - | 4% | 2% | 1% | 1% | - | - | - |
| c019 | incumbent | 1,151.3 | 68% | - | 11% | 12% | 6% | - | - | 1% | 1% | 1% | - | - | - | - | 0% | 0% | - |
| c020 | check-oracle | 220.3 | 66% | - | 20% | 7% | 5% | - | - | 1% | - | 0% | - | - | - | - | - | - | 0% |
| c020 | incumbent | 300.4 | 70% | - | 13% | 10% | 3% | - | - | 0% | 2% | 1% | - | - | - | - | - | - | - |

### Relevance and re-reads (sums over runs, % of shown bytes)

| Card | Arm | Outcome | Runs | gold function | gold file, other lines | other library files | other workspace files | unattributed | Re-read (in context) | Re-read (after omission) | Identical repeat calls | Used later (obs) | Quoted later (of attributed) |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| c007 | incumbent | all | 40 | 5% | 22% | 47% | 4% | 22% | 5% | 6% | 25 | 52% | 2% |
| c007 | incumbent | accepted | 32 | 6% | 26% | 42% | 3% | 24% | 5% | 2% | 10 | 60% | 3% |
| c007 | incumbent | rejected-finish | 4 | 5% | 20% | 41% | 10% | 25% | 5% | 1% | 6 | 61% | 2% |
| c007 | incumbent | rejected-budget | 4 | 4% | 13% | 66% | 2% | 15% | 7% | 22% | 9 | 21% | 1% |
| c018 | native | all | 40 | 7% | 26% | 36% | 9% | 22% | 2% | 0% | 12 | 28% | 2% |
| c018 | native | accepted | 29 | 10% | 33% | 28% | 7% | 23% | 2% | 0% | 6 | 41% | 2% |
| c018 | native | rejected-finish | 1 | 0% | 0% | 84% | 0% | 16% | 1% | 0% | 0 | 81% | 0% |
| c018 | native | rejected-budget | 10 | 3% | 15% | 49% | 13% | 20% | 2% | 0% | 6 | 4% | 0% |
| c019 | incumbent | all | 40 | 5% | 23% | 40% | 4% | 27% | 5% | 5% | 24 | 43% | 2% |
| c019 | incumbent | accepted | 31 | 8% | 29% | 35% | 3% | 26% | 5% | 0% | 14 | 56% | 3% |
| c019 | incumbent | rejected-finish | 2 | 8% | 19% | 44% | 0% | 28% | 6% | 0% | 0 | 50% | 7% |
| c019 | incumbent | rejected-budget | 7 | 2% | 16% | 47% | 7% | 29% | 4% | 14% | 10 | 21% | 1% |
| c020 | check-oracle | all | 5 | 3% | 15% | 48% | 2% | 32% | 5% | 0% | 1 | 39% | 1% |
| c020 | check-oracle | accepted | 3 | 4% | 20% | 43% | 2% | 31% | 5% | 0% | 1 | 42% | 1% |
| c020 | check-oracle | rejected-budget | 2 | 1% | 8% | 55% | 3% | 34% | 5% | 0% | 0 | 35% | 2% |
| c020 | incumbent | all | 5 | 4% | 13% | 51% | 5% | 26% | 5% | 9% | 6 | 19% | 1% |
| c020 | incumbent | rejected-finish | 2 | 15% | 31% | 14% | 8% | 32% | 11% | 0% | 1 | 46% | 3% |
| c020 | incumbent | rejected-budget | 3 | 1% | 8% | 62% | 5% | 25% | 4% | 12% | 5 | 12% | 0% |

### Context carried and what the pre-locating bytes were

Carried = tool-result bytes summed over every request that still contained them (what the model re-reads each response; Claude Code's continuous conversation carries every earlier result). Before-locating composition is over located runs only.

| Card | Arm | Outcome | Runs | Carried KB (median) | Carried / prompt | Carried from results with no gold-file line | Before locating: gold file | other library | other workspace | unattributed |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| c007 | incumbent | all | 40 | 208.2 | 77% | 67% | 41% | 43% | 2% | 13% |
| c007 | incumbent | accepted | 32 | 173.1 | 76% | 61% | 46% | 38% | 2% | 14% |
| c007 | incumbent | rejected-finish | 4 | 399.4 | 80% | 73% | 32% | 52% | 4% | 11% |
| c007 | incumbent | rejected-budget | 4 | 380.2 | 80% | 78% | 24% | 64% | 0% | 12% |
| c018 | native | all | 40 | 101.0 | - | 65% | 50% | 30% | 6% | 14% |
| c018 | native | accepted | 29 | 70.6 | - | 56% | 52% | 31% | 5% | 12% |
| c018 | native | rejected-finish | 1 | 20.1 | - | 100% | 0% | 0% | 0% | 0% |
| c018 | native | rejected-budget | 10 | 151.9 | - | 80% | 44% | 26% | 10% | 20% |
| c019 | incumbent | all | 40 | 166.0 | 76% | 63% | 44% | 41% | 2% | 14% |
| c019 | incumbent | accepted | 31 | 121.7 | 75% | 53% | 51% | 34% | 1% | 13% |
| c019 | incumbent | rejected-finish | 2 | 279.8 | 76% | 73% | 29% | 58% | 0% | 13% |
| c019 | incumbent | rejected-budget | 7 | 383.6 | 79% | 76% | 29% | 54% | 2% | 16% |
| c020 | check-oracle | all | 5 | 444.1 | 80% | 80% | 23% | 58% | 4% | 15% |
| c020 | check-oracle | accepted | 3 | 444.1 | 81% | 71% | 27% | 55% | 3% | 15% |
| c020 | check-oracle | rejected-budget | 2 | 460.5 | 78% | 92% | 16% | 63% | 5% | 16% |
| c020 | incumbent | all | 5 | 352.4 | 80% | 77% | 16% | 54% | 4% | 26% |
| c020 | incumbent | rejected-finish | 2 | 269.1 | 75% | 42% | 96% | 0% | 0% | 4% |
| c020 | incumbent | rejected-budget | 3 | 574.8 | 82% | 88% | 11% | 58% | 4% | 27% |

### Failure reading of rejected runs

| Card | Arm | never-located | located, no library edit | located, edited elsewhere | edited gold function (not site) | edited gold function + site |
|---|---|--:|--:|--:|--:|--:|
| c007 | incumbent | 2 | 2 | 2 | 2 | 0 |
| c018 | native | 6 | 5 | 0 | 0 | 0 |
| c019 | incumbent | 2 | 4 | 1 | 2 | 0 |
| c020 | check-oracle | 1 | 0 | 1 | 0 | 0 |
| c020 | incumbent | 1 | 3 | 0 | 1 | 0 |

### Locating cost vs an oracle-guided outline ladder

| Card | Arm | Located runs | Median KB before locating | Outline KB (whole repo) | Median ladder KB (outline + gold fn) | Runs cheaper than the ladder | Median responses to locate | Median whole-file-read share of shown bytes |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| c007 | incumbent | 38/40 | 12.0 | 10.3 | 11.1 | 18/38 | 4.0 | 39% |
| c018 | native | 34/40 | 8.9 | 10.3 | 11.2 | 20/34 | 5.5 | 28% |
| c019 | incumbent | 38/40 | 12.2 | 10.3 | 11.1 | 18/38 | 4.0 | 28% |
| c020 | check-oracle | 4/5 | 37.8 | 10.3 | 10.8 | 1/4 | 12.5 | 0% |
| c020 | incumbent | 4/5 | 46.8 | 10.3 | 10.8 | 1/4 | 15.0 | 39% |

### Per task: outline rank vs observed locating

| Task | Outline fn rank | File rank | Gold-file outline B | reticle: acc | reticle: located | reticle: site seen at | reticle: KB before site | check-oracle: acc | check-oracle: located | check-oracle: site seen at | check-oracle: KB before site | native: acc | native: located | native: site seen at | native: KB before site |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 001 | 28 | 6 | 667 | 1/5 | 5/5 | 15 | 45.6 | 0/1 | 1/1 | 15 | 51.6 | 0/2 | 1/2 | 19 | 20.7 |
| 002 | 263 | 2 | 2,959 | 4/4 | 4/4 | 5.0 | 9.3 | - | - | - | - | 2/2 | 2/2 | 6.0 | 6.9 |
| 022 | 263 | 20 | 853 | 2/5 | 5/5 | 10 | 46.0 | 1/1 | 1/1 | 14 | 59.9 | 0/2 | 0/2 | - | - |
| 023 | 263 | 3 | 2,959 | 4/4 | 4/4 | 5.0 | 11.0 | - | - | - | - | 2/2 | 2/2 | 5.5 | 11.8 |
| 024 | 263 | 2 | 2,959 | 4/4 | 4/4 | 9.0 | 13.5 | - | - | - | - | 2/2 | 2/2 | 13.5 | 11.0 |
| 025 | 9 | 3 | 150 | 4/4 | 4/4 | 3.0 | 3.8 | - | - | - | - | 2/2 | 2/2 | 4.5 | 2.1 |
| 032 | 16 | 6 | 853 | 0/5 | 4/5 | 13.0 | 19.3 | 0/1 | 0/1 | - | - | 0/2 | 1/2 | 8 | 9.2 |
| 033 | 90 | 2 | 2,177 | 4/4 | 4/4 | 4.0 | 18.4 | - | - | - | - | 1/2 | 1/2 | 14 | 23.0 |
| 034 | 9 | 1 | 2,959 | 4/4 | 4/4 | 3.0 | 3.4 | - | - | - | - | 2/2 | 2/2 | 3.0 | 1.5 |
| 040 | 2 | 1 | 370 | 4/4 | 4/4 | 3.0 | 5.3 | - | - | - | - | 2/2 | 2/2 | 2.5 | 4.6 |
| 042 | 2 | 2 | 853 | 4/4 | 4/4 | 3.0 | 9.6 | - | - | - | - | 2/2 | 2/2 | 7.0 | 6.3 |
| 043 | 263 | 8 | 301 | 4/4 | 4/4 | 6.0 | 26.6 | - | - | - | - | 2/2 | 2/2 | 15.5 | 15.5 |
| 044 | 263 | 20 | 104 | 4/4 | 4/4 | 4.0 | 14.8 | - | - | - | - | 2/2 | 2/2 | 3.5 | 9.2 |
| 046 | 263 | 20 | 104 | 4/4 | 4/4 | 4.0 | 6.9 | - | - | - | - | 2/2 | 2/2 | 6.0 | 9.9 |
| 057 | 9 | 2 | 2,959 | 0/5 | 1/5 | 8 | 56.2 | 1/1 | 1/1 | 11 | 24.0 | 0/2 | 1/2 | 20 | 11.2 |
| 060 | 263 | 20 | 305 | 4/4 | 4/4 | 4.5 | 10.9 | - | - | - | - | 1/2 | 2/2 | 5.0 | 12.0 |
| 061 | 25 | 1 | 853 | 0/5 | 5/5 | 3 | 5.0 | 1/1 | 1/1 | 4 | 4.8 | 1/2 | 2/2 | 9.0 | 7.4 |
| 073 | 1 | 1 | 512 | 4/4 | 4/4 | 2.5 | 6.3 | - | - | - | - | 2/2 | 2/2 | 5.0 | 5.5 |
| 075 | 48 | 6 | 305 | 4/4 | 4/4 | 3.0 | 15.5 | - | - | - | - | 2/2 | 2/2 | 5.5 | 12.7 |
| 076 | 16 | 2 | 853 | 4/4 | 4/4 | 3.0 | 12.1 | - | - | - | - | 2/2 | 2/2 | 3.0 | 7.8 |

### Trajectories of the persistent failures

| Run | Outcome | Resp | Site seen | Fn read | File seen | Model names fn | First lib edit | Edit files | Edited fn/site | Shown KB | KB before site | Reading |
|---|---|--:|--:|--:|--:|--:|--:|---|:-:|--:|--:|---|
| c007-sqlparse-mut-001-r1 | rejected-finish | 15 | 11 | 11 | 9 | 8 | 13 | filters/reindent.py | -/- | 50.7 | 45.6 | located-edited-elsewhere |
| c007-sqlparse-mut-001-r2 | accepted | 19 | 16 | 16 | 16 | - | 17 | filters/reindent.py | -/- | 79.1 | 65.5 | located-edited-elsewhere |
| c018-sqlparse-mut-001-r1 | rejected-budget | 20 | - | - | - | - | - | scratch_test.py | -/- | 27.8 | (never) | never-located |
| c018-sqlparse-mut-001-r2 | rejected-budget | 20 | 19 | 19 | 19 | - | - | scratch_test.py, scratch_test2.py | -/- | 20.9 | 20.7 | located-no-library-edit |
| c019-sqlparse-mut-001-r1 | rejected-budget | 20 | 15 | 15 | 11 | 10 | - | - | -/- | 84.0 | 33.9 | located-no-library-edit |
| c019-sqlparse-mut-001-r2 | rejected-finish | 16 | 9 | 9 | 9 | - | 15 | filters/reindent.py | -/- | 43.9 | 34.4 | located-edited-elsewhere |
| c020-sqlparse-mut-001-r1-check-oracle | rejected-budget | 20 | 15 | 15 | 6 | 15 | 18 | filters/reindent.py | -/- | 58.9 | 51.6 | located-edited-elsewhere |
| c020-sqlparse-mut-001-r1-incumbent | rejected-budget | 20 | 20 | 20 | 20 | - | - | - | -/- | 98.5 | 98.5 | located-no-library-edit |
| c007-sqlparse-mut-022-r1 | rejected-budget | 20 | 6 | 6 | 2 | - | - | - | -/- | 152.6 | 46.0 | located-no-library-edit |
| c007-sqlparse-mut-022-r2 | accepted | 17 | 15 | 15 | 2 | 15 | 15 | filters/reindent.py | fn/site | 54.0 | 52.9 | edited-gold-function+site |
| c018-sqlparse-mut-022-r1 | rejected-budget | 20 | - | - | 3 | - | - | (run command), repro.py | -/- | 32.4 | (never) | never-located |
| c018-sqlparse-mut-022-r2 | rejected-budget | 20 | - | - | 5 | - | - | t.py | -/- | 12.9 | (never) | never-located |
| c019-sqlparse-mut-022-r1 | accepted | 15 | 10 | 10 | 2 | 10 | 10 | filters/reindent.py | fn/site | 36.6 | 33.9 | edited-gold-function+site |
| c019-sqlparse-mut-022-r2 | rejected-budget | 20 | 7 | 7 | 2 | - | - | - | -/- | 130.9 | 43.3 | located-no-library-edit |
| c020-sqlparse-mut-022-r1-check-oracle | accepted | 16 | 14 | 14 | 2 | 14 | 14 | filters/reindent.py | fn/site | 60.6 | 59.9 | edited-gold-function+site |
| c020-sqlparse-mut-022-r1-incumbent | rejected-budget | 20 | 16 | 16 | 2 | - | - | - | -/- | 97.5 | 70.8 | located-no-library-edit |
| c007-sqlparse-mut-032-r1 | rejected-budget | 20 | 12 | 13 | 4 | 18 | - | - | -/- | 39.0 | 15.8 | located-no-library-edit |
| c007-sqlparse-mut-032-r2 | rejected-budget | 20 | - | - | 14 | - | - | repro.py, repro2.py, repro3.py, repro4.py | -/- | 22.0 | (never) | never-located |
| c018-sqlparse-mut-032-r1 | rejected-budget | 20 | 8 | 8 | 5 | 6 | - | scratch_test.py | -/- | 12.8 | 9.2 | located-no-library-edit |
| c018-sqlparse-mut-032-r2 | rejected-budget | 20 | - | - | 8 | - | - | repro.py | -/- | 9.5 | (never) | never-located |
| c019-sqlparse-mut-032-r1 | rejected-budget | 20 | 7 | 7 | 4 | - | - | - | -/- | 40.2 | 12.5 | located-no-library-edit |
| c019-sqlparse-mut-032-r2 | rejected-budget | 20 | 18 | 18 | 4 | 16 | - | - | -/- | 36.1 | 31.3 | located-no-library-edit |
| c020-sqlparse-mut-032-r1-check-oracle | rejected-budget | 20 | - | - | 17 | - | - | - | -/- | 37.2 | (never) | never-located |
| c020-sqlparse-mut-032-r1-incumbent | rejected-budget | 20 | 14 | 14 | 4 | - | - | - | -/- | 40.8 | 22.8 | located-no-library-edit |
| c007-sqlparse-mut-057-r1 | rejected-finish | 17 | - | - | 7 | - | 15 | engine/grouping.py | -/- | 29.9 | (never) | never-located |
| c007-sqlparse-mut-057-r2 | rejected-finish | 14 | 8 | 8 | 8 | - | 11 | engine/grouping.py | -/- | 71.2 | 56.2 | located-edited-elsewhere |
| c018-sqlparse-mut-057-r1 | rejected-budget | 20 | 20 | 20 | 20 | - | - | scratch_test.py | -/- | 11.2 | 11.2 | located-no-library-edit |
| c018-sqlparse-mut-057-r2 | rejected-finish | 7 | - | - | - | - | 6 | (run command), engine/grouping.py | -/- | 5.3 | (never) | never-located |
| c019-sqlparse-mut-057-r1 | rejected-budget | 20 | - | - | 7 | - | - | - | -/- | 43.4 | (never) | never-located |
| c019-sqlparse-mut-057-r2-a2 | rejected-budget | 20 | - | - | 10 | - | 19 | engine/grouping.py | -/- | 46.5 | (never) | never-located |
| c020-sqlparse-mut-057-r1-check-oracle | accepted | 20 | 11 | 11 | 8 | 18 | 19 | sql.py | fn/site | 49.6 | 24.0 | edited-gold-function+site |
| c020-sqlparse-mut-057-r1-incumbent | rejected-finish | 16 | - | - | 8 | - | 13 | engine/grouping.py | -/- | 33.6 | (never) | never-located |
| c007-sqlparse-mut-061-r1 | rejected-finish | 19 | 3 | 3 | 2 | 1 | 15 | filters/reindent.py | fn/- | 47.4 | 3.5 | edited-gold-function |
| c007-sqlparse-mut-061-r2 | rejected-budget | 20 | 4 | 4 | 4 | - | 17 | filters/reindent.py | fn/- | 45.7 | 5.0 | edited-gold-function |
| c018-sqlparse-mut-061-r1 | rejected-budget | 20 | 16 | 16 | 16 | - | - | repro.py | -/- | 22.4 | 13.5 | located-no-library-edit |
| c018-sqlparse-mut-061-r2 | accepted | 3 | 2 | 2 | 2 | 1 | 2 | filters/reindent.py | fn/site | 1.7 | 1.3 | edited-gold-function+site |
| c019-sqlparse-mut-061-r1 | rejected-finish | 17 | 4 | 4 | 2 | 16 | 16 | filters/reindent.py | fn/- | 26.2 | 4.4 | edited-gold-function |
| c019-sqlparse-mut-061-r2 | rejected-budget | 20 | 3 | 3 | 2 | - | 15 | filters/reindent.py | fn/- | 52.4 | 12.1 | edited-gold-function |
| c020-sqlparse-mut-061-r1-check-oracle | accepted | 11 | 4 | 4 | 4 | 10 | 7 | filters/reindent.py | fn/site | 14.0 | 4.8 | edited-gold-function+site |
| c020-sqlparse-mut-061-r1-incumbent | rejected-finish | 17 | 3 | 3 | 2 | 10 | 14 | filters/reindent.py | fn/- | 29.9 | 11.9 | edited-gold-function |

- c019: skipped c019-sqlparse-mut-057-r2 (superseded restart)
- c019: skipped c019-sqlparse-mut-075-r1 (superseded restart)
- c019: skipped c019-sqlparse-mut-075-r1-a2 (superseded restart)
- c019: skipped c019-sqlparse-mut-076-r1 (superseded restart)
- c019: skipped c019-sqlparse-mut-076-r1-a2 (superseded restart)
- c020: c020-sqlparse-mut-001-r2-incumbent has no result yet (unfinished), skipped
