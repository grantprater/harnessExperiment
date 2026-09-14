"""Dynamic Runtime Execution Probe for Codebase Navigation.

Rather than statically searching across dozens of files, the runtime probe
executes the failing test/reproduction command and extracts:
1. Active Execution Trace: The exact sequence of functions and files that were executed.
2. Failure Diagnostics: On assertion failure or exception, captures the exact failure line,
   call stack, and differing values.
3. Invariant Footprint: Shows the active execution path through the codebase.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import sys
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class RuntimeExecutionTracer:
    """Instruments execution to record executed files, functions, and active call paths."""

    def __init__(self, target_prefix: str):
        self.target_prefix = target_prefix.replace("\\", "/").rstrip("/")
        self.executed_functions: List[Dict[str, Any]] = []
        self._seen_calls: Set[Tuple[str, str, int]] = set()

    def trace_calls(self, frame, event, arg):
        if event == "call":
            co = frame.f_code
            filename = co.co_filename.replace("\\", "/")
            if self.target_prefix and self.target_prefix in filename:
                func_name = co.co_name
                lineno = frame.f_lineno
                # Skip module load time, lambdas, and dataclass internal annotation calls
                if func_name in ("<module>", "<genexpr>", "__annotate__") or func_name.startswith("__"):
                    return self.trace_calls

                key = (filename, func_name)
                if key not in self._seen_calls:
                    self._seen_calls.add(key)
                    rel = filename.split(self.target_prefix)[-1].lstrip("/")
                    args = {}
                    for arg_name in co.co_varnames[:co.co_argcount]:
                        val = frame.f_locals.get(arg_name)
                        try:
                            r = repr(val)
                            args[arg_name] = r if len(r) <= 60 else r[:57] + "..."
                        except Exception:
                            args[arg_name] = "<unprintable>"
                    self.executed_functions.append({
                        "file": rel,
                        "function": func_name,
                        "line": lineno,
                        "args": args
                    })
        return self.trace_calls


@contextlib.contextmanager
def _probe_sandbox(
    work_dir: Path,
    test_path: Path,
    test_filter: Optional[str],
    stdout_buf: io.StringIO,
    stderr_buf: io.StringIO,
    tracer: RuntimeExecutionTracer
):
    """Context manager ensuring execution isolation, directory switching, and stdout/stderr capture."""
    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    old_sys_argv = list(sys.argv)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_trace = sys.gettrace()
    try:
        os.chdir(work_dir)
        if str(work_dir) not in sys.path:
            sys.path.insert(0, str(work_dir))
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        sys.argv = [str(test_path)] + ([test_filter] if test_filter else [])
        sys.settrace(tracer.trace_calls)
        yield
    finally:
        sys.settrace(old_trace)
        os.chdir(old_cwd)
        sys.path = old_sys_path
        sys.argv = old_sys_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def _extract_exception_frames(exc_tb, target_prefix: str) -> List[Dict[str, Any]]:
    """Extract clean call frames filtering by target prefix."""
    frames = []
    for frame_summary in traceback.extract_tb(exc_tb):
        fn = frame_summary.filename.replace("\\", "/")
        rel = fn.split(target_prefix)[-1].lstrip("/") if target_prefix in fn else frame_summary.filename
        frames.append({
            "file": rel,
            "line": frame_summary.lineno,
            "function": frame_summary.name,
            "code": frame_summary.line
        })
    return frames


def run_with_probe(
    test_path: Union[str, Path],
    target_prefix: str = "",
    cwd: Optional[Union[str, Path]] = None,
    test_filter: Optional[str] = None
) -> Dict[str, Any]:
    """Execute a test with dynamic call tracing and assertion diagnostics."""
    test_path = Path(test_path).resolve()
    work_dir = Path(cwd).resolve() if cwd else test_path.parent

    tracer = RuntimeExecutionTracer(target_prefix=str(target_prefix))
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    passed = False
    error_info: Optional[Dict[str, Any]] = None

    with _probe_sandbox(work_dir, test_path, test_filter, stdout_buf, stderr_buf, tracer):
        try:
            runpy.run_path(str(test_path), run_name="__main__")
            passed = True
        except SystemExit as se:
            passed = (se.code == 0 or se.code is None)
            if not passed:
                error_info = {
                    "type": "TestFailure",
                    "code": se.code,
                    "output": stderr_buf.getvalue() + stdout_buf.getvalue()
                }
        except Exception as ex:
            passed = False
            exc_type, exc_val, exc_tb = sys.exc_info()
            error_info = {
                "type": exc_type.__name__ if exc_type else "Error",
                "message": str(exc_val),
                "frames": _extract_exception_frames(exc_tb, target_prefix),
                "output": stderr_buf.getvalue() + stdout_buf.getvalue()
            }

    # Parse failure details from test output if available
    raw_output = (error_info.get("output", "") if error_info else stdout_buf.getvalue() + stderr_buf.getvalue()).strip()
    clean_failure = None
    if not passed and raw_output:
        # Extract AssertionError block or traceback
        fail_match = re.search(r"FAIL: ([^\n]+)\n-+\nTraceback[^\n]*\n(.*?)(?=\n={3,}|\Z)", raw_output, re.DOTALL)
        if fail_match:
            clean_failure = {
                "failing_test": fail_match.group(1).strip(),
                "trace": fail_match.group(2).strip()
            }

    return {
        "passed": passed,
        "raw_output": raw_output,
        "clean_failure": clean_failure,
        "executed_call_chain": tracer.executed_functions,
        "failure_diagnostics": error_info
    }


def format_probe_summary(probe_result: Dict[str, Any]) -> str:
    """Format probe results into an actionable diagnostic map."""
    lines = ["=== DYNAMIC EXECUTION PROBE RESULT ==="]
    if probe_result["passed"]:
        lines.append("Status: PASSED (All tests executed without exception)")
    else:
        cf = probe_result.get("clean_failure")
        if cf:
            lines.append(f"Status: FAILED -> {cf['failing_test']}")
            lines.append("\nDiagnostic Failure Trace:")
            lines.append(cf["trace"])
        else:
            diag = probe_result.get("failure_diagnostics") or {}
            lines.append(f"Status: FAILED -> {diag.get('type', 'Error')}")
            if "output" in diag:
                # Keep last 15 lines of output
                out_lines = diag["output"].splitlines()
                lines.append("\n" + "\n".join(out_lines[-15:]))

    calls = probe_result.get("executed_call_chain", [])
    lines.append(f"\nExecution Footprint: Functions Executed During Test ({len(calls)} call sites):")
    for c in calls[:15]:
        args_repr = ", ".join(f"{k}={v}" for k, v in c["args"].items() if k != "self")
        lines.append(f"  - {c['file']}:{c['line']:4d} | {c['function']}({args_repr})")
    if len(calls) > 15:
        lines.append(f"  ... and {len(calls) - 15} additional calls.")

    lines.append("=== END PROBE ===")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_script = sys.argv[1]
        prefix = sys.argv[2] if len(sys.argv) > 2 else "dispatchdesk"
        res = run_with_probe(target_script, target_prefix=prefix)
        print(format_probe_summary(res))
