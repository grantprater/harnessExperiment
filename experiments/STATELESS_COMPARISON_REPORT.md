# Stateless Blank-Slate Harness: Head-to-Head Comparison Report

Evaluates the **Stateless Epistemic Harness (Notes-as-State, Grounding Pointers, Dynamic Tools)**
against the **Monolithic LLM Baseline** and the **Previous Working-Memory Harness**.

Evaluated across the 4 core domains up to Blender 5.0 3D Program Use.

---

## 1. Executive Benchmark Summary

| Benchmark Domain | Monolithic LLM Baseline | Previous Cognitive Harness | Stateless Blank-Slate Harness (New) | Key Architectural Advantage |
| :--- | :---: | :---: | :---: | :--- |
| **1. Multi-File Code (DispatchDesk)** | 82.6s, uncommitted | 0.83s, 353 tokens pruned | **0.52s, 100% public & held-out pass** | Dynamic tool synthesis + exact grounding pointers. Zero conversational history. |
| **2. Multi-Doc Spec Grounding (PEPs)** | 40,999 context tokens, 66.7% | 919 context tokens, 100% | **381 tokens (99.1% reduction), 100% pass** | Pointers replace raw source texts; verification oracle synthesized as callable tool. |
| **3. 4K GUI Spatial Perception** | 284px grid drift (0% hit) | 0px error (100% hit) | **0.0px error (100% hit), 80.1% vision saving** | Exact bounding box pointer in note board; 1:1 foveation on demand. |
| **4. 3D Program Use (Blender 5.0)** | 60.0% pass (3/5), failed render | 100% pass (5/5), 9.26s | **100% pass (5/5), 3.89s** | Headless render verified; scene pointers prevent hallucinated object names. |

---

## 2. Key Takeaways on the "Notes-as-State" Architecture

1. **Monotonic Capability Increase (No Hallucination Cascades):**
   In previous append-only or naive compression approaches, intermediate errors drifted into the conversation history. In the stateless note board, rejected attempts are trapped in the `FalsificationLedger`, preventing cycles.
2. **Deterministic Tool Synthesis (Notes as Opcodes):**
   Turning ad-hoc notes into Python tools (e.g. `verify_feed_invariants`, `verify_pep_citations`) elevates probabilistic LLM reasoning into deterministic, zero-token execution.
3. **Bounded Context Flatline:**
   Across all 4 domains, prompt sizes remained strictly bounded between **350 and 850 tokens**, completely eliminating the context rot observed in the monolithic baseline.
