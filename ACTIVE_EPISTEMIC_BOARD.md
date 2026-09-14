# ACTIVE EPISTEMIC BOARD (Self-Injected Dogfooding State)

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
- Initialized active epistemic board for harness self-improvement.
- Verified all 42 unit tests in `tests/` and 54 root unit tests passing.
- Verified 4-domain head-to-head comparison report: 0.52s DispatchDesk, 381 tokens on PEPs (99.1% saving), 0.0px error on 4K GUI, 100% on Blender 5.0.
