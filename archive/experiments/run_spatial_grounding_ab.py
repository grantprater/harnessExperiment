"""Controlled A/B on ScreenSpot-Pro: direct grounding vs Reticle two-scale foveation, reworded prompts.

Both arms ask every model call for named, normalized coordinates ({"x": 0-1000, "y": 0-1000}
with each edge defined in words), reject out-of-range answers instead of clicking them, and
log the raw reply from every stage.

- A_direct: one call on the full screenshot.
- B_reticle: original harness geometry (512x512 overview -> 800x600 native-resolution crop),
  with the coarse answer projected via normalized coordinates.
"""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.cognitive.llm_client import LLMClient
import spatial_loader as sl
import spatial_verifier as sv

LLMClient._load_dotenv_if_present()
BASE_URL = "https://openrouter.ai/api/v1"
MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
API_KEY = os.getenv("OPENROUTER_API_KEY")
if not API_KEY:
    sys.exit("OPENROUTER_API_KEY missing from .env")
OUT = ROOT / "experiments" / "spatial_grounding_reworded_results.json"
THUMB = 512
CROP_W, CROP_H = 800, 600

PROMPT = """{context}
Task: {instruction}
Find the UI element to click for this task and give the coordinates of its center, normalized to this image:
x: 0 = left edge, 1000 = right edge
y: 0 = top edge, 1000 = bottom edge
Example: an element in the exact middle of the image is {{"x": 500, "y": 500}}.
Reply with ONLY the JSON object {{"x": <0-1000>, "y": <0-1000>}}."""


def select_tasks(per_suite: int = 0):
    """Original eval's 3 index-0 tasks, plus `per_suite` extra sub-30px targets per suite."""
    tasks = []
    for suite in ["android_studio_macos", "excel_macos", "blender_windows"]:
        ann = sl.fetch_task_annotations(suite)
        tasks.append((suite, 0))
        picked = 0
        for i, it in enumerate(ann):
            if picked >= per_suite:
                break
            b = it["bbox"]
            if i != 0 and max(b[2] - b[0], b[3] - b[1]) < 30:
                tasks.append((suite, i))
                picked += 1
    return tasks


def parse_xy(text: str):
    """Return ((x, y), None) normalized 0-1000, or (None, reason)."""
    num = r"(-?\d+(?:\.\d+)?)"
    mx = re.search(r"[\"']?\bx[\"']?\s*[:=]\s*" + num, text)
    my = re.search(r"[\"']?\by[\"']?\s*[:=]\s*" + num, text)
    if not (mx and my):
        return None, "unparseable"
    x, y = float(mx.group(1)), float(my.group(1))
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None, f"out_of_range ({x:g}, {y:g})"
    return (x, y), None


def ask_xy(client: LLMClient, img: Image.Image, instruction: str, context: str):
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    msg = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT.format(context=context, instruction=instruction)},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}]
    res = client.chat_completion(msg)
    xy, reason = parse_xy(res["content"])
    stage = {"raw": res["content"][:300], "normalized_xy": list(xy) if xy else None, "rejected": reason}
    return xy, res["usage"]["total_tokens"], stage


def run_a_direct(client, full: Image.Image, w, h, instruction):
    xy, tok, stage = ask_xy(client, full, instruction, "This is a full desktop screenshot.")
    pt = (xy[0] / 1000 * w, xy[1] / 1000 * h) if xy else None
    return pt, tok, {"direct": stage}


