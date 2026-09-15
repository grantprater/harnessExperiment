"""Empirical evaluation: Direct Baseline vs Additive Foveated Refinement (with Fallback).

Evaluates on ScreenSpot-Pro high-resolution tasks:
- Arm A (Direct Baseline): Full screenshot in native aspect ratio -> predict (x, y).
- Arm B (Additive Refinement): Full screenshot -> global proposal (gx, gy) ->
  1:1 native-resolution crop around (gx, gy) -> fine refinement with refusal/fallback.
  If fine stage reports target missing or unparseable, gracefully falls back to (gx, gy).
"""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.cognitive.llm_client import LLMClient
import spatial_loader as sl
import spatial_verifier as sv

DIRECT_PROMPT = """You are an expert GUI automation agent.
Screen Resolution: {width}x{height}
Task: {instruction}

Locate the exact UI element to click for this task.
Return the normalized coordinates of its center:
- x: 0 = leftmost pixel, 1000 = rightmost pixel
- y: 0 = topmost pixel, 1000 = bottommost pixel

Return ONLY valid JSON in this exact format:
{{"x": <number 0-1000>, "y": <number 0-1000>}}
"""

FINE_REFINE_PROMPT = """You are an expert GUI automation agent inspecting a zoomed-in 1:1 pixel patch of a desktop screen.
Original Task: {instruction}
Patch Size: {crop_w}x{crop_h} (native resolution)

Carefully inspect this image patch to see if the target UI element for the task is visible here.
- If the target element IS visible: identify its center relative to this patch (0-1000 range).
- If the target element is NOT visible in this patch: explicitly set "found" to false.

Return ONLY valid JSON in one of these two formats:
If found:
{{"found": true, "x": <number 0-1000>, "y": <number 0-1000>}}
If not found:
{{"found": false, "reason": "<brief reason why it is not here>"}}
"""


def encode_image(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def parse_coords(text: str) -> Tuple[Optional[float], Optional[float], str]:
    num = r"(-?\d+(?:\.\d+)?)"
    mx = re.search(r"[\"']?\bx[\"']?\s*[:=]\s*" + num, text)
    my = re.search(r"[\"']?\by[\"']?\s*[:=]\s*" + num, text)
    if not (mx and my):
        return None, None, "unparseable"
    x, y = float(mx.group(1)), float(my.group(1))
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None, None, f"out_of_range({x},{y})"
    return x, y, "ok"


def run_arm_a_direct(
    client: LLMClient,
    full_img: Image.Image,
    instruction: str
) -> Dict[str, Any]:
    w, h = full_img.size
    t0 = time.time()
    b64 = encode_image(full_img)
    prompt = DIRECT_PROMPT.format(width=w, height=h, instruction=instruction)

    msg = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]
    }]

    resp = client.chat_completion(msg)
    raw = resp["content"]
    x, y, status = parse_coords(raw)
    elapsed = time.time() - t0

    pt = None
    if x is not None and y is not None:
        pt = (x / 1000.0 * w, y / 1000.0 * h)

    return {
        "point": pt,
        "elapsed_s": round(elapsed, 2),
        "tokens": resp.get("usage", {}).get("total_tokens", 0),
        "raw_response": raw,
        "parse_status": status
    }


