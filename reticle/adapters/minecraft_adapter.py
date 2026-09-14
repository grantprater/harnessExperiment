"""Minecraft Adapter and Simulated Voxel Environment for the Reticle Cognitive Harness.

Provides both:
1. SimulatedMinecraftEnvironment: Ultra-fast, deterministic in-memory voxel world
   following canonical Minecraft rules (mining hardness, tool tiers, durability, recipes).
2. MinecraftBotClient: HTTP client communicating with the Mineflayer Node.js sidecar.
3. MinecraftAdapter: Unified abstraction layer for active experimentation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error


@dataclass
class VoxelBlock:
    name: str
    hardness: float
    required_tool_type: Optional[str] = None
    min_tool_tier: int = 0  # 0: Hand, 1: Wood, 2: Stone, 3: Iron, 4: Diamond
    drops_item: Optional[str] = None
    drop_count: int = 1


# Canonical Minecraft block definitions
CANONICAL_BLOCKS: Dict[str, VoxelBlock] = {
    "air": VoxelBlock(name="air", hardness=0.0),
    "dirt": VoxelBlock(name="dirt", hardness=0.5, drops_item="dirt", drop_count=1),
    "oak_log": VoxelBlock(name="oak_log", hardness=2.0, drops_item="oak_log", drop_count=1),
    "stone": VoxelBlock(
        name="stone",
        hardness=1.5,
        required_tool_type="pickaxe",
        min_tool_tier=1,
        drops_item="cobblestone",
        drop_count=1
    ),
    "iron_ore": VoxelBlock(
        name="iron_ore",
        hardness=3.0,
        required_tool_type="pickaxe",
        min_tool_tier=2,
        drops_item="raw_iron",
        drop_count=1
    ),
    "diamond_ore": VoxelBlock(
        name="diamond_ore",
        hardness=3.0,
        required_tool_type="pickaxe",
        min_tool_tier=3,
        drops_item="diamond",
        drop_count=1
    ),
    "crafting_table": VoxelBlock(name="crafting_table", hardness=2.5, drops_item="crafting_table", drop_count=1),
}

# Canonical Tool Tiers
TOOL_TIERS: Dict[str, Tuple[str, int, int]] = {
    # name: (tool_type, tier, max_durability)
    "wooden_pickaxe": ("pickaxe", 1, 59),
    "stone_pickaxe": ("pickaxe", 2, 131),
    "iron_pickaxe": ("pickaxe", 3, 250),
    "diamond_pickaxe": ("pickaxe", 4, 1561),
    "wooden_axe": ("axe", 1, 59),
    "stone_axe": ("axe", 2, 131),
}

# Canonical 2x2 and 3x3 Recipes
CANONICAL_RECIPES: Dict[str, Dict[str, Any]] = {
    "oak_planks": {
        "ingredients": {"oak_log": 1},
        "yields": {"oak_planks": 4},
        "requires_table": False
    },
    "stick": {
        "ingredients": {"oak_planks": 2},
        "yields": {"stick": 4},
        "requires_table": False
    },
    "crafting_table": {
        "ingredients": {"oak_planks": 4},
        "yields": {"crafting_table": 1},
        "requires_table": False
    },
    "wooden_pickaxe": {
        "ingredients": {"oak_planks": 3, "stick": 2},
        "yields": {"wooden_pickaxe": 1},
        "requires_table": True
    },
    "stone_pickaxe": {
        "ingredients": {"cobblestone": 3, "stick": 2},
        "yields": {"stone_pickaxe": 1},
        "requires_table": True
    },
}


class SimulatedMinecraftEnvironment:
    """In-memory deterministic Minecraft world for active experimentation and skill benchmarking."""

    def __init__(self):
        self.voxels: Dict[Tuple[int, int, int], VoxelBlock] = {}
        self.player_pos: Tuple[float, float, float] = (0.0, 64.0, 0.0)
        self.inventory: Dict[str, int] = {}
        self.tool_durability: Dict[str, int] = {}
        self.equipped_tool: Optional[str] = None
        self.health: float = 20.0
        self.total_ticks: int = 0
        self.event_log: List[Dict[str, Any]] = []

    def set_block(self, x: int, y: int, z: int, block_name: str):
        block = CANONICAL_BLOCKS.get(block_name, VoxelBlock(name=block_name, hardness=1.0))
        self.voxels[(x, y, z)] = block

    def get_block(self, x: int, y: int, z: int) -> VoxelBlock:
        return self.voxels.get((x, y, z), CANONICAL_BLOCKS["air"])

    def add_item(self, item_name: str, count: int = 1):
        self.inventory[item_name] = self.inventory.get(item_name, 0) + count
        if item_name in TOOL_TIERS and item_name not in self.tool_durability:
            self.tool_durability[item_name] = TOOL_TIERS[item_name][2]

    def remove_item(self, item_name: str, count: int = 1) -> bool:
        current = self.inventory.get(item_name, 0)
        if current < count:
            return False
        if current == count:
            del self.inventory[item_name]
        else:
            self.inventory[item_name] = current - count
        return True

    def equip(self, item_name: Optional[str]) -> bool:
        if item_name is None:
            self.equipped_tool = None
            return True
        if self.inventory.get(item_name, 0) > 0:
            self.equipped_tool = item_name
            return True
        return False

    def dig_block(self, x: int, y: int, z: int) -> Dict[str, Any]:
        block = self.get_block(x, y, z)
        if block.name == "air":
            return {"success": False, "reason": "block_is_air"}

        # Calculate tool efficiency and tier eligibility
        tool_type, tool_tier = None, 0
        if self.equipped_tool and self.equipped_tool in TOOL_TIERS:
            tool_type, tool_tier, _ = TOOL_TIERS[self.equipped_tool]

        can_harvest = True
        if block.required_tool_type is not None:
            if tool_type != block.required_tool_type or tool_tier < block.min_tool_tier:
                can_harvest = False

        # Compute mining duration ticks
        base_hardness = block.hardness
        if can_harvest:
            speed_mult = 1.0 + (tool_tier * 2.0 if tool_tier > 0 else 0.0)
            duration_ticks = max(1, int((base_hardness * 1.5 / speed_mult) * 20))
        else:
            duration_ticks = max(1, int((base_hardness * 5.0) * 20))

        self.total_ticks += duration_ticks

        # Deplete tool durability if tool used
        if self.equipped_tool and self.equipped_tool in self.tool_durability:
            self.tool_durability[self.equipped_tool] -= 1
            if self.tool_durability[self.equipped_tool] <= 0:
                self.remove_item(self.equipped_tool, 1)
                del self.tool_durability[self.equipped_tool]
                self.equipped_tool = None
                self.event_log.append({"event": "tool_broke", "pos": (x, y, z)})

        # Remove voxel from world
        self.set_block(x, y, z, "air")

        # Yield drops if eligible
        dropped_item, dropped_count = None, 0
        if can_harvest and block.drops_item:
            dropped_item = block.drops_item
            dropped_count = block.drop_count
            self.add_item(dropped_item, dropped_count)

        result = {
            "success": True,
            "broken_block": block.name,
            "duration_ticks": duration_ticks,
            "harvested": can_harvest,
            "dropped_item": dropped_item,
            "dropped_count": dropped_count,
            "pos": (x, y, z)
        }
        self.event_log.append({"event": "block_broken", **result})
        return result

    def craft_recipe(self, recipe_name: str, count: int = 1) -> Dict[str, Any]:
        recipe = CANONICAL_RECIPES.get(recipe_name)
        if not recipe:
            return {"success": False, "reason": f"unknown_recipe: {recipe_name}"}

        # Check required crafting table if applicable
        if recipe.get("requires_table", False):
            has_table = self.inventory.get("crafting_table", 0) > 0 or any(
                b.name == "crafting_table" for b in self.voxels.values()
            )
            if not has_table:
                return {"success": False, "reason": "requires_crafting_table"}

        # Verify ingredient availability
        for ing, req_count in recipe["ingredients"].items():
            if self.inventory.get(ing, 0) < req_count * count:
                return {"success": False, "reason": f"insufficient_ingredient: {ing}"}

        # Deduct ingredients and grant product
        for ing, req_count in recipe["ingredients"].items():
            self.remove_item(ing, req_count * count)

        yielded_items = {}
        for prod, p_count in recipe["yields"].items():
            total_produced = p_count * count
            self.add_item(prod, total_produced)
            yielded_items[prod] = total_produced

        self.total_ticks += 10 * count
        return {"success": True, "recipe": recipe_name, "yielded": yielded_items}


class MinecraftBotClient:
    """HTTP Client connecting to the Node.js Mineflayer sidecar."""

    def __init__(self, bridge_url: str = "http://127.0.0.1:3000"):
        self.bridge_url = bridge_url.rstrip("/")

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.bridge_url}{endpoint}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e), "success": False}

    def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.bridge_url}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e), "success": False}

    def get_status(self) -> Dict[str, Any]:
        return self._get("/status")

    def get_state(self) -> Dict[str, Any]:
        """Return structured proprioception explicitly reported by the bridge.

        Missing values remain absent/unknown; callers must not infer them from
        the camera frame or defaults.
        """
        return self._get("/state")

    def connect(self, host: str = "localhost", port: int = 25565, username: str = "ReticleAgent", version: Optional[str] = "1.21.4") -> Dict[str, Any]:
        payload: Dict[str, Any] = {"host": host, "port": port, "username": username}
        if version:
            payload["version"] = version
        return self._post("/connect", payload)

    def probe_block(self, x: int, y: int, z: int) -> Dict[str, Any]:
        return self._post("/probe", {"probe_type": "block_at", "params": {"x": x, "y": y, "z": z}})

    def probe_inventory(self, item_name: str) -> int:
        res = self._post("/probe", {"probe_type": "inventory_count", "params": {"item_name": item_name}})
        return res.get("count", 0)

    def do_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/action", {"action": action, "params": params})

    def release_all(self) -> Dict[str, Any]:
        return self.do_action("release_all", {})


class MinecraftAdapter:
    """Unified adapter supporting both real Mineflayer and deterministic simulation."""

    def __init__(self, mode: str = "simulated", bridge_url: str = "http://127.0.0.1:3000"):
        self.mode = mode
        self.sim = SimulatedMinecraftEnvironment() if mode == "simulated" else None
        self.client = MinecraftBotClient(bridge_url) if mode == "mineflayer" else None

    def probe_block(self, x: int, y: int, z: int) -> Dict[str, Any]:
        if self.mode == "simulated":
            b = self.sim.get_block(x, y, z)
            return {"name": b.name, "hardness": b.hardness, "material": b.name}
        return self.client.probe_block(x, y, z)

    def get_inventory_count(self, item_name: str) -> int:
        if self.mode == "simulated":
            return self.sim.inventory.get(item_name, 0)
        return self.client.probe_inventory(item_name)

    def get_state(self) -> Dict[str, Any]:
        if self.mode == "simulated":
            return {
                "connected": True,
                "source": "simulated_environment",
                "observed_at": time.time(),
                "health": self.sim.health,
                "inventory": dict(self.sim.inventory),
                "yaw": None,
                "pitch": None,
                "position": list(self.sim.player_pos),
                "equipped": self.sim.equipped_tool,
                "durability": self.sim.tool_durability.get(self.sim.equipped_tool) if self.sim.equipped_tool else None,
            }
        return self.client.get_state()

    def execute_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.mode == "simulated":
            if action == "dig":
                return self.sim.dig_block(params["x"], params["y"], params["z"])
            elif action == "craft":
                return self.sim.craft_recipe(params["recipe_name"], params.get("count", 1))
            elif action == "equip":
                success = self.sim.equip(params.get("item_name"))
                return {"success": success, "equipped": self.sim.equipped_tool}
            else:
                return {"success": False, "reason": f"unsupported_sim_action: {action}"}
        return self.client.do_action(action, params)

    def release_all(self) -> Dict[str, Any]:
        if self.mode == "simulated":
            return {"success": True, "action": "release_all"}
        return self.client.release_all()
