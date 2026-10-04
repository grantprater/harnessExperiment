# Reticle post-edit checks in Claude Code

This directory ports the check-hook probe (`experiments/check_hook_probe/`, `reticle/runtime/check_hooks.py`,
`reticle/tools/check_hooks.py`, `reticle/runtime/observation_delta.py`) to Claude Code. Nothing here has run
against a live model. It is meant for interactive, exploratory use.

| Directory | What it is |
|---|---|
| `reticle-checks/` | A standard Claude Code plugin made of command hooks (Python 3.10+, stdlib only). This is the mechanism, and it works under `claude -p`. |
| `reticle-checks-pane/` | A Claude Code mod (function hooks, `register.tsx`): a status line and a `/checks` pane. It is read-only and changes nothing the model sees. |
| `fixture-calc/` | A tiny project with one seeded bug (`mean` divides by `len + 1`), five unittest tests (one failing), and `.claude/reticle-checks.json`. |

## Try it

```powershell
cd cc/fixture-calc
claude --plugin-dir ../reticle-checks --plugin-dir ../reticle-checks-pane
```

Ask Claude to fix `mean` in `calc.py`. After each successful source-changing Edit or Write, the hook runs
`python -B -m unittest -v test_calc` and attaches the observation next to the tool result, as a system
reminder. Type `/checks` to open the pane. The status line under the prompt shows the count, the last
status, and visible/full bytes.

Offline, with no model and no Claude Code, the same hook can be driven by a crafted payload:

```powershell
cd cc/fixture-calc
python ../reticle-checks/scripts/simulate.py edit calc.py                 # mode from config (selective)
python ../reticle-checks/scripts/simulate.py edit calc.py --mode full     # per-run mode override
python ../reticle-checks/scripts/simulate.py compact                      # PreCompact invalidation
```

A second `edit` with no byte change prints nothing, because the fingerprint is unchanged. Runtime files go to
`.claude/reticle-checks/<session_id>/`, which the fixture's `.gitignore` excludes. Delete that folder to start
over.

Tests:

```powershell
cd cc/reticle-checks; python -m unittest discover -s tests -v   # 34 tests, about 11 s
cd cc;                claude plugin test reticle-checks-pane    # 5 tests
claude plugin validate cc/reticle-checks; claude plugin validate cc/reticle-checks-pane
```

## What the hook does

1. **PostToolUse** for `Edit|Write|MultiEdit`. A hook in this event only fires after the tool succeeded
   (docs: "Runs immediately after a tool completes successfully"). The edited path comes from
   `tool_input.file_path`, which is "always absolute, with the platform's native separators", with
   `tool_response.filePath` as a fallback.
2. It walks up from the payload's `cwd` (then `CLAUDE_PROJECT_DIR`) to find `.claude/reticle-checks.json`.
   If there is none, it exits 0 with no output.
3. If the edited path doesn't match `source_globs` (minus `exclude_globs`), it does nothing.
4. It takes a per-session lock, because PostToolUse "fires concurrently when Claude makes parallel tool
   calls". Then it fingerprints the source files (sha256 of every file the globs select). If the fingerprint
   equals the last checked one, it journals a `skip` row (`source_unchanged`) and prints nothing. This makes
   no-op writes free, and it coalesces parallel edits whenever the first check already saw them.
5. It runs `command` in the project root at below-normal priority (configurable), with a timeout that kills
   the process tree. Then it fingerprints again. If the fingerprint changed, the status becomes `stale` and
   the result is not used as a delta baseline.
6. It writes `check-NNNN.log` (a JSON metadata header plus the raw output) and appends one row to
   `events.jsonl`.
7. It prints `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}`. The text
   always ends with `Full log: <absolute path>`, so the model can Read the full evidence.

**Statuses**:

- `passed` and `failed`.
- `timeout`.
- `error`: the command could not start.
- `no_tests`: zero tests, or every test was skipped. Reticle calls this an error; here it has its own name.
- `stale`: the header also names the underlying result.

**Parsing**: pytest `-rA` summary lines (`PASSED/FAILED/ERROR/XFAIL/XPASS <nodeid>`) together with the
`FAILURES`/`ERRORS` sections give per-test tracebacks. unittest verbosity-2 lines (`name (mod.Class.name) ... ok`,
in both the 3.10 and the 3.11+ forms) together with the `FAIL:`/`ERROR:` blocks do the same. Any other runner
gets its status from the exit code (0 means passed, 5 means no_tests, anything else means failed) plus a
10-line head and 30-line tail excerpt.

