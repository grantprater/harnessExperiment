"""Multimodal Closed-Loop Cognitive Harness (Code -> Execution -> Visual Inspection -> Refinement).

Demonstrates the multimodal epistemic loop:
1. Actuation: Model synthesizes code (bpy script).
2. Execution: Headless environment executes code and produces a visual artifact (render_output.png).
3. Visual Transduction & Invariant Verification:
   - Evaluates deterministic scene graph AST invariants (modifiers, lights, materials).
   - Inspects the rendered still with the VLM (checking emission, framing, lighting).
4. Epistemic Crystallization:
   - Any visual, symbolic, or runtime error is crystallized into the Falsification Ledger.
5. Sensory Evaporation:
   - The rendered image is pruned from the working context window for the next turn.
   - Subsequent turns receive flatline context: Epistemic Note Board + Current Code.
"""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.cognitive.llm_client import LLMClient
import blender_env as be
import blender_verifier as bv

FIXTURE_BLEND = ROOT / "experiments" / "blender_bench" / "fixtures" / "prop_studio.blend"

SYSTEM_PROMPT = """You are an expert 3D graphics engineer automating Blender 5.0 headlessly via Python bpy.
Write robust, complete, and syntactically correct Python code that operates on the existing Blender scene.
Always return your complete implementation inside a ```python ``` code block.
"""

INITIAL_PROMPT = """# Task: 3D Prop Studio Automation (Blender 5.0)

You are automating modifications to the existing scene in `prop_studio.blend`.

## Required Engineering & Visual Invariants:
1. Object 'Chassis_Base': Add a Bevel modifier (type='BEVEL') with width=0.05 and segments=3.
2. Object 'Sensor_Array': Create a new material named 'Cyber_Glow' with use_nodes=True.
   Add an Emission shader node with cyan emission color (0.0, 0.8, 1.0, 1.0) and strength=15.0.
   Connect its Emission output to the Material Output 'Surface' input.
   Assign this material to Sensor_Array.
3. Object 'Key_Light': Set light energy to 800.0W and warm color (1.0, 0.95, 0.8).
4. Object 'Studio_Camera': Set camera focal length to 55.0mm and enable depth of field (dof.use_dof=True).
   Ensure Studio_Camera cleanly frames the entire prop assembly without clipping.
5. Headless Visual Render:
   - Set `bpy.context.scene.render.filepath = os.path.abspath('render_output.png')`
   - Render the frame with `bpy.ops.render.render(write_still=True)`
   - Save the blend file with `bpy.ops.wm.save_mainfile()`

CRITICAL BLENDER CONVENTION:
In headless mode on Windows, `scene.render.filepath` MUST be an absolute path (using `os.path.abspath('render_output.png')`), otherwise Blender defaults to the program directory and fails.

Return ONLY the complete executable Python script inside a ```python ``` code block.
"""

VISUAL_INSPECTION_PROMPT = """You are a Quality Assurance 3D Supervisor reviewing a rendered frame from Blender 5.0.
The scene was supposed to show a multi-part mechanical prop consisting of:
1. A beveled rectangular Chassis_Base at the bottom.
2. A cylindrical Turret_Mount in the middle.
3. A spherical Sensor_Array mounted on top with a vibrant glowing cyan/blue emission shader (strength 15.0).
4. An Antenna_Mast on the side.
5. A 55mm camera shot where the entire prop (from chassis to top glowing sensor) is framed without clipping.

Examine this rendered frame carefully.
Respond with valid JSON:
{
  "visible_prop": <true/false>,
  "sensor_glowing_cyan": <true/false>,
  "fully_framed": <true/false>,
  "lighting_adequate": <true/false>,
  "visual_defects": "<clear, actionable critique describing any framing clipping, missing glow, or defects, or 'None'>"
}
"""

REVISE_PROMPT = """# Multimodal Feedback on 3D Scene Execution (Turn {turn})

Your previous Blender script was executed headlessly. Here are the empirical results:

## 1. Deterministic Scene Graph Verification
- Invariants Passed: {passed_invariants}
- Invariants Failed: {failed_invariants}
- Headless Render Generated: {render_verified}

## 2. Execution Errors & Traceback
{execution_errors}

## 3. Visual Inspection Supervisor Findings
```json
{visual_critique}
```

## 4. Epistemic Action Directives
{epistemic_directives}

Review the current code, correct any Python exceptions, node connections, camera positioning / aiming, modifier attributes, or render settings,
and provide the complete, corrected Python script.

Current Code:
```python
{current_code}
```

Return ONLY the complete corrected script inside a ```python ``` code block.
"""


