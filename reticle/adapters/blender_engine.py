"""Blender 5.0 Execution Environment and Headless Adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Union

DEFAULT_BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe")


@dataclass
class BlenderRunResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    traceback: str
    duration_s: float
    output_files: List[str]


def get_blender_path() -> Optional[Path]:
    if DEFAULT_BLENDER_EXE.exists():
        return DEFAULT_BLENDER_EXE
    # Check PATH
    import shutil
    which = shutil.which("blender")
    return Path(which) if which else None


def verify_blender_installed() -> bool:
    return get_blender_path() is not None


def run_blender_script(
    script_code: str,
    blend_file: Optional[Union[Path, str]] = None,
    args: Optional[List[str]] = None,
    timeout: int = 60,
    blender_exe: Optional[Path] = None,
    cwd: Optional[Union[Path, str]] = None
) -> BlenderRunResult:
    """Execute a Python script inside Blender in background mode."""
    exe = blender_exe or get_blender_path()
    if not exe:
        raise FileNotFoundError("Blender executable not found.")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script_code)
        script_path = Path(f.name)

    cmd = [str(exe), "--background"]
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
            duration_s=float(timeout),
            output_files=[]
        )
    finally:
        try:
            script_path.unlink()
        except Exception:
            pass
