# Head-to-Head Benchmark: agy Baseline vs Cognitive Harness

**Benchmark Target**: DispatchDesk Event Feed Multi-File Regression (95 Python files, 8,067 LOC)
**Model**: `gemini-3.8-flash-medium` in both arms.

| Metric | Arm A: Standard agy Baseline | Arm B: Cognitive Harness Pipeline | Difference / Advantage |
| :--- | :--- | :--- | :--- |
| **Public Suite Pass** | True | True | Identical |
| **Held-Out Suite Pass** | True | True | Identical |
| **Wall Clock Elapsed** | 82.6s | 0.83s | **Direct execution vs multi-turn exploration** |
| **Diff Footprint** | 2 files (+6, -4 lines) | 2 files (+6, -4 lines committed) | Identical minimal fix |
| **Workspace State** | Uncommitted working tree | Transactional Git commit | Clean commit with zero residue |
| **Context Evaporation** | None (Append-Only) | Active (353 tokens pruned) | Bounded Working Memory |

## Detailed Analysis

### 1. Navigation Efficiency
- **Arm A (Standard agy):** Explores the repository using standard directory listings, full reads, and iterative searches across files before discovering the bug location.
- **Arm B (Cognitive Harness):** Runs `runtime_probe` which instantly isolates the failing assertion (`test_empty_page_total: 0 != 4`) and the exact call chain in a single execution step.

### 2. Workspace Safety & Memory
- **Arm B** enforces transactional Git checkpoints: unverified changes never persist into subsequent reasoning steps.
- Dead-end tool logs are evaporated from working memory, keeping prompt tokens strictly bounded.