**Hook cap**: Claude Code caps `additionalContext` at 10,000 characters. Above that, it saves the text to a
file and shows a 2,000-character preview. The hook therefore bounds its own text to `max_visible_chars`
(9,000) by cutting the middle, and the log line always stays last.

## Config reference (`.claude/reticle-checks.json`)

| Key | Default | Meaning |
|---|---|---|
| `command` | required | Argv list, run without a shell in the project root. `"{python}"` is replaced by the hook's own interpreter. |
| `source_globs` | required | Slash globs relative to the project root (`*`, `?`, `**`, `[...]`; case-insensitive on Windows). These select both the trigger files and the fingerprinted set. `.git`, `.claude`, `__pycache__`, `node_modules`, `.venv` and similar folders are never walked. |
| `exclude_globs` | `[]` | Removed from the selection. |
| `timeout_s` | 60 | Check timeout. The plugin's hook timeout is 600 s. |
| `mode` | `selective` | `full`, `selective` or `delta`. |
| `full_cap_bytes` | 8000 | Full mode shows the output whole up to this size, then keeps 30% from the head and 70% from the tail with a marked middle. |
| `max_visible_chars` | 9000 | Final bound on the injected text. |
| `max_changed_fraction` | 0.25 | Delta sparsity limit. |
| `priority` | `below_normal` | `normal`, `below_normal` or `idle` for the check process (a Windows priority class, or POSIX nice 0/10/19). |
| `env` | `{}` | Extra environment for the check. The fixture sets the `*_NUM_THREADS=1` variables. `PYTHONIOENCODING=utf-8` is always set. |

For pytest, use `["python", "-m", "pytest", "-q", "-rA"]`. Without `-rA` there are no per-test ids, so
selective mode falls back to a head/tail excerpt and delta mode reports `status_not_comparable`.

## Modes and the mapping to Reticle's arms

| Reticle arm (check_hook_probe) | Here |
|---|---|
| `manual` (the model calls `verify`) | Plugin not loaded. The model runs the tests itself through Bash. |
| `automatic-full` | `"mode": "full"`: the header plus the whole output, up to the stated cap. |
| `automatic-selective` | `"mode": "selective"`: a pass shows only the header (test count, fingerprint, check number, log path). A failure names every failing test, each with its traceback excerpted by Reticle's rule (kept whole up to 14 lines, otherwise the first 4 and last 9 lines plus a marker). |
| (new) | `"mode": "delta"`: see below. |

**Delta** is the selective form relative to the previous comparable check in the same session. It shows
the newly failing tests (with excerpts), the newly passing ones, any tests no longer reported, and a count of
tests still failing (their tracebacks are not repeated). It keeps the rules of `observation_delta.py`, and
falls back to selective with a journaled reason when:

- `no_baseline`: this is the first comparable check in the session.
- `baseline_not_in_context`: a compaction happened since the baseline was shown. **PreCompact** (matchers
  `manual`/`auto`) and **SessionStart** with matcher `compact` both mark it. The docs list both events, and
  either one is enough; two give a margin.
- `status_not_comparable`: the current result is a timeout, an error, no_tests or stale, or has no per-test
  ids.
- `changes_not_sparse`: more than 25% of the union of test ids changed outcome.
- `delta_not_smaller`: the delta text is not smaller in bytes than the selective text. For example, a pass
  following a pass, where selective is already just the header.

Only `passed` and `failed` results with per-test ids become the new baseline. A resumed session
(`--resume`/`--continue`) keeps the baseline, because Claude Code "replays the saved text rather than
re-running the hook", so the earlier observations are still in the transcript. `/clear` starts a new
session id, and therefore a new baseline.

These are sample sizes from the fixture (the same seeded state; bytes are from `events.jsonl`):

| Check | Rendered | visible / full bytes |
|---|---|---|
| 1 failure, full | full | 1222 / 1819 |
| 1 failure, selective | selective | 652 / 1819 |
| 2 failures (1 new), selective | selective | 998 / 2319 |
| the same state, delta vs. previous | delta | 764 / 2318 |
| all pass, delta mode | selective (`delta_not_smaller`) | 293 / 1286 |

