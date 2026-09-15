"""OCR-augmented grounding A/B on ScreenSpot-Pro sub-30px targets.

Both arms send the unmodified full screenshot with the same normalized-coordinate prompt
as run_spatial_grounding_ab.py. The OCR arm only adds a list of locally OCR'd text snippets
(RapidOCR on the native-resolution image) with positions in the same 0-1000 coordinates.

- A_direct: screenshot + prompt.
- B_ocr:    screenshot + OCR list + prompt.

Run from experiments/ so the OpenRouter key in experiments/.env is picked up.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from PIL import Image
from rapidocr import RapidOCR

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from run_spatial_grounding_ab import API_KEY, BASE_URL, MODEL, LLMClient, ask_xy
import spatial_loader as sl
import spatial_verifier as sv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

OUT = ROOT / "experiments" / "spatial_grounding_ocr_results.json"

# 5 text + 5 icon sub-30px targets, all with cached screenshots.
TASKS = [
    ("android_studio_macos", 2), ("excel_macos", 6), ("excel_macos", 61), ("blender_windows", 5), ("blender_windows", 47),
    ("android_studio_macos", 3), ("android_studio_macos", 20), ("excel_macos", 13), ("excel_macos", 63), ("blender_windows", 14),
]

MIN_SCORE = 0.5   # drop low-confidence reads
MAX_CHARS = 60    # drop long body text
MAX_ITEMS = 250   # cap list size, in reading order

BASE_CONTEXT = "This is a full desktop screenshot."
OCR_CONTEXT = """This is a full desktop screenshot.

Text detected on this screenshot by OCR (may contain misreadings), with positions in the same 0-1000 coordinates:
{lines}

Use these as reference points. The element to click may be an icon, field or handle next to a label rather than the text itself."""


def ocr_lines(engine: RapidOCR, img_path: str, w: int, h: int):
    t0 = time.time()
    r = engine(img_path)
    elapsed = time.time() - t0
    items = []
    if r.boxes is not None:
        for box, text, score in zip(r.boxes, r.txts, r.scores):
            text = text.strip()
            if score < MIN_SCORE or not text or len(text) > MAX_CHARS:
                continue
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            items.append((min(ys), min(xs), text,
                          (round(min(xs) / w * 1000), round(max(xs) / w * 1000),
                           round(min(ys) / h * 1000), round(max(ys) / h * 1000))))
    items.sort(key=lambda it: (it[0], it[1]))
    kept = items[:MAX_ITEMS]
    lines = "\n".join(f"[{i}] {json.dumps(text, ensure_ascii=False)} x {b[0]}-{b[1]}, y {b[2]}-{b[3]}"
                      for i, (_, _, text, b) in enumerate(kept))
    stats = {"ocr_raw": len(r.txts or []), "ocr_kept": len(kept), "ocr_chars": len(lines), "ocr_s": round(elapsed, 1)}
    return lines, stats


def run_arm(arm: str, s: dict, full: Image.Image, context: str):
    w, h = s["canvas_size"]
    bbox = tuple(s["ground_truth_bbox"])
    rec = {"arm": arm, "suite": s["suite"], "index": s["index"], "model": MODEL, "bbox": list(bbox)}
    client = LLMClient(api_key=API_KEY, base_url=BASE_URL, model=MODEL)
    try:
        t0 = time.time()
        xy, tokens, stage = ask_xy(client, full, s["instruction"], context)
        rec.update(time_s=round(time.time() - t0, 1), tokens=tokens, stage=stage)
        if xy is None:
            rec.update(point=None, hit=False, dist_px=None)
        else:
            pt = (xy[0] / 1000 * w, xy[1] / 1000 * h)
            ev = sv.evaluate_grounding(pt, bbox, (w, h))
            rec.update(point=[round(pt[0], 1), round(pt[1], 1)], hit=ev.hit, dist_px=ev.euclidean_distance_px)
    except Exception as e:
        rec.update(error=repr(e)[:300])
    return rec


def main():
    engine = RapidOCR()
    print(f"{len(TASKS)} tasks x 2 arms on {MODEL}", flush=True)
    results = []
    for suite, idx in TASKS:
        s = sl.load_spatial_sample(suite, idx)
        ui_type = sl.fetch_task_annotations(suite)[idx]["ui_type"]
        w, h = s["canvas_size"]
        with Image.open(s["local_img_path"]) as im:
            full = im.convert("RGB")
        lines, stats = ocr_lines(engine, s["local_img_path"], w, h)
        print(f"\n{suite} #{idx} [{ui_type}] {s['instruction'][:60]!r} | OCR {stats['ocr_kept']}/{stats['ocr_raw']} "
              f"snippets kept, {stats['ocr_s']}s", flush=True)
        for arm, context in [("A_direct", BASE_CONTEXT), ("B_ocr", OCR_CONTEXT.format(lines=lines))]:
            rec = run_arm(arm, s, full, context)
            rec.update(ui_type=ui_type, instruction=s["instruction"], **(stats if arm == "B_ocr" else {}))
            results.append(rec)
            if "error" in rec:
                status = f"ERR {rec['error']}"
            elif rec["point"] is None:
                status = f"REJECTED {rec['stage']['rejected']}"
            else:
                status = f"{'HIT ' if rec['hit'] else 'miss'} {rec['dist_px']:.0f}px"
            print(f"  {arm:8s} {status} | tokens {rec.get('tokens', '-')} | raw {rec.get('stage', {}).get('raw', '')!r}",
                  flush=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for label, keep in [("all", lambda r: True), ("text targets", lambda r: r["ui_type"] == "text"),
                        ("icon targets", lambda r: r["ui_type"] == "icon")]:
        print(f"[{label}]")
        for arm in ("A_direct", "B_ocr"):
            rs = [r for r in results if r["arm"] == arm and keep(r)]
            ok = [r for r in rs if "error" not in r]
            hits = sum(r["hit"] for r in ok)
            dists = [r["dist_px"] for r in ok if r["dist_px"] is not None]
            med = f"{statistics.median(dists):.0f}px" if dists else "n/a"
            tok = f"{statistics.mean(r['tokens'] for r in ok):.0f}" if ok else "n/a"
            print(f"  {arm:8s} {hits}/{len(ok)} hits  median dist {med}  mean tokens {tok}  errors {len(rs) - len(ok)}")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
