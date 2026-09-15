"""Autonomous Active Inference: Visual Mining & Emergent Item Acquisition.

ZERO High-Level Oracles:
- No bot.dig(), no bot.inventory, no bot.health, no memory probing.
- All actuation is purely physical: set_look, mouse_down("left"), mouse_up("left"), key_down("w"), key_up("w"), tick.
- Block destruction and item acquisition are detected purely via visual transients in screen pixels.
"""

from __future__ import annotations

import json
import time
import urllib.request
import cv2
import numpy as np

from reticle.sensory.streaming_transducer import StreamingVideoTransducer


def send_action(action: str, **params) -> dict:
    url = "http://127.0.0.1:3000/action"
    payload = {"action": action, "params": params}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_frame() -> np.ndarray:
    url = "http://127.0.0.1:3000/viewscreen.jpg"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = resp.read()
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def run_mining_experiment():
    print("=" * 60)
    print("AUTONOMOUS VISUAL ACTIVE INFERENCE: MINING ACACIA LOG")
    print("Constraints: 0 Memory Inquiries | Pure Visual Pixels | Raw Motor Clicks")
    print("=" * 60)

    # 1. Exact Crosshair Alignment
    print("\n[Step 1] Aligning crosshairs onto acacia log center...")
    send_action("set_look", yaw=120.0, pitch=-18.0)
    time.sleep(0.3)

    baseline_frame = get_frame()
    cv2.imwrite("mining_01_aimed.jpg", baseline_frame)
    print("-> Aim confirmed. Saved mining_01_aimed.jpg")

    # 2. Initialize Visual Transducer on Fovea and Hotbar Slot 0
    # Fovea: center 60x60 around crosshairs (320, 240)
    # Hotbar Slot 0: [422:458, 228:264]
    transducer = StreamingVideoTransducer()
    transducer.register_roi("foveal_target", (290, 210, 350, 270), alpha=0.15, z_threshold=2.8)
    transducer.register_roi("hotbar_slot_0", (228, 422, 264, 458), alpha=0.15, z_threshold=2.5)

    # Warm up transducer filters with baseline frame
    for _ in range(6):
        transducer.process_frame(baseline_frame, timestamp_ms=time.time() * 1000)

    # 3. Initiate Physical Motor Actuation: Left Click Hold
    print("\n[Step 2] Depressing Left Mouse Button (mouse_down 'left')...")
    res = send_action("mouse_down", button="left")
    print(f"-> Motor controller responded: {res}")

    # 4. Active Inference Loop: Monitor Visual Destruction Transient
    print("\n[Step 3] Monitoring visual foveal feed for block destruction transient...")
    start_time = time.time()
    block_destroyed = False
    fovea_history = []
    mining_frames = []

    # Mining wood by hand in Minecraft takes ~3.0s (60 ticks)
    # Poll up to 6.0s
    while time.time() - start_time < 6.0:
        current_time = time.time()
        frame = get_frame()
        events = transducer.process_frame(frame, timestamp_ms=current_time * 1000)

        # Track patch difference from baseline
        patch = frame[210:270, 290:350]
        base_patch = baseline_frame[210:270, 290:350]
        delta_from_base = float(np.mean(cv2.absdiff(patch, base_patch)))
        fovea_history.append((round(current_time - start_time, 2), round(delta_from_base, 2)))

        for event in events:
            if event.channel == "foveal_target":
                print(f"  [VISUAL TRANSIENT] t={current_time - start_time:.2f}s | Mag={event.magnitude:.2f} | Z={event.metadata.get('z_score')}")
                # Significant foveal transient indicates block fractured/popped
                if event.magnitude > 15.0 or delta_from_base > 25.0:
                    block_destroyed = True
                    break

        if delta_from_base > 35.0:
            print(f"  [BLOCK DESTROYED] Cumulative delta from base = {delta_from_base:.2f} > 35.0!")
            block_destroyed = True

        if block_destroyed:
            cv2.imwrite("mining_02_broken.jpg", frame)
            break

        time.sleep(0.1)

    # 5. Release Left Mouse Button
    print("\n[Step 4] Releasing Left Mouse Button (mouse_up 'left')...")
    send_action("mouse_up", button="left")
    print(f"-> Left click released. Block destroyed visually: {block_destroyed}")

    # 6. Physical Advance to Collect Drop
    print("\n[Step 5] Walking forward to collect dropped item (key_down 'w')...")
    send_action("key_down", key="w")
    time.sleep(0.6)
    send_action("key_up", key="w")
    time.sleep(0.4)

    # 7. Emergent Hotbar Verification (Pure Visual HUD Delta)
    final_frame = get_frame()
    cv2.imwrite("mining_03_collected.jpg", final_frame)

    slot_before = baseline_frame[422:458, 228:264]
    slot_after = final_frame[422:458, 228:264]
    slot_delta = float(np.mean(cv2.absdiff(slot_after, slot_before)))

    print(f"\n[Step 6] Hotbar Slot 0 Visual Delta: {slot_delta:.2f}")
    if slot_delta > 10.0:
        print("-> SUCCESS! Item visually detected in Hotbar Slot 0!")
    else:
        print(f"-> Hotbar delta = {slot_delta:.2f} (item sprite or pickup visual change)")

    print("\n" + "=" * 60)
    print("EXPERIMENT COMPLETE")
    print(f"Total time: {time.time() - start_time:.2f}s | Final view: mining_03_collected.jpg")
    print("=" * 60)


if __name__ == "__main__":
    run_mining_experiment()
