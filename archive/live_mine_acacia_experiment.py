"""Live Mine Acacia Log Experiment via Pure Visual Perception and Raw Motor Control."""

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
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_frame() -> np.ndarray:
    url = "http://127.0.0.1:3000/viewscreen.jpg"
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = resp.read()
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def run_experiment():
    print("=" * 60)
    print("STEP 1: FOVEAL ALIGNMENT ON ACACIA LOG")
    print("=" * 60)
    send_action("set_look", yaw=84.5, pitch=-6.5)
    time.sleep(0.3)

    frame = get_frame()
    cv2.imwrite("step1_aligned.jpg", frame)
    print("Crosshair aligned. Saved step1_aligned.jpg")

    print("\n" + "=" * 60)
    print("STEP 2: MOTOR ADVANCE UP LEDGE TOWARD LOG")
    print("=" * 60)
    # Jump and walk forward 1 step onto the grass
    send_action("key_down", key="space")
    send_action("key_down", key="w")
    time.sleep(0.4)
    send_action("key_up", key="space")
    send_action("key_up", key="w")
    time.sleep(0.4)

    # Re-aim down slightly at the block directly in front
    send_action("set_look", yaw=84.5, pitch=-12.0)
    time.sleep(0.3)

    frame = get_frame()
    cv2.imwrite("step2_approached.jpg", frame)
    print("Approached log. Saved step2_approached.jpg")


if __name__ == "__main__":
    run_experiment()
