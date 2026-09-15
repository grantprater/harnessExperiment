"""LLM Skill Synthesis, Verification, and Self-Repair Loop.

Enables the LLM Cortex to synthesize executable Python behavioral skills using ONLY
raw interaction primitives (mouse movement, clicks, keystrokes, and physics ticks).

Workflow:
1. Prompt LLM with raw motor API schema and target behavioral invariant.
2. Dynamically compile and execute candidate code inside a sandboxed trial.
3. Capture runtime residuals / exceptions.
4. Autonomous Repair Loop: Feed error tracebacks back to the LLM if execution fails.
5. Crystallization: Save verified Python skills into procedural memory (/skills/).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from pathlib import Path
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

from reticle.core.evidence_ledger import EvidenceLedger
from reticle.adapters.minecraft_adapter import SimulatedMinecraftEnvironment
from reticle.adapters.raw_motor_controller import RawMotorController
from harness import LLMClient


@dataclass
class SynthesisResult:
    skill_name: str
    code: str
    success: bool
    iterations_required: int
    execution_metrics: Dict[str, Any]
    error_traceback: Optional[str] = None
    saved_path: Optional[str] = None


RAW_MOTOR_API_DOCS = """
Available Raw Motor Controller Primitives (System 1 Interface):
----------------------------------------------------------------
controller.set_look(yaw: float, pitch: float) -> None
    Orient player view (yaw: -180 to 180 horizontal, pitch: -90 up to 90 down).
controller.mouse_move(dx: float, dy: float, sensitivity: float = 0.15) -> None
    Relative mouse movement adjusting yaw and pitch.
controller.mouse_down(button: str = 'left') -> None
    Press down mouse button ('left' for mining/attacking, 'right' for placing).
controller.mouse_up(button: str = 'left') -> None
    Release mouse button.
controller.key_down(key: str) -> None
    Press down movement key ('w', 'a', 's', 'd', 'space', 'shift').
controller.key_up(key: str) -> None
    Release movement key.
controller.raycast_crosshair() -> Tuple[Optional[Tuple[int, int, int]], Optional[VoxelBlock], float]
    Returns ((x, y, z), block_obj, distance). If air or out of reach, pos is None.
controller.tick(count: int = 1) -> Dict[str, Any]
    Advances world physics by `count` ticks. Returns dict with 'broken_blocks', 'player_pos', etc.
