"""Fixed unittest observations for opt-in post-edit hooks.

Full diagnostics are retained regardless of model-facing representation. This is
trusted code execution, not isolation against hostile candidate programs.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

VERSION = 'post-edit-check-v1'
CHECK_PROGRAM = r'''
import contextlib, io, json, unittest
log = io.StringIO()
with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
    suite = unittest.defaultTestLoader.loadTestsFromName("test_contract")
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
value = {"tests_run": result.testsRun, "failures": len(result.failures),
         "errors": len(result.errors), "skipped": len(result.skipped),
         "unexpected_successes": len(result.unexpectedSuccesses),
         "successful": result.wasSuccessful(), "output": log.getvalue(),
         "diagnostics": [{"test": str(test), "traceback": trace}
                         for test, trace in result.failures + result.errors]}
print(json.dumps(value))
'''


def source_fingerprint(workspace, paths):
    values = {}
    for name in sorted(paths):
        path = Path(workspace)/name
        values[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


class FixedUnittestCheck:
    def __init__(self, workspace, interpreter, *, timeout=15):
        self.workspace = Path(workspace)
        self.interpreter = str(interpreter)
        self.timeout = timeout

    def __call__(self):
        started = time.monotonic()
        try:
            process = subprocess.run([self.interpreter, '-B', '-c', CHECK_PROGRAM],
                cwd=self.workspace, capture_output=True, text=True, timeout=self.timeout)
            if process.returncode != 0:
                raise ValueError('Check process exited without a valid test result')
            value = json.loads(process.stdout)
            count = value['tests_run']
            if type(count) is not int or count <= 0 or count <= value['skipped']:
                raise ValueError('No non-skipped tests executed')
            status = 'passed' if value['successful'] else 'failed'
            return {**value, 'status': status, 'duration_s': round(time.monotonic()-started, 4)}
        except subprocess.TimeoutExpired:
            return {'status': 'timeout', 'output': 'Fixed test check timed out.',
                    'duration_s': round(time.monotonic()-started, 4)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {'status': 'error', 'output': f'Check execution error: {type(exc).__name__}: {exc}',
                    'duration_s': round(time.monotonic()-started, 4)}


def render_check(result, mode, handle, source_revision):
    header = (f"Check {result['status']}; tests={result.get('tests_run', 'unknown')}; "
              f"source={source_revision[:12]}; full evidence={handle}.")
    if mode == 'full':
        return header + '\n' + result['output']
    if mode != 'selective':
        raise ValueError('Check representation must be full or selective')
    if result['status'] == 'passed':
        return header
    diagnostics = result.get('diagnostics', [])
    if not diagnostics:
        return header + '\n' + result['output']
    # Deterministic exact diagnostic excerpts; all individual failures remain named.
    parts = [header]
    for diagnostic in diagnostics:
        trace = diagnostic['traceback'].splitlines()
        excerpts = trace if len(trace) <= 14 else [*trace[:4], '[middle omitted; retrieve full evidence]', *trace[-9:]]
        parts += [diagnostic['test'], '\n'.join(excerpts)]
    return '\n'.join(parts)