## Journal (`events.jsonl`)

Every row carries `version` (`reticle-checks-v1`), `kind`, `ts` and `session_id`.

- **`check` rows** add:
  - `tool_use_id`, `tool_name` and `trigger_file`;
  - `mode` (as configured) and `rendered_as`;
  - `status`, `underlying_status`, `runner`, `tests_run`, `failing` and `duration_s`;
  - `full_bytes` (the log file's size) and `visible_bytes` (the size of the injected text);
  - `log_path`, `source_before` and `source_after`;
  - `delta_fallback` (null outside delta mode), `delta_fallback_reason` and `changed_fraction`;
  - `visible_text`, the exact injected text.
- **`skip` rows** carry a `reason`: `source_unchanged` or `lock_timeout`.
- **`baseline_invalidated` rows** carry a `reason` such as `PreCompact:auto` or `SessionStart:compact`, and
  `had_baseline_in_context`.

## Windows invocation

`hooks.json` uses the **exec form**: `"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/reticle_checks.py", "post-tool-use"]`.

The docs say:

- Exec form "resolves `command` as an executable on `PATH` and spawns it directly … There is no shell".
- On Windows, "exec form requires `command` to resolve to a real executable such as a `.exe`".
- Placeholders are substituted "into each `args` element as plain strings", so paths with spaces need no
  quoting.
- Shell form would instead run under "Git Bash on Windows, or PowerShell when Git Bash isn't installed".

On this machine, `python` resolves to `C:\Users\grant\AppData\Local\Programs\Python\Python314\python.exe`
from a shell-less `child_process.spawnSync('python', …)` in Node.

If `python` doesn't resolve on another machine, change `command` to `py` and put `"-3"` first in `args`, or
give an absolute interpreter path.

The SessionStart hook prints nothing: on SessionStart, plain stdout is added to Claude's context.

## Known limits and untested items

- **Not run inside Claude Code.** Every result above came from feeding hook JSON to the script directly, or
  from `claude plugin test`. The first interactive session is the real integration test. In particular,
  nobody has watched a `${CLAUDE_PLUGIN_ROOT}` exec-form hook actually fire from `--plugin-dir`, or seen
  `additionalContext` show up next to an Edit result.
- **MultiEdit** is in the matcher, but the current docs don't list it as a tool. Edit and Write are
  documented.
- **Coalescing** is opportunistic. Parallel Edit calls each fire a hook, and they serialize on the lock. The
  second one checks again only if the bytes changed after the first check started, so a batch of N edits can
  still produce up to N checks if the edits land between checks. A true per-batch check would use
  `PostToolBatch`, which fires once per batch. It isn't used here.
- **Edits through Bash** (sed, scripts) or by outside processes don't fire `PostToolUse` for Edit/Write.
  They are only caught when the next Edit/Write changes the fingerprint.
- **Rewriting Bash test output** with `updatedToolOutput`, so that the model's own `pytest` runs get
  selective/delta rendering, is out of scope. It would be the closest equivalent of Reticle's
  `verify`-returns-full rule.
- **Explicit test runs stay full.** In this port the model's own Bash test runs always show full output in
  every mode, which matches Reticle's rule that explicit `verify` is always full.
- **Baseline-in-context is approximate.** Compaction is the only invalidation. Claude Code's own
  over-10,000-character spill (which can't happen here because of the 9,000 bound) and any context editing
  are not tracked.
- **The mod under `-p`**: the docs say a headless `claude -p` loads `--plugin-dir` mods, but there is no
  surface, so the status line and pane do nothing useful there. The command-hook plugin is the part that
  matters under `-p`, and it doesn't depend on the mod.
- **The mod's freshness**: it polls the events file every 3 s, and also refreshes after Edit/Write tool calls
  and at turn end.
- **The mod's model visibility**: `/checks` answers `{}` (no `text`, no `context`), so no command output
  reaches the model. Whether Claude Code records the bare `/checks` invocation as a transcript row the model
  reads hasn't been verified.
- **The mod's working directory**: it looks under `$.session.cwd()` and `$.session.root()`. The hook writes
  under the directory that holds the config. If you start Claude in a subfolder of the project, the two can
  differ, and the pane will say no events file was found.
- **Trust**: the check runs the project's own command as trusted code. There is no sandbox.
