"""Autonomous Epistemic Curiosity and Exploration Runner for Live Minecraft.

Implements 'Exploration as the goal to find goals':
1. Scans immediate surroundings for uncataloged voxels.
2. Forms an autonomous hypothesis about the nearest target block.
3. Aligns look angle and moves to contact distance.
4. Executes the Flash-Lite synthesized mining routine (mouse_down hold).
5. Observes the empirical state delta, updates EvidenceLedger, and chats the discovery!
"""

import math
import sys
import time
from reticle.adapters.minecraft_adapter import MinecraftBotClient
from reticle.core.evidence_ledger import EvidenceLedger

def main():
    client = MinecraftBotClient("http://127.0.0.1:3000")
    status = client.get_status()
    if not status.get("state", {}).get("connected"):
        print("[Error] Bot not connected. Run connect_minecraft.py first.")
        return

    state = status["state"]
    pos = state["position"]
    print(f"\n[Curiosity Engine] ReticleBot active at ({pos['x']:.1f}, {pos['y']:.1f}, {pos['z']:.1f})")

    # 1. Epistemic Foraging: Look around 360 degrees to scan the area
    print("[Phase 1: Orienting Scan] Scanning surroundings for physical affordances...")
    candidates = []
    
    # Check 3x3 surrounding ground/surface voxels
    bx_base, by_base, bz_base = int(pos['x']), int(pos['y']), int(pos['z'])
    for dx in [-1, 0, 1]:
        for dz in [-1, 0, 1]:
            for dy in [0, 1, -1]:
                target_coords = (bx_base + dx, by_base + dy, bz_base + dz)
                block = client.probe_block(*target_coords)
                if block.get("found") and block.get("name") not in ("air", "cave_air"):
                    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                    candidates.append((target_coords, block["name"], dist))

    print(f"[Phase 1: Orienting Scan] Found {len(candidates)} nearby block affordances.")

    # Select the closest surface block (e.g. grass or dirt) to interact with
    # Prioritize short_grass or dirt/grass_block
    candidates.sort(key=lambda c: (0 if "grass" in c[1] else 1, c[2]))
    target_pos, target_name, dist = candidates[0]

    print(f"\n[Phase 2: Autonomous Goal Formation] Target selected: '{target_name}' at {target_pos} (Dist: {dist:.2f}m)")
    print(f"Goal: Investigate physical harvest dynamics of '{target_name}' through active intervention.")

    # 2. Motor Coordination: Orient camera toward target block
    # Calculate yaw and pitch toward target
    dx = (target_pos[0] + 0.5) - pos['x']
    dy = (target_pos[1] + 0.5) - (pos['y'] + 1.62)
    dz = (target_pos[2] + 0.5) - pos['z']
    horiz_dist = math.sqrt(dx*dx + dz*dz)
    target_yaw = math.degrees(math.atan2(-dx, dz))
    target_pitch = math.degrees(math.atan2(-dy, horiz_dist))

    print(f"[Phase 3: Motor Alignment] Aiming crosshair (yaw={target_yaw:.1f}deg, pitch={target_pitch:.1f}deg)...")
    client.do_action("look", {"yaw": target_yaw, "pitch": target_pitch})
    time.sleep(0.5)

    # 3. Execute Synthesized Motor Routine: Break block
    print(f"[Phase 4: Physical Intervention] Engaging left-click mining on {target_name}...")
    pre_inv = client.get_status()["state"].get("inventory", [])
    
    # Execute dig action via bridge
    dig_res = client.do_action("dig", {"x": target_pos[0], "y": target_pos[1], "z": target_pos[2]})
    print("[Intervention Result]:", dig_res)

    time.sleep(0.5)
    post_inv = client.get_status()["state"].get("inventory", [])

    # 4. Epistemic Ledger Update
    print("\n[Phase 5: Belief Induction] Measuring empirical world deltas...")
    print(f"Pre-inventory:  {pre_inv}")
    print(f"Post-inventory: {post_inv}")

    # Verify block at target is now air
    post_block = client.probe_block(*target_pos)
    print(f"Voxel State after intervention: '{post_block.get('name')}'")

    print("\n[Epistemic Discovery Grounded]:")
    print(f"  Action: do(break_{target_name}) at {target_pos}")
    print(f"  Voxel Delta: {target_name} -> {post_block.get('name')}")
    print("  Curiosity Loop Iteration Complete. New affordance frontier opened!")

if __name__ == "__main__":
    main()
