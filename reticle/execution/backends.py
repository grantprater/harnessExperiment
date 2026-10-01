"""Trusted local supervision, its Linux namespace confinement, and an explicitly isolated OCI backend."""

from __future__ import annotations

from dataclasses import dataclass, field, replace as dataclass_replace
import ctypes
from ctypes import wintypes
import json
import os
import posixpath
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple
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
    # Isolated backends mount the working directory writable iff this is true; None follows
    # mutates_workspace. Set it for a private copy (e.g. an evaluation root) whose writes
    # are not mutations of the session workspace.
    writable_mount: Optional[bool] = None

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


CONFINEMENT_NAME = "unshare-confined"
CONFINEMENT_VERSION = "unshare-confined-v1"
# Read-only system directories bound into the confined root, where they exist (merged-/usr symlinks such as
# /bin -> usr/bin are recreated as symlinks). /etc is bound for the loader cache, passwd and certificate lookups.
CONFINEMENT_SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc")
CONFINEMENT_UNSHARE = ("unshare", "--user", "--map-root-user", "--net", "--mount", "--pid", "--fork",
                       "--kill-child")
CONFINEMENT_SETPRIV = ("setpriv", "--no-new-privs", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all")
# Where the new root is staged: the first of these that exists on the host and is not an ancestor of the working
# directory or of a bind source (the tmpfs mounted there hides that host directory, in the private namespace only).
CONFINEMENT_STAGES = ("/mnt", "/media", "/srv", "/opt", "/var/empty", "/run", "/tmp")
# The new root's own /dev, /proc and /tmp: no read-only bind may target them.
CONFINEMENT_RESERVED = ("/dev", "/proc", "/tmp")
# sh -c script run inside the new user, mount, PID and network namespaces. Arguments: $1 the working directory,
# $2 1 if it is writable, $3 the staging directory, then SOURCE TARGET pairs to bind read-only, "--", then the
# command. It builds a new root on a tmpfs that holds only a minimal /dev, a fresh /proc of the private PID namespace,
# a fresh /tmp, those read-only binds and the working directory; pivots into it and detaches the host root; then
# drops every capability and runs the command. `set -e`: any failed step aborts before the command runs, so nothing
# ever runs half-confined.
CONFINEMENT_SCRIPT = r'''set -eu
wd=$1; writable=$2; R=$3; shift 3
outer_path=$PATH
PATH=$PATH:/usr/sbin:/sbin:/usr/bin:/bin
ro() {
  mount -o remount,bind,ro "$1" 2>/dev/null || mount -o remount,bind,ro,nosuid,nodev "$1" 2>/dev/null \
    || mount -o remount,bind,ro,nosuid,nodev,noexec "$1"
}
rro() {
  ro "$1"
  for sub in $(awk -v p="$1/" 'index($5, p) == 1 {print $5}' /proc/self/mountinfo); do ro "$sub"; done
}
mount -t tmpfs -o mode=755 reticle-root "$R"
mkdir "$R/dev" "$R/proc" "$R/tmp" "$R/.reticle-old-root"
mount -t tmpfs -o mode=755,nosuid reticle-dev "$R/dev"
for node in null zero full random urandom; do
  if [ -e "/dev/$node" ]; then : > "$R/dev/$node"; mount --bind "/dev/$node" "$R/dev/$node"; fi
done
ln -s /proc/self/fd "$R/dev/fd"
ln -s /proc/self/fd/0 "$R/dev/stdin"
ln -s /proc/self/fd/1 "$R/dev/stdout"
ln -s /proc/self/fd/2 "$R/dev/stderr"
mkdir "$R/dev/shm"
mount -t tmpfs -o mode=1777,nosuid,nodev,size=64m reticle-shm "$R/dev/shm"
mount -t proc -o nosuid,nodev,noexec proc "$R/proc" 2>/dev/null || true
mount -t tmpfs -o mode=1777,nosuid,nodev,size=256m reticle-tmp "$R/tmp"
while [ "$1" != "--" ]; do
  src=$1; dst=$2; shift 2
  if [ -L "$src" ] && [ "$src" = "$dst" ]; then
    mkdir -p "$R$(dirname "$dst")"; ln -s "$(readlink "$src")" "$R$dst"
  elif [ -d "$src" ]; then
    mkdir -p "$R$dst"; mount --rbind "$src" "$R$dst"; rro "$R$dst"
  elif [ -e "$src" ]; then
    mkdir -p "$R$(dirname "$dst")"; : > "$R$dst"; mount --bind "$src" "$R$dst"; ro "$R$dst"
  fi
done
shift
mkdir -p "$R$wd"
mount --bind "$wd" "$R$wd"
if [ "$writable" != 1 ]; then ro "$R$wd"; fi
cd "$R"
pivot_root . .reticle-old-root
cd /
umount -l /.reticle-old-root
rmdir /.reticle-old-root
cd "$wd"
PATH=$outer_path HOME=/tmp TMPDIR=/tmp TMP=/tmp TEMP=/tmp GIT_CEILING_DIRECTORIES=$(dirname "$wd")
export PATH HOME TMPDIR TMP TEMP GIT_CEILING_DIRECTORIES
exec ''' + " ".join(CONFINEMENT_SETPRIV) + ''' -- "$@"
'''




def _inside(path: str, parent: str) -> bool:
    """True if the POSIX path is parent or below it."""
    return path == parent or parent == "/" or path.startswith(parent.rstrip("/") + "/")


def _posix_directory(path: str | Path) -> str:
    """The working directory as the confined root names it: resolved on POSIX. Elsewhere (only argument-construction
    tests: confinement never runs there) a POSIX-style path is normalised as given."""
    if os.name == "posix":
        return str(Path(path).resolve())
    return posixpath.normpath(str(path).replace("\\", "/"))


def interpreter_roots(interpreter: str | Path) -> List[str]:
    """The directories a Python interpreter needs: its venv (sys.prefix), its base installation (sys.base_prefix
    and the exec prefixes) and the directory of the executable it resolves to. Asked of the interpreter itself, so
    a uv- or pyenv-managed base outside /usr is found."""
    completed = subprocess.run(
        [str(interpreter), "-I", "-c",
         "import json, sys; print(json.dumps([sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix]))"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if completed.returncode != 0:
        raise BackendUnavailableError(
            f"task interpreter {interpreter} did not report its prefixes: {completed.stderr.strip()[:200]}"
        )
    roots = list(json.loads(completed.stdout))
    roots.append(posixpath.dirname(os.path.realpath(str(interpreter))))
    return roots


def confinement_binds(extra_roots: List[str], system_paths=CONFINEMENT_SYSTEM_PATHS,
                      exists=os.path.lexists, realpath=os.path.realpath) -> List[Tuple[str, str]]:
    """(source, target) pairs to bind read-only, in order. System paths that exist are bound at their own path (the
    script recreates a symlink such as /bin -> usr/bin instead of following it). Each extra root is bound from its
    real path, at the real path and, when it differs, at the path as given. A target at or below a target already
    kept is dropped (that bind already shows it); a kept target below a new one is replaced by it."""
    pairs: List[Tuple[str, str]] = [(path, path) for path in system_paths if exists(path)]
    for root in extra_roots:
        given = posixpath.normpath(str(root))
        real = posixpath.normpath(realpath(given))
        for target in dict.fromkeys((real, given)):
            pairs.append((real, target))
    kept: List[Tuple[str, str]] = []
    for source, target in pairs:
        if any(_inside(target, other) for _, other in kept):
            continue
        kept = [(s, t) for s, t in kept if not _inside(t, target)]
        kept.append((source, target))
    return kept


def confinement_stage(directory: str, binds: List[Tuple[str, str]], isdir=os.path.isdir) -> str:
    """The staging directory: the first CONFINEMENT_STAGES entry that exists and is not an ancestor of the working
    directory or of a bind source (its host contents are hidden while the new root is built)."""
    for stage in CONFINEMENT_STAGES:
        if not isdir(stage):
            continue
        if _inside(directory, stage) or any(_inside(source, stage) for source, _ in binds):
            continue
        return stage
    raise BackendUnavailableError(f"no staging directory for the confined root among {', '.join(CONFINEMENT_STAGES)}")


class ConfinedLocalBackend(TrustedLocalBackend):
    """Trusted-local execution confined like the OCI backend, on Linux, without an engine or host root.

    Every command runs in new user, mount, PID and network namespaces (util-linux unshare; the cloud VM passed
    experiments/cloud/probe_isolation.sh with unshare -rnm). Inside, a tmpfs root holds only the working directory
    (writable unless the request is read-only), read-only system directories (CONFINEMENT_SYSTEM_PATHS), the task
    interpreter's venv and base installation (read-only), a minimal /dev, a fresh /proc of the private PID namespace
    and a private /tmp per command. pivot_root moves into it and the host root is detached, so nothing else on the
    host is reachable by any path. The only network interface is an unconfigured loopback. git cannot climb above the
    working directory (nothing above it exists, and GIT_CEILING_DIRECTORIES says so). setpriv drops every capability
    and sets no_new_privs before the command runs, so it cannot remount, mount or chroot its way back.

    Fails closed: availability() runs one full confined command; if that fails on this host, run() raises
    BackendUnavailableError and nothing runs.
    """

    name = "trusted-local-confined"
    host_isolation = False  # paths keep their host names (the workspace path, the interpreter path)
    confinement = CONFINEMENT_NAME

    def __init__(self, interpreter: Optional[str | Path] = None,
                 readonly_binds: Optional[List[Tuple[str, str]]] = None, stage: Optional[str] = None):
        self.interpreter = interpreter
        self._binds = list(readonly_binds) if readonly_binds is not None else None
        self._stage = stage
        self._problem: Optional[str] = None
        self._checked = False

    def binds(self) -> List[Tuple[str, str]]:
        """Read-only (source, target) binds, computed on first use (asking the task interpreter for its prefixes)."""
        if self._binds is None:
            roots = interpreter_roots(self.interpreter) if self.interpreter is not None else []
            self._binds = confinement_binds(roots)
        return self._binds

    def build_command(self, request: ExecutionRequest) -> List[str]:
        """The host argv: unshare, then the confinement script with its arguments, then the request's command."""
        directory = _posix_directory(request.working_directory)
        if not directory.startswith("/"):
            raise ValueError(f"confinement needs a POSIX working directory, not {directory}")
        writable = request.mutates_workspace if request.writable_mount is None else request.writable_mount
        binds = self.binds()
        for _, target in binds:
            if target in CONFINEMENT_RESERVED or _inside(target, "/proc"):
                raise ValueError(f"read-only bind {target} would cover the confined root's own /dev, /proc or /tmp")
            if _inside(directory, target) or _inside(target, directory):
                raise ValueError(f"working directory {directory} overlaps the read-only bind {target}")
        if directory in CONFINEMENT_RESERVED or _inside(directory, "/proc"):
            raise ValueError(f"working directory {directory} is reserved in the confined root")
        stage = self._stage or confinement_stage(directory, binds)
        flat = [part for pair in binds for part in pair]
        return [*CONFINEMENT_UNSHARE, "--", "sh", "-c", CONFINEMENT_SCRIPT, "reticle-confine",
                directory, "1" if writable else "0", stage, *flat, "--", *request.command]

    def availability(self) -> Optional[str]:
        """Why confinement cannot run on this host, or None. Checked once per backend: the tools must exist and one
        full confined `true` (every mount, the pivot and the capability drop) must succeed."""
        if self._checked:
            return self._problem
        self._checked = True
        self._problem = self._probe()
        return self._problem

    @staticmethod
    def _platform_problem() -> Optional[str]:
        if os.name != "posix" or not sys.platform.startswith("linux"):
            return f"--sandbox {CONFINEMENT_NAME} needs Linux namespaces; this host is {sys.platform}"
        return None

    def _probe(self) -> Optional[str]:
        problem = self._platform_problem()
        if problem:
            return problem
        for tool in ("unshare", "setpriv", "pivot_root", "mount", "umount"):
            if shutil.which(tool) is None and not any(
                    os.path.exists(posixpath.join(d, tool)) for d in ("/usr/sbin", "/sbin", "/usr/bin", "/bin")):
                return f"--sandbox {CONFINEMENT_NAME} needs util-linux {tool}"
        try:
            with tempfile.TemporaryDirectory(prefix="reticle-confine-check-") as scratch:
                probe = ExecutionRequest(command=["true"], working_directory=scratch, timeout_seconds=60)
                result = TrustedLocalBackend.run(self, dataclass_replace(probe, command=self.build_command(probe)))
        except (OSError, ValueError, BackendUnavailableError, subprocess.SubprocessError) as exc:
            return f"--sandbox {CONFINEMENT_NAME} self-test could not start: {exc}"
        if result.status != "success":
            detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()[-300:]
            return f"--sandbox {CONFINEMENT_NAME} self-test failed (exit {result.exit_code}): {detail}"
        return None

    def run(self, request: ExecutionRequest, cancellation_event: Optional[threading.Event] = None) -> ExecutionResult:
        problem = self.availability()
        if problem:
            raise BackendUnavailableError(problem)
        wrapped = dataclass_replace(request, command=self.build_command(request))
        return super().run(wrapped, cancellation_event)




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

    def user_arguments(self) -> List[str]:
        """Run as a non-root guest user that can manage its own workspace files.

        Rootless Podman's keep-id maps the guest user to the unprivileged host user, so bind
        mounted files are owned by the guest and chmod works (pytest's cache and shutil.copy2
        need it). Docker keeps the fixed nobody user; chmod on its bind mounts may be denied.
        """
        if "podman" in Path(self.engine).name.lower():
            return ["--userns", "keep-id"]
        return ["--user", "65534:65534"]

    def build_command(self, request: ExecutionRequest, container_name: str) -> List[str]:
        workspace = Path(request.working_directory).resolve()
        mount = f"type=bind,src={workspace},dst=/workspace"
        writable = request.mutates_workspace if request.writable_mount is None else request.writable_mount
        if not writable:
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
            *self.user_arguments(),
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
