"""Spatial GUI Dataset Loader (ScreenSpot-Pro).

Fetches, parses, and caches real-world high-resolution GUI grounding samples
from the official ScreenSpot-Pro benchmark (ICLR 2025) on Hugging Face.
Supports 4K/retina desktop interfaces (macOS, Windows, Linux).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
from PIL import Image

HF_REPO_BASE = "https://huggingface.co/datasets/likaixin/ScreenSpot-Pro"
CACHE_DIR = Path(__file__).parent / "spatial_cache"


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def fetch_task_annotations(suite_name: str = "android_studio_macos") -> List[Dict[str, Any]]:
    """Fetch task metadata (instructions, bounding boxes) for a specific application suite."""
    cache_file = _ensure_cache_dir() / f"{suite_name}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    url = f"{HF_REPO_BASE}/raw/main/annotations/{suite_name}.json"
    headers = {"User-Agent": "CognitiveSpatialHarness/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read().decode("utf-8")

    data = json.loads(content)
    cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def fetch_screenshot_image(img_filename: str, use_cache: bool = True) -> Path:
    """Download and cache the high-resolution screenshot for a task."""
    clean_name = Path(img_filename).name
    cache_img = _ensure_cache_dir() / clean_name
    if use_cache and cache_img.exists():
        return cache_img

    url = f"{HF_REPO_BASE}/resolve/main/images/{img_filename}"
    headers = {"User-Agent": "CognitiveSpatialHarness/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        img_bytes = resp.read()

    cache_img.write_bytes(img_bytes)
    return cache_img


def load_spatial_sample(suite_name: str = "android_studio_macos", index: int = 0) -> Dict[str, Any]:
    """Load a complete spatial sample including ground truth bounding box and cached image."""
    annotations = fetch_task_annotations(suite_name)
    if index >= len(annotations):
        raise IndexError(f"Index {index} out of bounds for suite '{suite_name}' ({len(annotations)} items).")

    item = annotations[index]
    img_filename = item["img_filename"]
    local_img_path = fetch_screenshot_image(img_filename)

    with Image.open(local_img_path) as img:
        width, height = img.size

    bbox = item["bbox"]  # [x1, y1, x2, y2]
    center_x = (bbox[0] + bbox[2]) / 2.0
    center_y = (bbox[1] + bbox[3]) / 2.0

    return {
        "suite": suite_name,
        "index": index,
        "instruction": item["instruction"],
        "img_filename": img_filename,
        "local_img_path": str(local_img_path),
        "canvas_size": (width, height),
        "ground_truth_bbox": bbox,
        "target_center": (center_x, center_y),
        "data_type": item.get("data_type", "icon/widget")
    }
