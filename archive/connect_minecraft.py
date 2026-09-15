"""Connect Reticle Cognitive Harness to an Actual Minecraft Game.

Instructions:
1. In Minecraft, open a singleplayer world.
2. Press ESC -> Click 'Open to LAN' -> Set 'Allow Cheats: ON' -> Click 'Start LAN World'.
3. Note the port number displayed in game chat (e.g. 54321).
4. Run: python connect_minecraft.py --port <PORT>
"""

import argparse
import subprocess
import sys
import time
from reticle.adapters.minecraft_adapter import MinecraftBotClient

def main():
    parser = argparse.ArgumentParser(description="Connect Reticle to actual Minecraft")
    parser.add_argument("--port", type=int, default=25565, help="LAN port displayed in Minecraft chat")
    parser.add_argument("--host", type=str, default="localhost", help="Minecraft server host")
    parser.add_argument("--username", type=str, default="ReticleBot", help="Bot username in world")
    args = parser.parse_args()

    client = MinecraftBotClient("http://127.0.0.1:3000")

    # 1. Check if sidecar is running
    status = client.get_status()
    if "error" in status:
        print("[Launcher] Starting Node.js Mineflayer bridge sidecar...")
        bridge_proc = subprocess.Popen(
            ["node", "index.js"],
            cwd="reticle/adapters/minecraft_bridge",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(2)
        status = client.get_status()
        if "error" in status:
            print("[Error] Could not start Mineflayer bridge sidecar. Check node installation.")
            sys.exit(1)

    print(f"[Launcher] Sidecar is active! Connecting {args.username} to {args.host}:{args.port}...")
    conn_res = client.connect(host=args.host, port=args.port, username=args.username)
    print("[Connection Request Sent]:", conn_res)

    print("Waiting 5 seconds for bot to spawn in your Minecraft world...")
    time.sleep(5)

    bot_status = client.get_status()
    state = bot_status.get("state", {})
    if state.get("connected"):
        print("\n[SUCCESS] ReticleBot has spawned into your Minecraft world!")
        print(f"Position: {state.get('position')}")
        print(f"Health: {state.get('health')}/20 | Food: {state.get('food')}")
        print(f"Inventory: {state.get('inventory')}")
        print("\nLook around in your Minecraft game - you should see ReticleBot standing near spawn!")
    else:
        print("\n[Pending/Retry]: Bot hasn't spawned yet. Ensure Minecraft is 'Open to LAN' on port", args.port)

if __name__ == "__main__":
    main()
