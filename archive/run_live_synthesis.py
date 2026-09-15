"""Live LLM Skill Synthesis Run using Gemini 3.6 Flash."""

import sys
from pathlib import Path
from reticle.adapters.minecraft_adapter import SimulatedMinecraftEnvironment
from reticle.adapters.raw_motor_controller import RawMotorController
from reticle.minecraft.skill_synthesizer import SkillSynthesizer
from harness import LLMClient

def main():
    client = LLMClient()
    print(f"[Live Runner] Model: {client.model} (Mock: {client.mock_mode})")

    def env_factory():
        env = SimulatedMinecraftEnvironment()
        env.set_block(0, 65, 2, "oak_log")
        controller = RawMotorController(env=env)
        controller.set_look(yaw=0.0, pitch=0.0)
        return env, controller

    def verifier(env, controller, result):
        has_log = env.inventory.get("oak_log", 0) >= 1
        success_flag = bool(result.get("success", False))
        return has_log and success_flag

    synthesizer = SkillSynthesizer(llm_client=client, skills_dir="skills")
    
    goal = (
        "Aim at the oak_log block in front of you. Check that a block is targeted using raycast_crosshair(). "
        "Hold left click (controller.mouse_down('left')) while ticking the controller in a loop (controller.tick(1)) "
        "until the block breaks (broken_blocks in tick result is non-empty) or max 100 ticks. "
        "Always release the click in a finally block (controller.mouse_up('left')). "
        "Return {'success': True, 'ticks_elapsed': ticks} on success, or {'success': False, 'ticks_elapsed': ticks}."
    )

    result = synthesizer.synthesize_skill(
        skill_name="live_mine_oak_log",
        goal_description=goal,
        env_factory=env_factory,
        verification_fn=verifier,
        max_repair_attempts=3
    )

    print("\n==========================================")
    print(f"Synthesis Succeeded: {result.success}")
    print(f"Iterations Required: {result.iterations_required}")
    print(f"Saved Path: {result.saved_path}")
    print("==========================================")
    print("Synthesized Python Code by Gemini:")
    print("------------------------------------------")
    print(result.code)
    print("------------------------------------------")
    if result.error_traceback:
        print("Failure Diagnostic:")
        print(result.error_traceback)

if __name__ == "__main__":
    main()
