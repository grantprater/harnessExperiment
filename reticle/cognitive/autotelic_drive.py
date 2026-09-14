"""Autotelic Drive Engine & Affordance-Gated Memory Index.

Implements intrinsic motivation and self-directed goal generation:
1. Homeostatic Drive (Vitality & Daylight/Nightfall Threat)
2. Empowerment Drive (Causal Horizon & Tool Unlocking Potential)
3. Curiosity Drive (Decaying Spatial/Voxel Novelty)
4. Affordance-Gated Memory Indexing (Sparse, context-safe retrieval <30 tokens)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


@dataclass
class HomeostaticMetrics:
    health_ratio: Optional[float] # None means unavailable
    daylight_factor: float        # 1.0 = high noon, 0.3 = dusk, 0.0 = midnight
    urgency_score: float          # 0.0 (safe/calm) to 1.0 (critical threat)
    status_summary: str           # e.g. "CALM (Full health, midday)" or "URGENT (Dusk approaching)"


@dataclass
class EmpowermentMetrics:
    current_verbs: List[str]      # e.g. ["punch_soft_blocks", "walk", "jump"]
    unlockable_verbs: List[str]   # e.g. ["craft_planks", "craft_table", "craft_pickaxe"]
    empowerment_gap: float        # Higher gap = greater internal pressure to synthesize tools
    status_summary: str           # e.g. "EXPANSION_READY (Holding log; 3 recipes unlockable)"


@dataclass
class CuriosityMetrics:
    bearing_familiarity: Dict[int, float]  # bearing -> [0.0 (unexplored) .. 1.0 (satiated)]
    frontier_bearing: int                  # Bearing with highest residual curiosity
    highest_novelty: float                 # Peak curiosity value
    status_summary: str


@dataclass
class InternalDriveState:
    homeostasis: HomeostaticMetrics
    empowerment: EmpowermentMetrics
    curiosity: CuriosityMetrics
    dominant_drive: str                    # "HOMEOSTASIS" | "EMPOWERMENT" | "CURIOSITY"
    relevant_memories: List[str]


class AffordanceGatedMemoryIndex:
    """Sparse memory store that indexes crystallized invariants by sensory affordance tags."""

    def __init__(self, storage_path: str | Path = "crystallized_beliefs.jsonl"):
        self.storage_path = Path(storage_path)
        self.beliefs: List[Dict[str, Any]] = []
        self._load_or_seed_defaults()

    def _load_or_seed_defaults(self):
        if self.storage_path.exists():
            with open(self.storage_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        self.beliefs.append(json.loads(line))
        else:
            # Seed core foundational invariants discovered through prior play
            seeds = [
                {
                    "tags": ["acacia_log", "wood", "log"],
                    "text": "1 Wood log can be crafted into 4 planks in personal 2x2 grid without a table."
                },
                {
                    "tags": ["wood_planks", "planks"],
                    "text": "4 Planks craft 1 Crafting Table; 2 Planks craft 4 Sticks."
                },
                {
                    "tags": ["crafting_table", "table"],
                    "text": "A Crafting Table unlocks 3x3 synthesis of wooden pickaxes, axes, and swords."
                },
                {
                    "tags": ["nightfall", "dusk", "threat"],
                    "text": "Night darkness spawns hostile skeletons and creepers; an enclosed shelter protects health."
                },
                {
                    "tags": ["stone", "pickaxe"],
                    "text": "Stone requires a wooden pickaxe to harvest; punching stone with bare hands yields no drops."
                }
            ]
            self.beliefs = seeds
            self.save()

    def save(self):
        with open(self.storage_path, "w", encoding="utf-8") as f:
            for b in self.beliefs:
                f.write(json.dumps(b) + "\n")

    def add_belief(self, tags: List[str], text: str):
        self.beliefs.append({"tags": tags, "text": text})
        self.save()

    def query(self, active_tags: Set[str], max_results: int = 2) -> List[str]:
        """Returns at most max_results matching crystallized beliefs (<30 tokens total)."""
        scored = []
        for b in self.beliefs:
            overlap = len(active_tags.intersection(set(b.get("tags", []))))
            if overlap > 0:
                scored.append((overlap, b["text"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in scored[:max_results]]


class AutotelicDriveEngine:
    """Calculates internal pressures (Homeostasis, Empowerment, Curiosity) and arbitrates goals."""

    def __init__(self, memory_index: Optional[AffordanceGatedMemoryIndex] = None):
        self.memory = memory_index or AffordanceGatedMemoryIndex()
        self.bearing_visits: Dict[int, float] = {0: 0.2, 45: 0.1, 90: 0.5, 135: 0.1, 180: 0.1, 225: 0.0, 270: 0.0, 315: 0.1}

    def evaluate_homeostasis(self, frame_bgr: np.ndarray, health_hearts: Optional[float] = None,
                             sheltered: Optional[bool] = None) -> HomeostaticMetrics:
        """Estimates daylight from sky luminance and combines with health to assess threat."""
        # Top 15% of frame represents the sky
        h, w = frame_bgr.shape[:2]
        sky_patch = frame_bgr[:int(h * 0.15), :]
        # Sky luminance (gray scale mean)
        gray_sky = cv2.cvtColor(sky_patch, cv2.COLOR_BGR2GRAY) if HAS_CV2 else np.mean(sky_patch)
        sky_luminance = float(np.mean(gray_sky))

        # Daylight scale: 180+ is clear day (1.0), 120 is dusk (0.5), <50 is night (0.1)
        daylight = max(0.05, min(1.0, (sky_luminance - 30.0) / 160.0))
        # Unknown health is represented as neutral evidence, never as full health.
        health_ratio = None if health_hearts is None else max(0.0, min(1.0, health_hearts / 20.0))

        # Threat urgency spikes as daylight drops or health drops
        exposure = (1.0 - daylight) * 0.65
        if sheltered is True:
            exposure *= 0.2
        elif sheltered is False:
            exposure = min(1.0, exposure + 0.1 * (1.0 - daylight))
        # Shelter cannot suppress an observed health emergency.
        urgency = max(exposure, 1.0 - health_ratio if health_ratio is not None else 0.0)

        if urgency > 0.6:
            summary = f"CRITICAL_URGENCY (Daylight={daylight:.2f}, Health={health_hearts if health_hearts is not None else 'unknown'}/20)"
        elif urgency > 0.35:
            summary = f"MODERATE_URGENCY (Brightness proxy={daylight:.2f}, Health={health_hearts})"
        else:
            summary = f"LOW_OBSERVED_URGENCY (Brightness proxy={daylight:.2f}, Health={health_hearts if health_hearts is not None else 'unknown'}, Shelter={sheltered})"

        return HomeostaticMetrics(
            health_ratio=health_ratio,
            daylight_factor=round(daylight, 2),
            urgency_score=round(urgency, 2),
            status_summary=summary
        )

    def evaluate_empowerment(self, inventory_items: Dict[str, int]) -> EmpowermentMetrics:
        """Measures the gap between current action verbs and accessible unlockable verbs."""
        current_verbs = ["punch_soft_blocks", "walk", "jump"]
        unlockable_verbs = []

        has_wood = any(k.endswith(("_log", "_wood", "_stem", "_hyphae")) and v > 0 for k, v in inventory_items.items())
        has_planks = any("plank" in k and v > 0 for k, v in inventory_items.items())
        has_table = inventory_items.get("crafting_table", 0) > 0
        has_pickaxe = any(k.endswith("_pickaxe") and v > 0 for k, v in inventory_items.items())

        if has_wood and not has_planks:
            unlockable_verbs.extend(["craft_planks", "craft_crafting_table", "craft_sticks"])
        if has_planks and not has_table:
            unlockable_verbs.append("craft_crafting_table")
            unlockable_verbs.append("craft_sticks")
        if has_table and not has_pickaxe:
            unlockable_verbs.append("craft_wooden_pickaxe")
        if has_pickaxe:
            current_verbs.append("mine_stone")

        # Gap is proportional to unlockable verbs
        gap = len(unlockable_verbs) / 4.0
        if gap > 0:
            summary = f"EXPANSION_READY ({len(unlockable_verbs)} new capabilities waiting to be synthesized)"
        else:
            summary = f"STABLE ({len(current_verbs)} active capabilities)"

        return EmpowermentMetrics(
            current_verbs=current_verbs,
            unlockable_verbs=unlockable_verbs,
            empowerment_gap=round(gap, 2),
            status_summary=summary
        )

    def evaluate_curiosity(self, current_facing_yaw: float) -> CuriosityMetrics:
        """Evaluates residual curiosity across the spatial frontier with decaying familiarity."""
        best_bearing = 0
        highest_novelty = 0.0

        for bearing, familiarity in self.bearing_visits.items():
            novelty = 1.0 - familiarity
            if novelty > highest_novelty:
                highest_novelty = novelty
                best_bearing = bearing

        summary = f"FRONTIER_ACTIVE (Highest novelty at {best_bearing}°: {highest_novelty:.2f})"
        return CuriosityMetrics(
            bearing_familiarity={k: round(v, 2) for k, v in self.bearing_visits.items()},
            frontier_bearing=best_bearing,
            highest_novelty=round(highest_novelty, 2),
            status_summary=summary
        )

    def mark_bearing_visited(self, yaw: float, weight: float = 0.3):
        """Decays curiosity along visited bearings."""
        closest_bearing = int(round(yaw / 45.0) * 45) % 360
        self.bearing_visits[closest_bearing] = min(1.0, self.bearing_visits.get(closest_bearing, 0.0) + weight)

    def arbitrate_drives(
        self,
        frame_bgr: np.ndarray,
        inventory_items: Dict[str, int],
        current_facing_yaw: float,
        health_hearts: Optional[float] = None,
        sheltered: Optional[bool] = None,
        foveal_tags: Optional[Set[str]] = None
    ) -> InternalDriveState:
        """Arbitrates between Homeostasis, Empowerment, and Curiosity and queries sparse memory."""
        homeo = self.evaluate_homeostasis(frame_bgr, health_hearts, sheltered)
        empower = self.evaluate_empowerment(inventory_items)
        curiosity = self.evaluate_curiosity(current_facing_yaw)

        # Arbitration logic:
        # 1. If physical threat / nightfall is high (>0.45), Homeostasis takes absolute precedence.
        # 2. Else if empowerment gap is high (>0.4) and we have uncrafted raw matter, Empowerment takes precedence.
        # 3. Else Curiosity drives exploration toward the spatial frontier.
        if homeo.urgency_score >= 0.45:
            dominant = "HOMEOSTASIS"
        elif empower.empowerment_gap > 0:
            dominant = "EMPOWERMENT"
        else:
            dominant = "CURIOSITY"

        # Query memory index with active tags
        active_tags = set(foveal_tags or [])
        if any("log" in k or "wood" in k for k in inventory_items.keys()):
            active_tags.add("acacia_log")
            active_tags.add("wood")
        if any("planks" in k for k in inventory_items.keys()):
            active_tags.add("wood_planks")
            active_tags.add("planks")
        if "crafting_table" in inventory_items:
            active_tags.add("crafting_table")
            active_tags.add("table")
        if homeo.urgency_score > 0.35:
            active_tags.add("nightfall")
            active_tags.add("threat")

        memories = self.memory.query(active_tags, max_results=2)

        return InternalDriveState(
            homeostasis=homeo,
            empowerment=empower,
            curiosity=curiosity,
            dominant_drive=dominant,
            relevant_memories=memories
        )
