"""Controlled Head-to-Head 3D Program Use Benchmark on Blender 5.0.

Evaluates multi-component scene graph editing, geometric modifiers, PBR shaders,
lighting, camera optics, and headless rendering on the least capable model:
Model: gemini-3.6-flash-low (effort=low).

Arms:
- Arm A (Baseline): Monolithic bpy generation without scene graph perception or probe feedback.
- Arm B (Cognitive Harness): Macro scene skeleton foveation -> Transactional runtime probe ->
  Saccadic error recovery -> Deterministic invariant verification.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import blender_env as be
import blender_perception as bp
import blender_verifier as bv

BENCH_DIR = ROOT / "experiments" / "blender_bench"
FIXTURE_BLEND = BENCH_DIR / "fixtures" / "prop_studio.blend"
MODEL_NAME = "gemini-3.6-flash-low"
MODEL_EFFORT = "low"

TASK_INSTRUCTION = (
    "In the existing Blender scene 'prop_studio.blend', implement the following modifications using Python bpy:\n"
    "1. On object 'Chassis_Base': Add a Bevel modifier (type='BEVEL') with width=0.05 and segments=3.\n"
    "2. On object 'Sensor_Array': Create a new material named 'Cyber_Glow' with use_nodes=True. "
    "Add an Emission shader node with emission color (0.0, 0.8, 1.0, 1.0) and strength=15.0, "
    "and connect its Emission output to the Material Output 'Surface' input. Assign this material to Sensor_Array.\n"
    "3. On object 'Key_Light': Set light energy to 800.0W and color to (1.0, 0.95, 0.8).\n"
    "4. On object 'Studio_Camera': Set camera lens focal length to 55.0mm and enable depth of field (dof.use_dof=True).\n"
    "5. Set scene.render.filepath = 'render_output.png', and render the frame with bpy.ops.render.render(write_still=True).\n"
    "6. Save the blend file with bpy.ops.wm.save_mainfile()."
)


def call_model(prompt: str, timeout: int = 180) -> str:
    cmd = [
        "agy",
        "--model", MODEL_NAME,
        "--effort", MODEL_EFFORT,
        "--dangerously-skip-permissions",
        f"--print={prompt}"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        print(f"Warning: call_model timed out after {timeout}s.")
        return ""


def extract_python_code(text: str) -> str:
    """Extract python code from markdown code block or fallback to raw text."""
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    return text.strip()


def setup_work_blend(dest_dir: Path) -> Tuple[Path, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_blend = dest_dir / "prop_studio.blend"
    render_out = dest_dir / "render_output.png"
    shutil.copy(FIXTURE_BLEND, target_blend)
    if render_out.exists():
        render_out.unlink()
    return target_blend, render_out


def run_benchmark():
    print("=================================================================")
    print("BLENDER 5.0 END-TO-END PROGRAM USE BENCHMARK")
    print(f"Model: {MODEL_NAME} (effort={MODEL_EFFORT})")
    print("=================================================================\n")

    work_a = BENCH_DIR / "work_arm_a"
    work_b = BENCH_DIR / "work_arm_b"

    blend_a, render_a = setup_work_blend(work_a)
    blend_b, render_b = setup_work_blend(work_b)

    # ==========================================
    # ARM A: Monolithic Unaugmented Baseline
    # ==========================================
    print("--- [Arm A: Monolithic Baseline Generation] ---")
    arm_a_prompt = (
        f"You are a 3D graphics engineer writing a Python bpy script for Blender 5.0.\n"
        f"Task:\n{TASK_INSTRUCTION}\n\n"
        f"Write ONLY executable Python code that runs headlessly in Blender."
    )
    t0 = time.time()
    arm_a_raw = call_model(arm_a_prompt)
    arm_a_code = extract_python_code(arm_a_raw)

    # Run Arm A script in Blender
    run_res_a = be.run_blender_script(arm_a_code, blend_file=blend_a)
    arm_a_time = time.time() - t0

    # Verify Arm A invariants
    eval_a = bv.verify_prop_studio_scene(blend_a, expected_render_path=render_a)
    print(f"Arm A Execution: {run_res_a.success} in {arm_a_time:.2f}s | Score: {eval_a.score*100:.1f}%")
    if run_res_a.traceback:
        print(f"Arm A Traceback: {run_res_a.traceback[:200]}...")

    # ==========================================
    # ARM B: Cognitive Blender Harness
    # ==========================================
    print("\n--- [Arm B: Cognitive Blender Harness] ---")
    t0 = time.time()
    # 1. Macro Scene Sensor: Extract scene skeleton
    scene_data = bp.extract_scene_graph(blend_b)
    scene_skeleton = bp.render_scene_skeleton(scene_data)

    # 2. Foveated Generation with Scene Affordances
    arm_b_prompt = (
        f"You are an expert Blender 5.0 automation engineer.\n"
        f"=== Current Scene Graph Topology ===\n{scene_skeleton}\n\n"
        f"Task:\n{TASK_INSTRUCTION}\n\n"
        f"Important Blender 5.0 conventions:\n"
        f"- Use obj.modifiers.new(name='Bevel', type='BEVEL')\n"
        f"- For material nodes, ensure material.use_nodes = True, create an 'ShaderNodeEmission' node, "
        f"and link its 'Emission' output to the 'Surface' input of 'Material Output'.\n"
        f"- Ensure context and active object handling is robust in headless mode.\n\n"
        f"Return ONLY the executable Python script in a markdown code block."
    )
    arm_b_raw = call_model(arm_b_prompt)
    arm_b_code = extract_python_code(arm_b_raw)

    # 3. Transactional Runtime Probe Execution
    run_res_b = be.run_blender_script(arm_b_code, blend_file=blend_b)

    # 4. Saccadic Error Recovery if runtime probe caught a traceback
    if not run_res_b.success and run_res_b.traceback:
        print(f"Probe caught exception:\n{run_res_b.traceback[:200]}...")
        fix_prompt = (
            f"The following script threw an exception in Blender 5.0:\n"
            f"```python\n{arm_b_code}\n```\n\n"
            f"Traceback:\n{run_res_b.traceback}\n\n"
            f"Please fix the script and return only the corrected Python code."
        )
        arm_b_fixed_raw = call_model(fix_prompt)
        arm_b_code = extract_python_code(arm_b_fixed_raw)
        # Re-run patched script
        setup_work_blend(work_b)
        run_res_b = be.run_blender_script(arm_b_code, blend_file=blend_b)

    arm_b_time = time.time() - t0

    # 5. Deterministic Invariant Verification
    eval_b = bv.verify_prop_studio_scene(blend_b, expected_render_path=render_b)
    print(f"Arm B Execution: {run_res_b.success} in {arm_b_time:.2f}s | Score: {eval_b.score*100:.1f}%")

    # Generate Markdown Report
    report_path = ROOT / "experiments" / "BLENDER_COMPARISON_REPORT.md"
    report_lines = [
        "# Head-to-Head 3D Program Use Benchmark: Blender 5.0 Scene Editing",
        "",
        f"- **Model Evaluated**: `{MODEL_NAME}` (Reasoning Effort: `{MODEL_EFFORT}`)",
        "- **Evaluation Date**: 2026-09-14",
        "- **Application**: Blender 5.0.0 (Official Windows x64 Build)",
        "- **Test Project**: `prop_studio.blend` (Multi-part mechanical prop + 3-point studio lighting + camera)",
        "",
        "---",
        "",
        "## 1. Executive Summary & Key Takeaways",
        "",
        "| Metric | Arm A (Monolithic Baseline) | Arm B (Cognitive Harness) | Delta / Impact |",
        "| :--- | :---: | :---: | :---: |",
        f"| **Invariant Pass Rate** | {eval_a.score*100:.1f}% ({len(eval_a.passed_invariants)}/5) | {eval_b.score*100:.1f}% ({len(eval_b.passed_invariants)}/5) | **+{ (eval_b.score - eval_a.score)*100:.1f}%** |",
        f"| **bpy Execution Success** | {'✅' if run_res_a.success else '❌'} | {'✅' if run_res_b.success else '❌'} | **{'Crash avoided' if run_res_b.success and not run_res_a.success else 'Consistent'}** |",
        f"| **Headless Visual Render Still** | {'✅' if eval_a.render_verified else '❌'} | {'✅' if eval_b.render_verified else '❌'} | **{'Visual verified' if eval_b.render_verified else 'Unverified'}** |",
        f"| **Turnaround Latency** | {arm_a_time:.2f}s | {arm_b_time:.2f}s | {arm_b_time/max(0.1, arm_a_time):.2f}x |",
        "",
        "---",
        "",
        "## 2. Invariant Breakdown",
        "",
        "| Invariant Target | Arm A Result | Arm B Result |",
        "| :--- | :---: | :---: |",
    ]

    all_invariants = [
        "Invariant 1: Chassis_Base Bevel modifier (width=0.05, segments>=3)",
        "Invariant 2: Sensor_Array Cyber_Glow emission shader (strength>=10)",
        "Invariant 3: Key_Light energy boosted to >= 700W",
        "Invariant 4: Studio_Camera focal length 55mm with Depth of Field",
        "Invariant 5: Headless visual still rendered successfully"
    ]

    for inv in all_invariants:
        res_a = any(inv in p for p in eval_a.passed_invariants)
        res_b = any(inv in p for p in eval_b.passed_invariants)
        report_lines.append(f"| `{inv.split(':')[1].strip()}` | {'✅' if res_a else '❌'} | {'✅' if res_b else '❌'} |")

    report_lines.extend([
        "",
        "---",
        "",
        "## 3. Runtime Probe & Saccadic Fix Analysis",
        "",
        f"- **Arm A Traceback**: `{run_res_a.traceback[:300] if run_res_a.traceback else 'None'}`",
        f"- **Arm B Traceback**: `{run_res_b.traceback[:300] if run_res_b.traceback else 'None'}`",
        "",
        "### Arm A Generated Code (Sample)",
        "```python",
        arm_a_code[:500] + ("..." if len(arm_a_code) > 500 else ""),
        "```",
        "",
        "### Arm B Generated Code (Sample)",
        "```python",
        arm_b_code[:500] + ("..." if len(arm_b_code) > 500 else ""),
        "```",
        ""
    ])

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n[SUCCESS] Blender benchmark complete! Report saved to {report_path}")


if __name__ == "__main__":
    run_benchmark()
