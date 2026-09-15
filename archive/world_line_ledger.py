"""Epistemic World-Line Ledger for Temporal Video Reasoning.

Maintains an immutable ledger of entity identities, spatio-temporal trajectories,
and state predicates across video intervals. Enables active evaporation of dense
raw video frames from LLM working memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EntityInterval:
    interval_id: str
    entity_id: str
    label: str
    t_start: float
    t_end: float
    state_predicate: str  # e.g., "at_rest", "in_motion", "in_contact_with(E_01)"
    start_coords: Tuple[float, float]  # (x, y) normalized or pixel
    end_coords: Tuple[float, float]
    provenance_frames: List[int] = field(default_factory=list)
    confidence: float = 1.0


class WorldLineLedger:
    """Manages verified entity world lines and state transitions over time."""

    def __init__(self):
        self.intervals: List[EntityInterval] = []
        self.evaporated_frame_ranges: List[Tuple[int, int]] = []

    def record_interval(
        self,
        entity_id: str,
        label: str,
        t_start: float,
        t_end: float,
        state_predicate: str,
        start_coords: Tuple[float, float],
        end_coords: Tuple[float, float],
        provenance_frames: Optional[List[int]] = None,
        confidence: float = 1.0
    ) -> EntityInterval:
        int_id = f"wl_{len(self.intervals) + 1:03d}"
        item = EntityInterval(
            interval_id=int_id,
            entity_id=entity_id.strip(),
            label=label.strip(),
            t_start=round(t_start, 2),
            t_end=round(t_end, 2),
            state_predicate=state_predicate.strip(),
            start_coords=(round(start_coords[0], 2), round(start_coords[1], 2)),
            end_coords=(round(end_coords[0], 2), round(end_coords[1], 2)),
            provenance_frames=provenance_frames or [],
            confidence=confidence
        )
        self.intervals.append(item)
        return item

    def mark_frames_evaporated(self, start_frame: int, end_frame: int):
        """Record that raw frame sequence has been distilled into the ledger."""
        self.evaporated_frame_ranges.append((start_frame, end_frame))

    def render_ledger_view(self) -> str:
        """Render high-density working memory table of verified entity world-lines."""
        if not self.intervals:
            return "=== WORLD-LINE LEDGER: (No intervals recorded yet) ==="

        lines = [
            f"=== WORLD-LINE LEDGER ({len(self.intervals)} intervals recorded) ===",
            "| ID | Entity | Time Interval [s] | State Predicate | Start Coords | End Coords | Provenance |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ]

        for i in self.intervals:
            lines.append(
                f"| `{i.interval_id}` | **{i.label}** (`{i.entity_id}`) | `{i.t_start}s - {i.t_end}s` | "
                f"`{i.state_predicate}` | `{i.start_coords}` | `{i.end_coords}` | "
                f"`frames: {i.provenance_frames}` |"
            )

        if self.evaporated_frame_ranges:
            lines.append("\nEvaporated Frame Ranges (Raw images discarded from working memory):")
            for s, e in self.evaporated_frame_ranges:
                lines.append(f"  - Frames [{s} -> {e}]")

        lines.append("=== END WORLD-LINE LEDGER ===")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "intervals": [asdict(i) for i in self.intervals],
            "evaporated_frame_ranges": self.evaporated_frame_ranges
        }, indent=2)
