#!/usr/bin/env bash
# Does `--sandbox unshare-confined` confine the model's commands on this Linux VM? The cloud integrity fix
# (experiments/cloud/INTEGRITY_AUDIT_019-021.md, "Fix"); cloud cards stay paused until this passes on the VM.
#
#   bash experiments/cloud/probe_confinement.sh
#
# No model call, no campaign, no install. It builds a throwaway run directory inside the checkout, laid out like a
# real run (experiments/p6_pilot/runs/<run>/sessions/<task>__<model>/{workspace,evaluator,verifier}), and runs a
# battery of escape attempts through the runner's own confined backend (run_pilot.resolve_execution("trusted-local",
# ..., "unshare-confined"), the object the run tool, the evaluator and check() use), each as the run tool would issue
# it: argv, no shell, the workspace as working directory, the task interpreter for python. Each escape must be
# blocked; the positive controls (python, pytest, workspace writes) must work. It prints PASS or FAIL per check and
#   CONFINEMENT: PASS          every escape blocked, every control worked (exit 0)
#   CONFINEMENT: FAIL          at least one escape got through or a control broke (exit 1)
#   CONFINEMENT: UNAVAILABLE   the backend refuses to run here (fail closed; exit 2)
# It removes the throwaway run directory, the sentinels it planted and anything it wrote, and leaves nothing else.

set -uo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.runtime/test-venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
cd "$ROOT" || exit 2
info() { printf 'INFO %s\n' "$*"; }
info "checkout $ROOT; driver $PY; uid $(id -u); kernel $(uname -r); $(unshare --version 2>/dev/null | head -1)"
info "tools: setpriv=$(command -v setpriv || echo missing) pivot_root=$(command -v pivot_root || ls /usr/sbin/pivot_root /sbin/pivot_root 2>/dev/null | head -1 || echo missing) git=$(command -v git || echo missing) curl=$(command -v curl || echo missing) pip=$(command -v pip || echo missing)"

exec "$PY" - "$ROOT" <<'PYEOF'
import json, os, shutil, socket, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(ROOT), str(ROOT / "experiments" / "p6_pilot")]
import run_pilot  # noqa: E402
from reticle.execution import ExecutionRequest  # noqa: E402

PASSES, FAILS = [], []
def check(ok, label, detail=""):
    (PASSES if ok else FAILS).append(label)
    print(("PASS " if ok else "FAIL ") + label + (f" ({detail})" if detail else ""), flush=True)
def info(text):
    print("INFO " + text, flush=True)

backend, execution = run_pilot.resolve_execution("trusted-local", "unused", "unshare-confined")
TASK_PY = str(run_pilot.TASK_PYTHON)
info(f"task interpreter {TASK_PY}; contract {execution['sandbox']['version']}; authority: {execution['authority']}")
problem = backend.availability()
if problem:
    print(f"FAIL 0 the confined backend refuses to run here: {problem}")
    print("CONFINEMENT: UNAVAILABLE")
    sys.exit(2)
check(True, "0 confined backend self-test")
info("read-only binds: " + " ".join(t for _, t in backend.binds()))

pid = os.getpid()
run_dir = ROOT / "experiments" / "p6_pilot" / "runs" / f"probe-confinement-{pid}"
session = run_dir / "sessions" / "probe-task__probe-model"
ws, evaluator, verifier = session / "workspace", session / "evaluator", session / "verifier"
planted = []  # (path, created_parents_root) removed at the end
def plant(path: Path, text: str):
    top = path.parent
    while not top.parent.exists():
        top = top.parent
    created = None if path.parent.exists() else top
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    planted.append((path, created))

def run(argv, *, mutates=True, writable=None, cwd=None, limit=64_000_000, timeout=300):
    request = ExecutionRequest(command=list(argv), working_directory=cwd or ws, timeout_seconds=timeout,
                               output_limit_bytes=limit, environment={"PYTHONPATH": str(ws)},
                               mutates_workspace=mutates, writable_mount=writable)
    result = backend.run(request)
    return result.exit_code, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")

