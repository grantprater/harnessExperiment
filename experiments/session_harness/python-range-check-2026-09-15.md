# Python version range check (deferred installed-workflow track)

Date: 2026-09-15  
Question: does the advertised `requires-python = ">=3.9"` match what runs?  
Source: working tree after S2b and before the runner v4 edits (191 tests at that point).  
Method, per version: a fresh uv venv with the declared dependencies (`pillow opencv-python numpy
pyyaml`), then `python -m unittest discover -s tests` (offline; the four live OCI tests skip).

| Python | Result |
|---|---|
| 3.9.25 | 191 run, 6 errors, 4 skipped. All six are in `tests.test_falsification_eval`: `experiments/falsification_eval/run_falsification_eval.py` calls `tempfile.TemporaryDirectory(ignore_cleanup_errors=True)`, which requires Python 3.10. |
| 3.10.21 | 191 run, 1 failure, 4 skipped: `TrustedLocalSupervisionTests.test_timeout_and_output_flood_do_not_hang_controller` (`flood.error_kind` is `None`, expected `output_limit`). It also failed when run alone. |
| 3.11.16 | 191 passed, 4 skipped |
| 3.13.15 (`.runtime/test-venv`) | passed (same tree) |
| 3.14.0 | 191 passed, 4 skipped |

Other observations:

- All 52 package files parse with `ast.parse(..., feature_version=(3, 9))`. This checks grammar
  only, not runtime API use.
- `import reticle` imports `reticle.verifiers.blender_verifier`, which imports Pillow at module load,
  so every `reticle.*` import (including `reticle.runtime`) currently requires Pillow.
- No `yaml` import exists in the package. `numpy` and `cv2` are imported only optionally
  (`reticle/cognitive/autotelic_drive.py`).

Not investigated: the cause of the 3.10 output-limit failure, and whether to narrow
`requires-python` or fix the code. The plan revision on 2026-09-15 defers the installed
workflow, so these are recorded here rather than acted on. The uv venvs are kept under
`.runtime/py39-venv`, `.runtime/py310-venv`, `.runtime/py311-venv`, and `.runtime/py314-venv`.
