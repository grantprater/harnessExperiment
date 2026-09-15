# S2b: pinned OCI candidate/evaluator path, E0 boundary probes, no-API controls

Date: 2026-09-15  
Status: S2b gates run; no model or API calls  
Source base: `70b6a9f` plus the shared dirty S2a/S2b working tree; exact file hashes in
`S2b-source-manifest.sha256`  
Engine: Podman 5.8.6, rootless WSL 2 machine (amd64)  
Image: `localhost/reticle-p6-task:py313-v1`, image ID
`8b74015e5079d613ccd9f17d891fc540cf5b9d6a427b2512b92e6f50eafe355b`, built from
`python:3.13-alpine@sha256:7415fbc3…` plus `experiments/p6_pilot/oci/requirements.lock`
(the `.runtime/bugs-venv` versions, binary wheels only; colorama omitted)

## What changed

- `run_pilot.py` runner v3: `--backend {trusted-local,oci}`. OCI resolves the tag to an image ID
  and runs by ID; there is no fallback. Candidate `run` commands and the evaluator use the same
  backend, with the guest interpreter (`python`) and guest `PYTHONPATH` (`/workspace[/src]`). The
  execution contract, including image ID and container user arguments, is recorded in `config.json`
  and included in the protocol hash. The new `tester` client runs the existing test roots without
  editing anything. Every result records `initial_workspace_revision` plus the head and tail of each tool result.
- `ExecutionRequest.writable_mount`: `AcceptanceRunner` mounts its private evaluation copy writable
  (the evaluator installs fixed inputs and writes JUnit XML there) while still journaling the
  evaluation as read-only with respect to the candidate workspace.
- `WorkspaceTracker`: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and
  `.hypothesis` are outside source revision scope. They are also left out of evaluator
  snapshots. Sourceless `.pyc` files outside those directories stay in scope.
- Podman guest user is now `--userns keep-id` (was `--user 65534:65534`); see Round 1 below.
  Docker keeps 65534.

## Validation

```powershell
$env:RETICLE_OCI_TEST_IMAGE = 'localhost/reticle-p6-task:py313-v1'
.\.runtime\test-venv\Scripts\python.exe -m unittest discover -s tests
# 191 passed, 0 skipped (the previously skipped live OCI tests ran)
```

## E0 boundary probes (`run_s2b_controls.py`)

The same probe runs as a candidate `run` command on both backends. Trusted-local is the positive
control. Expectations and the decision rule are fixed in the script and written to `card.json`
before the probes run. Raw tool outputs are kept in `s2b_runs/<run>/raw.jsonl`.

| Check | trusted-local expected / observed | isolated-oci expected / observed |
|---|---|---|
| sibling evaluator file readable (host path, `../evaluator`) | True / True | False / False |
| credential sentinel file readable | True / True | False / False |
| host-process credential env var visible | False / False | False / False |
| host loopback listener reachable | True / True | False / False |
| public IP 1.1.1.1:443 reachable | not attempted | False / False |
| DNS resolves | not attempted | False / False |
| workspace write | True / True | True / True |
| workspace chmod (run 2 only) | True / True | True / True |
| source write changes revision | True / True | True / True |
| pytest succeeds in fixture | True / True | True / True |
| cache directories created | True / True | True / True |
| cache files leave revision unchanged | True / True | True / True |

- `s2b-e0-1` (guest uid 65534): 22 of 22 checks matched.
- `s2b-e0-2` (keep-id, with the chmod check added): 24 of 24 matched.
- Audit: OCI denials are `FileNotFoundError` on sibling and credential paths, `gaierror` for DNS,
  `ConnectionRefusedError`/`OSError` for sockets. The container environment has no host variables
  (only image variables plus `PYTHONIOENCODING`). The cache directories created were `__pycache__`.

## Pipeline controls: 14 real-repository tasks x 5 clients, isolated OCI

Expected acceptance was fixed before the runs: gold accepted; noop, breaker, gamer, and tester
rejected. Generated tables (from `config.json`/`results.jsonl` only):
[round 1](s2b_runs/S2b-controls-table-s2b-oci.md), [round 2](s2b_runs/S2b-controls-table-s2b-oci2.md).
One-task smoke first: `s2b-oci-smoke-gold`, boltons-474 accepted, 16 tests observed, evaluator
journaled on `isolated-oci` with guest paths.

| Round | Guest user | gold accepted | noop rejected | breaker rejected | gamer rejected | tester rejected |
|---|---|---:|---:|---:|---:|---:|
| 1 (`s2b-oci-*`) | `--user 65534:65534` | 14/14 | 14/14 | 14/14 | 14/14 | 14/14 |
| 2 (`s2b-oci2-*`) | `--userns keep-id` | 14/14 | 14/14 | 14/14 | 14/14 | 14/14 |