def run_b_reticle(client, full: Image.Image, w, h, instruction):
    thumb = full.resize((THUMB, THUMB), Image.Resampling.BILINEAR)
    xy, tok1, coarse = ask_xy(client, thumb, instruction,
                              "This is a shrunken overview of a full desktop screenshot. The element may be too "
                              "small to see clearly; give your best estimate of where it is.")
    log = {"coarse": coarse}
    if not xy:
        return None, tok1, log
    gx, gy = xy[0] / 1000 * w, xy[1] / 1000 * h
    cw, ch = min(CROP_W, w), min(CROP_H, h)
    x1 = int(max(0, min(w - cw, gx - cw / 2)))
    y1 = int(max(0, min(h - ch, gy - ch / 2)))
    log["coarse_global"] = [round(gx), round(gy)]
    log["crop_bbox"] = [x1, y1, x1 + cw, y1 + ch]
    xy2, tok2, fine = ask_xy(client, full.crop((x1, y1, x1 + cw, y1 + ch)), instruction,
                             "This is a zoomed-in, full-resolution crop of part of a desktop screenshot.")
    log["fine"] = fine
    pt = (x1 + xy2[0] / 1000 * cw, y1 + xy2[1] / 1000 * ch) if xy2 else None
    return pt, tok1 + tok2, log


ARMS = {"A_direct": run_a_direct, "B_reticle": run_b_reticle}


def run_one(task, arm):
    suite, idx = task
    s = sl.load_spatial_sample(suite, idx)
    w, h = s["canvas_size"]
    bbox = tuple(s["ground_truth_bbox"])
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    rec = {"suite": suite, "index": idx, "arm": arm, "model": MODEL, "canvas": [w, h], "bbox": list(bbox),
           "instruction": s["instruction"]}
    client = LLMClient(api_key=API_KEY, base_url=BASE_URL, model=MODEL)
    try:
        with Image.open(s["local_img_path"]) as im:
            full = im.convert("RGB")
        t0 = time.time()
        pt, tok, log = ARMS[arm](client, full, w, h, s["instruction"])
        rec.update(time_s=round(time.time() - t0, 1), tokens=tok, stages=log)
        if "crop_bbox" in log:
            c = log["crop_bbox"]
            rec["target_in_crop"] = c[0] <= cx <= c[2] and c[1] <= cy <= c[3]
        if pt is None:
            rec.update(point=None, hit=False, dist_px=None)
        else:
            ev = sv.evaluate_grounding(pt, bbox, (w, h))
            rec.update(point=[round(pt[0], 1), round(pt[1], 1)], hit=ev.hit, dist_px=ev.euclidean_distance_px)
    except Exception as e:
        rec.update(error=repr(e)[:300])
    return rec


def main():
    tasks = select_tasks()
    jobs = [(t, a) for t in tasks for a in ARMS]
    print(f"{len(tasks)} tasks x {len(ARMS)} arms on {MODEL}", flush=True)
    results = []
    for job in jobs:  # sequential: free-tier rate limits
        rec = run_one(*job)
        results.append(rec)
        if "error" in rec:
            status = f"ERR {rec['error']}"
        elif rec["point"] is None:
            status = "REJECTED " + "; ".join(f"{k}: {v['rejected']}" for k, v in rec["stages"].items()
                                             if isinstance(v, dict) and v.get("rejected"))
        else:
            status = f"{'HIT ' if rec['hit'] else 'miss'} {rec['dist_px']:.0f}px"
        if "target_in_crop" in rec:
            status += f" | target in crop: {rec['target_in_crop']}"
        print(f"{rec['arm']:9s} {rec['suite']:22s} #{rec['index']:<3d} {status}", flush=True)
        for name, st in rec.get("stages", {}).items():
            if isinstance(st, dict):
                print(f"            {name:6s} raw: {st['raw']!r}", flush=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for arm in ARMS:
        rs = [r for r in results if r["arm"] == arm]
        ok = [r for r in rs if "error" not in r]
        hits = sum(r["hit"] for r in ok)
        dists = [r["dist_px"] for r in ok if r["dist_px"] is not None]
        med = f"{statistics.median(dists):.0f}px" if dists else "n/a"
        rejected = sum(r["point"] is None for r in ok)
        print(f"  {arm:9s} {hits}/{len(ok)} hits  median dist {med}  rejected {rejected}  errors {len(rs) - len(ok)}")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
