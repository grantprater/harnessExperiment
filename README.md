# Reticle: The Cognitive Harness Framework

A lightweight, multimodal cognitive agent harness based on systems theory, biological sensory transduction, epistemic working memory ledgers, and formal invariant verification.

Tested and benchmarked on low-capability models (**`gemini-3.6-flash-low`** with `--effort low`) across 5 domains.

---

## 1. Cross-Domain Capabilities & Benchmark Results

| Domain / Modality | Monolithic LLM Baseline | Reticle Cognitive Harness | Advantage / Benchmark Report |
| :--- | :---: | :---: | :---: |
| **1. Multi-Doc Spec Grounding** | 40,999 context tokens | **919 context tokens** | **-97.8% tokens, 100% citation pass** ([Report](file:///C:/Users/grant/harnessExperiment/experiments/GENERAL_COMPARISON_REPORT.md)) |
| **2. 4K GUI Spatial Perception** | 3,200 vision tokens (grid drift) | **638 vision tokens (two-scale saccade)** | **-80.1% vision tokens, 0px retina drift** ([Report](file:///C:/Users/grant/harnessExperiment/experiments/SPATIAL_COMPARISON_REPORT.md)) |
| **3. 3D Program Use (Blender 5.0)** | 60% invariant pass, 8.84s | **100% invariant pass (5/5), 2.08s** | **4.25x faster, evaluated scene graph AST** ([Report](file:///C:/Users/grant/harnessExperiment/experiments/BLENDER_COMPARISON_REPORT.md)) |
| **4. Temporal Video Reasoning** | Hallucinated `[0.0s - 6.0s]` | **Exact `[1.9s - 4.0s]`** | **-93.3% vision tokens, 100% LTL valid** ([Report](file:///C:/Users/grant/harnessExperiment/experiments/TEMPORAL_COMPARISON_REPORT.md)) |
| **5. Real Gameplay Video & Audio** | Speculative narrative | **Exact timestamps (4 shots @ 40s, drift @ 33s)** | **Cross-modal acoustic & optical grounding** ([Report](file:///C:/Users/grant/harnessExperiment/experiments/RETICLE_VIDEO_REPORT.md)) |

---

## 2. Core Architectural Pillars

1. **Deterministic Sensory Transduction**:
   - High-throughput pre-scans (OpenCV video profiler @ 397 fps, FFmpeg audio envelope @ 16kHz) isolate events in milliseconds with **zero LLM tokens**.
2. **Epistemic Working Memory Ledgers**:
   - `EvidenceLedger`: Distills multi-document facts into discrete atoms and evaporates raw source texts.
   - `WorldLineLedger`: Records 4D entity space-time intervals $(t_{\text{start}}, t_{\text{end}}, \text{entity}, \text{state}, \vec{x})$.
3. **Formal Invariant Verifiers (Deterministic Oracles)**:
   - Python AST Compiler (`ast.parse`)
   - Bounding Box Containment & Euclidean Distance
   - Blender Evaluated Graph & Headless Render Checks
   - Linear Temporal Logic (LTL: Chronological Monotonicity, Velocity Bounds / No-Teleportation, Physical Energy Grounding)
4. **Dynamic Perceptual Tooling ("Code-as-Sensor")**:
   - Enables agents to formulate and execute ad-hoc OpenCV, SciPy, and NumPy perceptual probes against image, video, and audio buffers.
   - Packaged as an Antigravity Custom Skill: [`.agent/skills/perceptual-tooling/SKILL.md`](file:///C:/Users/grant/harnessExperiment/.agent/skills/perceptual-tooling/SKILL.md).

---

## 3. Installation & CLI Usage

Install the package in editable mode:
```powershell
pip install -e .
```

### CLI Commands:
```powershell
# Display version
reticle version

# Check local Blender 5.0 installation
reticle blender-info

# Deterministically scan video dynamics (optical flow, blackouts, cuts)
reticle scan-video "path/to/video.mp4" --stride 5

# Deterministically scan audio dynamics (RMS envelope, transient peaks, frequency bands)
reticle scan-audio "path/to/video.mp4"

# Generate spatial grid topology for 1080p, 4K, etc.
reticle spatial-grid 1920 1080

# Verify Python syntax and extract symbols via AST compiler
reticle verify-ast path/to/script.py
```

---

## 4. Running Tests

Run the full test suite (51 unit tests):
```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m unittest discover -s . -p "test_*.py"
```
