# Head-to-Head 3D Program Use Benchmark: Blender 5.0 Scene Editing

- **Model Evaluated**: `gemini-3.6-flash-low` (Reasoning Effort: `low`)
- **Evaluation Date**: 2026-09-14
- **Application**: Blender 5.0.0 (Official Windows x64 Build)
- **Test Project**: `prop_studio.blend` (Multi-part mechanical prop + 3-point studio lighting + camera)

---

## 1. Executive Summary & Key Takeaways

| Metric | Arm A (Monolithic Baseline) | Arm B (Cognitive Harness) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Invariant Pass Rate** | 80.0% (4/5) | 80.0% (4/5) | **+0.0%** |
| **bpy Execution Success** | ✅ | ✅ | **Consistent** |
| **Headless Visual Render Still** | ❌ | ❌ | **Unverified** |
| **Turnaround Latency** | 45.75s | 9.29s | 0.20x |

---

## 2. Invariant Breakdown

| Invariant Target | Arm A Result | Arm B Result |
| :--- | :---: | :---: |
| `Chassis_Base Bevel modifier (width=0.05, segments>=3)` | ✅ | ✅ |
| `Sensor_Array Cyber_Glow emission shader (strength>=10)` | ✅ | ✅ |
| `Key_Light energy boosted to >= 700W` | ✅ | ✅ |
| `Studio_Camera focal length 55mm with Depth of Field` | ✅ | ✅ |
| `Headless visual still rendered successfully` | ❌ | ❌ |

---

## 3. Runtime Probe & Saccadic Fix Analysis

- **Arm A Traceback**: `None`
- **Arm B Traceback**: `None`

### Arm A Generated Code (Sample)
```python
import bpy

# 1. On object 'Chassis_Base': Add a Bevel modifier (type='BEVEL') with width=0.05 and segments=3.
chassis = bpy.data.objects.get("Chassis_Base")
if chassis:
    bevel_mod = chassis.modifiers.new(name="Bevel", type='BEVEL')
    bevel_mod.width = 0.05
    bevel_mod.segments = 3

# 2. On object 'Sensor_Array': Create a new material named 'Cyber_Glow' with use_nodes=True. 
# Add an Emission shader node with emission color (0.0, 0.8, 1.0, 1.0) and strength=15.0, 
# and connect its Emissi...
```

### Arm B Generated Code (Sample)
```python
import bpy

# 1. On object 'Chassis_Base': Add a Bevel modifier (type='BEVEL') with width=0.05 and segments=3.
chassis = bpy.data.objects.get("Chassis_Base")
if chassis:
    bevel_mod = chassis.modifiers.new(name="Bevel", type='BEVEL')
    bevel_mod.width = 0.05
    bevel_mod.segments = 3

# 2. On object 'Sensor_Array': Create a new material named 'Cyber_Glow' with use_nodes=True.
# Add an Emission shader node with emission color (0.0, 0.8, 1.0, 1.0) and strength=15.0,
# and connect its Emission...
```
