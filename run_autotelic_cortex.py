"""Autotelic Agent Execution: Closed-Loop Intrinsic Motivation on Live Minecraft.

Demonstrates:
1. Internal Drive Calculation: Homeostasis, Empowerment, Curiosity (sub-1ms).
2. Affordance-Gated Memory Retrieval: Injects 1-2 relevant crystallized rules (<30 tokens).
3. System 2 Cortex (Gemini Flash-Lite Latest): Self-generates goal based on internal drive pressure.
4. System 1 Physical Motor Execution: Runs physical actuation via bridge.
5. Invariant Consolidation: Updates beliefs based on observed outcome.
"""

from __future__ import annotations

import json
import time
import urllib.request
import argparse
from pathlib import Path
import cv2
import numpy as np

from harness import LLMClient
from reticle.cognitive.autotelic_drive import AutotelicDriveEngine, AffordanceGatedMemoryIndex
from reticle.cognitive.capability_ledger import CapabilityLedger
from reticle.minecraft.hud_perception import HUDPerceptionTransducer


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


def get_structured_state() -> dict:
    """Read live bridge state; absent fields remain unknown."""
    url = "http://127.0.0.1:3000/state"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            state = json.loads(resp.read().decode("utf-8"))
            return state if isinstance(state, dict) else {}
    except Exception as exc:
        return {"connected": False, "source": "unavailable", "error": str(exc)}


