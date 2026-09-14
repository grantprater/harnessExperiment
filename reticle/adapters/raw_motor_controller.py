"""Low-Level Raw Motor Controller (Mouse & Keyboard Actuation Primitives).

Implements pure physical interaction primitives:
- mouse_move(dx, dy), set_look(yaw, pitch)
- mouse_down(button), mouse_up(button)
- key_down(key), key_up(key)
- wait_ticks(n)

Eliminates high-level oracle abstractions (like bot.dig() or bot.craft()) so that
all behaviors (mining, walking, jumping, attacking) must be synthesized as emergent
procedural motor skills running at 20-60Hz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from reticle.adapters.minecraft_adapter import (
    SimulatedMinecraftEnvironment,
    VoxelBlock,
    CANONICAL_BLOCKS,
    TOOL_TIERS
)


@dataclass
class RawMotorState:
    yaw: float = 0.0      # Horizontal rotation in degrees [-180, 180]
    pitch: float = 0.0    # Vertical tilt in degrees [-90 (up), 90 (down)]
    mouse_buttons_held: Set[str] = field(default_factory=set)  # {"left", "right"}
    keys_held: Set[str] = field(default_factory=set)           # {"w", "a", "s", "d", "space", "shift"}
    active_dig_target: Optional[Tuple[int, int, int]] = None
    accumulated_dig_ticks: int = 0


class RawMotorController:
    """Controls player embodiment strictly via mouse movement, clicks, and keystrokes."""

    def __init__(self, env: SimulatedMinecraftEnvironment, reach_distance: float = 4.5):
        self.env = env
        self.reach_distance = reach_distance
        self.state = RawMotorState()
        self.action_history: List[Dict[str, Any]] = []

    def mouse_move(self, dx: float, dy: float, sensitivity: float = 0.15):
        """Relative mouse movement adjusting yaw (horizontal) and pitch (vertical)."""
        self.state.yaw = (self.state.yaw + dx * sensitivity) % 360.0
        if self.state.yaw > 180.0:
            self.state.yaw -= 360.0
        self.state.pitch = max(-90.0, min(90.0, self.state.pitch + dy * sensitivity))
        self.action_history.append({"type": "mouse_move", "dx": dx, "dy": dy, "yaw": self.state.yaw, "pitch": self.state.pitch})

    def set_look(self, yaw: float, pitch: float):
        """Absolute look orientation."""
        self.state.yaw = max(-180.0, min(180.0, yaw))
        self.state.pitch = max(-90.0, min(90.0, pitch))
        self.action_history.append({"type": "set_look", "yaw": self.state.yaw, "pitch": self.state.pitch})

    def mouse_down(self, button: str = "left"):
        """Press down a mouse button ('left' for attack/mine, 'right' for place/use)."""
        self.state.mouse_buttons_held.add(button.lower())
        self.action_history.append({"type": "mouse_down", "button": button})

    def mouse_up(self, button: str = "left"):
        """Release a mouse button."""
        b = button.lower()
        if b in self.state.mouse_buttons_held:
            self.state.mouse_buttons_held.remove(b)
        if b == "left":
            # Reset digging progression
            self.state.active_dig_target = None
            self.state.accumulated_dig_ticks = 0
        self.action_history.append({"type": "mouse_up", "button": button})

    def key_down(self, key: str):
        """Press down a key ('w', 's', 'a', 'd', 'space', 'shift', 'e', '1'..'9')."""
        k = key.lower()
        self.state.keys_held.add(k)
        self.action_history.append({"type": "key_down", "key": k})

    def key_up(self, key: str):
        """Release a key."""
        k = key.lower()
        if k in self.state.keys_held:
            self.state.keys_held.remove(k)
        self.action_history.append({"type": "key_up", "key": k})

    def release_all(self):
        """Release every held input, including after cancellation or errors."""
        for button in tuple(self.state.mouse_buttons_held):
            self.mouse_up(button)
        for key in tuple(self.state.keys_held):
            self.key_up(key)

    def raycast_crosshair(self) -> Tuple[Optional[Tuple[int, int, int]], Optional[VoxelBlock], float]:
        """Calculates exact 3D voxel intersection from camera position along (yaw, pitch) ray."""
        px, py, pz = self.env.player_pos
        eye_pos = (px, py + 1.62, pz)  # Minecraft eye height

        # Direction vector from yaw (deg) and pitch (deg)
        yaw_rad = math.radians(self.state.yaw)
        pitch_rad = math.radians(self.state.pitch)
        dx = -math.sin(yaw_rad) * math.cos(pitch_rad)
        dy = -math.sin(pitch_rad)
        dz = math.cos(yaw_rad) * math.cos(pitch_rad)

        # Step along ray
        step_size = 0.05
        max_steps = int(self.reach_distance / step_size)

        for step in range(1, max_steps + 1):
            dist = step * step_size
            curr_x = int(math.floor(eye_pos[0] + dx * dist))
            curr_y = int(math.floor(eye_pos[1] + dy * dist))
            curr_z = int(math.floor(eye_pos[2] + dz * dist))

            block = self.env.get_block(curr_x, curr_y, curr_z)
            if block.name != "air":
                return (curr_x, curr_y, curr_z), block, dist

        return None, None, self.reach_distance

    def tick(self, count: int = 1) -> Dict[str, Any]:
        """Advances physics ticks while processing currently held mouse buttons and keys."""
        broken_blocks = []
        for _ in range(count):
            self.env.total_ticks += 1

            # 1. Process continuous key movement
            px, py, pz = self.env.player_pos
            yaw_rad = math.radians(self.state.yaw)
            speed = 0.215  # Normal walking speed in blocks per tick

            moved_x, moved_z = 0.0, 0.0
            if "w" in self.state.keys_held:
                moved_x += -math.sin(yaw_rad) * speed
                moved_z += math.cos(yaw_rad) * speed
            if "s" in self.state.keys_held:
                moved_x += math.sin(yaw_rad) * speed
                moved_z += -math.cos(yaw_rad) * speed
            if "a" in self.state.keys_held:
                moved_x += -math.cos(yaw_rad) * speed
                moved_z += -math.sin(yaw_rad) * speed
            if "d" in self.state.keys_held:
                moved_x += math.cos(yaw_rad) * speed
                moved_z += math.sin(yaw_rad) * speed

            self.env.player_pos = (px + moved_x, py, pz + moved_z)

            # 2. Process continuous left mouse button (Mining / Attacking)
            if "left" in self.state.mouse_buttons_held:
                target_pos, target_block, dist = self.raycast_crosshair()
                if target_pos and target_block and target_block.name != "air":
                    if self.state.active_dig_target != target_pos:
                        # Switched focus to a new block
                        self.state.active_dig_target = target_pos
                        self.state.accumulated_dig_ticks = 0

                    self.state.accumulated_dig_ticks += 1

                    # Check required ticks to break
                    tool_type, tool_tier = None, 0
                    if self.env.equipped_tool and self.env.equipped_tool in TOOL_TIERS:
                        tool_type, tool_tier, _ = TOOL_TIERS[self.env.equipped_tool]

                    can_harvest = True
                    if target_block.required_tool_type is not None:
                        if tool_type != target_block.required_tool_type or tool_tier < target_block.min_tool_tier:
                            can_harvest = False

                    speed_mult = 1.0 + (tool_tier * 2.0 if (tool_tier > 0 and can_harvest) else 0.0)
                    required_ticks = max(1, int((target_block.hardness * (1.5 if can_harvest else 5.0) / speed_mult) * 20))

                    if self.state.accumulated_dig_ticks >= required_ticks:
                        # Voxel fully broken!
                        dig_res = self.env.dig_block(*target_pos)
                        broken_blocks.append(dig_res)
                        self.state.active_dig_target = None
                        self.state.accumulated_dig_ticks = 0
                else:
                    self.state.active_dig_target = None
                    self.state.accumulated_dig_ticks = 0

        return {
            "ticks_advanced": count,
            "player_pos": self.env.player_pos,
            "broken_blocks": broken_blocks,
            "dig_progress": self.state.accumulated_dig_ticks
        }