def extract_python_code(text: str) -> str:
    matches = re.findall(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    matches_generic = re.findall(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if matches_generic:
        return matches_generic[-1].strip()
    return text.strip()


def encode_image(img_path: Path) -> str:
    with Image.open(img_path) as im:
        buf = BytesIO()
        im.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")


def inspect_render_visually(client: LLMClient, render_path: Path) -> Dict[str, Any]:
    """Transient sensory transduction: pass image to VLM, extract critique, then evaporate."""
    if not render_path.exists() or render_path.stat().st_size < 1000:
        return {
            "visible_prop": False,
            "sensor_glowing_cyan": False,
            "fully_framed": False,
            "lighting_adequate": False,
            "visual_defects": "Render file missing or empty."
        }

    b64 = encode_image(render_path)
    msg = [{
        "role": "user",
        "content": [
            {"type": "text", "text": VISUAL_INSPECTION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]
    }]

    resp = client.chat_completion(msg)
    raw = resp["content"]

    try:
        clean = raw.strip()
        if "```json" in clean:
            clean = clean.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean:
            clean = clean.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(clean)
        return data
    except Exception:
        return {
            "visible_prop": "prop" in raw.lower(),
            "sensor_glowing_cyan": "cyan" in raw.lower() or "glow" in raw.lower(),
            "fully_framed": "clip" not in raw.lower(),
            "lighting_adequate": "dark" not in raw.lower(),
            "visual_defects": raw[:300]
        }


def build_epistemic_directives(run_res: Any, verify_res: Any, critique: Dict[str, Any], render_exists: bool) -> str:
    """Compile structured falsification record into actionable directives for the next turn."""
    directives = []
    if run_res.traceback:
        directives.append(f"CRITICAL RUNTIME EXCEPTION: The script crashed before completion. Fix the Python error shown in the traceback above.")
    if verify_res.failed_invariants:
        directives.append(f"Fix failed deterministic invariants: {verify_res.failed_invariants}")
    if not render_exists:
        directives.append("CRITICAL: Set `bpy.context.scene.render.filepath = os.path.abspath('render_output.png')` and call `bpy.ops.render.render(write_still=True)`.")
    if not critique.get("sensor_glowing_cyan"):
        directives.append("Visual Oracle: The cyan glowing Sensor_Array was NOT visible or glowing in the rendered frame.")
    if not critique.get("fully_framed"):
        defects = critique.get("visual_defects", "")
        directives.append(f"Visual Oracle: Prop assembly is partially clipped or out of frame ({defects}). Reframe Studio_Camera to capture the full assembly cleanly.")
    if not directives:
        directives.append("Review visual defects and refine scene setup.")
    return "\n".join(f"- {d}" for d in directives)


def run_multimodal_trial(client: LLMClient, max_turns: int = 3) -> Dict[str, Any]:
    print("=" * 80)
    print("RUNNING MULTIMODAL CLOSED-LOOP HARNESS: BLENDER 5.0 3D SCENE")
    print(f"Model: {client.model} | Sensory Evaporation: ACTIVE | Max Turns: {max_turns}")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        target_blend = work_dir / "prop_studio.blend"
        render_png = work_dir / "render_output.png"
        shutil.copy(FIXTURE_BLEND, target_blend)

        total_tokens = 0
        t0 = time.time()
        turn_history = []
        current_code = ""

        for turn in range(1, max_turns + 1):
            print(f"\n{'=' * 40}")
            print(f"[Turn {turn}/{max_turns}] Generating code...")
            print(f"{'=' * 40}")

            if turn == 1:
                prompt = INITIAL_PROMPT
            else:
                last_turn = turn_history[-1]
                v_res = last_turn["verify_res"]
                critique = last_turn["critique"]
                r_res = last_turn["run_res"]
                directives = build_epistemic_directives(r_res, v_res, critique, render_png.exists())

                if r_res.traceback:
                    execution_errors = f"```\n{r_res.traceback}\n```\nScript crashed during execution. Fix this runtime exception first."
                else:
                    execution_errors = "None (script executed without Python runtime exceptions)"

                prompt = REVISE_PROMPT.format(
                    turn=turn,
                    passed_invariants="\n  * " + "\n  * ".join(v_res.passed_invariants) if v_res.passed_invariants else "None",
                    failed_invariants="\n  * " + "\n  * ".join(v_res.failed_invariants) if v_res.failed_invariants else "None",
                    render_verified=render_png.exists(),
                    execution_errors=execution_errors,
                    visual_critique=json.dumps(critique, indent=2) if critique else "Render file missing.",
                    epistemic_directives=directives,
                    current_code=current_code
                )

            # FLATLINE CONTEXT DISPATCH (Sensory Evaporation)
            # The model never sees raw pixels in its coding context window.
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]

            resp = client.chat_completion(messages)
            turn_tokens = resp.get("usage", {}).get("total_tokens", 0)
            total_tokens += turn_tokens
            current_code = extract_python_code(resp["content"])
            print(f"  Generated {len(current_code.splitlines())} lines of bpy code ({round(time.time() - t0, 2)}s, {turn_tokens} tokens)")

            # Clear previous render still
            if render_png.exists():
                render_png.unlink()

            # Execute code in Blender headlessly
            print("  Executing headless Blender render...")
            run_res = be.run_blender_script(current_code, blend_file=target_blend, timeout=45, cwd=work_dir)
            verify_res = bv.verify_prop_studio_scene(target_blend, expected_render_path=render_png)

            print(f"  Blender Return Code: {run_res.returncode} (Success: {run_res.success})")
            if run_res.traceback:
                print(f"  Blender Traceback: {run_res.traceback[:200]}")
            print(f"  Scene Invariants: {len(verify_res.passed_invariants)}/5 passed")
            if verify_res.passed_invariants:
                print(f"    Passed: {verify_res.passed_invariants}")
            if verify_res.failed_invariants:
                print(f"    Failed: {verify_res.failed_invariants}")
            print(f"  Render Still Exists: {render_png.exists()} ({render_png.stat().st_size if render_png.exists() else 0} bytes)")

            # Transient Visual Inspection (Perception)
            critique = {}
            if render_png.exists() and render_png.stat().st_size > 5000:
                print("  Performing transient visual inspection on rendered frame...")
                critique = inspect_render_visually(client, render_png)
                print(f"  Visual Inspection: Prop visible={critique.get('visible_prop')}, Fully framed={critique.get('fully_framed')}, Glowing Cyan={critique.get('sensor_glowing_cyan')}")
                if critique.get("visual_defects") and critique.get("visual_defects") != "None":
                    print(f"  Visual Defects: {critique.get('visual_defects')}")

            turn_history.append({
                "turn": turn,
                "code": current_code,
                "run_res": run_res,
                "verify_res": verify_res,
                "critique": critique,
                "render_exists": render_png.exists()
            })

            # Termination Criteria: Deterministic invariants pass + Visual requirements pass
            is_solved = (
                verify_res.passed
                and critique.get("visible_prop", False)
                and critique.get("sensor_glowing_cyan", False)
                and critique.get("fully_framed", False)
            )

            if is_solved:
                print(f"\n>>> SOLVED ON TURN {turn}! All engineering & visual invariants satisfied.")
                artifact_dir = ROOT / "experiments" / "multimodal_loop"
                artifact_dir.mkdir(parents=True, exist_ok=True)
                if render_png.exists():
                    shutil.copy(render_png, artifact_dir / "final_multimodal_render.png")
                    print(f"  Saved final render artifact to: {artifact_dir / 'final_multimodal_render.png'}")
                return {
                    "solved": True,
                    "turns_used": turn,
                    "passed_invariants": verify_res.passed_invariants,
                    "failed_invariants": verify_res.failed_invariants,
                    "render_verified": render_png.exists(),
                    "visual_critique": critique,
                    "elapsed_s": round(time.time() - t0, 2),
                    "total_tokens": total_tokens,
                    "turn_history": [
                        {
                            "turn": th["turn"],
                            "invariants_passed": len(th["verify_res"].passed_invariants),
                            "critique": th["critique"]
                        }
                        for th in turn_history
                    ]
                }

            print(f"\n[Sensory Evaporation] Wiping raw render frame from memory. Carrying forward only Epistemic Ledger.")

        # If loop finishes without complete visual solve
        artifact_dir = ROOT / "experiments" / "multimodal_loop"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if render_png.exists():
            shutil.copy(render_png, artifact_dir / "final_multimodal_render.png")
            print(f"  Saved latest render artifact to: {artifact_dir / 'final_multimodal_render.png'}")

        last_turn = turn_history[-1]
        return {
            "solved": False,
            "turns_used": max_turns,
            "passed_invariants": last_turn["verify_res"].passed_invariants,
            "failed_invariants": last_turn["verify_res"].failed_invariants,
            "render_verified": last_turn["render_exists"],
            "visual_critique": last_turn["critique"],
            "elapsed_s": round(time.time() - t0, 2),
            "total_tokens": total_tokens,
            "turn_history": [
                {
                    "turn": th["turn"],
                    "invariants_passed": len(th["verify_res"].passed_invariants),
                    "critique": th["critique"]
                }
                for th in turn_history
            ]
        }


if __name__ == "__main__":
    client = LLMClient(model="gemini-flash-lite-latest")
    res = run_multimodal_trial(client, max_turns=3)
    print("\n" + "=" * 80)
    print("MULTIMODAL TRIAL RESULT:", "SUCCESS" if res["solved"] else "PARTIAL")
    print(f"Turns: {res['turns_used']} | Elapsed: {res['elapsed_s']}s | Tokens: {res['total_tokens']}")
    print(f"Final Visual Critique: {json.dumps(res['visual_critique'], indent=2)}")
    print("=" * 80)
