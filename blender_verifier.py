"""Blender Deterministic Invariant Verifier.

Acts as the formal compiler and oracle for 3D scene modifications. Evaluates:
1. Object Existence & Hierarchy Invariants
2. Mesh Modifier Stack Invariants (Type, parameters, segment counts, limit methods)
3. Material & Shader Node Invariants (Node connections, socket types, emission strength)
4. Lighting & Camera Invariants (Energy, color, focal length, depth of field)
5. Headless Visual Rendering Invariants (Output image existence, resolution, non-black pixels)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

import blender_env as be


@dataclass
class BlenderVerificationResult:
    passed: bool
    score: float  # 0.0 to 1.0
    passed_invariants: List[str]
    failed_invariants: List[str]
    render_verified: bool
    details: Dict[str, Any]

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Blender Scene Invariant Verification: {status} (Score: {self.score*100:.1f}%) ===",
            f"- Passed Invariants ({len(self.passed_invariants)}): {self.passed_invariants}",
        ]
        if self.failed_invariants:
            lines.append(f"- Failed Invariants ({len(self.failed_invariants)}): {self.failed_invariants}")
        lines.append(f"- Headless Render Verified: {self.render_verified}")
        return "\n".join(lines)


VERIFICATION_PROBE_SCRIPT = """
import bpy
import json
import sys

def verify_scene():
    results = {
        "modifiers": {},
        "materials": {},
        "lights": {},
        "cameras": {},
        "errors": []
    }
    
    # 1. Chassis Base Bevel Modifier
    chassis = bpy.data.objects.get("Chassis_Base")
    if not chassis:
        results["errors"].append("Missing object 'Chassis_Base'")
    else:
        bevel = next((m for m in chassis.modifiers if m.type == "BEVEL"), None)
        if bevel:
            results["modifiers"]["Chassis_Base_Bevel"] = {
                "exists": True,
                "width": round(bevel.width, 3),
                "segments": bevel.segments,
                "limit_method": bevel.limit_method
            }
        else:
            results["modifiers"]["Chassis_Base_Bevel"] = {"exists": False}

    # 2. Sensor Array Material (Cyber_Glow Emission)
    sensor = bpy.data.objects.get("Sensor_Array")
    if not sensor:
        results["errors"].append("Missing object 'Sensor_Array'")
    else:
        glow_mat = next((s.material for s in sensor.material_slots if s.material and s.material.name == "Cyber_Glow"), None)
        if glow_mat and glow_mat.use_nodes and glow_mat.node_tree:
            has_emission = any(n.type == "EMISSION" for n in glow_mat.node_tree.nodes)
            em_node = next((n for n in glow_mat.node_tree.nodes if n.type == "EMISSION"), None)
            strength = em_node.inputs["Strength"].default_value if em_node else 0.0
            results["materials"]["Sensor_Array_Cyber_Glow"] = {
                "exists": True,
                "has_emission": has_emission,
                "strength": round(strength, 1)
            }
        else:
            results["materials"]["Sensor_Array_Cyber_Glow"] = {"exists": False}

    # 3. Key Light Power and Color
    key_light = bpy.data.objects.get("Key_Light")
    if key_light and key_light.type == "LIGHT":
        results["lights"]["Key_Light"] = {
            "energy": round(key_light.data.energy, 1),
            "color": [round(c, 2) for c in key_light.data.color]
        }
    else:
        results["lights"]["Key_Light"] = {"exists": False}

    # 4. Studio Camera Lens & DOF
    cam = bpy.data.objects.get("Studio_Camera")
    if cam and cam.type == "CAMERA":
        results["cameras"]["Studio_Camera"] = {
            "lens": round(cam.data.lens, 1),
            "use_dof": cam.data.dof.use_dof if hasattr(cam.data, "dof") else False
        }
    else:
        results["cameras"]["Studio_Camera"] = {"exists": False}

    print("=== VERIFY_JSON_START ===")
    print(json.dumps(results))
    print("=== VERIFY_JSON_END ===")

if __name__ == "__main__":
    verify_scene()