def run_arm_b_additive_refinement(
    client: LLMClient,
    full_img: Image.Image,
    instruction: str,
    crop_w: int = 800,
    crop_h: int = 600
) -> Dict[str, Any]:
    w, h = full_img.size
    t0 = time.time()

    # Step 1: Global proposal on full image
    global_res = run_arm_a_direct(client, full_img, instruction)
    g_pt = global_res["point"]

    if g_pt is None:
        return {
            "point": None,
            "global_proposal": None,
            "refined": False,
            "fallback_used": True,
            "reason": "Global proposal failed to parse",
            "elapsed_s": round(time.time() - t0, 2),
            "tokens": global_res["tokens"]
        }

    gx, gy = g_pt

    # Step 2: Extract 1:1 foveated patch around global proposal
    cw, ch = min(crop_w, w), min(crop_h, h)
    x1 = int(max(0, min(w - cw, gx - cw / 2)))
    y1 = int(max(0, min(h - ch, gy - ch / 2)))
    x2, y2 = x1 + cw, y1 + ch
    crop_box = (x1, y1, x2, y2)

    crop_img = full_img.crop(crop_box)
    crop_b64 = encode_image(crop_img)

    # Step 3: Foveated refinement with refusal option
    refine_prompt = FINE_REFINE_PROMPT.format(
        instruction=instruction,
        crop_w=cw,
        crop_h=ch
    )

    msg = [{
        "role": "user",
        "content": [
            {"type": "text", "text": refine_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{crop_b64}"}}
        ]
    }]

    resp = client.chat_completion(msg)
    raw = resp["content"]
    total_tokens = global_res["tokens"] + resp.get("usage", {}).get("total_tokens", 0)
    elapsed = time.time() - t0

    # Parse fine response
    found = True
    if '"found": false' in raw.lower() or '"found":false' in raw.lower():
        found = False

    lx, ly, status = parse_coords(raw)

    if found and lx is not None and ly is not None:
        # Refined prediction projected back to global canvas
        refined_pt = (x1 + (lx / 1000.0) * cw, y1 + (ly / 1000.0) * ch)
        return {
            "point": refined_pt,
            "global_proposal": g_pt,
            "crop_box": crop_box,
            "refined": True,
            "fallback_used": False,
            "elapsed_s": round(elapsed, 2),
            "tokens": total_tokens,
            "fine_raw": raw
        }
    else:
        # Fallback to global proposal!
        return {
            "point": g_pt,
            "global_proposal": g_pt,
            "crop_box": crop_box,
            "refined": False,
            "fallback_used": True,
            "fallback_reason": "Target reported not found or unparseable in fine crop",
            "elapsed_s": round(elapsed, 2),
            "tokens": total_tokens,
            "fine_raw": raw
        }


def run_benchmark():
    client = LLMClient(model="gemini-flash-lite-latest")
    suites = ["android_studio_macos", "excel_macos", "blender_windows"]
    
    tasks = [
        ("blender_windows", 0),
        ("excel_macos", 0),
        ("android_studio_macos", 0),
        ("blender_windows", 1),
        ("excel_macos", 2),
    ]

    print("=" * 80)
    print("LIVE EMPIRICAL BENCHMARK: DIRECT BASELINE vs ADDITIVE FOVEATION (WITH FALLBACK)")
    print(f"Model: {client.model} | Endpoint: {client.base_url}")
    print("=" * 80)

    results = []

    for suite, idx in tasks:
        sample = sl.load_spatial_sample(suite, idx)
        w, h = sample["canvas_size"]
        bbox = tuple(sample["ground_truth_bbox"])
        cx, cy = sample["target_center"]
        instruction = sample["instruction"]

        print(f"\n--- Task: {suite} [#{idx}] ---")
        print(f"Instruction: {instruction}")
        print(f"Canvas: {w}x{h} | GT Center: ({cx:.1f}, {cy:.1f}) | BBox: {list(bbox)}")

        with Image.open(sample["local_img_path"]) as img:
            full_img = img.convert("RGB")

            # Arm A: Direct Baseline
            print("  Running Arm A (Direct Baseline)...", end=" ", flush=True)
            res_a = run_arm_a_direct(client, full_img, instruction)
            ev_a = None
            if res_a["point"]:
                ev_a = sv.evaluate_grounding(res_a["point"], bbox, (w, h))
                print(f"{'HIT' if ev_a.hit else 'MISS'} | Dist: {ev_a.euclidean_distance_px:.1f}px ({res_a['elapsed_s']}s)")
            else:
                print(f"FAILED TO PARSE ({res_a['elapsed_s']}s)")

            # Arm B: Additive Refinement with Fallback
            print("  Running Arm B (Additive Refinement)...", end=" ", flush=True)
            res_b = run_arm_b_additive_refinement(client, full_img, instruction)
            ev_b = None
            if res_b["point"]:
                ev_b = sv.evaluate_grounding(res_b["point"], bbox, (w, h))
                ref_str = "REFINED" if res_b.get("refined") else "FALLBACK"
                print(f"{'HIT' if ev_b.hit else 'MISS'} [{ref_str}] | Dist: {ev_b.euclidean_distance_px:.1f}px ({res_b['elapsed_s']}s)")
            else:
                print(f"FAILED ({res_b['elapsed_s']}s)")

            results.append({
                "suite": suite,
                "index": idx,
                "instruction": instruction,
                "canvas": [w, h],
                "gt_bbox": list(bbox),
                "gt_center": [cx, cy],
                "arm_a": {
                    "point": list(res_a["point"]) if res_a["point"] else None,
                    "hit": ev_a.hit if ev_a else False,
                    "dist_px": round(ev_a.euclidean_distance_px, 1) if ev_a else None,
                    "elapsed_s": res_a["elapsed_s"],
                    "tokens": res_a["tokens"]
                },
                "arm_b": {
                    "point": list(res_b["point"]) if res_b["point"] else None,
                    "hit": ev_b.hit if ev_b else False,
                    "dist_px": round(ev_b.euclidean_distance_px, 1) if ev_b else None,
                    "refined": res_b.get("refined", False),
                    "fallback_used": res_b.get("fallback_used", False),
                    "crop_box": list(res_b.get("crop_box", [])) if res_b.get("crop_box") else None,
                    "elapsed_s": res_b["elapsed_s"],
                    "tokens": res_b["tokens"]
                }
            })

    out_file = ROOT / "experiments" / "additive_spatial_results.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nSaved live results to:", out_file)


if __name__ == "__main__":
    run_benchmark()

