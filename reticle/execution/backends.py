"""Trusted local supervision and an explicitly isolated OCI backend."""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4


EXECUTION_STATUSES = {"success", "error", "timeout", "cancelled", "rejected"}


class BackendUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionRequest:
    command: List[str]
    working_directory: str | Path
    timeout_seconds: float = 30.0
    output_limit_bytes: int = 1_000_000
    environment: Dict[str, str] = field(default_factory=dict)
    mutates_workspace: bool = False

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(part, str) and part for part in self.command):
            raise ValueError("command must be a non-empty list of non-empty strings")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.output_limit_bytes <= 0:
            raise ValueError("output_limit_bytes must be positive")


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    exit_code: Optional[int]
    stdout: bytes
    stderr: bytes
    duration_ms: int
    backend: str
    host_isolation: bool
    output_truncated: bool = False
    error_kind: Optional[str] = None
    diagnostic: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in EXECUTION_STATUSES:
            raise ValueError(f"Unsupported execution status: {self.status}")


def _clean_environment(overrides: Dict[str, str]) -> Dict[str, str]:
    """Pass OS essentials, but do not inherit credentials or the full host environment."""
    allowed = (
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "PATH",
        "LANG",
        "LC_ALL",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    for name, value in overrides.items():
        if not isinstance(name, str) or not isinstance(value, str) or "=" in name or "\x00" in name:
            raise ValueError(f"Invalid environment entry: {name!r}")
        environment[name] = value
    return environment


if os.name == "nt":
    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


class _ProcessTree:
    """Own a process tree and terminate all descendants as one unit."""

    def __init__(self, process: subprocess.Popen[bytes]):
        self.process = process
        self._job = None
        if os.name == "nt":
            job = _kernel32.CreateJobObjectW(None, None)
            if not job:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            information = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            information.BasicLimitInformation.LimitFlags = 0x00002000
            ok = _kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(information), ctypes.sizeof(information)
            )
            if not ok:
                error = ctypes.get_last_error()
                _kernel32.CloseHandle(job)
                raise OSError(error, "SetInformationJobObject failed")
            ok = _kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle))
            if not ok:
                error = ctypes.get_last_error()
                _kernel32.CloseHandle(job)
                raise OSError(error, "AssignProcessToJobObject failed")
            self._job = job

    def terminate(self) -> None:
        if os.name == "nt" and self._job:
            _kernel32.TerminateJobObject(self._job, 1)
        elif os.name != "nt" and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        elif self.process.poll() is None:
            self.process.kill()

    def close(self) -> None:
        if os.name == "nt" and self._job:
            _kernel32.CloseHandle(self._job)
            self._job = None


class TrustedLocalBackend:
    """Supervised local execution. This does not isolate from the host."""

    name = "trusted-local"
    host_isolation = False

    def run(
        self,
        request: ExecutionRequest,
        cancellation_event: Optional[threading.Event] = None,
    ) -> ExecutionResult:
        working_directory = Path(request.working_directory).resolve()
        if not working_directory.is_dir():
            raise ValueError(f"Working directory is not a directory: {working_directory}")
        started = time.monotonic()
        bootstrap = Path(__file__).with_name("bootstrap.py")
        creationflags = 0
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [sys.executable, str(bootstrap), json.dumps(request.command)],
            cwd=working_directory,
            env=_clean_environment(request.environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            **popen_kwargs,
        )
        tree: Optional[_ProcessTree] = None
        stdout = bytearray()
        stderr = bytearray()
        output_exceeded = threading.Event()
        output_lock = threading.Lock()

        def collect(stream, target: bytearray) -> None:
            while True:
                chunk = stream.read(65_536)
                if not chunk:
                    return
                with output_lock:
                    remaining = request.output_limit_bytes - len(stdout) - len(stderr)
                    if remaining > 0:
                        target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        output_exceeded.set()

        try:
            tree = _ProcessTree(process)
            assert process.stdin is not None
            process.stdin.write(b"R")
            process.stdin.close()
            assert process.stdout is not None and process.stderr is not None
            readers = [
                threading.Thread(target=collect, args=(process.stdout, stdout), daemon=True),
                threading.Thread(target=collect, args=(process.stderr, stderr), daemon=True),
            ]
            for reader in readers:
                reader.start()
            status = "error"
            error_kind = None
            diagnostic = None
            while process.poll() is None:
                if cancellation_event is not None and cancellation_event.is_set():
                    status, error_kind = "cancelled", "cancelled"
                    tree.terminate()
                    break
                if output_exceeded.is_set():
                    status, error_kind = "error", "output_limit"
                    diagnostic = f"Combined output exceeded {request.output_limit_bytes} bytes"
                    tree.terminate()
                    break
                if time.monotonic() - started >= request.timeout_seconds:
                    status, error_kind = "timeout", "timeout"
                    diagnostic = f"Execution exceeded {request.timeout_seconds} seconds"
                    tree.terminate()
                    break
                time.sleep(0.01)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tree.terminate()
                process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=5)
            if status == "error" and error_kind is None:
                status = "success" if process.returncode == 0 else "error"
                error_kind = None if status == "success" else "process_exit"
            return ExecutionResult(
                status=status,
                exit_code=process.returncode,
                stdout=bytes(stdout),
                stderr=bytes(stderr),
                duration_ms=round((time.monotonic() - started) * 1000),
                backend=self.name,
                host_isolation=self.host_isolation,
                output_truncated=output_exceeded.is_set(),
                error_kind=error_kind,
                diagnostic=diagnostic,
            )
        except Exception:
            if tree is not None:
                tree.terminate()
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            raise
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            if tree is not None:
                tree.close()


