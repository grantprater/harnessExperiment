"""Live Visual Explorer & Autonomous Embodied Agent.

Perceives exclusively via the bot's rendered viewscreen (GET /viewscreen.jpg).
Interacts exclusively via raw motor primitives (set_look, mouse_move, mouse_down, mouse_up, key_down, key_up, tick).
ZERO direct inventory or health information.
"""

from __future__ import annotations

import json
import time
import urllib.request
import numpy as np
import cv2

from reticle.sensory.streaming_transducer import StreamingVideoTransducer


class LiveMinecraftBotSession:
    """Client for the live Mineflayer bridge enforcing strict visual/motor boundaries."""

    def __init__(self, bridge_url: str = "http://127.0.0.1:3000"):
        self.bridge_url = bridge_url.rstrip("/")

    def get_viewscreen_frame(self) -> np.ndarray:
        """Fetches the latest visual frame from the bot's own eyes."""
        url = f"{self.bridge_url}/viewscreen.jpg"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def send_motor_action(self, action: str, **params) -> dict:
        """Sends raw physical motor actuation."""
        url = f"{self.bridge_url}/action"
        payload = {"action": action, "params": params}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def set_look(self, yaw: float, pitch: float):
        return self.send_motor_action("set_look", yaw=yaw, pitch=pitch)

    def mouse_move(self, dx: float, dy: float):
        return self.send_motor_action("mouse_move", dx=dx, dy=dy)

    def mouse_down(self, button: str = "left"):
        return self.send_motor_action("mouse_down", button=button)

    def mouse_up(self, button: str = "left"):
        return self.send_motor_action("mouse_up", button=button)

    def key_down(self, key: str):
        return self.send_motor_action("key_down", key=key)

    def key_up(self, key: str):
        return self.send_motor_action("key_up", key=key)

    def tick(self, count: int = 1):
        return self.send_motor_action("tick", ticks=count)


def run_live_visual_exploration(duration_seconds: float = 8.0):
    print("=" * 60)
    print("STARTING STRICTLY EMBODIED LIVE VISUAL EXPLORATION")
    print("Rule: 0 Oracle Inquiries | Pure Visual Pixels | Raw Motor Keys/Clicks")
    print("=" * 60)

    session = LiveMinecraftBotSession()

    # Initialize streaming video transducer on 640x480 frame
    transducer = StreamingVideoTransducer()
    # (x1, y1, x2, y2)
    transducer.register_roi("fovea_crosshair", (300, 220, 340, 260), z_threshold=2.0)
    transducer.register_roi("lower_peripheral", (100, 380, 540, 470), z_threshold=2.0)

    start_time = time.time()
    step = 0
    yaw_sweep = [0, 45, 90, 135, 180, 225, 270, 315]

    while time.time() - start_time < duration_seconds:
        step += 1
        target_yaw = yaw_sweep[step % len(yaw_sweep)]

        # 1. Physical motor actuation: turn gaze
        session.set_look(yaw=float(target_yaw), pitch=5.0)
        session.tick(2)

        # 2. Pure visual perception: sample frame
        frame = session.get_viewscreen_frame()
        events = transducer.process_frame(frame, timestamp_ms=time.time() * 1000.0)

        event_desc = ", ".join([f"{e.channel}(mag={e.magnitude}, z={e.metadata.get('z_score')})" for e in events]) if events else "steady"
        print(f"Step {step:02d}: Look yaw={target_yaw:3d}° | Frame: {frame.shape} | Visual Events: {event_desc}")

        # If visual transient detected, perform an active physical probe (short forward tap)
        if events:
            print(f"  -> Visual change detected! Active probing: tapping forward key...")
            session.key_down("w")
            session.tick(3)
            session.key_up("w")

        time.sleep(0.2)

    # Save final visual frame
    final_frame = session.get_viewscreen_frame()
    cv2.imwrite("exploration_final_view.jpg", final_frame)
    print("=" * 60)
    print(f"Exploration complete ({step} steps). Final view saved to exploration_final_view.jpg")
    print("=" * 60)


if __name__ == "__main__":
    run_live_visual_exploration(8.0)
