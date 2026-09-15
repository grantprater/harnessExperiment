"""Spatial Perception and Multi-Scale Visual Saccade Engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from PIL import Image


@dataclass
class SpatialSector:
    sector_id: str
    name: str
    row: int
    col: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    normalized_bbox: Tuple[float, float, float, float]  # (nx1, ny1, nx2, ny2) in [0.0, 1.0]

    def contains_point(self, x: float, y: float) -> bool:
        return self.bbox[0] <= x <= self.bbox[2] and self.bbox[1] <= y <= self.bbox[3]

    def contains_bbox(self, target_bbox: Tuple[int, int, int, int]) -> bool:
        """Returns True if target center falls inside this sector."""
        cx = (target_bbox[0] + target_bbox[2]) / 2.0
        cy = (target_bbox[1] + target_bbox[3]) / 2.0
        return self.contains_point(cx, cy)


def create_spatial_grid(
    canvas_width: int,
    canvas_height: int,
    rows: int = 3,
    cols: int = 3,
    overlap_ratio: float = 0.05
) -> List[SpatialSector]:
    """Partition canvas into a hierarchical spatial grid with boundary overlap."""
    sectors = []
    cell_w = canvas_width / cols
    cell_h = canvas_height / rows
    overlap_x = int(cell_w * overlap_ratio)
    overlap_y = int(cell_h * overlap_ratio)

    name_map_3x3 = {
        (0, 0): "Top-Left (Toolbar / Menu)",
        (0, 1): "Top-Center (Main Toolbar / Tabs)",
        (0, 2): "Top-Right (Controls / Status)",
        (1, 0): "Middle-Left (Project Tree / Sidebar)",
        (1, 1): "Center (Active Workspace / Viewport)",
        (1, 2): "Middle-Right (Properties / Inspector)",
        (2, 0): "Bottom-Left (Terminal / Logs)",
        (2, 1): "Bottom-Center (Console / Timeline)",
        (2, 2): "Bottom-Right (Status Bar / Controls)"
    }

    for r in range(rows):
        for c in range(cols):
            x1 = max(0, int(c * cell_w) - overlap_x)
            y1 = max(0, int(r * cell_h) - overlap_y)
            x2 = min(canvas_width, int((c + 1) * cell_w) + overlap_x)
            y2 = min(canvas_height, int((r + 1) * cell_h) + overlap_y)

            nx1 = round(x1 / canvas_width, 3)
            ny1 = round(y1 / canvas_height, 3)
            nx2 = round(x2 / canvas_width, 3)
            ny2 = round(y2 / canvas_height, 3)

            sid = f"S_{r}_{c}"
            name = name_map_3x3.get((r, c), f"Sector [{r},{c}]")

            sectors.append(SpatialSector(
                sector_id=sid,
                name=name,
                row=r,
                col=c,
                bbox=(x1, y1, x2, y2),
                normalized_bbox=(nx1, ny1, nx2, ny2)
            ))

    return sectors


def render_spatial_map(
    sectors: List[SpatialSector],
    canvas_size: Tuple[int, int]
) -> str:
    """Render a high-density, low-token text representation of the spatial layout."""
    w, h = canvas_size
    lines = [
        f"=== Canvas Spatial Topology ({w}x{h}) ===",
        "| Sector ID | Name | Pixel Bounding Box [x1, y1, x2, y2] | Normalized [0.0-1.0] |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for s in sectors:
        lines.append(
            f"| `{s.sector_id}` | **{s.name}** | `[{s.bbox[0]}, {s.bbox[1]}, {s.bbox[2]}, {s.bbox[3]}]` | "
            f"`[{s.normalized_bbox[0]:.2f}, {s.normalized_bbox[1]:.2f}, {s.normalized_bbox[2]:.2f}, {s.normalized_bbox[3]:.2f}]` |"
        )
    lines.append("=== End Spatial Map ===")
    return "\n".join(lines)


def foveated_crop(
    image_source: Union[str, Path, Image.Image],
    crop_bbox: Tuple[int, int, int, int],
    out_path: Optional[Union[str, Path]] = None
) -> Image.Image:
    """Extract a full-resolution pixel sub-patch without downsampling distortion."""
    if isinstance(image_source, (str, Path)):
        img = Image.open(image_source)
    else:
        img = image_source

    x1, y1, x2, y2 = crop_bbox
    cropped = img.crop((x1, y1, x2, y2))

    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out)

    return cropped


def project_to_global(
    local_point: Tuple[float, float],
    sector_bbox: Tuple[int, int, int, int]
) -> Tuple[float, float]:
    """Translate local crop coordinates back to global canvas coordinates."""
    lx, ly = local_point
    x1, y1, _, _ = sector_bbox
    return (round(x1 + lx, 2), round(y1 + ly, 2))


def project_to_local(
    global_point: Tuple[float, float],
    sector_bbox: Tuple[int, int, int, int]
) -> Tuple[float, float]:
    """Translate global canvas coordinates into local crop coordinates."""
    gx, gy = global_point
    x1, y1, _, _ = sector_bbox
    return (round(gx - x1, 2), round(gy - y1, 2))


def generate_overview_thumbnail(
    image_source: Union[str, Path, Image.Image],
    max_dim: int = 512,
    out_path: Optional[Union[str, Path]] = None
) -> Tuple[Image.Image, float]:
    """Downsample large image to a coarse thumbnail for visual saccade routing."""
    if isinstance(image_source, (str, Path)):
        img = Image.open(image_source)
    else:
        img = image_source

    orig_w, orig_h = img.size
    scale = min(max_dim / orig_w, max_dim / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    thumb = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        thumb.save(out_path)
    return thumb, scale
