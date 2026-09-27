# ACTIVE EPISTEMIC BOARD (Self-Injected Dogfooding State)

> Historical board, not active instructions. As of 2026-09-15, use the stage ledger in
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Counts, pointers, rejected-path rules,
> and completion claims below have not been revalidated and must not direct current work.

## 1. GOAL & INVARIANTS (ACCEPTANCE CRITERIA)
**Goal:** Incrementally optimize and harden the Reticle Cognitive Harness architecture using its own "Notes-as-State, Tools-as-Opcodes" principles.

**Strict Verification Invariants:**
- [x] Invariant 1: 100% pass on all unit tests (`tests/test_*.py` -> 42/42 tests passing).
- [x] Invariant 2: 100% pass on all root discovery tests (`test_*.py` -> 54/54 tests passing).
- [x] Invariant 3: Zero regression across the 4 benchmark domains (DispatchDesk, PEPs, 4K ScreenSpot, Blender 5.0).
- [ ] Invariant 4: Sleep Consolidation Engine (`consolidate.py`) synthesized to automatically graduate episodic traces into verified `./skills/*.py`.
- [ ] Invariant 5: CLI integration (`reticle run-stateless`) wired into `reticle/cli.py`.

---

## 2. FALSIFICATION LEDGER (REJECTED PATHS - DO NOT REPEAT)
| ID | Step | Falsified Hypothesis | Action Attempted | Rejection Evidence |
| :--- | :--- | :--- | :--- | :--- |
| `f_01` | 1 | Unbounded append-only conversational history | Standard chat `messages.append(turn)` | Context explosion; 40k tokens in spec grounding, attention drift on large repos. |
| `f_02` | 1 | Permanent sensory downgrading into fuzzy summaries | Compressing 4K screens & video into text logs | Loss of fine-grained spatial/syntactic affordances; 284px retina drift. |
| `f_03` | 2 | Relative file paths for headless Blender render output | `scene.render.filepath = 'render_output.png'` | Render still saved to Blender executable directory rather than target destination. Fixed: use `.resolve()`. |
| `f_04` | 2 | Raw `shutil.rmtree` on `.git` directory on Windows | `shutil.rmtree(dest)` | `PermissionError: [WinError 5] Access is denied` on read-only git pack files. Fixed: use `safe_rmtree` with `stat.S_IWRITE`. |

---

## 3. GROUNDING POINTERS (EXACT LOCATIONS IN RAW ENVIRONMENT)
| ID | Target File / Component | Locator (Lines/Symbol) | Semantic Role | Verified |
| :--- | :--- | :--- | :--- | :--- |
| `ptr_01` | `stateless_harness.py` | `L36-L65` (`FalsificationLedger`) | Traps negative knowledge to monotonically prune dead ends | Yes |
| `ptr_02` | `stateless_harness.py` | `L76-L113` (`GroundingLedger`) | Spatial & symbolic pointer registry (addresses, not data) | Yes |
| `ptr_03` | `stateless_harness.py` | `L119-L200` (`DynamicToolRegistry`) | Synthesizes Python tools via AST validation into callable opcodes | Yes |
| `ptr_04` | `stateless_harness.py` | `L206-L242` (`EpistemicNoteBoard`) | Compiles stateless 5-plane state packet for each blank-slate turn | Yes |
| `ptr_05` | `stateless_harness.py` | `L380-L536` (`BlankSlateHarness`) | Stateless execution loop with invariant checking and trace logging | Yes |
| `ptr_06` | `reticle/cli.py` | `L1-L132` | CLI entrypoints for Reticle commands | Yes |
| `ptr_07` | `experiments/run_stateless_comparison_bench.py` | `L1-L470` | 4-domain benchmark runner (DispatchDesk, PEPs, 4K Screen, Blender) | Yes |

---

## 4. SYNTHESIZED RUNTIME TOOLS (COMPOUNDED CAPABILITIES)
| Tool Name | Location / Type | Description |
| :--- | :--- | :--- |
| `verify_feed_invariants` | Synthesized Python probe | Deterministically tests public & held-out test contracts on DispatchDesk in zero context tokens. |
| `verify_pep_citations` | Synthesized Python probe | Validates presence of exact formal specification citations across PEP 484, 585, and 695. |
| `verify_prop_studio_scene` | `blender_verifier.py` | Evaluates evaluated scene graph AST and headless render still in Blender 5.0. |
| `evaluate_grounding` | `spatial_verifier.py` | Computes Euclidean distance and bounding box containment on 4K screenshots. |
| `safe_rmtree` | `stateless_harness.py` utility | Recursively deletes directories on Windows overriding git read-only permissions. |

---

## 5. LAST ACTION DELTA (IMMEDIATE FEEDBACK)
- [Multi-Module Refactoring Meta-Loop Completed]:
  1. `stateless_harness.py`: `run()` decomposed into `_dispatch_tool()` (complexity 152.2 -> 78.7, branches 22 -> 11).
  2. `harness.py`: `run()` decomposed into `_dispatch_tool()` (complexity 157.8 -> 125.6, branches 23 -> 18).
  3. `perception.py`: `extract_outline()` de-duplicated using `_format_function_outline()` (complexity 136.2 -> 93.6).
  4. `temporal_verifier.py`: `verify_temporal_invariants()` decomposed into modular monotonicity, continuity, and energy checkers.
  5. `doc_perception.py`: `parse_document_structure()` decomposed into `_detect_heading()` and `_create_section_node()`.
  6. `doc_generator.py`: `verify_document()` decomposed into `_extract_sections()`, `_verify_code_blocks()`, and `_verify_citations()`.
  7. `runtime_probe.py`: `run_with_probe()` decomposed using `_probe_sandbox()` context manager and `_extract_exception_frames()`.
  8. `blender_verifier.py`: `verify_prop_studio_scene()` decomposed into declarative `_evaluate_scene_invariants()`.
  9. `reticle/cognitive/capability_ledger.py`: `record_trial()` simplified by encapsulating `record_outcome()` on `CapabilityRecord`.
- 100% Invariant Verification: All 42 unit tests in `tests/` and 54 root tests green.
- Benchmark Verification: 100% pass across all 4 domains (DispatchDesk, PEPs, 4K ScreenSpot, Blender 5.0). Zero regressions.