def _run_autotelic_cycle_once(engine=None, llm=None, cycle_index: int = 0, log_path: str = "autotelic_cycles.jsonl", prior_feedback=None, capability_ledger=None):
    print("=" * 65)
    print("AUTOTELIC AGENT: INTRINSICALLY MOTIVATED DECISION CYCLE")
    print("=" * 65)

    engine = engine or AutotelicDriveEngine()
    llm = llm or LLMClient()
    hud_transducer = HUDPerceptionTransducer(
        health_roi=(140, 404, 294, 414),
        hotbar_roi=(145, 438, 495, 474)
    )

    # 1. Grab fresh viewscreen frame and live structured proprioception.
    frame = get_frame()
    cv2.imwrite("autotelic_pre_state.jpg", frame)
    live_state = get_structured_state()

    # 2. Evaluate physical state (Health and Inventory from perception and episodic grounding)
    hud_state = hud_transducer.perceive_hud(frame)
    inventory_observed = isinstance(live_state.get("inventory"), dict)
    inventory = dict(live_state.get("inventory") or {}) if inventory_observed else {}
    health = live_state.get("health")
    yaw = live_state.get("yaw")

    # 3. Calculate Internal Drives & Sparse Memory Retrieval (<1ms)
    t0 = time.perf_counter()
    drive_state = engine.arbitrate_drives(
        frame_bgr=frame,
        inventory_items=inventory,
        current_facing_yaw=yaw,
        health_hearts=float(health) if isinstance(health, (int, float)) else None,
        sheltered=live_state.get("sheltered")
    )
    drive_eval_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[Sensory Engine - {drive_eval_ms:.3f}ms]")
    print(f"  Dominant Drive Pressure: {drive_state.dominant_drive}")
    print(f"  Homeostasis Status     : {drive_state.homeostasis.status_summary}")
    print(f"  Empowerment Status     : {drive_state.empowerment.status_summary}")
    print(f"  Curiosity Frontier     : {drive_state.curiosity.status_summary}")
    print(f"  Affordance Memories    : {drive_state.relevant_memories}")

    # 4. Construct Minimal (~120 token) Working Memory State for System 2 Cortex
    state_packet = {
        "internal_pressures": {
            "dominant_drive": drive_state.dominant_drive,
            "homeostatic_urgency": drive_state.homeostasis.status_summary,
            "empowerment_gap": drive_state.empowerment.status_summary,
            "curiosity_frontier": drive_state.curiosity.status_summary
        },
        "focal_memories": drive_state.relevant_memories,
        "current_possessions": inventory if inventory_observed else None,
        "observation_source": live_state.get("source", "unknown"),
        "prior_cycle_feedback": prior_feedback
    }
    if capability_ledger is not None:
        state_packet["capability_coverage"] = capability_ledger.coverage()
        # Keep the cortex packet bounded as the sidecar ledger grows.
        state_packet["capability_evidence"] = capability_ledger.summaries()[-5:]

    # 5. System 2 Cortex: Self-Directed Goal Generation (Flash-Lite)
    system_prompt = (
        "You are an autotelic autonomous agent in an open Minecraft world.\n"
        "You have NO human instructions or external tasks.\n"
        "Analyze your internal drive pressures and focal memories.\n"
        "Determine which drive pressure requires action, formulate your own goal, predict the sensory outcome,\n"
        "and specify the physical motor actuation to execute.\n"
        "Output MUST be strictly JSON with keys:\n"
        "  - prioritized_drive: string ('HOMEOSTASIS' | 'EMPOWERMENT' | 'CURIOSITY')\n"
        "  - self_generated_goal: string\n"
        "  - rationale: string\n"
        "  - predicted_sensory_delta: string\n"
        "  - motor_action: dict with 'type' ('craft' | 'place' | 'move' | 'explore'), 'params' (dict)\n"
        "      * if type='craft': params={'recipe': string, 'quantity': int, 'predicted_inventory_delta': dict of exact signed item count changes}\n"
        "Craft and place are supplied bridge routines, not learned skills.\n"
        "      * if type='place': params={'item': string (e.g. 'crafting_table')}\n"
        "      * if type='move' or 'explore': params={'yaw': float, 'pitch': float, 'walk_duration_s': float}\n"
        "Output strictly valid JSON without markdown."
    )

    user_prompt = f"Internal State & Focal Memories:\n{json.dumps(state_packet, indent=2)}\n\nWhat self-directed goal do you choose to pursue?"

    t_llm0 = time.time()
    resp = llm.chat_completion([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    cortex_time = time.time() - t_llm0

    content = resp.get("content", "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    decision = json.loads(content)

    print(f"\n[System 2 Cortex - {cortex_time:.2f}s]")
    print(f"  Prioritized Drive  : {decision.get('prioritized_drive')}")
    print(f"  Self-Generated Goal: {decision.get('self_generated_goal')}")
    print(f"  Rationale          : {decision.get('rationale')}")
    print(f"  Predicted Delta    : {decision.get('predicted_sensory_delta')}")
    print(f"  Motor Action       : {decision.get('motor_action')}")

    # 6. Physical Actuation Dispatch
    action = decision.get("motor_action", {})
    action_type = action.get("type", "move")
    params = action.get("params", {})

    print(f"\n[System 1 Spinal Dispatch: {action_type}]")
    action_started = time.monotonic()
    action_result = {"success": False, "reason": "unsupported_action"}
    if action_type == "move" or action_type == "explore":
        yaw = float(params.get("yaw", 0.0))
        pitch = float(params.get("pitch", 0.0))
        walk_s = max(0.0, min(float(params.get("walk_duration_s", 0.8)), 1.5))
        try:
            look_result = send_action("set_look", yaw=yaw, pitch=pitch)
            down_result = send_action("key_down", key="w") if look_result.get("success") else {"success": False}
            if not down_result.get("success"):
                action_result = {"success": False, "reason": "look_or_key_down_failed"}
            else:
                started = time.monotonic()
                while time.monotonic() - started < walk_s:
                    time.sleep(min(0.1, walk_s))
                    check = get_structured_state()
                    old_h, new_h = live_state.get("health"), check.get("health")
                    if check.get("connected") is not True or (isinstance(old_h, (int, float)) and isinstance(new_h, (int, float)) and new_h < old_h):
                        action_result = {"success": False, "reason": "damage_or_disconnect", "interrupted": True}
                        break
                else:
                    action_result = {"success": True, "action": action_type}
        finally:
            up_result = send_action("release_all")
            action_result["released"] = bool(up_result.get("success"))
            if not action_result["released"]:
                action_result["success"] = False
                action_result["reason"] = "release_unconfirmed"
        print(f"-> Gaze turned to {yaw}° and walked forward {walk_s}s.")
    elif action_type == "craft":
        recipe = params.get("recipe", "crafting_table")
        qty = params.get("quantity", 1)
        action_result = send_action("craft", recipe=recipe, quantity=qty)
        print(f"-> Physical craft dispatched to bridge: {action_result}")
    elif action_type == "place" or action_type == "place_block":
        action_result = send_action("place_block")
        print(f"-> Block placement dispatched to bridge: {action_result}")

    post_frame = get_frame()
    cv2.imwrite("autotelic_post_state.jpg", post_frame)
    post_state = get_structured_state()
    post_inventory_observed = isinstance(post_state.get("inventory"), dict)
    observed_inventory = dict(post_state.get("inventory") or {}) if post_inventory_observed else {}
    inventory_delta = ({k: observed_inventory.get(k, 0) - inventory.get(k, 0)
                       for k in set(inventory) | set(observed_inventory)
                       if observed_inventory.get(k, 0) != inventory.get(k, 0)}
                       if inventory_observed and post_inventory_observed else None)
    pre_pos, post_pos = live_state.get("position"), post_state.get("position")
    displaced = (pre_pos is not None and post_pos is not None and pre_pos != post_pos)
    predicted_delta = params.get("predicted_inventory_delta") if isinstance(params, dict) else None
    if action_type == "craft":
        action_result["verified"] = bool(action_result.get("success") and isinstance(predicted_delta, dict) and predicted_delta and
                                          inventory_delta is not None and all(isinstance(v, int) and inventory_delta.get(k, 0) == v for k, v in predicted_delta.items()))
    elif action_type in ("move", "explore"):
        action_result["verified"] = bool(action_result.get("success") and displaced)
    else:
        action_result["verified"] = False
    capability_evidence = None
    if capability_ledger is not None:
        capability_evidence = capability_ledger.record_trial(
            action, inventory_delta, duration_s=time.monotonic() - action_started,
            pre_state=live_state, post_state_known=inventory_delta is not None,
            expected_delta=predicted_delta if isinstance(predicted_delta, dict) else None,
        )
    observed_yaw = post_state.get("yaw")
    if isinstance(observed_yaw, (int, float)):
        engine.mark_bearing_visited(float(observed_yaw))
    record = {"cycle": cycle_index, "pre_state": live_state, "decision": decision,
              "action_result": action_result, "post_state": post_state,
              "inventory_delta": inventory_delta,
              "capability_evidence": capability_evidence}
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(json.dumps(record, default=str) + "\n")
    print(f"-> Observed result: executed={action_result.get('success', False)}, verified={action_result['verified']}, inventory_delta={inventory_delta}")
    print("-> Post-action frame saved to autotelic_post_state.jpg")

    print("\n" + "=" * 65)
    print("AUTOTELIC CYCLE COMPLETED WITH OBSERVED OUTCOME")
    return {"decision": decision, "action_result": action_result,
            "pre_state": live_state, "post_state": post_state,
            "inventory_delta": inventory_delta, "capability_evidence": capability_evidence}


def run_autotelic_cycle(max_cycles: int = 1, log_path: str = "autotelic_cycles.jsonl"):
    """Run a bounded sequence, retaining drive state and observed feedback."""
    max_cycles = max(1, min(int(max_cycles), 100))
    engine = AutotelicDriveEngine()
    llm = LLMClient()
    capability_path = str(Path(log_path).with_suffix('.capabilities.json'))
    capability_ledger = CapabilityLedger(capability_path)
    results = []
    prior_feedback = None
    for cycle_index in range(max_cycles):
        result = _run_autotelic_cycle_once(engine, llm, cycle_index, log_path, prior_feedback, capability_ledger)
        results.append(result)
        prior_feedback = {"action_result": result.get("action_result"), "inventory_delta": result.get("inventory_delta"), "post_state": result.get("post_state"), "capability_evidence": result.get("capability_evidence")}
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run bounded observed autotelic cycles")
    parser.add_argument("--cycles", type=int, default=1, help="number of cycles (1-100)")
    parser.add_argument("--log", default="autotelic_cycles.jsonl", help="JSONL observation log")
    args = parser.parse_args()
    run_autotelic_cycle(args.cycles, args.log)
