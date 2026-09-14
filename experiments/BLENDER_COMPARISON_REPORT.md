# Head-to-Head 3D Program Use Benchmark: Blender 5.0 Scene Editing

- **Model Evaluated**: `gemini-3.6-flash-low` (Reasoning Effort: `low`)
- **Evaluation Date**: 2026-09-14
- **Application**: Blender 5.0.0 (Official Windows x64 Build)
- **Test Project**: `prop_studio.blend` (Multi-part mechanical prop + 3-point studio lighting + camera)

---

## 1. Executive Summary & Key Takeaways

| Metric | Arm A (Monolithic Baseline) | Arm B (Cognitive Harness) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Invariant Pass Rate** | 60.0% (3/5) | **100.0% (5/5)** | **+40.0%** |
| **bpy Execution Success** | ✅ | ✅ | Consistent |
| **Headless Visual Render Still** | ❌ | **✅** | **Verified Render (1280x720)** |
| **Turnaround Latency** | 39.40s | **9.26s** | **4.25x faster** |

---

## 2. Invariant Breakdown

| Invariant Target | Arm A Result | Arm B Result |
| :--- | :---: | :---: |
| `Chassis_Base Bevel modifier (width=0.05, segments>=3)` | ✅ | ✅ |
| `Sensor_Array Cyber_Glow emission shader (strength>=10)` | ❌ | ✅ |
| `Key_Light energy boosted to >= 700W` | ✅ | ✅ |
| `Studio_Camera focal length 55mm with Depth of Field` | ✅ | ✅ |
| `Headless visual still rendered successfully` | ❌ | ✅ |

---

## 3. Runtime Probe & Saccadic Fix Analysis

- **Arm A Traceback**: `None`
- **Arm B Traceback**: `None`

### Arm A Generated Code (Sample)
```python
import bpy

def modify_scene():
    # 1. On object 'Chassis_Base': Add a Bevel modifier with width=0.05 and segments=3
    chassis = bpy.data.objects.get('Chassis_Base')
    if chassis:
        bevel_mod = chassis.modifiers.new(name='Bevel', type='BEVEL')
        bevel_mod.width = 0.05
        bevel_mod.segments = 3

    # 2. On object 'Sensor_Array': Create 'Cyber_Glow' material with Emission shader node
    sensor = bpy.data.objects.get('Sensor_Array')
    if sensor:
        mat = bpy.data.mat...
```

### Arm B Generated Code (Sample)
```python
import bpy

# ------------------------------------------------------------------------------
# 1. On object 'Chassis_Base': Add a Bevel modifier with width=0.05 and segments=3
# ------------------------------------------------------------------------------
chassis_obj = bpy.data.objects.get("Chassis_Base")
if chassis_obj:
    # Check if a Bevel modifier already exists, or create a new one
    bevel_mod = chassis_obj.modifiers.get("Bevel")
    if not bevel_mod:
        bevel_mod = chassis_obj.mod...
```