"""


class SkillSynthesizer:
    """Orchestrates LLM code generation of raw motor behavioral skills with verification."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        skills_dir: str | Path = "skills",
        evidence_ledger: Optional[EvidenceLedger] = None
    ):
        self.client = llm_client or LLMClient()
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_ledger = evidence_ledger or EvidenceLedger()

    def synthesize_skill(
        self,
        skill_name: str,
        goal_description: str,
        env_factory: Callable[[], Tuple[SimulatedMinecraftEnvironment, RawMotorController]],
        verification_fn: Callable[[SimulatedMinecraftEnvironment, RawMotorController, Dict[str, Any]], bool],
        max_repair_attempts: int = 3,
        fallback_code: Optional[str] = None
    ) -> SynthesisResult:
        """Synthesize, test, and repair a Python behavioral skill using raw motor primitives."""

        system_prompt = (
            "You are an expert autonomous robotics and game AI engineer.\n"
            "Your task is to write an autonomous behavioral skill in pure Python.\n"
            "CRITICAL RULES:\n"
            "1. You must ONLY use the provided RawMotorController API primitives (mouse_down, mouse_up, set_look, tick, key_down, etc.).\n"
            "2. Do NOT use non-existent high-level helper functions.\n"
            "3. Always release any pressed keys or mouse buttons in a `finally` block.\n"
            "4. Return a dictionary containing at least: {'success': bool, 'ticks_elapsed': int}.\n"
            "5. Output ONLY the raw executable Python function without markdown backticks or commentary."
        )

        user_prompt = (
            f"Goal: {goal_description}\n\n"
            f"{RAW_MOTOR_API_DOCS}\n\n"
            f"Write a Python function with the signature:\n"
            f"def {skill_name}(controller: RawMotorController, **kwargs) -> dict:\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        attempt = 0
        last_error = None
        candidate_code = fallback_code or ""

        while attempt < max_repair_attempts:
            attempt += 1

            if not candidate_code or attempt > 1:
                if self.client.mock_mode:
                    # In mock mode, if fallback_code is provided, use it
                    if fallback_code:
                        candidate_code = fallback_code
                    else:
                        candidate_code = (
                            f"def {skill_name}(controller, **kwargs):\n"
                            f"    pos, block, dist = controller.raycast_crosshair()\n"
                            f"    if not pos:\n"
                            f"        return {{'success': False, 'reason': 'no_target'}}\n"
                            f"    controller.mouse_down('left')\n"
                            f"    ticks = 0\n"
                            f"    try:\n"
                            f"        while ticks < 100:\n"
                            f"            res = controller.tick(1)\n"
                            f"            ticks += 1\n"
                            f"            if res['broken_blocks']:\n"
                            f"                return {{'success': True, 'ticks_elapsed': ticks}}\n"
                            f"    finally:\n"
                            f"        controller.mouse_up('left')\n"
                            f"    return {{'success': False, 'ticks_elapsed': ticks}}\n"
                        )
                else:
                    resp = self.client.chat_completion(messages)
                    candidate_code = self._clean_code_response(resp.get("content", ""))

            # 2. Compile candidate code
            compiled_fn, compile_err = self._compile_function(candidate_code, skill_name)
            if compile_err:
                last_error = f"Compilation Error: {compile_err}"
                messages.append({"role": "assistant", "content": candidate_code})
                messages.append({"role": "user", "content": f"Code failed compilation:\n{last_error}\nPlease fix the syntax and output the corrected function."})
                candidate_code = ""
                continue

            # 3. Test candidate in a clean sandbox trial
            env, controller = env_factory()
            try:
                exec_result = compiled_fn(controller)
                passed = verification_fn(env, controller, exec_result)
                if passed:
                    # Invariant verified! Save skill to procedural memory
                    out_path = self.skills_dir / f"{skill_name}.py"
                    out_path.write_text(candidate_code, encoding="utf-8")

                    self.evidence_ledger.record_evidence(
                        claim=f"Synthesized skill '{skill_name}' verified against physical trial",
                        source_doc="SkillSynthesizer",
                        section=skill_name,
                        verbatim_quote=f"Passed verification after {attempt} iteration(s). Metrics: {exec_result}",
                        topic="skill_synthesis",
                        confidence=1.0
                    )

                    return SynthesisResult(
                        skill_name=skill_name,
                        code=candidate_code,
                        success=True,
                        iterations_required=attempt,
                        execution_metrics=exec_result,
                        saved_path=str(out_path)
                    )
                else:
                    last_error = f"Behavioral Invariant Failed: Trial executed but did not achieve verification objective. Result: {exec_result}"
            except Exception as e:
                tb_str = traceback.format_exc()
                last_error = f"Runtime Exception during execution:\n{tb_str}"

            # Feed failure traceback back to LLM for self-repair
            messages.append({"role": "assistant", "content": candidate_code})
            messages.append({"role": "user", "content": f"Trial failed with:\n{last_error}\nPlease diagnose the bug, correct the logic, and output the fixed function."})
            candidate_code = ""

        return SynthesisResult(
            skill_name=skill_name,
            code=candidate_code,
            success=False,
            iterations_required=attempt,
            execution_metrics={},
            error_traceback=last_error
        )

    def _compile_function(self, code_str: str, function_name: str) -> Tuple[Optional[Callable], Optional[str]]:
        local_scope: Dict[str, Any] = {}
        try:
            exec(code_str, {"RawMotorController": RawMotorController, "math": __import__("math")}, local_scope)
            fn = local_scope.get(function_name)
            if not fn or not callable(fn):
                return None, f"Function {function_name} not defined in code."
            return fn, None
        except Exception as e:
            return None, str(e)

    def _clean_code_response(self, text: str) -> str:
        lines = text.strip().splitlines()
        code_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
                continue
            code_lines.append(line)
        return "\n".join(code_lines).strip()