try:
    ws.mkdir(parents=True)
    (ws / "mod.py").write_text("def double(x):\n    return 2 * x\n", encoding="utf-8")
    (ws / "test_mod.py").write_text("from mod import double\n\n\ndef test_double():\n    assert double(2) == 4\n",
                                    encoding="utf-8")
    plant(evaluator / "files" / "tests" / "test_hidden.py", "HIDDEN-TEST-SENTINEL\n")
    plant(verifier / "test_reticle_repro.py", "VERIFIER-SENTINEL\n")
    repos = ROOT / ".runtime" / "bug-mining" / "repos"
    clone_files = sorted(repos.glob("*/setup.py")) + sorted(repos.glob("*/pyproject.toml")) if repos.is_dir() else []
    clone_file = clone_files[0] if clone_files else None
    if clone_file is None:  # a stand-in where the healthy clones live, so the check is never vacuous
        clone_file = ROOT / ".runtime" / "bug-mining" / f"probe-sentinel-{pid}.txt"
        plant(clone_file, "CLONE-SENTINEL\n")
    host_tmp = Path("/tmp") / f"reticle-probe-host-{pid}.txt"
    plant(host_tmp, "HOST-TMP-SENTINEL\n")
    tasks_json = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
    verifiers_dir = ROOT / "experiments" / "session_harness" / "verifiers"
    for path in (clone_file, tasks_json, host_tmp):
        info(f"host sees {path}: {path.exists()}")

    # ---- positive controls ------------------------------------------------------------------------------------
    code, out, err = run([TASK_PY, "-c", "1"])
    check(code == 0, "1 positive: task interpreter runs (python -c 1)", err.strip()[-200:])
    code, out, err = run([TASK_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_mod.py"])
    check(code == 0 and "1 passed" in out, "2 positive: pytest on a tiny test in the workspace", (out + err).strip()[-200:])
    code, out, err = run([TASK_PY, "-c", "open('written.txt', 'w').write('ok')"])
    check(code == 0 and (ws / "written.txt").read_text() == "ok", "3 positive: write in the workspace, seen on the host", err.strip()[-200:])
    code, out, err = run(["sh", "-c", "echo e > eval.txt"], mutates=False, writable=True)
    check(code == 0 and (ws / "eval.txt").exists(), "4 positive: an evaluation root (writable_mount) is writable", err.strip()[-200:])
    code, out, err = run(["sh", "-c", "echo r > readonly.txt"], mutates=False)
    check(code != 0 and not (ws / "readonly.txt").exists(), "5 a read-only request cannot write its directory")

    # ---- filesystem ----------------------------------------------------------------------------------------------
    allowed = [str(ws), "/dev", "/proc", "/tmp"] + [t for _, t in backend.binds()]
    def allowed_path(line):
        if any(line == a or line.startswith(a.rstrip("/") + "/") for a in allowed):
            return True
        return any(a.startswith(line.rstrip("/") + "/") for a in allowed) or line == "/"  # an ancestor directory
    code, out, err = run(["find", "/"], timeout=600)
    lines = [l for l in out.splitlines() if l]
    outside = [l for l in lines if not allowed_path(l)]
    markers = [m for m in ("bug-mining", "tasks.mutations", "verifiers", "evaluator", "test_hidden", "/.git",
                           f"reticle-probe-host-{pid}", "harness-sealed") if m in out]
    check(lines and not outside and not markers, "6 find / lists only the workspace, system and interpreter paths",
          f"{len(lines)} paths; outside {len(outside)} {outside[:5]}; markers {markers}")
    for label, argv in (("7 cat the healthy clone", ["cat", str(clone_file)]),
                        ("8 cat the task bank", ["cat", str(tasks_json)]),
                        ("9 ls the verifiers directory", ["ls", str(verifiers_dir)]),
                        ("10 cat the sibling evaluator's hidden test", ["cat", "../evaluator/files/tests/test_hidden.py"]),
                        ("11 cat the run's verifier copy", ["cat", str(verifier / "test_reticle_repro.py")]),
                        ("12 cat the host /tmp", ["cat", str(host_tmp)]),
                        ("13 cat the task bank through /proc/1/root", ["cat", f"/proc/1/root{tasks_json}"]),
                        ("14 cat the clone through /proc/1/root", ["cat", f"/proc/1/root{clone_file}"])):
        code, out, err = run(argv)
        leaked = code == 0 or any(s in out for s in ("SENTINEL", '"tasks"', "mutation_patch"))
        check(not leaked, label + " is blocked", f"exit {code}; {(out or err).strip()[:120]!r}")
    code, out, err = run(["ls", "-a", str(ROOT)])
    names = set(out.split()) - {".", ".."}
    # The checkout's path exists only as the chain of empty directories leading to the workspace and the task venv.
    check(names <= {"experiments", ".runtime"}, "13b ls the checkout root shows only the path to this run and the venv",
          f"exit {code}; {sorted(names)}")
    code, out, err = run(["ls", "-a", str(ROOT / ".runtime")])
    names = set(out.split()) - {".", ".."}
    check(names <= {Path(TASK_PY).parent.parent.name}, "13c ls .runtime shows only the task venv (no bug-mining)",
          f"exit {code}; {sorted(names)}")
    code, out, err = run(["ls", "-a", ".."])
    names = set(out.split()) - {".", ".."}
    check(names == {"workspace"}, "15 ls .. shows only the workspace", f"exit {code}; {sorted(names)}")
    code, out, err = run(["ls", "-a", str(ROOT / "experiments")])
    names = set(out.split()) - {".", ".."}
    check(names <= {"p6_pilot"}, "16 the checkout's experiments/ holds only the path to this run", f"{sorted(names)}")

    # ---- git -------------------------------------------------------------------------------------------------------
    if shutil.which("git"):
        code, out, err = run(["git", "log", "--oneline", "-3"])
        check(code != 0 and not out.strip(), "17 git log in the workspace finds no repository", (err or out).strip()[:120])
        code, out, err = run(["git", "-C", str(ROOT), "log", "--oneline", "-1"])
        check(code != 0 and not out.strip(), "18 git -C <checkout> log fails", (err or out).strip()[:120])
        code, out, err = run(["git", "rev-parse", "--show-toplevel"])
        check(code != 0, "19 git rev-parse --show-toplevel fails", (err or out).strip()[:120])
    else:
        info("17-19 git is not installed on this VM; git checks skipped")

    # ---- network ---------------------------------------------------------------------------------------------------
    fetch = ("import socket, urllib.request\nr = {}\n"
             "for n, a in (('https', lambda: urllib.request.urlopen('https://pypi.org/simple/sqlparse/', timeout=8).read(1)),"
             " ('socket', lambda: socket.create_connection(('1.1.1.1', 443), timeout=8).close()),"
             " ('dns', lambda: socket.getaddrinfo('pypi.org', 443))):\n"
             "    try:\n        a(); r[n] = 'reached'\n    except Exception as e:\n        r[n] = 'blocked'\n"
             "print(' '.join(f'{k}={v}' for k, v in r.items()))\n")
    baseline = subprocess.run([TASK_PY, "-c", fetch], capture_output=True, text=True, timeout=120).stdout.strip()
    check("https=reached" in baseline, "20 baseline: the host itself reaches pypi.org (so the denials below mean something)", baseline)
    code, out, err = run([TASK_PY, "-c", fetch])
    check(out.strip() == "https=blocked socket=blocked dns=blocked", "21 python https, socket and DNS are blocked", out.strip() or err.strip()[-120:])
    code, out, err = run([TASK_PY, "-c", "import socket; print(' '.join(sorted(n for _, n in socket.if_nameindex())))"])
    check(out.strip() == "lo", "22 only the loopback interface exists", out.strip() or err.strip()[-120:])
    pips = [[p, "download"] for p in ("pip", "pip3") if shutil.which(p)]
    pips += [[py, "-m", "pip", "download"] for py in (TASK_PY, "/usr/bin/python3", "/usr/local/bin/python3")
             if os.path.exists(py) and subprocess.run([py, "-m", "pip", "--version"], capture_output=True).returncode == 0]
    if not pips:
        info("23 no pip on this VM; pip download not tried")
    for n, argv in enumerate(pips):
        dest = ws / f"dl{n}"
        code, out, err = run([*argv, "sqlparse==0.4.4", "--no-deps", "--no-binary", ":all:", "-d", str(dest), "--timeout", "8", "--retries", "0"])
        got = list(dest.glob("*")) if dest.exists() else []
        check(code != 0 and not got, f"23.{n} {' '.join(argv)} sqlparse fails", f"exit {code}; files {len(got)}")
    if shutil.which("curl"):
        code, out, err = run(["curl", "-sS", "-m", "8", "https://pypi.org/simple/sqlparse/"])
        check(code != 0 and not out.strip(), "24 curl https://pypi.org fails", (err or out).strip()[:120])
    else:
        info("24 curl is not installed; the python https check (21) covers it")

    # ---- /tmp ------------------------------------------------------------------------------------------------------
    secret = f"/tmp/reticle-probe-secret-{pid}"
    code, out, err = run([TASK_PY, "-c", f"open({secret!r}, 'w').write('s'); print(open({secret!r}).read())"])
    check(code == 0 and out.strip() == "s", "25 positive: /tmp is writable and readable within a command", err.strip()[-120:])
    code, out, err = run(["cat", secret])
    check(code != 0 and not out, "26 a second command cannot see the first one's /tmp file", f"exit {code}")
    check(not os.path.exists(secret), "27 the confined /tmp write never reached the host /tmp")

    # ---- privileges ------------------------------------------------------------------------------------------------
    venv = Path(TASK_PY).parent.parent
    for label, argv in (("28 remount /usr read-write", ["mount", "-o", "remount,rw,bind", "/usr"]),
                        ("29 write into /usr", ["touch", "/usr/reticle-probe"]),
                        ("30 write into the task venv", ["touch", str(venv / "reticle-probe")]),
                        ("31 chroot", [TASK_PY, "-c", "import os; os.chroot('/tmp')"]),
                        ("32 nested user namespace unlocking /usr",
                         ["unshare", "-rm", "sh", "-c", "mount -o remount,rw,bind /usr && touch /usr/reticle-probe"])):
        code, out, err = run(argv)
        check(code != 0, label + " is refused", f"exit {code}; {(err or out).strip()[:100]!r}")
    check(not Path("/usr/reticle-probe").exists() and not (venv / "reticle-probe").exists(),
          "33 nothing was written to the host's /usr or venv")
    code, out, err = run(["ls", "/proc"])
    pids = [n for n in out.split() if n.isdigit()]
    if not out.strip():
        info("34 /proc is empty: the fresh proc mount was refused here (no host processes visible either way)")
    check(len(pids) <= 3, "34 /proc shows only the private PID namespace", f"{len(pids)} pids: {pids[:6]}")
finally:
    for leftover in (Path("/usr/reticle-probe"), Path(TASK_PY).parent.parent / "reticle-probe"):
        if leftover.exists():
            print(f"FAIL an escape wrote {leftover} on the host; removing it")
            FAILS.append(str(leftover))
            try:
                leftover.unlink()
            except OSError:
                pass
    shutil.rmtree(run_dir, ignore_errors=True)
    for path, created in planted:
        try:
            path.unlink()
        except OSError:
            pass
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
    for leftover in ("/tmp/reticle-probe-secret-%d" % pid, "/usr/reticle-probe"):
        if os.path.exists(leftover):
            print(f"FAIL cleanup: {leftover} exists on the host")
            FAILS.append("cleanup")

print(f"SUMMARY {len(PASSES)} passed, {len(FAILS)} failed")
print("CONFINEMENT: PASS" if not FAILS else "CONFINEMENT: FAIL")
sys.exit(0 if not FAILS else 1)
PYEOF