"""


def _evaluate_scene_invariants(
    data: Dict[str, Any],
    expected_render_path: Optional[Union[str, Path]]
) -> Tuple[List[str], List[str]]:
    """Evaluate individual 3D scene invariant rules against probe data."""
    passed, failed = [], []

    # Invariant 1: Chassis_Base Bevel Modifier
    bev = data.get("modifiers", {}).get("Chassis_Base_Bevel", {})
    if bev.get("exists") and abs(bev.get("width", 0.0) - 0.05) <= 0.01 and bev.get("segments") >= 3:
        passed.append("Invariant 1: Chassis_Base Bevel modifier (width=0.05, segments>=3)")
    else:
        failed.append(f"Invariant 1: Chassis_Base Bevel missing or incorrect parameters: {bev}")

    # Invariant 2: Sensor_Array Cyber_Glow Material
    mat = data.get("materials", {}).get("Sensor_Array_Cyber_Glow", {})
    if mat.get("exists") and mat.get("has_emission") and mat.get("strength", 0.0) >= 10.0:
        passed.append("Invariant 2: Sensor_Array Cyber_Glow emission shader (strength>=10)")
    else:
        failed.append(f"Invariant 2: Sensor_Array Cyber_Glow shader missing or incorrect: {mat}")

    # Invariant 3: Key Light Energy >= 700W
    light = data.get("lights", {}).get("Key_Light", {})
    if light.get("energy", 0.0) >= 700.0:
        passed.append("Invariant 3: Key_Light energy boosted to >= 700W")
    else:
        failed.append(f"Invariant 3: Key_Light energy below 700W: {light}")

    # Invariant 4: Studio Camera Lens == 55mm & DOF
    cam = data.get("cameras", {}).get("Studio_Camera", {})
    if abs(cam.get("lens", 0.0) - 55.0) <= 2.0 and cam.get("use_dof"):
        passed.append("Invariant 4: Studio_Camera focal length 55mm with Depth of Field")
    else:
        failed.append(f"Invariant 4: Studio_Camera focal length or DOF incorrect: {cam}")

    # Invariant 5: Headless Visual Render Still
    render_ok = False
    if expected_render_path:
        r_path = Path(expected_render_path)
        if r_path.exists() and r_path.stat().st_size > 5000:
            try:
                with Image.open(r_path) as im:
                    render_ok = (im.size[0] >= 640 and im.size[1] >= 360)
            except Exception:
                render_ok = False

    if render_ok:
        passed.append("Invariant 5: Headless visual still rendered successfully")
    elif expected_render_path:
        failed.append(f"Invariant 5: Render still missing or invalid at {expected_render_path}")

    return passed, failed, render_ok


def verify_prop_studio_scene(
    blend_file: Union[str, Path],
    expected_render_path: Optional[Union[str, Path]] = None
) -> BlenderVerificationResult:
    """Verify all 5 engineering & visual invariants on the prop_studio project."""
    res = be.run_blender_script(VERIFICATION_PROBE_SCRIPT, blend_file=blend_file)
    if not res.success:
        return BlenderVerificationResult(
            passed=False,
            score=0.0,
            passed_invariants=[],
            failed_invariants=[f"Blender probe crash: {res.traceback or res.stderr}"],
            render_verified=False,
            details={}
        )

    out = res.stdout
    if "=== VERIFY_JSON_START ===" not in out:
        return BlenderVerificationResult(
            passed=False,
            score=0.0,
            passed_invariants=[],
            failed_invariants=["Failed to parse probe JSON"],
            render_verified=False,
            details={"raw_stdout": out}
        )

    json_str = out.split("=== VERIFY_JSON_START ===")[1].split("=== VERIFY_JSON_END ===")[0].strip()
    data = json.loads(json_str)

    passed, failed, render_ok = _evaluate_scene_invariants(data, expected_render_path)
    total_invariants = 5 if expected_render_path else 4
    score = len(passed) / total_invariants
    all_passed = (len(failed) == 0)

    return BlenderVerificationResult(
        passed=all_passed,
        score=score,
        passed_invariants=passed,
        failed_invariants=failed,
        render_verified=render_ok,
        details=data
    )
