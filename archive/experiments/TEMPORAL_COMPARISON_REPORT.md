# Head-to-Head Temporal / Video Reasoning Benchmark: Animated Physics Sequence

- **Model Evaluated**: `gemini-3.6-flash-low` (Reasoning Effort: `low`)
- **Evaluation Date**: 2026-09-14
- **Video Source**: Blender 5.0 Animated Physical Sequence (60 frames, 10 fps, 6.0 seconds)
- **Ground Truth Motion Interval**: `2.0s - 4.0s` (Frames 20 to 40)

---

## 1. Executive Summary & Key Takeaways

| Metric | Arm A (Monolithic Baseline) | Arm B (Cognitive Temporal Harness) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Motion Interval Accuracy** | ❌ (Failed) | **✅ (Exact [2.0s - 4.0s])** | **Deterministic Optical Grounding** |
| **Vision Tokens Consumed** | 18,000 tokens | **1,200 tokens** | **-93.3% token reduction** |
| **LTL Formal Verification** | ❌ (Unverified prose) | **✅ (100.0% LTL Valid)** | **Formal Proof of No Teleportation** |
| **Optical Profiler Overhead** | 0.0s | **0.372s** | Negligible sub-second pass |

---

## 2. Linear Temporal Logic (LTL) Invariant Verification

- **Chronological Monotonicity**: ✅
- **Spatial Continuity & No Teleportation**: ✅
- **Physical Motion Energy Grounding**: ✅

---

## 3. Epistemic World-Line Ledger View
```text
=== WORLD-LINE LEDGER (4 intervals recorded) ===
| ID | Entity | Time Interval [s] | State Predicate | Start Coords | End Coords | Provenance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `wl_001` | **Carrier Cart** (`Carrier_Cart`) | `0.0s - 2.0s` | `at_rest` | `(-3.0, 0.0)` | `(-3.0, 0.0)` | `frames: [1, 20]` |
| `wl_002` | **Carrier Cart** (`Carrier_Cart`) | `2.0s - 4.0s` | `in_motion` | `(-3.0, 0.0)` | `(3.0, 0.0)` | `frames: [20, 40]` |
| `wl_003` | **Carrier Cart** (`Carrier_Cart`) | `4.0s - 6.0s` | `at_rest` | `(3.0, 0.0)` | `(3.0, 0.0)` | `frames: [40, 60]` |
| `wl_004` | **Pillar** (`Stationary_Pillar`) | `0.0s - 6.0s` | `at_rest` | `(0.0, 2.0)` | `(0.0, 2.0)` | `frames: [1, 60]` |
=== END WORLD-LINE LEDGER ===
```

---

## 4. Architectural Analysis: How to Bridge the Video Verifiability Gap

1. **Sub-Second Optical Profiling Pre-Empts Video Tokens**:
   - Instead of streaming all 60 frames into the LLM context, `temporal_perception.py` computed the RMS frame energy profile in milliseconds.
   - The motion energy curve was 0.0 for Frames 1-19, peaked at 0.035 for Frames 20-39, and dropped to 0.0 for Frames 40-60.
2. **Formal LTL Invariants Replace Subjective Grading**:
   - The LLM's claims are verified against mathematical constraints: velocity limits (no teleportation), non-overlapping entity states, and non-zero optical energy grounding.
