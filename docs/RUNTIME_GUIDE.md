# Runtime guide

Feature reference extracted from the README on 2026-10-03. For current direction
and results, start with [PROJECT_STATE.md](PROJECT_STATE.md).

## Interactive terminal

Run `powershell -ExecutionPolicy Bypass -File tools/install-cli.ps1` once, then open
a new terminal. From the folder you want to work in:

```powershell
reticle
reticle "Profile this project and explain the slowest paths"
reticle --client openrouter --model MODEL_ID
reticle --resume PATH_TO_SESSION
reticle "Run the tests and fix the failure" --once
reticle --check
```

The default connection uses the OpenAI subscription OAuth registration made for
**Reticle Harness**, through its Responses adapter, with `gpt-6.1-sol`. The existing protected login is reused and
renewed automatically. `reticle login` connects a new account; `reticle models`
lists available models; `--model` selects one. This uses your shared ChatGPT plan,
as described in the [official subscription documentation](https://developers.openai.com/siwc/token-sharing-open-source/).
It does not read Codex's credential file. `--client codex` is an alias for this
subscription connection. `--client claude-cli --model sonnet` selects the separate
Claude subscription adapter. OpenRouter uses `OPENROUTER_API_KEY` from the environment or the
harness's private `experiments/.env` or `.env`; it requires a model ID. A generic
chat-completions connection uses `--client api --base-url URL --model MODEL_ID`
and `OPENAI_API_KEY`. Credentials are not copied into session configuration.
`--check` checks local configuration without sending a model request.

Use an existing Docker/Podman image for isolated command execution:

```powershell
reticle --backend isolated-oci --container-engine podman --container-image docker.io/library/python:3.13-alpine
```

The model connection and controller run on the host; commands run inside the
container with only the task workspace mounted, networking disabled, and a
read-only container root. File editing tools operate on the workspace from the
host. `--container-python` selects the guest Python executable. Images must
already exist locally; no image is pulled and execution never falls back to
trusted-local when isolation fails. The default remains `--backend trusted-local`.

The [reasoning horizon pilot](../experiments/session_harness/REASONING-horizon-pilot.md)
compares evidence-memory with the existing advisory symbolic rules over staged tasks.

Reticle runs its own file and command tools on your current folder using the
trusted-local backend. Session records live in `.reticle/`; `/session` shows the
path, `/exit` quits, and `--resume` restores conversation history. Each task allows
30 model responses by default (`--max-steps` changes this). Interrupted external
actions may require reconciliation; restarting does not blindly replay them.

The terminal accepts follow-up prompts after every task; `--once` exits after the
opening task. Each model step shows assistant messages, tool activity and provider
token usage. Turn and session totals include input, output and cached input tokens
when reported; missing measurements are shown as unreported or partial. `/usage`
shows session totals, including saved calls after resume. `--quiet` hides intermediate
output while keeping final answers and totals.

`--model-usage` also exposes provider-reported token measurements to the model on
the next request: task and session totals, last-call input/output and cached input,
with unreported or partial measurements labeled explicitly. This is cumulative
spend across calls, not current context occupancy or a token allowance. Cached input
is already included in input, so it is not added twice. The option is off by default
and works with `--runtime-updates`. Telemetry stays in the trailing resource-status
message to preserve the cache-oriented prompt layout.

For batch experiments, collect JSON without changing the model's feedback unless
that is the variable being tested:

```powershell
reticle "Run this experiment" --once --quiet --session-dir runs/trial-01/session --usage-report runs/trial-01/usage.json
reticle usage runs/trial-01/session --output runs/trial-01/usage.json
```

Reports include per-call measurements, task/session totals, stop reasons, model and
provider identifiers when reported, runtime versions, tool-schema hashes, context
policy versions and whether `--model-usage` was enabled. Missing token counts are
`null`, and totals include missing-call counts. Failed requests remain in the report;
failed/retried provider attempts can consume tokens without reporting usage, so
their unmeasured spend is not fabricated. Reports omit prompts, tool output and
credentials. `--usage-report` updates after each user turn and also works in
supervised mode; `reticle usage` exports an existing session without a model call.

The historical `--context-policy pressure-v4` uses the cache-oriented
`pressure-recent-v4` policy: changing resource status
comes last, and old transcript exchanges are removed in stable pages. Cache hits
still depend on the provider; the token display uses reported cache usage.

Two toolsets exist. `reticle/tools/primitives.py` is reticle-tools-v3, the default and
the one every run card pins. `reticle/tools/toolset_v4.py` (`ToolSuiteV4`) is v4, opt-in;
the interactive harness (`reticle/interactive.py`) and check hooks select it. The rest
of this section describes v4.

The v4 coding tools include `apply_patch(path, patch)` for single-file unified diffs
alongside `replace_text`. All patch hunks must match before the file changes.
`search_text` and `search_output` accept `regex=true` and `context_lines` (0–100),
with literal matching as the default. `run` accepts a workspace-relative `cwd` and
either one `command` or a `commands` array (up to 50), executed sequentially in
separate processes. Sequences stop on failure unless `stop_on_error=false`; shell
operators and persistent shell state are unavailable. `timeout_seconds` applies to
each command. Large command results show the start, end and numbered diagnostic
excerpts, with output handles for exact paging and search.

### Updating the running harness

Start with `reticle --runtime-updates` to run each user turn in a separate Python
worker using a fixed snapshot of the harness. The terminal and provider connection
stay in the supervisor. File edits become active only after explicit validation and
activation; editing a loaded module does not change the current turn.

When the workspace contains the harness repository, the model can call
`activate_runtime(source_root=".", reason="...")` after editing it, then finish its
turn normally. The tool snapshots the Python package, checks syntax and protected
file hashes, and runs import, session-read compatibility and controller smoke checks
in a separate process against a copy of the session. A successful check queues the
version; the next user turn starts it only after another readiness check. `/reload`
performs the same staging from the terminal. `/runtime` shows the active and pending
versions. `--resume SESSION --runtime-updates` retains the selected version, history,
notes, output handles and usage totals. `--once` leaves a queued update for resume.
The session also contains a recovery launcher: `python SESSION/runtime-updates/resume.py`.
It verifies and loads the saved supervisor snapshot, so it can resume even if edits
have made the checkout's normal CLI unimportable. Use the same Python environment
that runs Reticle; provider settings such as `--client` and `--model` still apply.

Snapshots and activation state live under `SESSION/runtime-updates/`. Model request
events record the runtime version and the hash of the exact tool schemas used.
Startup failure keeps or restores the previous working version. A failure after
turn dispatch stops visibly and never automatically reruns that turn. Pending
updates cannot activate while external actions have unknown outcomes.

This first version permits changes to tools, context policies, the controller and
interactive behavior. It requires storage, journal/task schemas, task budgets,
session ownership, workspace tracking, telemetry export, execution backends, provider/auth adapters
and supervisor/bootstrap files to match the session's initial version. Core changes
need a fresh supervisor/session until a migration protocol exists. The provider
broker also enforces the configured response, attempt and context limits.

Runtime updates execute **trusted Python code**. File-hash checks and separate
processes provide version consistency and recovery, not an OS security boundary:
workers retain local filesystem access, and arbitrary Python can monkeypatch its
own objects. Validation provides compatibility smoke checks, not proof that a
candidate improves behavior; run the relevant regression suite before staging.
Activation within a user turn and state migrations are not implemented yet.

When editing the harness itself, new processes use edited Python files. The
running terminal retains already-loaded modules. Measure a baseline and run
changed harness versions in fresh processes for comparable optimization results.

### Generated tools

`reticle --extensions` enables a versioned Python tool library without requiring
edits to the harness. It works with ordinary multi-turn sessions, `--once`/`--resume`,
and `--runtime-updates`. The model can use its file tools to write an extension,
call `extension_stage(path="tools/my_tool")`, then finish the turn. The next user
turn validates and activates the queued version. The available schemas and code
versions stay frozen throughout each turn, including after staging a revision.

An extension directory contains `manifest.json`, its Python entry point, and any
helper modules or assets. For example:

```json
{
  "name": "ext_add",
  "description": "Add an offset to a number.",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "properties": {"n": {"type": "integer"}},
    "required": ["n"]
  },
  "entrypoint": "tool.py:execute",
  "smoke_tests": [{"arguments": {"n": 2}, "expected": 3}],
  "timeout_seconds": 30
}
```

```python
# tool.py
def execute(arguments, context):
    return arguments["n"] + 1
```

Entry points receive two dictionaries and return a JSON-serializable value.
`context["workspace"]` is the execution workspace, and `context["validation"]`
identifies smoke checks. The current working directory is also the execution
workspace; helper modules can be imported from the extension directory. Imports
and smoke tests run in a child process with a temporary workspace, never by loading
generated modules into the controller. There must be 1–20 smoke cases; `expected`
is optional, but when present the returned JSON must match it. Supply tests that
work without live external services. Smoke checks establish executability, not
task quality. The [scale-values example](../examples/extensions/scale_values/) is a
complete bundle.

Names must use `ext_` followed by lowercase letters, digits and underscores.
Parameter schemas support explicit object, array, string, integer, number, boolean
and null types, with descriptions, enums, required properties, numeric bounds and
length/item bounds. Objects reject extra properties; unsupported schema keywords
are rejected during staging. Bundles are limited to 100 files/10 MB, reject
symlinks, and include hashes of their schema, source and assets. Entry points use
`file.py:function` in the bundle's top directory. Dependencies must already be
installed in the execution environment; staging does not install packages.

`extension_list()` shows this turn's frozen versions and the library's active,
previous and pending versions. `extension_rollback(name="ext_add")` validates and
queues the previous version for the next turn. Invalid queued versions preserve
the active version; failed startup checks restore the previous valid version or
omit the tool if none exists. Invocation errors and timeouts are returned as tool
results without automatic retry or fallback. Recovery of unfinished calls retains
their original tool versions, even if another session changes the shared library.

By default, sources remain in the workspace and snapshots/state live in
`WORKSPACE/.reticle/extensions/`. `--extension-library PATH` selects a separate
library **within the workspace**; relative paths are workspace-relative. Use
separate libraries for independent experiment conditions. Sessions sharing a
library see its changes at their next turn boundary. Source edits alone do not
change a staged tool: call `extension_stage` again to create a new version.

Extensions use the configured execution backend and interpreter, with timeouts and
bounded output. Trusted-local executes trusted code and provides no OS sandbox.
`--backend isolated-oci` uses the existing container restrictions for both
validation and invocation; there is no fallback to local execution. Each invocation
is conservatively treated as a workspace mutation and follows command recovery
rules. Extensions receive no provider credentials from the harness. The registry
and extension dispatcher are protected modules during runtime updates.

Usage reports include each model request's extension versions, frozen turn
snapshots, invocation versions/status/duration and counts by tool version. Failed
or unfinished invocations are explicit. Tool-building tokens remain part of the
normal task/session token totals; no speculative per-tool token attribution is
added.

```powershell
reticle "Build a reusable tool for this task" --extensions --usage-report runs/tool-build.json
```

The [Blender mesh-audit extension](../examples/extensions/blender_mesh_audit/) provides
`ext_mesh_audit(blend_file, objects?, require_closed?)`. Stage a copy inside the
task workspace to expose it through the registry. Its smoke check actually runs
Blender on a clean cube. Invocation opens the saved scene with automatic script
execution disabled, writes a diagnostic JSON report, and leaves the scene file
unchanged. Blender must be available in the selected execution environment.

The audit checks source and evaluated meshes for winding, inward closed shells,
duplicate/degenerate faces, wire/non-manifold edges, invalid coordinates and
collapsed transforms. It also finds positive-area overlaps between nearly
coplanar, same-facing triangles, with object names and face indices. Acceptance
uses evaluated geometry; source findings remain diagnostic so valid modifier
workflows can pass. Default selection is render-visible mesh objects. Opposite
facing assembly contacts and ordinary intersections are permitted. Declare
`require_closed=false` for intentional open surfaces. Nonplanar faces, duplicate
vertices and some modifier/shading settings are advisory, not automatic failures.

This is a bounded check for concrete defects, not proof of visual quality. It does
not comprehensively detect self-intersections, audit every shader/custom-normal
effect, or inspect instance geometry. Incomplete audits do not pass. Keep multiple
view/light inspections alongside it, and use repairs selected for the diagnosed
problem rather than indiscriminately welding or unioning an assembly.

The furniture pilot's independent verifier now includes mesh-quality checks.
`experiments/blender_bench/run_extension_pilot.py --mesh-quality-tools --run-dir NEW_DIR`
also provides the audit extension from its first turn. The verifier implementation
stays outside the model's editable workspace. `audit_saved_furniture.py` can audit
an existing pilot into a new output directory without changing historical scores
or saved assets; it records asset hashes and the audit implementation hash.

### Context management

The CLI defaults to `--context-policy minimal` and `--max-context-bytes 32000`
(including schemas). Routine tool observations get at most a 1 KB preview before
retrieval notes; explicit reads can deliver a 4 KB page. Larger exact results stay
available through output handles. At task boundaries, a bounded handoff carries
recent reported outcomes, file pointers and a prior-user excerpt rather than
resending the completed tool transcript. The complete prior user message has an
authorized, redacted artifact reference; history/search remain available. Restore
applicable prior requirements before relying on a truncated excerpt. Current-turn
corrections remain in context. `--context-policy pressure-v4 --max-context-bytes
120000` selects the historical behavior for comparisons.
Older successful file-edit exchanges become path/status receipts once a newer
exchange exists, so generation source is not repeatedly resent. The latest
exchange and failed edits retain their tool-call/result pairing; read the current
file when its contents are needed.

### Operating the decision policy

`reticle --context-policy decision --token-target 10000` selects experimental
`decision-v1`. The default remains `minimal` until real comparisons justify a
promotion. Before each model request, the policy derives compact task state from
actual transcript results: recent observations, file pointers, failures without a
matching successful retry, and a next-step hint. Reported success is not task
acceptance. Requirements and criteria remain in the task contract; the state does
not invent a replacement plan or add a separate planning call.

Two repeated failures of the same invocation, consecutive failed observations,
or three retrievals without execution produce an escalation reason. Routine
result previews expand from 1 KB to 4 KB, within the same total request limit,
and the model receives a suggestion to broaden or replan. These are heuristics,
not proof that the current approach is wrong. An exact successful retry clears
its failure; other resolutions are not inferred automatically. State snapshots
and their reasons are journaled, linked to each model request, and included in
usage reports. The latest state is saved under `SESSION/decision-state/`.

`--token-target` is a **soft per-task target**, including reported input and output
tokens and cached input. It exposes token progress in decision state; missing
usage stays unknown. It does not impose a guaranteed provider-token cap. Without
a target or `--model-usage`, token totals are omitted from model-facing state.

Policy trials use a common driver, fixed arguments, shuffled trial order and
fresh run directories. Explicit invocation of the following performs nine real
two-asset runs and spends model tokens:

```powershell
.venv/Scripts/python.exe experiments/policy_bench/run_sweep.py --config experiments/policy_bench/autumn.json --output-dir experiments/policy_bench/runs/autumn-NEW
```

The supplied configuration compares `minimal`, `decision` and `pressure-v4`
three times each, with identical 32 KB context limits and a soft target of 5,000
tokens per asset. Individual driver logs and partial progress remain available.
Inspect the images independently. Add `evaluation.json` to each run with
`{"accepted": true, "source": "reviewer", "protocol_id": "your-fixed-review-v1"}`
after applying the same acceptance procedure; use `false` for rejected outputs.
The driver’s measured palette/file checks remain separate from that review.

`experiments/policy_bench/compare_runs.py RUN_A RUN_B ... --output NEW_REPORT.json`
reports cost across **all attempts**, including failed trials, acceptance and
unknown acceptance, calls, escalation counts, and token-target attainment. It
calculates tokens per accepted attempt only with complete reported usage and a
consistent independent evaluation protocol. Unknown retry costs are not invented.
No policy is promoted automatically. Start with mechanical tests/replays, then
use real repeated tasks to assess quality and total cost together.

Compaction and cache reuse are separate objectives. Replacing earlier history
changes the request prefix at that point; task handoffs begin a new task layout.
Dynamic decision state stays at the end to preserve the preceding prefix. The
`pressure-v4` comparator retains history in stable pages. Total tokens (including
cached input) and reported uncached input are compared separately. A future
checkpoint-based policy could freeze compacted pages and append between checkpoints;
the current decision policy does not promise append-only history or cache hits.

### Visual assets and UI style

`reticle --style-tools` enables four tools: `style_extract`, `style_profile`,
`style_check`, and `style_apply`. Extract a profile from 1–20 workspace images
and/or CSS files, then check candidates against its `profile_id`. Raster references
provide a sampled palette plus advisory brightness, contrast and edge density.
CSS references provide colors, font-family chains, spacing, radii and font sizes.
Checks return a compact decision and up to three failure examples with CSS
line/property evidence. Passing checks suppress tolerated color findings. Complete
reports are saved at the returned `report_path`, readable on demand. Profiles retain
reference hashes, extractor version and explicit measurement thresholds.

`style_apply` requires explicit operations and a new output path. For images,
`["palette"]` remaps colors to the reference palette and preserves dimensions and
alpha, writing PNG. CSS supports `palette`, `fonts`, `spacing`, `radii`, and
`font_sizes`, including simple custom properties used for those tokens. The tool
returns a change count and compact post-check; changed declarations and the diff
remain in its full report. Original files
and existing outputs are preserved.

For batch evaluations, extract/review a profile first, then launch a fresh session:

```powershell
reticle --style-tools --style-profile path/to/target-profile.json
```

The session pins the profile's content hash across turns and resume. Extracting
new proposals cannot replace the pinned target. Usage reports record target IDs,
checks, and applications alongside token use; runtime-update workers support the
same tools. This is trusted local execution, not a security boundary against a
model with filesystem/command access: independently validate the expected target
hash and verifier when scoring experiments.

The first version measures palette/token consistency, not full artistic style
transfer, composition, semantics, accessibility or rendered UI quality. It does
not evaluate browser cascade/imports, scope-aware CSS variables, every color
syntax, or fonts supplied by a browser. Unknown/unresolved CSS values and candidates
without supported comparison features cannot pass; image statistics are advisory.
Nearest-color remapping can merge distinct colors and reduce contrast; inspect
the new copy before using it.
Image palettes use a bounded thumbnail, so small details may be missed. Keep
reference-based visual review alongside these measurements.

Composition is a separate dimension, not a default condition of stylistic
consistency. A palette pass only establishes the configured palette tolerance.
Broader taste preferences should be reference-backed and advisory, with permitted
variation; promote a preference to an enforced rule only when the project calls
for it. The current checker does not infer or score those broader preferences.

Run the controlled offline demonstration (no model calls or downloads) into a
new directory:

```powershell
.venv/Scripts/python.exe experiments/style_tools/run_style_demo.py --output-dir experiments/style_tools/demo
```

Open its `preview.html` to compare reference, candidate and aligned copies.
`report.json` contains before/after checks and `ui.diff` contains the CSS edits.

### Evidence and learning

`reticle --learn` exposes the session ontology and saves a versioned knowledge
snapshot after each task. It reuses the latest snapshot from
`WORKSPACE/.reticle/knowledge/` on the next task; `--knowledge-library PATH`
selects another scoped library. Optional dependencies: install `.[reasoning]`.
The model explicitly records evidence-linked procedures, hypotheses, applicability
conditions and declared dependencies through the reasoning tools.

`--reasoning memory` exposes the ontology without consolidation;
`--reasoning symbolic` also enables its existing advisory rules. `--knowledge FILE`
selects an immutable snapshot for retrieval. `--knowledge-mode transcript`,
`graph`, or `valid` selects prior transcript excerpts, graph retrieval, or graph
retrieval with dependency rechecking (default). Retrieval and task-boundary
feedback are journaled; controller completion does not imply verified acceptance.

File changes invalidate dependent assertions transitively; superseded and
model-declared contradicted claims require rechecking. Matching file fingerprints
do not establish truth or dependency completeness. After edits/commands and at
finish, retrieved dependency findings accompany the tool result. These are
advisory and do not block execution. Snapshots are fixed during each task.

```powershell
reticle --learn
reticle knowledge export SESSION --library .reticle/knowledge
reticle knowledge inspect SNAPSHOT.json
reticle knowledge propose SNAPSHOT.json
```

The last command proposes bounded experiments from issues observed in multiple
sessions; it does not execute or promote changes. See the
[knowledge transfer pilot](../experiments/session_harness/KNOWLEDGE-transfer-pilot.md).