class IsolatedOCIBackend:
    """Docker/Podman backend with a single workspace mount and network disabled.

    The container image is part of the authority contract and must already exist.
    No host directory other than the declared workspace is mounted.
    """

    name = "isolated-oci"
    host_isolation = True

    def __init__(self, image: str, engine: Optional[str] = None):
        self.image = image
        self.engine = engine or self._discover_engine()

    @staticmethod
    def _discover_engine() -> str:
        for candidate in ("docker", "podman"):
            executable = shutil.which(candidate)
            if executable:
                return executable
        raise BackendUnavailableError(
            "Isolated OCI execution requires Docker or Podman; neither is installed"
        )

    def availability(self) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                [self.engine, "version"], capture_output=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"OCI engine unavailable: {exc}"
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
            return False, f"OCI engine unavailable: {detail.strip()}"
        return True, "available"

    def run(
        self,
        request: ExecutionRequest,
        cancellation_event: Optional[threading.Event] = None,
    ) -> ExecutionResult:
        available, detail = self.availability()
        if not available:
            raise BackendUnavailableError(detail)
        workspace = Path(request.working_directory).resolve()
        container_name = f"reticle-{uuid4().hex}"
        command = self.build_command(request, container_name)
        client_environment = {
            name: os.environ[name]
            for name in (
                "HOME",
                "USERPROFILE",
                "HOMEDRIVE",
                "HOMEPATH",
                "APPDATA",
                "LOCALAPPDATA",
                "XDG_RUNTIME_DIR",
                "DOCKER_HOST",
                "DOCKER_CONFIG",
                "CONTAINER_HOST",
                "CONTAINERS_CONF",
            )
            if name in os.environ
        }
        outer = ExecutionRequest(
            command=command,
            working_directory=workspace,
            timeout_seconds=request.timeout_seconds,
            output_limit_bytes=request.output_limit_bytes,
            # These configure the trusted OCI client only. Container variables
            # remain limited to the explicit --env entries in build_command().
            environment=client_environment,
        )
        result = TrustedLocalBackend().run(outer, cancellation_event)
        if result.status in {"timeout", "cancelled"} or result.error_kind == "output_limit":
            subprocess.run(
                [self.engine, "rm", "--force", container_name],
                capture_output=True,
                timeout=15,
                check=False,
            )
        return ExecutionResult(
            status=result.status,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            backend=self.name,
            host_isolation=True,
            output_truncated=result.output_truncated,
            error_kind=result.error_kind,
            diagnostic=result.diagnostic,
        )

    def build_command(self, request: ExecutionRequest, container_name: str) -> List[str]:
        workspace = Path(request.working_directory).resolve()
        mount = f"type=bind,src={workspace},dst=/workspace"
        if not request.mutates_workspace:
            mount += ",readonly"
        command = [
            self.engine,
            "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "128",
            "--memory", "512m",
            "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", mount,
            "--workdir", "/workspace",
        ]
        for name, value in request.environment.items():
            if not isinstance(name, str) or not isinstance(value, str) or "=" in name or "\x00" in name:
                raise ValueError(f"Invalid environment entry: {name!r}")
            command.extend(["--env", f"{name}={value}"])
        command.extend([self.image, *request.command])
        return command
