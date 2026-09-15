"""Blender 5.0 Execution Environment & Headless Bridge.

Wraps the local Blender 5.0 installation to execute headless Python scripts,
extract scene graph ASTs, and render verification stills.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe")


@dataclass
class BlenderRunResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    traceback: str
    duration_s: float
    output_files: List[str]


def verify_blender_installed() -> bool:
    return BLENDER_EXE.exists()


def run_blender_script(
    script_code: str,
    blend_file: Optional[Path | str] = None,
    args: Optional[List[str]] = None,
    timeout: int = 60,
    cwd: Optional[Path | str] = None
) -> BlenderRunResult:
    """Execute a Python script inside Blender in background mode."""
    if not verify_blender_installed():
        raise FileNotFoundError(f"Blender executable not found at: {BLENDER_EXE}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script_code)
        script_path = Path(f.name)

    cmd = [str(BLENDER_EXE), "--background"]
    if blend_file:
        cmd.append(str(blend_file))
    cmd.extend(["--python", str(script_path)])
    if args:
        cmd.append("--")
        cmd.extend(args)

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None
        )
        elapsed = time.time() - t0
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        success = (proc.returncode == 0)

        # Extract Python traceback if present
        traceback_str = ""
        if "Traceback (most recent call last):" in stdout:
            traceback_str = stdout.split("Traceback (most recent call last):", 1)[1]
        elif "Traceback (most recent call last):" in stderr:
            traceback_str = stderr.split("Traceback (most recent call last):", 1)[1]

        return BlenderRunResult(
            success=success and not bool(traceback_str),
            returncode=proc.returncode,
            stdout=stdout.strip(),
            stderr=stderr.strip(),
            traceback=traceback_str.strip(),
            duration_s=round(elapsed, 3),
            output_files=[]
        )
    except subprocess.TimeoutExpired:
        return BlenderRunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr="Blender execution timed out.",
            traceback=f"TimeoutExpired after {timeout}s",
            duration_s=timeout,
            output_files=[]
        )
    finally:
        try:
            script_path.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    test_script = "import bpy; print('BLENDER_OK: Objects in default scene:', len(bpy.data.objects))"
    res = run_blender_script(test_script)
    print("Blender Execution Success:", res.success)
    print("Duration:", res.duration_s, "s")
    print("Output:\n", res.stdout)
