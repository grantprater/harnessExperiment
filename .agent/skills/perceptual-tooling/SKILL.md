---
name: perceptual-tooling
description: Formulate and execute dynamic perceptual probes (code-as-sensor) using OpenCV, SciPy, and NumPy for computer vision and audio signal analysis.
---

# Perceptual Tooling: The "Code-as-Sensor" Paradigm

This skill guides the formulation, execution, and verification of **dynamic perceptual probes**.

When an agent needs to reason about visual interfaces, video dynamics, or acoustic events, passing thousands of raw video frames or entire 4K canvases directly into an LLM context causes:
1. **Severe Token Bloat**: Thousands of vision tokens per second.
2. **Temporal Hallucination**: Difficulty resolving millisecond-level boundaries (e.g., exact gunshot timestamps or button clicks).
3. **Unverifiable Claims**: Subjective natural language descriptions cannot be checked by an oracle.

**The Solution:** Treat code as a sensor. The agent formulates a focused mathematical or computer vision query as an ad-hoc Python script using `reticle.sensory` tools (`PerceptualProbeRunner`, `AudioTransducer`, `VideoStreamTransducer`), executes it against the raw buffer, and commits discrete, verified findings into the `WorldLineLedger`.

---

## 1. Core Perceptual Probe Recipes

### Recipe A: Ad-Hoc Acoustic Transient Detection (Gunshots, Impacts, Ability Roars)

```python
from reticle.sensory import AudioTransducer

# Ingest soundtrack directly from video or WAV
transducer = AudioTransducer("path/to/video.mp4")

# Detect transient impulse peaks (e.g. gunshots or ability SFX)
peaks = transducer.detect_transient_peaks(
    window_size_s=0.025,
    std_multiplier=2.5,
    min_distance_s=0.08
)

# Extract frequency band distribution (low vs mid vs high)
for p in peaks:
    print(f"Transient at t={p.timestamp_s}s (RMS: {p.amplitude_rms}, Prominence: {p.relative_prominence})")
    print(f"  Frequency bands: {p.channel_energy}")
```

### Recipe B: Optical Flow & Camera Velocity Profiling

```python
import cv2
from reticle.sensory import PerceptualProbeRunner

runner = PerceptualProbeRunner()
# Measure motion vector between consecutive frames
result = runner.probe_optical_flow(frame_prev, frame_curr)
# Returns: {"mean_magnitude": 12.4, "mean_dx": -2.1, "mean_dy": 0.5, "dominant_direction_deg": 166.5}
```

### Recipe C: Centroid Tracking & HUD State Monitoring

```python
from reticle.sensory import PerceptualProbeRunner

# Track specific color ranges (e.g. neon abilities, health bars, minimap markers)
res = PerceptualProbeRunner.probe_color_centroid(
    image_bgr=frame,
    lower_hsv=(90, 150, 150),   # e.g., Cyan/Blue drift mask
    upper_hsv=(130, 255, 255)
)
if res["found"]:
    print(f"Centroid: {res['centroid']}, Bounding Box: {res['bbox']}, Pixel Count: {res['pixel_count']}")
```

### Recipe D: Saccadic Two-Scale Zooming for High-Res Screens

```python
from reticle.sensory import generate_overview_thumbnail, foveated_crop, project_to_global

# 1. Coarse scale (512x512) for macro routing
thumb, scale = generate_overview_thumbnail("desktop_4k.png", max_dim=512)

# 2. Dense foveated crop (1:1 full resolution around target sector)
patch = foveated_crop("desktop_4k.png", crop_bbox=(600, 300, 1200, 900))

# 3. Project coordinates back to global canvas
global_click = project_to_global(local_point=(150, 220), sector_bbox=(600, 300, 1200, 900))
```

---

## 2. The Cross-Modal Verification Workflow

When analyzing multi-stream data (video + audio + HUD):

1. **Deterministic Pre-Scan**:
   Run `AudioTransducer` and `VideoStreamTransducer` to extract:
   - Acoustic transient peaks (gunshot impulses, ability casts).
   - Video motion energy profile & scene cuts (blackouts).
2. **Phase Saccades**:
   Select only anchor keyframes matching detected audio/visual phase transitions.
3. **Ledger Commit**:
   Commit state intervals to `WorldLineLedger`.
4. **LTL Proof**:
   Run `TemporalInvariantVerifier` to formally prove:
   - Monotonic time order ($t_{\text{start}} < t_{\text{end}}$).
   - No teleportation ($\Delta d / \Delta t \le v_{\text{max}}$).
   - Cross-modal grounding (visual actions coincide with acoustic impulses).
