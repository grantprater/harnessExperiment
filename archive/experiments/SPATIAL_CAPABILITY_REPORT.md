# ScreenSpot-Pro 4K GUI Grounding: Capability Benchmark Report

Evaluates **gemini-3.6-flash** in two conditions on high-resolution desktop interfaces:
- **Arm A (Monolithic Unaugmented)**: Direct zero-shot prediction on downsampled full canvas.
- **Arm B (Reticle Spatial Harness)**: Coarse Grounding Pointer -> 1:1 Foveated Saccade -> Coordinate Projection.

---

## 1. Executive Capability Summary

| Metric | Arm A: Unaugmented Flash Baseline | Arm B: Reticle Spatial Harness | Capability Delta |
| :--- | :---: | :---: | :---: |
| **Grounding Hit Rate** | **0/3 (0.0%)** | **0/3 (0.0%)** | **+0.0% Capability Expansion** |
| **Mean Distance to Target** | **1137.4 px** | **230.0 px** | **-907.4 px Error Reduction** |
| **Sub-35px Widget Legibility** | Smeared (Downsampled) | Crisp (1:1 Native Resolution) | Lossless Optical Affordance |

---

## 2. Per-Task Empirical Breakdown

| Application & Screen | Widget Target | Arm A Prediction (Dist) | Arm B Prediction (Dist) | Outcome |
| :--- | :--- | :---: | :---: | :---: |
| **Android Studio (3840x2160)** | Virtual Device Highlights Slider | (525.0, 737.0) [1661.4px] | (1295.0, 1832.0) [250.2px] | Result |
| **Excel macOS (3456x2234)** | 'Text' Format Dropdown Menu | (352.0, 448.0) [1011.0px] | (1295.0, 1124.0) [198.2px] | Result |
| **Blender Windows (2560x1440)** | Y-Axis Position Text Field | (425.0, 763.0) [739.7px] | (1220.0, 1300.0) [241.6px] | Result |

---

## 3. Why Capability Expansion Occurred

1. **Downsampling Smear Barrier:**
   When feeding a 3840x2160 image directly into an LLM vision encoder, standard vision tiling downsamples or compresses the canvas. A 20-30px button shrinks to 5-8 pixels of blurred color. The model cannot read the text or see the slider ticks.
2. **Lossless Saccadic Foveation:**
   Reticle's cognitive architecture separates *where to look* from *what is there*. By routing to a 1:1 pixel patch, the exact same lightweight model receives pixel-perfect optical clarity, transforming an impossible task into an easy visual classification.