Both rounds match the trusted-local P6 controls (`pipeline-*`, 14/14 each) task for task. In
both rounds, the noop and tester final revision equals the initial revision on all 14 tasks, including tester runs that
executed pytest in the workspace. Observed test counts under gold equal the task's
fail-to-pass plus pass-to-pass counts (for example boltons-474: 16; pyparsing-639: 1,838).

### Round 1 finding: chmod denied to the guest user (fixed)

The tester control's own `pytest -q tests` runs failed with `PytestCacheWarning: could not create
cache path ... Operation not permitted` on packaging-1330 and click-3805 (repos that turn warnings
into errors) and humanize-329. A direct mount probe isolated the cause:
as uid 65534, write, mkdir, mkdtemp, directory rename, and file replace succeed but `chmod` fails
with `EPERM`. It succeeds as container root and with `--userns keep-id` (guest uid 1000, the rootless host user).
Acceptance was unaffected because the evaluator runs pytest with `-p no:cacheprovider`, but live
candidates would have seen spurious failures (also for `shutil.copy2`). The backend now uses keep-id with Podman.
Round 2 reran every control and probe under the changed contract.

### Candidate-visible environment differences (round 2 tester vs trusted-local tester)

The tester's own run-tool results on `s2b-oci2-tester` vs `s2b-local-tester`: same outcome on
10 of 14 tasks. Differences, from the saved tool outputs:

| Task | OCI | trusted-local | Failing lines (saved output) |
|---|---|---|---|
| boltons-474, boltons-475 | 496 / 506 passed | 1 failed | local: `test_reverse_iter_lines` expects `\n`, got `\r\n` |
| marshmallow-3016 | 1184 passed | 1 failed | local: `test_from_timestamp_with_overflow_value` message differs |
| markdown-it-py-416 | 74 failed, 915 passed | collection error | OCI: `ModuleNotFoundError: Linkify enabled but not installed`; local: `UnicodeDecodeError: 'charmap'` |

Unchanged in both environments: tomlkit-549/551 and pyparsing-639 collection errors, packaging-1330
and click-3805 collection errors, humanize-329's 15 setup errors. linkify-it-py is absent from both the
image and the host venv. None of these affected acceptance (gold 14/14 in both environments).

### Elapsed time

| Measurement | OCI | trusted-local |
|---|---:|---:|
| gold, more-itertools-1270, five OCI batches in parallel (round 1) | 292.9 s | 7.4 s |
| gold, more-itertools-1270, run alone | 10.3 s | 7.4 s |
| tester `pytest -q tests`, more-itertools-1270, run alone (21,165 subtests) | 297.6 s | 13.7 s |

The evaluator's 604-test subset is close to trusted-local when run alone. The full more-itertools
suite is about 22 times slower in OCI. Its cause (bind-mount I/O versus CPU inside the VM) was not isolated. With the
default 120 s `run` timeout, a candidate running that full suite in OCI would time out.

## Residual threat model

- Candidate code executes during evaluation inside the same container and evaluation copy as the
  grader. It could overwrite `evaluation-junit.xml`, the copied bundle, or its own stdout report.
  Fixed test trees and root configuration are reinstalled, coverage is checked, and the gamer
  (conftest hook) control is rejected. That is a targeted regression, not arbitrary adversarial resistance.
- Native file tools (`read_file`, `write_file`, `replace_text`, `list_files`, `search`) run on the
  host, confined to the workspace by resolved-path checks. They are not inside the container.
- The image and engine are trusted. The image was built from PyPI wheels pinned by version, not by
  hash; runs pin the resulting image ID.
- The E0 probes cover guessable paths, one host listener, one public IP, and DNS. Mount scope is
  also asserted by the command-construction tests (one `--mount`).
- Docker was not exercised live.

## Gates

| S2 gate | Result |
|---|---|
| candidate cannot access sibling paths, credential sentinels, or network | passed (E0, both runs) |
| golden accepted; noop, breaker, and known gamer rejected (actual OCI path) | passed (14 tasks, both rounds) |
| caches do not falsely report source edits | passed (E0 fixture; noop/tester revision unchanged on 14 tasks) |
| unavailable isolated backend never falls back | unchanged; `test_missing_engine_fails_without_local_fallback` passes |

Not run: installed-wheel checks, Docker engine, any model run. Live runners still use the
non-reporting client, so HTTP retries are not charged to the task ledger.

## Next decision

Before E3 in OCI: (1) have `run_pilot.py`'s OpenRouter client adopt the attempt-reporting protocol;
(2) decide the candidate `run` timeout, or exclude slow suites, given the more-itertools measurement;
(3) decide whether to add linkify-it-py to the task environment (it changes the pinned image, so the
controls would have to be rerun).
